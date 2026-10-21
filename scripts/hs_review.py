"""
hs_review.py — Monthly People Ops Hubstaff review brief.

Reads the last three monthly master CSVs (oldest first) and prints a short
markdown brief: a "Discuss today" list of at most 15 items, then the detail
behind it — salaried hours trend, repeat SLA patterns, peer outliers, and
(optionally) unusual activity and unapproved leave. Built for the
hubstaff-review skill; the skill does the MCP and ClickUp pulls, this script
does every calculation.

Names from the ClickUp HR profiles (salaried, offboarded) are passed on the
command line and are never written to disk.

Usage:
    python scripts/hs_review.py \
        --months data/input/monthly/HS-2026-07-master.csv \
                 data/input/monthly/HS-2026-08-master.csv \
                 data/input/monthly/HS-2026-09-master.csv \
        --salaried "Name One,Name Two" \
        [--skip "Offboarded One,Offboarded Two"] \
        [--leave data/input/timeoff/TO-2026-09-01_to_2026-09-30.csv ...] \
        [--partial data/input/biweekly/HS-2026-10-01_to_2026-10-20.csv] \
        [--unusual data/input/hs_mcp/raw/UA-....json --members data/input/hs_mcp/raw/MEMBERS.json] \
        [--section salaried|patterns|peers|unusual|leave]
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import (HOURS_BASE, HOURS_OVERWORK_BASE, count_working_days, evaluate_flags,  # noqa: E402
                   get_exclusions, get_month_working_days, load_master_table)
from generate_peer_comparison import PEER_GROUPS  # noqa: E402

# ---------------------------------------------------------------------------
# Salaried hours rule — Jorn, People Ops 2 Oct 2026: salaried staff were
# priced on 180h/month; 169–170h is "within the range", 160–164h is not.
# One month under = alert, 2+ of the last 3 = serious (Aaqib, 21 Oct 2026).
# Confirm the floor with Jorn before treating it as policy.
# ---------------------------------------------------------------------------
SALARIED_TARGET = 180.0
SALARIED_FLOOR  = 170.0

PEER_GAP_PP = 10.0          # same rule as the peer comparison report
TOP_LIMIT   = 15            # Jorn: "ten, fifteen bullets"
PATTERN_METRICS = {"A": "activity", "H": "low hours", "M": "manual time",
                   "20": "low activity ≤20%", "30": "low activity ≤30%"}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = re.sub(r"^dr\.?\s+", "", s.strip().lower())
    return re.sub(r"\s+", " ", s)


LEADERSHIP = {norm(n) for g in PEER_GROUPS if g["id"] == "leadership" for n in g["members"]}


def match_names(wanted: list[str], available: list[str]) -> tuple[dict, list]:
    """Map each wanted (ClickUp) name to a CSV member name: exact, same last
    name with one first name a short form of the other (Fred / Frederick),
    token subset, then close spelling. Returns (mapping, unmatched)."""
    by_norm = {norm(a): a for a in available}
    mapping, unmatched = {}, []
    for w in wanted:
        n = norm(w)
        wt = n.split()
        if n in by_norm:
            mapping[w] = by_norm[n]
            continue
        cands = [a for k, a in by_norm.items() if k.split()[-1] == wt[-1] and len(k.split()) >= 2
                 and (k.split()[0].startswith(wt[0]) or wt[0].startswith(k.split()[0]))]
        if not cands:
            cands = [a for k, a in by_norm.items() if len(k.split()) >= 2 and set(k.split()) <= set(wt)]
        if not cands:
            cands = [by_norm[k] for k in difflib.get_close_matches(n, by_norm, n=1, cutoff=0.85)]
        if len(cands) == 1:
            mapping[w] = cands[0]
        else:
            unmatched.append(w)
    return mapping, unmatched


def month_of(csv_path: Path) -> date:
    m = re.search(r"(\d{4})-(\d{2})", csv_path.name)
    return date(int(m.group(1)), int(m.group(2)), 1)


def load_months(paths: list[Path], skip: set) -> list[dict]:
    months = []
    for p in paths:
        start = month_of(p)
        df = load_master_table(p)
        excl = {norm(n) for n in get_exclusions(start)} | skip
        df = df[~df["member"].apply(norm).isin(excl)].reset_index(drop=True)
        months.append({"start": start, "label": start.strftime("%b"), "df": df,
                       "rows": {r["member"]: r for _, r in df.iterrows()}})
    return months


def load_partial(csv_path: Path, skip: set) -> dict:
    """Month-to-date CSV (HS-YYYY-MM-DD_to_YYYY-MM-DD.csv) for the info-only
    column. Pace = salaried target prorated by Mon–Fri working days."""
    s, e = (date.fromisoformat(d) for d in re.findall(r"\d{4}-\d{2}-\d{2}", csv_path.name)[:2])
    df = load_master_table(csv_path)
    excl = {norm(n) for n in get_exclusions(s)} | skip
    df = df[~df["member"].apply(norm).isin(excl)]
    days, month_days = count_working_days(s, e), get_month_working_days(s)
    return {"start": s, "end": e, "label": f"{s:%b} {s.day}–{e.day}", "days": days, "month_days": month_days,
            "pace": SALARIED_TARGET * days / month_days, "rows": {r["member"]: r for _, r in df.iterrows()}}


def load_unpaid_leave(paths: list[Path]) -> dict:
    """{(YYYY-MM, member): approved Unpaid/Flex hours}. Total Worked Hours
    already includes approved time off, so salaried hours = total − unpaid."""
    out = {}
    for p in paths:
        df = pd.read_csv(p, dtype=str)
        df = df[(df["status"] == "approved") & (df["category"] == "Unpaid/Flex")]
        for _, r in df.iterrows():
            key = (r["date"][:7], r["member"])
            out[key] = out.get(key, 0.0) + float(r["hours"])
    return out


def table(headers: list[str], rows: list[list]) -> list[str]:
    """Markdown table lines. Pipes inside cells are escaped."""
    cell = lambda v: "" if v is None else str(v).replace("|", "\\|")  # noqa: E731
    return (["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
            + ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows])


# ---------------------------------------------------------------------------
# Sections — each returns (detail lines, [(priority, icon, name, area, why), ...])
# ---------------------------------------------------------------------------

def section_salaried(months, mapping: dict, unmatched: list, unpaid: dict, leave_months: set,
                     partial: dict | None = None, partial_map: dict | None = None):
    serious, alert, aside, top = [], [], [], []
    fmt = lambda h: "—" if h is None else (f"**{h:.0f}h**" if h < SALARIED_FLOOR else f"{h:.0f}h")  # noqa: E731

    def to_date(sal_name):
        """Month-to-date hours: shown for information, never flagged."""
        row = partial["rows"].get((partial_map or {}).get(sal_name))
        if row is None or pd.isna(row["total_hours"]):
            return "—"
        return f"{row['total_hours'] - unpaid.get((partial['start'].strftime('%Y-%m'), row['member']), 0.0):.0f}h"

    extra = (lambda n: [to_date(n)]) if partial else (lambda n: [])  # noqa: E731
    for sal_name, csv_name in mapping.items():
        hours, under = [], 0
        for mo in months:
            row = mo["rows"].get(csv_name)
            if row is None or pd.isna(row["total_hours"]):
                hours.append(None)
                continue
            h = row["total_hours"] - unpaid.get((mo["start"].strftime("%Y-%m"), csv_name), 0.0)
            hours.append(h)
            under += h < SALARIED_FLOOR
        latest = hours[-1]
        if latest is None:
            continue
        cells = [fmt(h) for h in hours] + extra(sal_name)
        trail = " / ".join(f"{h:.0f}" if h is not None else "—" for h in hours) + "h"
        if norm(csv_name) in LEADERSHIP:
            aside.append([sal_name, *cells, "Leadership"])
            continue
        if all(h is None for h in hours[:-1]):
            if latest < SALARIED_FLOOR:
                aside.append([sal_name, *cells, "New joiner, partial first month"])
            continue
        gaps = [SALARIED_TARGET - h for h in hours if h is not None and h < SALARIED_FLOOR]
        avg_gap = sum(gaps) / len(gaps) if gaps else 0
        if under >= 2:
            serious.append((under, avg_gap, [sal_name, *cells, f"{under} of {len(months)}", f"{avg_gap:.0f}h", "🔴 Serious"]))
            top.append((10 + under, "🔴", sal_name, "Salaried hours",
                        f"Under {SALARIED_FLOOR:.0f}h in {under} of {len(months)} months ({trail})"))
        elif latest < SALARIED_FLOOR:
            alert.append((avg_gap, [sal_name, *cells, f"1 of {len(months)}", f"{avg_gap:.0f}h", "⚠️ Alert"]))
            top.append((5, "⚠️", sal_name, "Salaried hours",
                        f"First month under {SALARIED_FLOOR:.0f}h ({latest:.0f}h in {months[-1]['label']})"))

    labels = [mo["label"] for mo in months]
    if partial:
        labels.append(f"{partial['label']} (pace {partial['pace']:.0f}h)")
    out = [f"## Salaried hours (target {SALARIED_TARGET:.0f}h, flag under {SALARIED_FLOOR:.0f}h)", ""]
    if not serious and not alert:
        out.append(f"No salaried staff under {SALARIED_FLOOR:.0f}h in {months[-1]['label']}.")
    else:
        rows = ([r for _, _, r in sorted(serious, key=lambda x: (-x[0], -x[1]))]
                + [r for _, r in sorted(alert, key=lambda x: -x[0])])
        out += table(["Name", *labels, f"Under {SALARIED_FLOOR:.0f}h", f"Avg short of {SALARIED_TARGET:.0f}h", "Status"], rows)
        out.append(f"\n_Bold = under {SALARIED_FLOOR:.0f}h._")
    if partial:
        out.append(f"\n_{partial['label']} is month to date, for information only (not flagged). Pace = "
                   f"{SALARIED_TARGET:.0f}h × {partial['days']} of {partial['month_days']} working days._")
    if aside:
        out += ["", "**Not ranked**", ""] + table(["Name", *labels, "Why"], sorted(aside, key=lambda r: (r[-1], r[0])))
    no_leave = [mo["label"] for mo in months if mo["start"].strftime("%Y-%m") not in leave_months]
    if no_leave:
        out.append(f"\n_No time-off file for {', '.join(no_leave)}: those totals still include approved unpaid leave._")
    if unmatched:
        out.append(f"\n_Salaried in ClickUp but not in the Hubstaff CSVs: {', '.join(sorted(unmatched))}._")
    return out, top


def section_patterns(months, salaried_csv: set):
    hits, lead, top = [], [], []
    latest_rows = months[-1]["rows"]
    for name in sorted(latest_rows):
        counts, latest_flags = {}, {}
        for mo in months:
            row = mo["rows"].get(name)
            if row is None:
                continue
            flags = evaluate_flags(row, HOURS_BASE, HOURS_OVERWORK_BASE)
            for k in PATTERN_METRICS:
                if k == "H" and name in salaried_csv:
                    continue  # salaried hours handled in their own section
                if flags.get(k) == "red":
                    counts[k] = counts.get(k, 0) + 1
            latest_flags = flags
        repeat = {k: c for k, c in counts.items() if c >= 2}
        if not repeat:
            continue
        if norm(name) in LEADERSHIP:
            lead.append(name)
            continue
        cells = {k: f"{c}/{len(months)}" + ("" if latest_flags.get(k) == "red" else f" (ok {months[-1]['label']})")
                 for k, c in repeat.items()}
        hits.append((max(repeat.values()), len(repeat), name, latest_rows[name]["team"], cells))
        full = [k for k, c in repeat.items() if c == len(months) and latest_flags.get(k) == "red"]
        if full:
            top.append((8 + len(full), "🔴", name, "SLA pattern",
                        f"Red every month: {', '.join(PATTERN_METRICS[k] for k in full)}"))
    out = [f"## Repeat SLA patterns (red in 2+ of the last {len(months)} months)", ""]
    if not hits:
        out.append("None.")
    else:
        used = [k for k in PATTERN_METRICS if any(k in h[4] for h in hits)]
        rows = [[name, team, *(cells.get(k, "") for k in used)]
                for _, _, name, team, cells in sorted(hits, key=lambda x: (-x[0], -x[1]))]
        out += table(["Name", "Team", *(PATTERN_METRICS[k].capitalize() for k in used)], rows)
        out.append(f"\n_Cells show months red out of {len(months)}._")
    if lead:
        out.append(f"\n_Leadership, not ranked: {', '.join(lead)}._")
    return out, top


def section_peers(months):
    hits, top = [], []
    last = len(months) - 1
    for g in PEER_GROUPS:
        if g["id"] == "leadership":
            continue
        members = {norm(n) for n in g["members"]}
        below = {}
        for i, mo in enumerate(months):
            rows = [(n, r) for n, r in mo["rows"].items() if norm(n) in members and not pd.isna(r["activity_pct"])]
            if len(rows) < 2:
                continue
            avg = sum(r["activity_pct"] for _, r in rows) / len(rows)
            for n, r in rows:
                if r["activity_pct"] - avg < -PEER_GAP_PP:
                    below.setdefault(n, []).append((i, r["activity_pct"], avg))
        for n, entries in below.items():
            latest = [e for e in entries if e[0] == last]
            if not latest:
                continue
            _, act, avg = latest[0]
            hits.append((len(entries), act - avg, [n, g["name"], f"{act:.0f}%", f"{avg:.0f}%", f"{act - avg:.0f} pts",
                                                   f"{len(entries)} of {len(months)}"]))
            if len(entries) >= 2:
                top.append((4 + len(entries), "👥", n, "Peer outlier",
                            f"{act:.0f}% activity vs {avg:.0f}% for {g['name']}, "
                            f"below peers {len(entries)} of {len(months)} months"))
    label = months[-1]["label"]
    out = [f"## Peer outliers (more than {PEER_GAP_PP:.0f} points below their group, {label})", ""]
    if not hits:
        out.append("None.")
    else:
        out += table(["Name", "Peer group", f"{label} activity", "Group avg", "Gap", "Months below"],
                     [r for _, _, r in sorted(hits, key=lambda x: (-x[0], x[1]))])
    return out, top


UNUSUAL_IGNORE = {"sustained_high_focus_time"}   # a positive signal, not a concern


def section_unusual(paths: list[Path], members_path: Path | None):
    rows = [ua for p in paths for ua in json.loads(p.read_text()).get("unusual_activities", [])]
    names = {}
    if members_path and members_path.exists():
        names = {u["id"]: u["name"] for u in json.loads(members_path.read_text()).get("users", [])}
    agg = {}
    for ua in rows:
        if ua["type"] in UNUSUAL_IGNORE or ua.get("confidence_level") == "low":
            continue
        a = agg.setdefault((ua["user_id"], ua["type"]), {"n": 0, "high": 0, "days": set()})
        a["n"] += 1
        a["high"] += ua.get("confidence_level") == "high"
        a["days"].add(ua["date"])
    out = ["## Unusual activity (medium/high confidence — review signals, not findings)", ""]
    top, rows = [], []
    for (uid, typ), a in sorted(agg.items(), key=lambda x: (-x[1]["high"], -x[1]["n"])):
        who = names.get(uid, uid)
        rows.append([who, typ.replace("_", " "), a["n"], len(a["days"]), a["high"]])
        if a["high"] >= 3:
            top.append((3, "🔎", who, "Unusual activity", f"{a['high']} high-confidence {typ.replace('_', ' ')} alerts"))
    out += table(["Name", "Alert type", "Alerts", "Days", "High confidence"], rows) if rows else ["No alerts in this window."]
    return out, top[:3]


def section_leave(paths: list[Path]):
    frames = [pd.read_csv(p, dtype=str) for p in paths]
    df = pd.concat(frames) if frames else pd.DataFrame()
    out = ["## Unapproved leave", ""]
    if df.empty or "status" not in df:
        return out + ["No time-off file passed."], []
    sub = df[df["status"] != "approved"]
    if sub.empty:
        return out + ["Every time-off request in this month is approved."], []
    sub = sub.assign(hours=sub["hours"].astype(float))
    rows = [[member, policy, f"{g['hours'].sum():.1f}h", len(g), g["status"].iloc[0]]
            for (member, policy), g in sub.groupby(["member", "policy_name"])]
    out += table(["Name", "Policy", "Hours", "Days", "Status"], rows)
    out.append("\n_Run the leave-approval-reminder skill to nudge approvers._")
    people = sub["member"].nunique()
    return out, [(2, "📝", f"{people} people", "Unapproved leave",
                  f"{sub['hours'].sum():.0f}h waiting for approval, reminders ready to send")]


def main():
    ap = argparse.ArgumentParser(description="People Ops Hubstaff review brief")
    ap.add_argument("--months", nargs=3, required=True, help="Three monthly master CSVs, oldest first")
    ap.add_argument("--salaried", default="", help="Comma-separated salaried names from ClickUp HR profiles")
    ap.add_argument("--skip", default="", help="Comma-separated offboarded/terminated names from ClickUp")
    ap.add_argument("--leave", nargs="*", default=[], help="TO-*.csv files for any of the months")
    ap.add_argument("--partial", help="Month-to-date HS-*_to_*.csv: adds an info-only column to the salaried table")
    ap.add_argument("--unusual", nargs="*", default=[], help="Raw MCP unusual-activities JSON pages")
    ap.add_argument("--members", help="Raw MCP members JSON (for unusual-activity names)")
    ap.add_argument("--section", choices=["salaried", "patterns", "peers", "unusual", "leave"])
    args = ap.parse_args()

    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]  # noqa: E731
    all_names = sorted({m for p in args.months for m in load_master_table(Path(p))["member"]})
    skip = {norm(n) for n in match_names(split(args.skip), all_names)[0].values()}
    months = load_months([Path(p) for p in args.months], skip)
    leave_paths = [Path(p) for p in args.leave]
    unpaid = load_unpaid_leave(leave_paths)
    leave_months = {re.search(r"TO-(\d{4}-\d{2})", p.name).group(1) for p in leave_paths}
    current = sorted({m for mo in months for m in mo["rows"]})
    sal_map, sal_unmatched = match_names(split(args.salaried), current)
    partial = load_partial(Path(args.partial), skip) if args.partial else None
    partial_map = match_names(list(sal_map), sorted(partial["rows"]))[0] if partial else None

    want = args.section
    detail, top = [], []

    def add(result):
        lines, items = result
        detail.extend(lines + [""])
        top.extend(items)

    if want in (None, "salaried"):
        if sal_map:
            add(section_salaried(months, sal_map, sal_unmatched, unpaid, leave_months, partial, partial_map))
        else:
            detail.extend(["## Salaried hours", "", "_No salaried list passed — pull it from the ClickUp HR profiles._", ""])
    if want in (None, "patterns"):
        add(section_patterns(months, set(sal_map.values())))
    if want in (None, "peers"):
        add(section_peers(months))
    if want in (None, "unusual") and args.unusual:
        add(section_unusual([Path(p) for p in args.unusual], Path(args.members) if args.members else None))
    if want in (None, "leave") and leave_paths:
        add(section_leave([p for p in leave_paths if months[-1]["start"].strftime("%Y-%m") in p.name]))

    span = f"{months[0]['start']:%b} – {months[-1]['start']:%b %Y}"
    out = [f"# Hubstaff review — {span}", ""]
    if want is None:
        # One row per person: highest priority wins the icon and rank, reasons are combined.
        people = {}
        for prio, icon, name, area, why in sorted(top, key=lambda x: -x[0]):
            p = people.setdefault(name, {"prio": prio, "icon": icon, "areas": [], "why": []})
            if p["areas"]:
                p["prio"] += 1   # flagged in more than one area: nudge up
            p["areas"].append(area)
            p["why"].append(why)
        ranked = sorted(people.items(), key=lambda x: -x[1]["prio"])
        rows = [[i, p["icon"], name, " + ".join(p["areas"]), "; ".join(p["why"])]
                for i, (name, p) in enumerate(ranked[:TOP_LIMIT], 1)]
        out += ["## Discuss today", ""] + table(["#", "", "Name", "Area", "Why"], rows)
        if len(ranked) > TOP_LIMIT:
            out.append(f"\n_{len(ranked) - TOP_LIMIT} more in the detail below._")
        out += ["", "---", ""]
    print("\n".join(out + detail))


if __name__ == "__main__":
    main()
