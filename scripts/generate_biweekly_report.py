"""
WebLife Ventures — Bi-Weekly Performance Report Generator
==========================================================
Generates a ranked HTML performance report from a Hubstaff master table CSV.

Usage:
    python scripts/generate_biweekly_report.py \
        --input data/input/master_table.csv \
        --start 2026-03-01 \
        --end 2026-03-11

Outputs:
    docs/<start>_to_<end>_biweekly_top_violators.html
    docs/index.html  (updated)

Severity Scoring Formula
-------------------------
Base points:
    Red    (🔴) = 10
    Yellow (⚠️) =  3
    Orange (🟠) =  7

Metric multipliers (reflecting violation priority hierarchy):
    A  (Activity %)       → 5×
    M  (Manual %)         → 4×
    H  (Low Hours 🔴)     → 3×
    H  (Overwork 🟠)      → 2×
    20 (Low Act ≤20%)     → 2×
    30 (Low Act ≤30%)     → 1.5×
    B  (Break %)          → 1×

Score = sum of (base_pts × multiplier) for all flags on an employee.
Break time (B) contributes to score but is excluded from displayed flag count.

Hours Proration
---------------
prorated_red    = (working_days_in_period / working_days_in_month) × 160
prorated_orange = (working_days_in_period / working_days_in_month) × 200
Working days = Monday–Friday only.
Note: US holidays and approved time-off are already included in Hubstaff
Total Worked Hours — no further exclusion is needed here.
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader

from utils import (
    calculate_prorated_thresholds,
    count_working_days,
    get_month_working_days,
    print_threshold_header,
    DOCS_DIR,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT     = Path(__file__).parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"

# ---------------------------------------------------------------------------
# SLA Thresholds (authoritative — matches data/reference/sla_violation_legend.md)
# ---------------------------------------------------------------------------
ACTIVITY_RED = 35.0       # Activity % < 35 → red
ACTIVITY_YELLOW = 45.0    # Activity % < 45 → yellow

BREAK_RED = 12.0          # Break % ≥ 12 → red
BREAK_YELLOW = 10.0       # Break % > 10 and < 12 → yellow

MANUAL_RED = 10.0         # Manual % ≥ 10 → red
MANUAL_YELLOW = 5.0       # Manual % ≥ 5 → yellow

LOW20_RED = 15.0          # Low Act ≤20% of worked hours ≥ 15 → red
LOW20_YELLOW = 7.5        # Low Act ≤20% of worked hours ≥ 7.5 → yellow

LOW30_RED = 20.0          # Low Act ≤30% of worked hours ≥ 20 → red
LOW30_YELLOW = 10.0       # Low Act ≤30% of worked hours ≥ 10 → yellow

HOURS_BASE = 160.0        # Full-month target hours
HOURS_OVERWORK_BASE = 200.0  # Full-month overwork threshold

# Scoring weights
SCORE_RED = 10
SCORE_YELLOW = 3
SCORE_ORANGE = 7

MULTIPLIERS = {
    "A": 5,
    "M": 4,
    "H_red": 3,
    "H_orange": 2,
    "20": 2,
    "30": 1.5,
    "B": 1,
}



# ---------------------------------------------------------------------------
# CSV loading and cleaning
# ---------------------------------------------------------------------------

def _parse_percent(value) -> float:
    """Convert '34.5%' or 34.5 or '34.5' to float 34.5. Returns NaN on failure."""
    if pd.isna(value):
        return float("nan")
    s = str(value).strip().replace("%", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _parse_hours(value) -> float:
    """Convert '12.5h', '12.5 h', '12.5', 12.5 to float. Returns NaN on failure."""
    if pd.isna(value):
        return float("nan")
    s = str(value).strip().lower().replace("h", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def load_master_table(csv_path: Path) -> pd.DataFrame:
    """Load and clean the master table CSV."""
    df = pd.read_csv(csv_path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)

    # Drop completely empty rows
    df = df.dropna(how="all").reset_index(drop=True)

    # Parse numeric columns
    percent_cols = {
        "Activity %": "activity_pct",
        "Break % of Total": "break_pct",
        "Manual % of Total": "manual_pct",
        "Low Activity % (≤20%)": "low20_pct",
        "Low Activity % (≤30%)": "low30_pct",
    }
    hour_cols = {
        "Total Worked Hours": "total_hours",
        "Break Time": "break_hours",
        "Total Manual Hours": "manual_hours",
        "Low Activity Hours (≤20%)": "low20_hours",
        "Low Activity Hours (≤30%)": "low30_hours",
    }

    for src, dest in percent_cols.items():
        if src in df.columns:
            df[dest] = df[src].apply(_parse_percent)
        else:
            df[dest] = float("nan")

    for src, dest in hour_cols.items():
        if src in df.columns:
            df[dest] = df[src].apply(_parse_hours)
        else:
            df[dest] = float("nan")

    # Normalise member name and team
    df["member"] = df.get("Member", df.get("member", pd.Series(["Unknown"] * len(df)))).fillna("Unknown")
    df["team"] = df.get("Team(s)", df.get("team", pd.Series(["—"] * len(df)))).fillna("—")

    return df


# ---------------------------------------------------------------------------
# Flag evaluation
# ---------------------------------------------------------------------------

def evaluate_flags(row: pd.Series, prorated_red: float, prorated_orange: float) -> dict:
    """
    Evaluate all SLA flags for a single employee row.
    Returns a dict with keys for each metric: 'A', 'H', 'B', 'M', '20', '30'
    Each value is one of: 'red', 'yellow', 'orange', or None.
    """
    flags = {}

    # Activity %
    a = row.get("activity_pct", float("nan"))
    if not pd.isna(a):
        if a < ACTIVITY_RED:
            flags["A"] = "red"
        elif a < ACTIVITY_YELLOW:
            flags["A"] = "yellow"
        else:
            flags["A"] = None
    else:
        flags["A"] = None

    # Total Hours — strict: red or orange, no yellow
    h = row.get("total_hours", float("nan"))
    if not pd.isna(h):
        if h < prorated_red:
            flags["H"] = "red"
        elif h >= prorated_orange:
            flags["H"] = "orange"
        else:
            flags["H"] = None
    else:
        flags["H"] = None

    # Break %
    b = row.get("break_pct", float("nan"))
    if not pd.isna(b):
        if b >= BREAK_RED:
            flags["B"] = "red"
        elif b > BREAK_YELLOW:
            flags["B"] = "yellow"
        else:
            flags["B"] = None
    else:
        flags["B"] = None

    # Manual %
    m = row.get("manual_pct", float("nan"))
    if not pd.isna(m):
        if m >= MANUAL_RED:
            flags["M"] = "red"
        elif m >= MANUAL_YELLOW:
            flags["M"] = "yellow"
        else:
            flags["M"] = None
    else:
        flags["M"] = None

    # Low Activity ≤20%
    l20 = row.get("low20_pct", float("nan"))
    if not pd.isna(l20):
        if l20 >= LOW20_RED:
            flags["20"] = "red"
        elif l20 >= LOW20_YELLOW:
            flags["20"] = "yellow"
        else:
            flags["20"] = None
    else:
        flags["20"] = None

    # Low Activity ≤30%
    l30 = row.get("low30_pct", float("nan"))
    if not pd.isna(l30):
        if l30 >= LOW30_RED:
            flags["30"] = "red"
        elif l30 >= LOW30_YELLOW:
            flags["30"] = "yellow"
        else:
            flags["30"] = None
    else:
        flags["30"] = None

    return flags


def calculate_score(flags: dict) -> float:
    """Calculate weighted severity score from flags dict."""
    score = 0.0
    for metric, status in flags.items():
        if status is None:
            continue
        if status == "red":
            base = SCORE_RED
            if metric == "H":
                score += base * MULTIPLIERS["H_red"]
            else:
                score += base * MULTIPLIERS.get(metric, 1)
        elif status == "yellow":
            base = SCORE_YELLOW
            score += base * MULTIPLIERS.get(metric, 1)
        elif status == "orange":
            base = SCORE_ORANGE
            if metric == "H":
                score += base * MULTIPLIERS["H_orange"]
            else:
                score += base * MULTIPLIERS.get(metric, 1)
    return score


def count_flags(flags: dict) -> tuple[int, int]:
    """
    Return (red_count, yellow_count) for display.
    Break yellow (B ⚠️) is EXCLUDED from displayed counts per SLA rules.
    Orange counts as red for display purposes.
    """
    red = 0
    yellow = 0
    for metric, status in flags.items():
        if status == "red" or status == "orange":
            red += 1
        elif status == "yellow":
            if metric == "B":
                continue  # Excluded from display count
            yellow += 1
    return red, yellow


# ---------------------------------------------------------------------------
# Cell formatting helpers
# ---------------------------------------------------------------------------

def fmt_activity(val, flag) -> str:
    if pd.isna(val):
        return ""
    pct = f"{val:.0f}%"
    if flag == "red":
        return f"🔴 {pct}"
    elif flag == "yellow":
        return f"⚠️ {pct}"
    return pct


def fmt_hours(val, flag) -> str:
    if pd.isna(val):
        return ""
    h = f"{val:.1f}h"
    if flag == "red":
        return f"🔴 {h}"
    elif flag == "orange":
        return f"🟠 {h}"
    return h


def fmt_percent_hours(hours_val, pct_val, flag) -> str:
    """Format as 'Xh (X.X%)' with optional flag indicator."""
    if pd.isna(hours_val) and pd.isna(pct_val):
        return ""
    h_str = f"{hours_val:.1f}h" if not pd.isna(hours_val) else "—"
    p_str = f"{pct_val:.1f}%" if not pd.isna(pct_val) else "—"
    combined = f"{h_str} ({p_str})"
    if flag == "red":
        return f"🔴 {combined}"
    elif flag == "yellow":
        return f"⚠️ {combined}"
    return combined


def fmt_flags_badge(red_count, yellow_count) -> str:
    parts = []
    if red_count > 0:
        parts.append(f"🔴 {red_count}")
    if yellow_count > 0:
        parts.append(f"⚠️ {yellow_count}")
    return " ".join(parts) if parts else ""


def row_severity_class(score: float) -> str:
    """Return CSS class for row shading based on score."""
    if score >= 60:
        return "severity-critical"
    elif score >= 30:
        return "severity-high"
    elif score >= 15:
        return "severity-medium"
    elif score > 0:
        return "severity-low"
    return ""


# ---------------------------------------------------------------------------
# Report data assembly
# ---------------------------------------------------------------------------

def build_report_data(df: pd.DataFrame, prorated_red: float, prorated_orange: float,
                      start: date, end: date) -> dict:
    """Process all rows and build template context dict."""

    rows_scored = []
    for _, row in df.iterrows():
        flags = evaluate_flags(row, prorated_red, prorated_orange)
        score = calculate_score(flags)
        red_count, yellow_count = count_flags(flags)
        rows_scored.append({
            "member": row["member"],
            "team": row["team"],
            "activity_pct": row.get("activity_pct", float("nan")),
            "total_hours": row.get("total_hours", float("nan")),
            "break_hours": row.get("break_hours", float("nan")),
            "break_pct": row.get("break_pct", float("nan")),
            "manual_hours": row.get("manual_hours", float("nan")),
            "manual_pct": row.get("manual_pct", float("nan")),
            "low20_hours": row.get("low20_hours", float("nan")),
            "low20_pct": row.get("low20_pct", float("nan")),
            "low30_hours": row.get("low30_hours", float("nan")),
            "low30_pct": row.get("low30_pct", float("nan")),
            "flags": flags,
            "score": score,
            "red_count": red_count,
            "yellow_count": yellow_count,
        })

    # Sort by score descending
    rows_scored.sort(key=lambda x: x["score"], reverse=True)

    # Section 1: Top 15
    top15 = []
    for rank, r in enumerate(rows_scored[:15], start=1):
        flags = r["flags"]
        top15.append({
            "rank": rank,
            "member": r["member"],
            "team": r["team"],
            "activity_cell": fmt_activity(r["activity_pct"], flags.get("A")),
            "hours_cell": fmt_hours(r["total_hours"], flags.get("H")),
            "break_cell": fmt_percent_hours(r["break_hours"], r["break_pct"], flags.get("B")),
            "manual_cell": fmt_percent_hours(r["manual_hours"], r["manual_pct"], flags.get("M")),
            "low20_cell": fmt_percent_hours(r["low20_hours"], r["low20_pct"], flags.get("20")),
            "low30_cell": fmt_percent_hours(r["low30_hours"], r["low30_pct"], flags.get("30")),
            "flags_badge": fmt_flags_badge(r["red_count"], r["yellow_count"]),
            "score": f"{r['score']:.1f}",
            "row_class": row_severity_class(r["score"]),
        })

    # Section 2: All Hours Violators (below prorated red threshold)
    hours_violators = []
    for r in rows_scored:
        h = r["total_hours"]
        if not pd.isna(h) and h < prorated_red:
            shortfall = prorated_red - h
            other_flags = fmt_flags_badge(r["red_count"], r["yellow_count"])
            hours_violators.append({
                "member": r["member"],
                "team": r["team"],
                "hours_worked": f"{h:.1f}h",
                "expected_hours": f"{prorated_red:.1f}h",
                "shortfall": f"{shortfall:.1f}h",
                "other_flags": other_flags,
            })
    # Sort ascending by hours (worst = least hours first)
    hours_violators.sort(key=lambda x: float(x["hours_worked"].replace("h", "")))

    period_working_days = count_working_days(start, end)

    return {
        "report_title": "Bi-Weekly Performance Report",
        "date_range": f"{start.strftime('%B %d, %Y')} — {end.strftime('%B %d, %Y')}",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "period_working_days": period_working_days,
        "prorated_red": f"{prorated_red:.1f}h",
        "prorated_orange": f"{prorated_orange:.1f}h",
        "total_employees": len(df),
        "total_flagged": sum(1 for r in rows_scored if r["score"] > 0),
        "top15": top15,
        "hours_violators": hours_violators,
        "hours_violator_count": len(hours_violators),
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        # Threshold reference strip values
        "thresh_activity_red": f"< {ACTIVITY_RED:.0f}%",
        "thresh_activity_yellow": f"< {ACTIVITY_YELLOW:.0f}%",
        "thresh_hours_red": f"< {prorated_red:.1f}h",
        "thresh_hours_orange": f"≥ {prorated_orange:.1f}h",
        "thresh_break_red": f"≥ {BREAK_RED:.0f}%",
        "thresh_break_yellow": f"> {BREAK_YELLOW:.0f}%",
        "thresh_manual_red": f"≥ {MANUAL_RED:.0f}%",
        "thresh_manual_yellow": f"≥ {MANUAL_YELLOW:.0f}%",
        "thresh_low20_red": f"≥ {LOW20_RED:.0f}%",
        "thresh_low20_yellow": f"≥ {LOW20_YELLOW:g}%",
        "thresh_low30_red": f"≥ {LOW30_RED:.0f}%",
        "thresh_low30_yellow": f"≥ {LOW30_YELLOW:.0f}%",
    }


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def render_report(context: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("biweekly_report_template.html")
    return template.render(**context)


# ---------------------------------------------------------------------------
# Output file management
# ---------------------------------------------------------------------------

def write_report(html: str, start: date, end: date) -> Path:
    """Write report directly to /docs/. Returns docs_path."""
    folder_name = f"{start.isoformat()}_to_{end.isoformat()}"
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    docs_filename = f"{folder_name}_biweekly_top_violators.html"
    docs_path = DOCS_DIR / docs_filename
    docs_path.write_text(html, encoding="utf-8")
    return docs_path


def update_index(start: date, end: date):
    """Import and call the update_index script logic."""
    sys.path.insert(0, str(Path(__file__).parent))
    import update_index as ui
    ui.regenerate_index()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate WebLife bi-weekly performance report.")
    parser.add_argument("--input", required=True, help="Path to master table CSV")
    parser.add_argument("--start", required=True, help="Period start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Period end date YYYY-MM-DD")
    parser.add_argument(
        "--exclude",
        default="",
        help="Comma-separated member names to exclude (cycle-specific, e.g. new hires in grace period)",
    )
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    csv_path = Path(args.input)

    if not csv_path.exists():
        print(f"ERROR: Input file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    # --- Step 1: Calculate prorated thresholds ---
    prorated_red, prorated_orange = calculate_prorated_thresholds(start, end)
    print_threshold_header(start, end, prorated_red, prorated_orange)

    # --- Step 2: Load and clean data ---
    print(f"Loading: {csv_path}")
    df = load_master_table(csv_path)
    print(f"Loaded {len(df)} employees.")

    # Sanity check: warn if expected columns are missing
    expected_cols = ["Member", "Activity %", "Total Worked Hours"]
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        print(f"WARNING: Missing expected columns: {missing}", file=sys.stderr)
        print(f"Available columns: {list(df.columns)}", file=sys.stderr)

    # Permanent exclusions: contractors and resigned personnel (per personnel_index.md)
    PERMANENT_EXCLUSIONS = [
        # Contractors
        "Nouman Khan",
        "Amjad Ali",
        "Abdullah Shinwari",
        "Hammad Rafique",
        "Tim Steele",
        "Hira Tariq",
        "Muhammad Talib",
        "Nangyial Ahmad",
        "Hafiz Aqeel",
        "Artyom Velmojko",
        # Resigned — add names here as they are confirmed offboarded
    ]

    # Cycle-specific exclusions passed via --exclude
    cycle_exclusions = [n.strip() for n in args.exclude.split(",") if n.strip()]

    all_exclusions = PERMANENT_EXCLUSIONS + cycle_exclusions
    if all_exclusions:
        before = len(df)
        df = df[~df["member"].isin(all_exclusions)].reset_index(drop=True)
        excluded_count = before - len(df)
        print(f"Excluded {excluded_count} employee(s): {', '.join(all_exclusions)}")
        print(f"Remaining: {len(df)} employees.")

    # --- Step 3: Build report data ---
    context = build_report_data(df, prorated_red, prorated_orange, start, end)
    print(f"Employees flagged: {context['total_flagged']} / {context['total_employees']}")
    print(f"Hours violators:   {context['hours_violator_count']}")

    # --- Step 4: Render HTML ---
    html = render_report(context)

    # --- Step 5: Write output files ---
    docs_path = write_report(html, start, end)
    print(f"Report written:    {docs_path}")

    # --- Step 6: Update index ---
    update_index(start, end)
    print(f"Index updated:     {DOCS_DIR / 'index.html'}")
    print("Done.")


if __name__ == "__main__":
    main()
