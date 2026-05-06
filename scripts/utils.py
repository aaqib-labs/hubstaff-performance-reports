"""
WebLife Ventures — Shared Utilities
====================================
Common helpers shared across all report generation scripts.
Import from here — do not duplicate in individual scripts.
"""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR  = REPO_ROOT / "docs"

HOURS_BASE          = 160.0   # Full-month target hours
HOURS_OVERWORK_BASE = 200.0   # Full-month overwork threshold

# ---------------------------------------------------------------------------
# SLA Thresholds (authoritative — matches data/reference/sla_violation_legend.md)
# ---------------------------------------------------------------------------
ACTIVITY_RED    = 35.0
ACTIVITY_YELLOW = 45.0
BREAK_RED       = 12.0
BREAK_YELLOW    = 10.0
MANUAL_RED      = 10.0
MANUAL_YELLOW   =  5.0
LOW20_RED       = 15.0
LOW20_YELLOW    =  7.5
LOW30_RED       = 20.0
LOW30_YELLOW    = 10.0

SCORE_RED    = 10
SCORE_YELLOW =  3
SCORE_ORANGE =  7

MULTIPLIERS = {
    "A":        5,
    "M":        4,
    "H_red":    3,
    "H_orange": 2,
    "20":       2,
    "30":       1.5,
    "B":        1,
}

# ---------------------------------------------------------------------------
# Exclusion lists
# ---------------------------------------------------------------------------
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
    # Part-time — excluded from performance reports
    "Unaiza Imran",
    # Terminated / Resigned — add names here as confirmed offboarded
    "Sarena Nicole Arokiasamy",
    "Reynalyn Gramatica",
]

# Friday Solutions members tracked via TMetric — excluded from Hubstaff reports
FS_EXCLUSIONS = [
    "Dhananjana Rathnayake",
    "Dulan Jayawickrama",
    "Gayan Keppetipola",
    "Hasan Zarook",
    "Abdul Gafoor Hasan Zarook",
    "Richard Fernando",
    "Ruwanya Wijesuriya",
    "Suleman",
    "Suleman Khan",
    "Thimal Caldera",
    "Matt Fuster",
    "Matthew Fuster",
]


# ---------------------------------------------------------------------------
# Working days + proration
# ---------------------------------------------------------------------------

def count_working_days(start: date, end: date) -> int:
    """Count Mon–Fri days between start and end (inclusive).

    Holidays do NOT need to be excluded here — Hubstaff and TMetric already
    include approved time-off and holiday hours in the employee's Total Worked
    Hours figure. The raw CSV total is the authoritative hours count.
    """
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:   # 0 = Mon … 4 = Fri
            count += 1
        current += timedelta(days=1)
    return count


def get_month_working_days(ref_date: date) -> int:
    """Count Mon–Fri days in the full calendar month of ref_date."""
    month_start = ref_date.replace(day=1)
    if ref_date.month == 12:
        month_end = ref_date.replace(year=ref_date.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = ref_date.replace(month=ref_date.month + 1, day=1) - timedelta(days=1)
    return count_working_days(month_start, month_end)


def calculate_prorated_thresholds(start: date, end: date) -> tuple[float, float]:
    """Return (prorated_red, prorated_orange) hours for the given period.

    Formula:
        prorated_red    = (working_days_in_period / working_days_in_month) × 160
        prorated_orange = (working_days_in_period / working_days_in_month) × 200
    """
    period_days = count_working_days(start, end)
    month_days  = get_month_working_days(start)
    if month_days == 0:
        raise ValueError("Month working days calculated as 0 — check date inputs.")
    ratio = period_days / month_days
    return round(ratio * HOURS_BASE, 2), round(ratio * HOURS_OVERWORK_BASE, 2)


def print_threshold_header(start: date, end: date,
                            prorated_red: float, prorated_orange: float) -> None:
    """Print the standard threshold summary to console before processing."""
    period_days = count_working_days(start, end)
    month_days  = get_month_working_days(start)
    print("=" * 60)
    print(f"Period:                 {start} to {end}")
    print(f"Working days (period):  {period_days}")
    print(f"Working days (month):   {month_days}")
    print(f"Prorated red threshold: {prorated_red}h  (< this = 🔴)")
    print(f"Prorated orange:        {prorated_orange}h  (≥ this = 🟠 overwork)")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CSV loading and cleaning
# ---------------------------------------------------------------------------

def _parse_percent(value) -> float:
    if pd.isna(value):
        return float("nan")
    s = str(value).strip().replace("%", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _parse_hours(value) -> float:
    if pd.isna(value):
        return float("nan")
    s = str(value).strip().lower().replace("h", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def load_master_table(csv_path: Path) -> pd.DataFrame:
    """Load and clean a Hubstaff master table CSV."""
    df = pd.read_csv(csv_path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)
    df = df.dropna(how="all").reset_index(drop=True)

    percent_cols = {
        "Activity %":             "activity_pct",
        "Break % of Total":       "break_pct",
        "Manual % of Total":      "manual_pct",
        "Low Activity % (≤20%)":  "low20_pct",
        "Low Activity % (≤30%)":  "low30_pct",
    }
    hour_cols = {
        "Total Worked Hours":          "total_hours",
        "Break Time":                  "break_hours",
        "Total Manual Hours":          "manual_hours",
        "Low Activity Hours (≤20%)":   "low20_hours",
        "Low Activity Hours (≤30%)":   "low30_hours",
    }

    for src, dest in percent_cols.items():
        df[dest] = df[src].apply(_parse_percent) if src in df.columns else float("nan")

    for src, dest in hour_cols.items():
        df[dest] = df[src].apply(_parse_hours) if src in df.columns else float("nan")

    df["member"] = df.get("Member", pd.Series(["Unknown"] * len(df))).fillna("Unknown")
    df["team"]   = df.get("Team(s)", pd.Series(["—"] * len(df))).fillna("—")

    return df


# ---------------------------------------------------------------------------
# Flag evaluation
# ---------------------------------------------------------------------------

def evaluate_flags(row: pd.Series, prorated_red: float, prorated_orange: float) -> dict:
    """Evaluate all SLA flags for a single employee row. Returns dict of metric→severity."""
    flags = {}

    a = row.get("activity_pct", float("nan"))
    if not pd.isna(a):
        flags["A"] = "red" if a < ACTIVITY_RED else ("yellow" if a < ACTIVITY_YELLOW else None)
    else:
        flags["A"] = None

    h = row.get("total_hours", float("nan"))
    if not pd.isna(h):
        flags["H"] = "red" if h < prorated_red else ("orange" if h >= prorated_orange else None)
    else:
        flags["H"] = None

    b = row.get("break_pct", float("nan"))
    if not pd.isna(b):
        flags["B"] = "red" if b >= BREAK_RED else ("yellow" if b > BREAK_YELLOW else None)
    else:
        flags["B"] = None

    m = row.get("manual_pct", float("nan"))
    if not pd.isna(m):
        flags["M"] = "red" if m >= MANUAL_RED else ("yellow" if m >= MANUAL_YELLOW else None)
    else:
        flags["M"] = None

    l20 = row.get("low20_pct", float("nan"))
    if not pd.isna(l20):
        flags["20"] = "red" if l20 >= LOW20_RED else ("yellow" if l20 >= LOW20_YELLOW else None)
    else:
        flags["20"] = None

    l30 = row.get("low30_pct", float("nan"))
    if not pd.isna(l30):
        flags["30"] = "red" if l30 >= LOW30_RED else ("yellow" if l30 >= LOW30_YELLOW else None)
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
            key = "H_red" if metric == "H" else metric
            score += SCORE_RED * MULTIPLIERS.get(key, 1)
        elif status == "yellow":
            score += SCORE_YELLOW * MULTIPLIERS.get(metric, 1)
        elif status == "orange":
            key = "H_orange" if metric == "H" else metric
            score += SCORE_ORANGE * MULTIPLIERS.get(key, 1)
    return score


def count_flags(flags: dict) -> tuple[int, int]:
    """Return (red_count, yellow_count). B⚠️ excluded from displayed count."""
    red = sum(1 for m, s in flags.items() if s in ("red", "orange"))
    yellow = sum(1 for m, s in flags.items() if s == "yellow" and m != "B")
    return red, yellow


# ---------------------------------------------------------------------------
# Cell formatting helpers
# ---------------------------------------------------------------------------

def fmt_activity(val, flag) -> str:
    if pd.isna(val):
        return ""
    pct = f"{val:.0f}%"
    if flag == "red":    return f"🔴 {pct}"
    if flag == "yellow": return f"⚠️ {pct}"
    return pct


def fmt_hours(val, flag) -> str:
    if pd.isna(val):
        return ""
    h = f"{val:.1f}h"
    if flag == "red":    return f"🔴 {h}"
    if flag == "orange": return f"🟠 {h}"
    return h


def fmt_percent_hours(hours_val, pct_val, flag) -> str:
    if pd.isna(hours_val) and pd.isna(pct_val):
        return ""
    h_str = f"{hours_val:.1f}h" if not pd.isna(hours_val) else "—"
    p_str = f"{pct_val:.1f}%"   if not pd.isna(pct_val)   else "—"
    combined = f"{h_str} ({p_str})"
    if flag == "red":    return f"🔴 {combined}"
    if flag == "yellow": return f"⚠️ {combined}"
    return combined


def fmt_flags_badge(red_count, yellow_count) -> str:
    parts = []
    if red_count > 0:    parts.append(f"🔴 {red_count}")
    if yellow_count > 0: parts.append(f"⚠️ {yellow_count}")
    return " ".join(parts) if parts else ""


def row_severity_class(score: float) -> str:
    if score >= 60:  return "severity-critical"
    if score >= 30:  return "severity-high"
    if score >= 15:  return "severity-medium"
    if score > 0:    return "severity-low"
    return ""
