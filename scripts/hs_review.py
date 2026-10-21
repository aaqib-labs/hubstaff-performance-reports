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
from utils import HOURS_BASE, HOURS_OVERWORK_BASE, evaluate_flags, get_exclusions, load_master_table  # noqa: E402
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
    """Map each wanted (ClickUp) name to a CSV member name: exact, first+last
    token, token subset, then close spelling. Returns (mapping, unmatched)."""
    by_norm = {norm(a): a for a in available}
    mapping, unmatched = {}, []
    for w in wanted:
        n = norm(w)
        wt = n.split()
        if n in by_norm:
            mapping[w] = by_norm[n]
            continue
        cands = [a for k, a in by_norm.items() if k.split()[0] == wt[0] and k.split()[-1] == wt[-1]]
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


# ---------------------------------------------------------------------------
# Sections — each returns (detail lines, [(priority, top bullet), ...])
# ---------------------------------------------------------------------------

def section_salaried(months, mapping: dict, unmatched: list, unpaid: dict, leave_months: set):
    serious, alert, new, lead, top = [], [], [], [], []
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
        trail = " / ".join(f"{mo['label']} {h:.0f}h" if h is not None else f"{mo['label']} —"
                           for mo, h in zip(months, hours))
        if norm(sal_name) in LEADERSHIP:
            lead.append(f"{sal_name} ({trail})")
            continue
        if all(h is None for h in hours[:-1]):
            if latest < SALARIED_FLOOR:
                new.append(f"{sal_name} ({months[-1]['label']} {latest:.0f}h)")
            continue
        gaps = [SALARIED_TARGET - h for h in hours if h is not None and h < SALARIED_FLOOR]
        avg_gap = sum(gaps) / len(gaps) if gaps else 0
        if under >= 2:
            serious.append((under, avg_gap, f"**{sal_name}** — {trail}. Under {SALARIED_FLOOR:.0f}h in {under} of "
                                            f"{len(months)} months, about {avg_gap:.0f}h short of {SALARIED_TARGET:.0f}h on average."))
            top.append((10 + under, f"🔴 **{sal_name}** (salaried) — under {SALARIED_FLOOR:.0f}h in {under} of "
                                    f"{len(months)} months: {trail}"))
        elif latest < SALARIED_FLOOR:
            alert.append((avg_gap, f"**{sal_name}** — {trail}. First month under {SALARIED_FLOOR:.0f}h "
                                   f"({SALARIED_TARGET - latest:.0f}h short of {SALARIED_TARGET:.0f}h)."))
            top.append((5, f"⚠️ **{sal_name}** (salaried) — first month under {SALARIED_FLOOR:.0f}h: {trail}"))

    out = [f"## Salaried hours (target {SALARIED_TARGET:.0f}h, flag under {SALARIED_FLOOR:.0f}h)", ""]
    if not serious and not alert:
        out.append(f"No salaried staff under {SALARIED_FLOOR:.0f}h in {months[-1]['label']}.")
    out += [f"- 🔴 Serious: {l}" for _, _, l in sorted(serious, key=lambda x: (-x[0], -x[1]))]
    out += [f"- ⚠️ Alert: {l}" for _, l in sorted(alert, key=lambda x: -x[0])]
    if new:
        out.append(f"\n_New this period, first month is partial (not flagged): {', '.join(new)}._")
    if lead:
        out.append(f"\n_Leadership, not ranked: {'; '.join(lead)}._")
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
        team = latest_rows[name]["team"]
        parts = [f"{PATTERN_METRICS[k]} {c}/{len(months)}" + ("" if latest_flags.get(k) == "red" else " (ok last month)")
                 for k, c in sorted(repeat.items(), key=lambda x: -x[1])]
        hits.append((max(repeat.values()), len(repeat), f"**{name}** ({team}) — red on {', '.join(parts)}"))
        full = [k for k, c in repeat.items() if c == len(months) and latest_flags.get(k) == "red"]
        if full:
            top.append((8 + len(full), f"🔴 **{name}** — red every month on "
                                       f"{', '.join(PATTERN_METRICS[k] for k in full)}"))
    out = [f"## Repeat SLA patterns (red in 2+ of the last {len(months)} months)", ""]
    if not hits:
        out.append("None.")
    out += [f"- {l}" for _, _, l in sorted(hits, key=lambda x: (-x[0], -x[1]))]
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
            hits.append((len(entries), f"**{n}** ({g['name']}) — {act:.0f}% vs group average {avg:.0f}% "
                                       f"in {months[-1]['label']}; below peers {len(entries)} of {len(months)} months"))
            if len(entries) >= 2:
                top.append((4 + len(entries), f"👥 **{n}** — {act:.0f}% activity vs {avg:.0f}% for "
                                              f"{g['name']}, below peers {len(entries)} of {len(months)} months"))
    out = [f"## Peer outliers (more than {PEER_GAP_PP:.0f} points below their group, {months[-1]['label']})", ""]
    if not hits:
        out.append("None.")
    out += [f"- {l}" for _, l in sorted(hits, key=lambda x: -x[0])]
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
    top = []
    if not agg:
        out.append("No alerts in this window.")
    for (uid, typ), a in sorted(agg.items(), key=lambda x: (-x[1]["high"], -x[1]["n"])):
        who = names.get(uid, uid)
        out.append(f"- **{who}** — {typ.replace('_', ' ')}: {a['n']} alerts on {len(a['days'])} days, "
                   f"{a['high']} high confidence")
        if a["high"] >= 3:
            top.append((3, f"🔎 **{who}** — {a['high']} high-confidence {typ.replace('_', ' ')} alerts"))
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
    for (member, policy), g in sub.groupby(["member", "policy_name"]):
        out.append(f"- **{member}** — {policy}: {g['hours'].sum():.1f}h over {len(g)} days, still {g['status'].iloc[0]}")
    out.append("\n_Run the leave-approval-reminder skill to nudge approvers._")
    people = sub["member"].nunique()
    return out, [(2, f"📝 {people} people have unapproved leave ({sub['hours'].sum():.0f}h) — reminders ready to send")]


def main():
    ap = argparse.ArgumentParser(description="People Ops Hubstaff review brief")
    ap.add_argument("--months", nargs=3, required=True, help="Three monthly master CSVs, oldest first")
    ap.add_argument("--salaried", default="", help="Comma-separated salaried names from ClickUp HR profiles")
    ap.add_argument("--skip", default="", help="Comma-separated offboarded/terminated names from ClickUp")
    ap.add_argument("--leave", nargs="*", default=[], help="TO-*.csv files for any of the months")
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

    want = args.section
    detail, top = [], []

    def add(result):
        lines, items = result
        detail.extend(lines + [""])
        top.extend(items)

    if want in (None, "salaried"):
        if sal_map:
            add(section_salaried(months, sal_map, sal_unmatched, unpaid, leave_months))
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
        ranked = sorted(top, key=lambda x: -x[0])
        out += ["## Discuss today", ""] + [f"{i}. {t}" for i, (_, t) in enumerate(ranked[:TOP_LIMIT], 1)]
        if len(ranked) > TOP_LIMIT:
            out.append(f"\n_{len(ranked) - TOP_LIMIT} more in the detail below._")
        out += ["", "---", ""]
    print("\n".join(out + detail))


if __name__ == "__main__":
    main()
