from __future__ import annotations

"""
WebLife Ventures — Role-Based Peer Comparison Report
=====================================================
Compares each employee against their functional peer group for a given month.
Shows team averages, variance from average, SLA flags, and outliers.

Usage:
    python scripts/generate_peer_comparison.py \
        --input data/input/monthly/HS-2026-03-master.csv \
        --start 2026-03-01 --end 2026-03-31

Output:
    docs/YYYY-MM-DD_to_YYYY-MM-DD_peer_comparison.html
    docs/index.html  (updated)
"""

import argparse
import calendar
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).parent))

from utils import (
    ACTIVITY_RED, ACTIVITY_YELLOW,
    BREAK_RED, BREAK_YELLOW,
    DOCS_DIR,
    LOW20_RED, LOW20_YELLOW,
    LOW30_RED, LOW30_YELLOW,
    MANUAL_RED, MANUAL_YELLOW,
    PERMANENT_EXCLUSIONS,
    calculate_prorated_thresholds,
    load_master_table,
)

REPO_ROOT     = Path(__file__).parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"

# ---------------------------------------------------------------------------
# New hires still in onboarding — flagged with context note in report
# ---------------------------------------------------------------------------
NEW_HIRES = {
    "nishantha hettiarachchi",
    "shen perera",
    "farshad ramsee",
    "prajwal kumar",
    "jomal mathew",
    "ibrahim adeeb",
    "akram khan",
}

# ---------------------------------------------------------------------------
# Peer Group Definitions
# Member names must match the Hubstaff CSV (case-insensitive matching used)
# manager: name of manager within group, or None (for leadership / cross-group)
# manager_label: shown in header when manager is not a member of this group
# ---------------------------------------------------------------------------
PEER_GROUPS = [
    {
        "id":            "leadership",
        "name":          "Leadership / Senior Level",
        "team_code":     "Executive & Senior Management",
        "manager":       None,
        "manager_label": None,
        "members": [
            "Lucas Robinson",
            "jorn wossner",
            "Adam Burdeshaw",
            "Eden Schweyer",
            "Fred Butson",
            "Saduka Sachintha",
        ],
    },
    {
        "id":            "dp_engineering",
        "name":          "Digital Product — Engineering",
        "team_code":     "DP-PLATFORM / DP-CRM",
        "manager":       "Adam Burdeshaw",
        "manager_label": None,
        "members": [
            "Adam Burdeshaw",
            "Dr. Yashoda Velananda",
            "Thushan Fernando",
            "Hasala Jayasuriya",
            "Upeksha Liyanage",
            "Nishantha Hettiarachchi",
            "Muhammad Usman",
            "Chathuranga Weerakoon",
            "Kianna Xue",
        ],
    },
    {
        "id":            "dp_site_content",
        "name":          "Digital Product — Site Content",
        "team_code":     "DP-SITECONTENT",
        "manager":       "Shehara Meadows",
        "manager_label": None,
        "members": [
            "Shehara Meadows",
            "Ramez Sedra",
            "Kunchana Prabashwara",
        ],
    },
    {
        "id":            "dp_catalog",
        "name":          "Digital Product — Catalog",
        "team_code":     "DP-CATALOG",
        "manager":       "Laleesha Wijeratne",
        "manager_label": None,
        "members": [
            "Laleesha Wijeratne",
            "Jomal Mathew",
        ],
    },
    {
        "id":            "dp_bi_data",
        "name":          "Digital Product — BI & Data",
        "team_code":     "DP-BI",
        "manager":       "Bihani Madushika",
        "manager_label": None,
        "members": [
            "Bihani Madushika",
            "Modhuka Paranagama",
            "Dilini Pathirana",
        ],
    },
    {
        "id":            "venia_cam",
        "name":          "Venia — Commercial Accounts",
        "team_code":     "VP-CO-CAM",
        "manager":       "Shannon Woods",
        "manager_label": None,
        "members": [
            "Shannon Woods",
            "Meredith Goostree",
            "Jesus Corral",
            "Monica Lopez",
        ],
    },
    {
        "id":            "venia_cr",
        "name":          "Venia — Customer Relations",
        "team_code":     "VP-CO-CR",
        "manager":       "Darren Karunaratne",
        "manager_label": None,
        "members": [
            "Darren Karunaratne",
            "Ounvin Ranaweera",
            "leora megan",
        ],
    },
    {
        "id":            "venia_cs",
        "name":          "Venia — Customer Support",
        "team_code":     "VP-CO-CS",
        "manager":       "Sara Higgason",
        "manager_label": None,
        "members": [
            "Sara Higgason",
            "Christine Mayol",
            "Mary Anne Soriano",
            "Joan Lopez",
            "Ma Aubrey Sustento",
            "Andrés Victoriano",
            "Vincent Deximo",
        ],
    },
    {
        "id":            "venia_op",
        "name":          "Venia — Order Processing",
        "team_code":     "VP-CO-OP",
        "manager":       "Rebecca Corona",
        "manager_label": None,
        "members": [
            "Rebecca Corona",
            "Shenallie Jayathillake",
            "Erandi Bandaranayake",
            "Subashi Silva",
            "Carmen Santos",
        ],
    },
    {
        "id":            "venia_sdr",
        "name":          "Venia — Sales Development",
        "team_code":     "VP-CO-SDR",
        "manager":       "Denise Marsha Elisa Moscare",
        "manager_label": None,
        "members": [
            "Denise Marsha Elisa Moscare",
            "Kristine Anne Dela Cruz",
            "Caryl Agamao",
            "Farhanah Junainah Umpar",
            "Sarah Madoro",
        ],
    },
    {
        "id":            "task_agency",
        "name":          "Task Agency",
        "team_code":     "TA-OPS / TA-PO / TA-TS",
        "manager":       "Sean Dehoedt",
        "manager_label": None,
        "members": [
            "Sean Dehoedt",
            "Jason Diaz",
            "Aaqib Hafeel",
            "Nawodya De Silva",
            "Tashia Bernardus",
            "Staffey Murugadas",
            "Shen Perera",
        ],
    },
    {
        "id":            "mkt_media",
        "name":          "Marketing — Media & Social",
        "team_code":     "MKT-MEDIA",
        "manager":       "Rannie Belen",
        "manager_label": None,
        "members": [
            "Rannie Belen",
            "Ransika Kalutharage",
            "Anna May Rubia",
        ],
    },
    {
        "id":            "mkt_design_video",
        "name":          "Marketing — Designers & Video",
        "team_code":     "MKT-MEDIA (Creative)",
        "manager":       None,
        "manager_label": "Rannie Belen",
        "members": [
            "Rishonath Siva",
            "Kawya Samarasinghe",
            "sanjula paulis",
            "Farshad Ramsee",
        ],
    },
    {
        "id":            "mkt_performance",
        "name":          "Marketing — Performance & Amazon",
        "team_code":     "MKT-AMAZON / MKT-PERFMKT / MKT-RGC",
        "manager":       "Saduka Sachintha",
        "manager_label": None,
        "members": [
            "Saduka Sachintha",
            "Hafiz Mudasir",
            "shenali edirisinghe",
            "Prajwal Kumar",
            "Sasindee Wijeratne",
            "Unaiza Imran",
        ],
    },
    {
        "id":            "finance",
        "name":          "Accounting & Finance",
        "team_code":     "FIN-ACC",
        "manager":       "Laci Burton",
        "manager_label": None,
        "members": [
            "Laci Burton",
            "Melanie Joy Pecaña",
            "Irene Padilla",
            "Dharshika Perera",
        ],
    },
    {
        "id":            "allintalent",
        "name":          "Recruitment — allintalent",
        "team_code":     "AiT-CLIENT / AiT-CANDIDATE",
        "manager":       "Kushani Kalpage",
        "manager_label": None,
        "members": [
            "Kushani Kalpage",
            "Menara Kahatapitiya",
            "Nireshwaran Aravinth",
            "Krishanthiny Krishnaraj",
            "Natalia Jayasundera",
            "Rasma Rizwan",
        ],
    },
    {
        "id":            "framework_friday",
        "name":          "Framework Friday — L&D",
        "team_code":     "FF-L&D",
        "manager":       "Jebby Rochelle",
        "manager_label": None,
        "members": [
            "Jebby Rochelle",
            "Fred Butson",
        ],
    },
]


# ---------------------------------------------------------------------------
# SLA flag evaluation
# ---------------------------------------------------------------------------

def _get_flags(row: pd.Series, prorated_red: float, prorated_orange: float) -> dict:
    """Return per-metric status dict."""
    def classify_act(v):
        if pd.isna(v): return None
        return "red" if v < ACTIVITY_RED else ("yellow" if v < ACTIVITY_YELLOW else None)

    def classify_hours(v):
        if pd.isna(v): return None
        return "red" if v < prorated_red else ("orange" if v >= prorated_orange else None)

    def classify_high(v, red_t, yel_t):
        if pd.isna(v): return None
        return "red" if v >= red_t else ("yellow" if v >= yel_t else None)

    return {
        "A":  classify_act(row.get("activity_pct")),
        "H":  classify_hours(row.get("total_hours")),
        "B":  classify_high(row.get("break_pct"),  BREAK_RED,  BREAK_YELLOW),
        "M":  classify_high(row.get("manual_pct"),  MANUAL_RED, MANUAL_YELLOW),
        "20": classify_high(row.get("low20_pct"),   LOW20_RED,  LOW20_YELLOW),
        "30": classify_high(row.get("low30_pct"),   LOW30_RED,  LOW30_YELLOW),
    }


def _count_flags(flags: dict) -> tuple[int, int]:
    """(red+orange count, yellow count). B yellow excluded from display count."""
    red = sum(1 for m, s in flags.items() if s in ("red", "orange"))
    yel = sum(1 for m, s in flags.items() if s == "yellow" and m != "B")
    return red, yel


def _flags_badge(flags: dict) -> str:
    red, yel = _count_flags(flags)
    parts = []
    if red: parts.append(f"🔴 {red}" if sum(1 for s in flags.values() if s == "red") == red else f"🟠 {red}")
    # refine: separate red and orange
    r = sum(1 for s in flags.values() if s == "red")
    o = sum(1 for s in flags.values() if s == "orange")
    parts = []
    if r: parts.append(f"🔴 {r}")
    if o: parts.append(f"🟠 {o}")
    if yel: parts.append(f"⚠️ {yel}")
    return " ".join(parts) if parts else "—"


STATUS_ICON = {"red": "🔴", "orange": "🟠", "yellow": "⚠️"}


def _fmt_metric(val, status, suffix="%", decimals=1) -> str:
    if pd.isna(val): return "—"
    icon = STATUS_ICON.get(status, "")
    s = f"{val:.{decimals}f}{suffix}"
    return f"{icon} {s}".strip() if icon else s


def _fmt_hours(val, status) -> str:
    if pd.isna(val): return "—"
    icon = STATUS_ICON.get(status, "")
    s = f"{val:.1f}h"
    return f"{icon} {s}".strip() if icon else s


# ---------------------------------------------------------------------------
# Build group data
# ---------------------------------------------------------------------------

def build_group(
    group_def: dict,
    df: pd.DataFrame,
    prorated_red: float,
    prorated_orange: float,
) -> dict | None:
    """
    Match group members to CSV rows, compute averages and variances.
    Returns None if fewer than 2 members found in CSV.
    """
    norm_members = {n.lower().strip(): n for n in group_def["members"]}
    manager_norm = group_def["manager"].lower().strip() if group_def["manager"] else None

    # Build display name lookup from CSV
    csv_lookup: dict[str, pd.Series] = {}
    csv_display: dict[str, str] = {}
    for _, row in df.iterrows():
        norm = row["member"].lower().strip()
        if norm in norm_members:
            csv_lookup[norm] = row
            csv_display[norm] = row["member"]

    if len(csv_lookup) < 2:
        return None

    # Compute team averages (only from members present in CSV)
    metrics = ["activity_pct", "total_hours", "manual_pct", "break_pct", "low20_pct", "low30_pct"]
    avgs: dict[str, float] = {}
    for m in metrics:
        vals = [csv_lookup[n].get(m, float("nan")) for n in csv_lookup if not pd.isna(csv_lookup[n].get(m, float("nan")))]
        avgs[m] = sum(vals) / len(vals) if vals else float("nan")

    # Build member rows
    manager_row = None
    other_rows  = []

    for norm_name, row in csv_lookup.items():
        display = csv_display[norm_name]
        flags   = _get_flags(row, prorated_red, prorated_orange)
        red_c, yel_c = _count_flags(flags)

        activity  = row.get("activity_pct", float("nan"))
        variance  = (activity - avgs["activity_pct"]) if not pd.isna(activity) and not pd.isna(avgs["activity_pct"]) else float("nan")

        # Outlier detection: flagged by peer context even if no SLA violation
        peer_outlier = (
            not pd.isna(variance)
            and flags["A"] is None          # no SLA flag
            and variance < -10              # >10pp below team avg
        )

        def _status_class(s): return s if s else "clean"

        member_data = {
            "display":          display,
            "is_manager":       norm_name == manager_norm,
            "is_new_hire":      norm_name in NEW_HIRES,
            "is_peer_outlier":  peer_outlier,
            "activity":         _fmt_metric(activity, flags["A"]),
            "activity_status":  _status_class(flags["A"]),
            "activity_raw":     activity,
            "variance":         variance,
            "variance_fmt":     f"+{variance:.1f}pts" if variance > 0 else f"{variance:.1f}pts" if not pd.isna(variance) else "—",
            "variance_class":   "var-pos" if variance > 0 else ("var-neg" if variance < -5 else "var-neutral") if not pd.isna(variance) else "var-neutral",
            "hours":            _fmt_hours(row.get("total_hours"), flags["H"]),
            "hours_status":     _status_class(flags["H"]),
            "manual":           _fmt_metric(row.get("manual_pct"), flags["M"]),
            "manual_status":    _status_class(flags["M"]),
            "break_pct":        _fmt_metric(row.get("break_pct"), flags["B"]),
            "break_status":     _status_class(flags["B"]),
            "low20":            _fmt_metric(row.get("low20_pct"), flags["20"]),
            "low20_status":     _status_class(flags["20"]),
            "low30":            _fmt_metric(row.get("low30_pct"), flags["30"]),
            "low30_status":     _status_class(flags["30"]),
            "flags_badge":      _flags_badge(flags),
            "red_count":        red_c,
            "yel_count":        yel_c,
            "total_flags":      red_c + yel_c,
        }

        if norm_name == manager_norm:
            manager_row = member_data
        else:
            other_rows.append(member_data)

    # Sort non-managers: flagged first (desc total flags), then by activity desc
    other_rows.sort(key=lambda r: (-r["total_flags"], -(r["activity_raw"] or 0)))

    # Manager always first
    rows = ([manager_row] if manager_row else []) + other_rows

    # Team average row
    avg_row = {
        "activity": f"{avgs['activity_pct']:.1f}%" if not pd.isna(avgs["activity_pct"]) else "—",
        "hours":    f"{avgs['total_hours']:.1f}h"   if not pd.isna(avgs["total_hours"])  else "—",
        "manual":   f"{avgs['manual_pct']:.1f}%"    if not pd.isna(avgs["manual_pct"])   else "—",
        "break_pct":f"{avgs['break_pct']:.1f}%"     if not pd.isna(avgs["break_pct"])    else "—",
        "low20":    f"{avgs['low20_pct']:.1f}%"     if not pd.isna(avgs["low20_pct"])    else "—",
        "low30":    f"{avgs['low30_pct']:.1f}%"     if not pd.isna(avgs["low30_pct"])    else "—",
    }

    # Members not found in CSV (absent this month)
    absent = [norm_members[n] for n in norm_members if n not in csv_lookup]

    return {
        "id":            group_def["id"],
        "name":          group_def["name"],
        "team_code":     group_def["team_code"],
        "manager_name":  group_def["manager"] or group_def.get("manager_label"),
        "member_count":  len(rows),
        "rows":          rows,
        "avg_row":       avg_row,
        "absent":        absent,
        "has_violations": any(r["total_flags"] > 0 for r in rows),
    }


# ---------------------------------------------------------------------------
# Build full report context
# ---------------------------------------------------------------------------

def build_context(
    df: pd.DataFrame,
    groups: list[dict],
    start: date,
    end: date,
    prorated_red: float,
    prorated_orange: float,
) -> dict:
    month_label = start.strftime("%B %Y")

    # Summary stats
    total_members     = sum(g["member_count"] for g in groups)
    total_flagged     = sum(1 for g in groups for r in g["rows"] if r["total_flags"] > 0)
    total_peer_outliers = sum(1 for g in groups for r in g["rows"] if r["is_peer_outlier"])

    return {
        "report_title":       "Role-Based Peer Comparison Report",
        "month_label":        month_label,
        "date_range":         f"{start.strftime('%B %d, %Y')} — {end.strftime('%B %d, %Y')}",
        "start_date":         start.isoformat(),
        "end_date":           end.isoformat(),
        "generated_at":       pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "prorated_red":       f"{prorated_red:.0f}h",
        "prorated_orange":    f"{prorated_orange:.0f}h",
        "total_groups":       len(groups),
        "total_members":      total_members,
        "total_flagged":      total_flagged,
        "total_peer_outliers": total_peer_outliers,
        "groups":             groups,
    }


# ---------------------------------------------------------------------------
# Render + write
# ---------------------------------------------------------------------------

def render_report(context: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    return env.get_template("peer_comparison_template.html").render(**context)


def write_report(html: str, start: date, end: date) -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCS_DIR / f"{start.isoformat()}_to_{end.isoformat()}_peer_comparison.html"
    path.write_text(html, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate role-based peer comparison report.")
    parser.add_argument("--input",  required=True, help="Path to monthly Hubstaff master CSV")
    parser.add_argument("--start",  required=True, help="Month start YYYY-MM-DD")
    parser.add_argument("--end",    required=True, help="Month end YYYY-MM-DD")
    args = parser.parse_args()

    start    = date.fromisoformat(args.start)
    end      = date.fromisoformat(args.end)
    csv_path = Path(args.input)

    if not csv_path.exists():
        print(f"ERROR: File not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    prorated_red, prorated_orange = calculate_prorated_thresholds(start, end)

    print("=" * 60)
    print(f"Peer Comparison Report: {start.strftime('%B %Y')}")
    print(f"Hours thresholds: red < {prorated_red:.0f}h | orange ≥ {prorated_orange:.0f}h")
    print("=" * 60)

    df = load_master_table(csv_path)
    excl = set(n.lower() for n in PERMANENT_EXCLUSIONS)
    df   = df[~df["member"].apply(lambda n: n.lower().strip() in excl)].reset_index(drop=True)
    print(f"Employees loaded: {len(df)}")

    groups = []
    for i, grp_def in enumerate(PEER_GROUPS, 1):
        result = build_group(grp_def, df, prorated_red, prorated_orange)
        if result is None:
            print(f"  [{i:02d}] {grp_def['name']:<45} SKIPPED (< 2 members found)")
            continue
        absent_note = f" | {len(result['absent'])} absent" if result["absent"] else ""
        print(f"  [{i:02d}] {grp_def['name']:<45} {result['member_count']} members{absent_note}")
        result["num"] = len(groups) + 1
        groups.append(result)

    context   = build_context(df, groups, start, end, prorated_red, prorated_orange)
    html      = render_report(context)
    docs_path = write_report(html, start, end)
    print(f"Report written: {docs_path}")

    import update_index as ui
    ui.regenerate_index()
    print(f"Index updated:  {DOCS_DIR / 'index.html'}")
    print("Done.")


if __name__ == "__main__":
    main()
