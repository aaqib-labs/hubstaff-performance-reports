from __future__ import annotations

"""
Cross-check the month-end report's hours against Hubstaff
==========================================================
Compares every hours figure the report shows (the report month and, for
Section 3, the two months before) with what Hubstaff holds today:

    Hubstaff total = tracked time (incl. manual and break project time)
                     + approved paid leave (TO CSVs) [+ paid holiday hours
                     for members who get them]

It reads saved Hubstaff MCP pulls only (never calls the API itself):
    --pulls   folder with raw JSON responses saved byte-for-byte:
              - get_organizations_organization_id_timesheets, one per month
                (date: {start, stop} = the month). One call covers everyone and
                includes names. This is the first pass.
              - optional: get_organizations_organization_id_activities_daily for
                ONE month and specific user_ids, fully paged, to confirm a
                difference. Where present for a member-month it replaces the
                timesheet figure. Never save part-paged org-wide pages: they
                would read as short months.
    TO CSVs   data/input/timeoff/TO-<month>.csv, rebuilt from the latest raw
              time-off pull (so late approvals are in)

Usage:
    python scripts/verify_hours.py --start 2026-10-01 --end 2026-10-31 \
        --pulls data/input/hubstaff_pulls/2026-10 [--holiday 2026-09=8] [--write-refresh]

Output: one line per difference of 0.1h or more, then a summary. A difference
equal to a month's paid holiday hours is reported as "holiday" (the member's
CSV includes it, or doesn't), not as an error. With --write-refresh, differences
in the two earlier months are written to data/input/salaried/hours_refresh.csv
(today's Hubstaff figure replaces that month's CSV figure in Section 3). A
difference in the report month itself means time was edited after the export:
re-export the CSV or note it; the script never changes the report month.
"""

import argparse
import csv
import glob
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from generate_biweekly_report import (  # noqa: E402
    REPO_ROOT, CATEGORY_PAID, month_starts_back, load_month_totals, load_month_leave,
    load_hours_refresh, norm_name, SALARIED_DIR,
)
from utils import get_exclusions  # noqa: E402

TOL = 0.1


def load_pulls(folder: Path) -> tuple[dict, dict]:
    """({(user_id, 'YYYY-MM'): tracked seconds}, {user_id: name}) from saved JSON pages."""
    rows, sheets, names = {}, {}, {}
    files = sorted(glob.glob(str(folder / "**" / "*.json"), recursive=True))
    if not files:
        print(f"ERROR: no JSON pages in {folder}", file=sys.stderr)
        sys.exit(1)
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"WARN: not JSON, skipped: {f}")
            continue
        for u in d.get("users", []) or []:
            if u.get("id") and u.get("name"):
                names[u["id"]] = u["name"]
        for r in d.get("daily_activities", []) or []:
            rows[r["id"]] = r  # de-duplicates overlapping pages
        for t in d.get("timesheets", []) or []:
            sheets[t["id"]] = t
    ts = {}
    for t in sheets.values():
        a, b = t["start_date"], t["stop_date"]
        if a[:7] != b[:7]:
            continue  # spans two months: not comparable
        k = (t["user_id"], a[:7])
        ts[k] = ts.get(k, 0) + (t.get("tracked") or 0)
    act = {}
    for r in rows.values():
        k = (r["user_id"], r["date"][:7])
        act[k] = act.get(k, 0) + (r.get("tracked") or 0)
    tracked = {**ts, **act}  # daily activities (targeted pulls) win
    return tracked, names


def main():
    ap = argparse.ArgumentParser(description="Cross-check report hours against saved Hubstaff pulls.")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--pulls", required=True, help="Folder of saved Hubstaff JSON pages")
    ap.add_argument("--holiday", action="append", default=[],
                    help="Paid holiday hours in a month, e.g. 2026-09=8 (Labor Day). Repeatable.")
    ap.add_argument("--write-refresh", action="store_true",
                    help="Write earlier-month differences to data/input/salaried/hours_refresh.csv")
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    months = month_starts_back(start, 3)
    holidays = {h.split("=")[0]: float(h.split("=")[1]) for h in args.holiday}
    tracked, names = load_pulls(Path(args.pulls))
    by_name = {}
    for uid, n in names.items():
        by_name.setdefault(norm_name(n), []).append(uid)
    excluded = {norm_name(n) for n in get_exclusions(start)}
    refresh = load_hours_refresh()

    diffs, holiday_only, missing, checked = [], 0, [], 0
    for i, m in enumerate(months):
        key_m = f"{m:%Y-%m}"
        totals = load_month_totals(m)
        if totals is None:
            print(f"{key_m}: no monthly CSV, skipped")
            continue
        leave = load_month_leave(m)
        paid_now = {}
        to = sorted((REPO_ROOT / "data" / "input" / "timeoff").glob(f"TO-{key_m}-01_to_*.csv"))
        if to:
            t = pd.read_csv(to[-1])
            t = t[(t["status"] == "approved") & (t["category"] == CATEGORY_PAID)]
            paid_now = t.groupby(t["member"].apply(norm_name))["hours"].sum().to_dict()
        else:
            print(f"WARN {key_m}: no TO CSV, paid leave not included")
        current = i == len(months) - 1
        for name, total in totals.items():
            if name in excluded:
                continue
            uids = by_name.get(name, [])
            if not uids or not any((u, key_m) in tracked for u in uids):
                missing.append(f"{name} ({key_m})")
                continue
            # What the report shows: CSV total, or the refresh figure (earlier months),
            # plus paid leave approved after that month's export
            shown = total
            if not current and (name, key_m) in refresh:
                shown = refresh[(name, key_m)][0]
            shown += leave.get(name, (0, 0, 0, 0))[3]
            hub = sum(tracked.get((u, key_m), 0) for u in uids) / 3600 + paid_now.get(name, 0.0)
            checked += 1
            d = shown - hub
            if abs(d) < TOL:
                continue
            hol = holidays.get(key_m, 0)
            if hol and abs(d - hol) < abs(d):
                # This member's CSV includes the paid holiday
                hub += hol
                d = shown - hub
                if abs(d) < TOL:
                    holiday_only += 1
                    continue
            diffs.append((key_m, current, name, shown, hub))

    print(f"Checked {checked} member-months over {', '.join(f'{m:%b %Y}' for m in months)}.")
    for key_m, current, name, shown, hub in sorted(diffs):
        where = "REPORT MONTH (edited after export)" if current else "earlier month"
        print(f"  {key_m} {name:30} report {shown:7.1f}h  Hubstaff {hub:7.1f}h  "
              f"({hub - shown:+.1f}h)  {where}")
    if holiday_only:
        print(f"{holiday_only} member-month(s) include the paid holiday (expected).")
    if missing:
        print(f"No Hubstaff data for {len(missing)} member-month(s): {', '.join(sorted(missing)[:20])}"
              + (" ..." if len(missing) > 20 else ""))
        ids = sorted({u for x in missing for u in by_name.get(x.rsplit(' (', 1)[0], [])})
        no_id = sorted({x.rsplit(' (', 1)[0] for x in missing if not by_name.get(x.rsplit(' (', 1)[0])})
        if ids:
            print(f"  Pull activities_daily for these user_ids (one call per month, fully paged): {ids}")
        if no_id:
            print(f"  No Hubstaff user id known (save a members pull with include users, "
                  f"or it is an old name): {', '.join(no_id)}")
    print("Earlier-month differences only matter for people in Section 3 (salaried).")
    print(f"Differences: {len(diffs)}")

    if args.write_refresh:
        earlier = [x for x in diffs if not x[1]]
        if not earlier:
            print("Nothing to write to hours_refresh.csv.")
            return
        path = SALARIED_DIR / "hours_refresh.csv"
        existing = []
        if path.exists():
            existing = list(csv.DictReader(open(path, encoding="utf-8")))
        keep = [r for r in existing
                if (norm_name(r["member"]), r["month"]) not in {(x[2], x[0]) for x in earlier}]
        today = date.today().isoformat()
        for key_m, _, name, shown, hub in earlier:
            src_total = load_month_totals(date.fromisoformat(key_m + "-01")).get(name)
            late = load_month_leave(date.fromisoformat(key_m + "-01")).get(name, (0, 0, 0, 0))[3]
            keep.append({"member": next(n for u in by_name[name] for n in [names[u]]),
                         "month": key_m, "hours": f"{hub - late:.1f}",
                         "csv_hours": f"{src_total:.1f}",
                         "source": f"Hubstaff MCP {today} (time edited after the export)"})
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["member", "month", "hours", "csv_hours", "source"])
            w.writeheader()
            w.writerows(keep)
        print(f"Wrote {len(earlier)} row(s) to {path}")


if __name__ == "__main__":
    main()
