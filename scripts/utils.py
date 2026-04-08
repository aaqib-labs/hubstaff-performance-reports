"""
WebLife Ventures — Shared Utilities
====================================
Common helpers shared across all report generation scripts.
Import from here — do not duplicate in individual scripts.
"""

from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR  = REPO_ROOT / "docs"

HOURS_BASE          = 160.0   # Full-month target hours
HOURS_OVERWORK_BASE = 200.0   # Full-month overwork threshold


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
