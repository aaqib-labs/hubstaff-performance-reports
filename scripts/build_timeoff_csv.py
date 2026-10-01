from __future__ import annotations

"""
WebLife Ventures — Time-Off CSV Builder
========================================
Turns raw Hubstaff time-off JSON (saved byte-for-byte from the Hubstaff MCP)
into a clean per-day CSV for the month-end report.

Usage:
    python scripts/build_timeoff_csv.py \
        --raw data/input/timeoff/raw/TO-RAW-2026-09-01_to_2026-09-30_*.json \
        --start 2026-09-01 --end 2026-09-30 \
        --out data/input/timeoff/TO-2026-09-01_to_2026-09-30.csv

Output columns (one row per request per day):
    member, hubstaff_user_id, request_id, policy_id, policy_name,
    category, status, date, hours

Rules (see plans/month-end-leave-breakdown-plan.md §4):
    - category comes from the POLICY-level `paid` flag, never the request-level one
    - submitted → unapproved; denied / cancelled are dropped
    - only days with start ≤ date ≤ end are kept; 0-hour days are dropped
    - de-duplicated on (request_id, date)
    - leave messages / responses are NEVER written out

A sidecar <out>.meta.json records the pull timestamp for the report header.
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

CATEGORY_PAID   = "Paid/Allocated"
CATEGORY_UNPAID = "Unpaid/Flex"

STATUS_MAP = {
    "approved":  "approved",
    "submitted": "unapproved",
    "pending":   "unapproved",
}
DROPPED_STATUSES = {"denied", "cancelled", "canceled"}

MAX_DAY_HOURS = 8.0

OUT_COLUMNS = [
    "member", "hubstaff_user_id", "request_id", "policy_id", "policy_name",
    "category", "status", "date", "hours",
]


def load_raw(paths: list[Path]) -> tuple[dict, dict, dict]:
    """Merge requests, users and policies across every page and file."""
    requests: dict[int, dict] = {}
    users:    dict[int, dict] = {}
    policies: dict[int, dict] = {}
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        for r in data.get("time_off_requests", []) or []:
            requests[r["id"]] = r
        for u in data.get("users", []) or []:
            users[u["id"]] = u
        for pol in data.get("time_off_policies", []) or []:
            policies[pol["id"]] = pol
    return requests, users, policies


def build_rows(requests: dict, users: dict, policies: dict,
               start: date, end: date) -> tuple[list[dict], list[str], dict]:
    """Return (rows, errors, stats)."""
    errors: list[str] = []
    stats = {
        "status_counts":    defaultdict(int),
        "dropped_requests": defaultdict(int),
        "zero_hour_days":   0,
        "out_of_range_days": 0,
        "duplicate_days":   0,
    }
    rows: list[dict] = []
    seen: set[tuple[int, str]] = set()

    for req in sorted(requests.values(), key=lambda r: r["id"]):
        raw_status = str(req.get("status", "")).lower()
        if raw_status in DROPPED_STATUSES:
            stats["dropped_requests"][raw_status] += 1
            continue
        if raw_status not in STATUS_MAP:
            errors.append(f"request {req['id']}: unknown status '{raw_status}'")
            continue
        status = STATUS_MAP[raw_status]

        pol = policies.get(req["time_off_policy_id"])
        if not pol or not pol.get("name") or not isinstance(pol.get("paid"), bool):
            errors.append(f"request {req['id']}: policy {req['time_off_policy_id']} "
                          f"has no name or paid flag — look it up, don't guess")
            continue
        category = CATEGORY_PAID if pol["paid"] else CATEGORY_UNPAID

        user = users.get(req["user_id"])
        name = (user or {}).get("name") or ""
        if not name.strip():
            errors.append(f"request {req['id']}: user {req['user_id']} has no name")
            continue

        kept_any = False
        for day in req.get("time_off_request_days", []) or []:
            d = date.fromisoformat(day["date"])
            if not (start <= d <= end):
                stats["out_of_range_days"] += 1
                continue
            amount = day.get("amount_used") or 0
            if amount == 0:
                stats["zero_hour_days"] += 1
                continue
            key = (req["id"], day["date"])
            if key in seen:
                stats["duplicate_days"] += 1
                continue
            seen.add(key)
            kept_any = True
            rows.append({
                "member":           name.strip(),
                "hubstaff_user_id": req["user_id"],
                "request_id":       req["id"],
                "policy_id":        pol["id"],
                "policy_name":      pol["name"],
                "category":         category,
                "status":           status,
                "date":             day["date"],
                "hours":            round(amount / 3600, 2),
            })
        if kept_any:
            stats["status_counts"][status] += 1

    rows.sort(key=lambda r: (r["member"].lower(), r["date"], r["request_id"]))
    return rows, errors, stats


def validate(rows: list[dict]) -> list[str]:
    """Return WARN messages (see plan §4 Validation)."""
    warns: list[str] = []
    per_member_day: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"approved": 0.0, "unapproved": 0.0, "requests": set()})
    for r in rows:
        if r["hours"] > MAX_DAY_HOURS:
            warns.append(f"{r['member']}, {r['date']}: {r['hours']:.1f}h on a single request-day "
                         f"({r['status']}, {r['policy_name']}, request {r['request_id']})")
        md = per_member_day[(r["member"], r["date"])]
        md[r["status"]] += r["hours"]
        md["requests"].add(r["request_id"])
    for (member, d), h in sorted(per_member_day.items()):
        if h["approved"] > 0 and h["unapproved"] > 0:
            warns.append(f"{member}, {d}: approved ({h['approved']:.1f}h) and unapproved "
                         f"({h['unapproved']:.1f}h) requests on the same date — possible duplicate")
        total = h["approved"] + h["unapproved"]
        if len(h["requests"]) > 1 and total > MAX_DAY_HOURS:
            warns.append(f"{member}, {d}: {len(h['requests'])} requests add up to {total:.1f}h "
                         f"(> {MAX_DAY_HOURS:.0f}h)")
    return warns


def print_summary(rows: list[dict], stats: dict) -> None:
    print("-" * 60)
    print("Requests kept by status:")
    for s in ("approved", "unapproved"):
        members = {r["member"] for r in rows if r["status"] == s}
        hours   = sum(r["hours"] for r in rows if r["status"] == s)
        print(f"  {s:<11} {stats['status_counts'][s]:>3} requests · {len(members):>2} members · {hours:.1f}h")
    for s, n in sorted(stats["dropped_requests"].items()):
        print(f"  dropped ({s}): {n} request(s)")
    print(f"Days outside period trimmed: {stats['out_of_range_days']}")
    print(f"Zero-hour days dropped (weekends inside ranges): {stats['zero_hour_days']}")
    print(f"Duplicate (request, date) rows dropped: {stats['duplicate_days']}")

    print("Hours by category × status:")
    cat = defaultdict(float)
    for r in rows:
        cat[(r["category"], r["status"])] += r["hours"]
    for c in (CATEGORY_PAID, CATEGORY_UNPAID):
        print(f"  {c:<15} approved {cat[(c, 'approved')]:>6.1f}h · unapproved {cat[(c, 'unapproved')]:>6.1f}h")

    print("Hours by exact policy × status:")
    pol = defaultdict(float)
    for r in rows:
        pol[(r["policy_name"], r["category"], r["status"])] += r["hours"]
    for (name, c, s), h in sorted(pol.items(), key=lambda kv: (kv[0][2], -kv[1])):
        print(f"  [{s:<10}] {name:<48} {c:<15} {h:>6.1f}h")
    print("-" * 60)


def write_csv(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({**r, "hours": f"{r['hours']:.2f}"})


def main():
    parser = argparse.ArgumentParser(description="Build the per-day time-off CSV from raw Hubstaff JSON.")
    parser.add_argument("--raw", nargs="+", required=True, help="Raw JSON files (all pages + policies)")
    parser.add_argument("--start", required=True, help="Period start YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Period end YYYY-MM-DD")
    parser.add_argument("--out", required=True, help="Output CSV path")
    parser.add_argument("--pulled-at", default=None,
                        help="When the raw data was pulled (ISO). Default: newest raw file mtime.")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    paths = [Path(p) for p in args.raw]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print(f"ERROR: raw file(s) not found: {missing}", file=sys.stderr)
        sys.exit(1)

    requests, users, policies = load_raw(paths)
    print(f"Loaded {len(requests)} requests, {len(users)} users, {len(policies)} policies "
          f"from {len(paths)} file(s).")

    rows, errors, stats = build_rows(requests, users, policies, start, end)
    warns = validate(rows)
    print_summary(rows, stats)

    for w in warns:
        print(f"WARN: {w}")
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    if errors:
        print(f"{len(errors)} error(s) — CSV not written.", file=sys.stderr)
        sys.exit(1)

    out = Path(args.out)
    write_csv(rows, out)

    if args.pulled_at:
        pulled_at = args.pulled_at
    else:
        newest = max(p.stat().st_mtime for p in paths)
        pulled_at = datetime.fromtimestamp(newest, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {"pulled_at": pulled_at, "start": start.isoformat(), "end": end.isoformat(),
            "rows": len(rows), "warnings": len(warns)}
    Path(str(out) + ".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"Wrote {len(rows)} rows → {out}  (pulled at {pulled_at}, {len(warns)} warning(s))")


if __name__ == "__main__":
    main()
