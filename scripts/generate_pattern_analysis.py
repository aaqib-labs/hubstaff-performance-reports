from __future__ import annotations

"""
WebLife Ventures — Q1 Repeated Pattern Analysis Report
=======================================================
Identifies employees with 2+ month SLA violation patterns across a full quarter.
Organised by violation category (12 sections), not by employee.

Usage:
    python scripts/generate_pattern_analysis.py \
        --months data/input/monthly/HS-2026-01-master.csv \
                 data/input/monthly/HS-2026-02-master.csv \
                 data/input/monthly/HS-2026-03-master.csv \
        --labels "January 2026" "February 2026" "March 2026" \
        --start 2026-01-01 --end 2026-03-31

    Add --sample to run with a subset of employees for structure review.

Outputs:
    docs/<start>_to_<end>_pattern_analysis.html
    docs/index.html  (updated)

Report Sections (12 + Executive Summary):
    1.  Activity Red         (A < 35%)
    2.  Activity Yellow      (A 35–45%)
    3.  Overwork             (H ≥ prorated orange)
    4.  Low Hours Red        (H < prorated red)
    5.  Manual Red           (M ≥ 10%)
    6.  Manual Yellow        (M 5–10%)
    7.  Low Act ≤20% Red     (≥ 15% of worked hrs)
    8.  Low Act ≤20% Yellow  (7.5–15%)
    9.  Low Act ≤30% Red     (≥ 20% of worked hrs)
    10. Low Act ≤30% Yellow  (10–20%)
    11. Break Red            (B ≥ 12%)
    12. Break Yellow         (B 10–12%)
    13. Executive Summary
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
    FS_EXCLUSIONS,
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
# Sample employee filter
# ---------------------------------------------------------------------------
SAMPLE_EMPLOYEES = [
    "Dharshika Perera", "Ali Asghar", "Prajwal Kumar", "Kushani Kalpage",
    "leora megan", "Shaarukshan Seralathan", "Natalia Jayasundera",
    "Brayden Robinson", "Jebby Rochelle", "Irene Padilla",
    "jorn wossner", "Kianna Xue", "Jomal Mathew",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _month_dates(csv_path: Path) -> tuple[date, date]:
    """Derive first and last day of month from filename HS-YYYY-MM-master.csv."""
    stem  = csv_path.stem          # e.g. HS-2026-01-master
    parts = stem.split("-")        # ['HS', '2026', '01', 'master']
    year, month = int(parts[1]), int(parts[2])
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _classify(value: float, red_thresh, yellow_thresh, direction: str = "low") -> str:
    """
    direction='low'  → red when value < red_thresh (activity)
    direction='high' → red when value >= red_thresh (break, manual, low act)
    direction='hours'→ red < prorated_red, orange >= prorated_orange
    Returns: 'red' | 'yellow' | 'orange' | 'clean'
    """
    if pd.isna(value):
        return "clean"
    if direction == "low":
        if value < red_thresh:    return "red"
        if value < yellow_thresh: return "yellow"
        return "clean"
    elif direction == "high":
        if value >= red_thresh:    return "red"
        if value >= yellow_thresh: return "yellow"
        return "clean"
    return "clean"


def _classify_hours(value: float, prorated_red: float, prorated_orange: float) -> str:
    if pd.isna(value):   return "clean"
    if value < prorated_red:     return "red"
    if value >= prorated_orange: return "orange"
    return "clean"


STATUS_ICON = {"red": "🔴", "orange": "🟠", "yellow": "⚠️", "clean": "✅"}


def _fmt_pct(value: float, status: str) -> str:
    if pd.isna(value): return "—"
    icon = STATUS_ICON.get(status, "")
    return f"{value:.1f}% {icon}".strip()


def _fmt_hours_val(value: float, status: str) -> str:
    if pd.isna(value): return "—"
    icon = STATUS_ICON.get(status, "")
    return f"{value:.1f}h {icon}".strip()


def _trend(values: list[float | None], higher_is_worse: bool = False) -> tuple[str, str]:
    """
    Determine trend across months (ignoring None = absent).
    Returns (label, css_class).
    higher_is_worse=True  for manual, break, low activity, overwork hours
    higher_is_worse=False for activity % (lower is worse)
    """
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return "➡️ Flat", "trend-stable"

    first, last = present[0], present[-1]

    # Bad→Good→Bad detection (need exactly 3 values, middle one clean)
    if len(values) == 3 and values[1] is not None:
        # Check if middle is clean relative to the metric direction
        # We pass statuses for this check via a separate path — simplified:
        # detect via pattern: first and last similar, middle clearly different
        pass

    delta = last - first
    threshold_pct = 5.0  # < 5pp change = flat
    threshold_h   = 15.0

    if abs(delta) < threshold_pct:
        return "➡️ Flat", "trend-stable"

    if higher_is_worse:
        if delta > 0:  return "⬆️ Worsening", "trend-up"
        else:          return "⬇️ Improving", "trend-down"
    else:
        if delta < 0:  return "⬆️ Worsening", "trend-up"
        else:          return "⬇️ Improving", "trend-down"


def _trend_hours(values: list[float | None], overwork: bool = False) -> tuple[str, str]:
    """Trend for hours. overwork=True means higher is worse."""
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return "➡️ Flat", "trend-stable"
    delta = present[-1] - present[0]
    if abs(delta) < 15:
        return "➡️ Flat", "trend-stable"
    if overwork:
        return ("⬆️ Worsening", "trend-up") if delta > 0 else ("⬇️ Improving", "trend-down")
    else:
        return ("⬆️ Worsening", "trend-up") if delta < 0 else ("⬇️ Improving", "trend-down")


def _detect_bad_good_bad(statuses: list[str | None]) -> bool:
    """True if month1=violation, month2=clean, month3=violation (exactly 3 months)."""
    if len(statuses) != 3:
        return False
    s1, s2, s3 = statuses
    if s1 is None or s2 is None or s3 is None:
        return False
    v1 = s1 in ("red", "yellow", "orange")
    v2 = s2 in ("red", "yellow", "orange")
    v3 = s3 in ("red", "yellow", "orange")
    return v1 and (not v2) and v3


def _action(status_last: str, months_violated: int) -> str:
    """Determine action label based on severity."""
    if status_last == "red" and months_violated == 3:
        return "Immediate escalation"
    if status_last == "red":
        return "Executive review"
    if months_violated == 3:
        return "Monitor closely"
    return "Escalate if continues"


def _score_sort(row: dict) -> tuple:
    """Sort key: months violated desc, severity desc, name asc."""
    severity_map = {"red": 3, "orange": 2, "yellow": 1, "clean": 0}
    last_sev = severity_map.get(row.get("status_last", "clean"), 0)
    return (-row["months_violated"], -last_sev, row["employee"].lower())


# ---------------------------------------------------------------------------
# Load and process all months
# ---------------------------------------------------------------------------

def load_all_months(
    csv_paths: list[Path],
    labels: list[str],
    sample: bool,
) -> tuple[dict, list[tuple[float, float]]]:
    """
    Returns:
        employee_month_data: {norm_name: {label: row_series, "display": name, "team": team}}
        thresholds: [(prorated_red, prorated_orange), ...]  per month
    """
    all_exclusions = set(n.lower() for n in PERMANENT_EXCLUSIONS + FS_EXCLUSIONS)
    sample_lower   = set(n.lower() for n in SAMPLE_EMPLOYEES) if sample else None

    employee_month_data: dict = {}
    thresholds: list[tuple[float, float]] = []

    for csv_path, label in zip(csv_paths, labels):
        month_start, month_end = _month_dates(csv_path)
        prorated_red, prorated_orange = calculate_prorated_thresholds(month_start, month_end)
        thresholds.append((prorated_red, prorated_orange))

        df = load_master_table(csv_path)
        df = df[~df["member"].apply(lambda n: n.lower() in all_exclusions)].reset_index(drop=True)
        if sample_lower:
            df = df[df["member"].apply(lambda n: n.lower() in sample_lower)].reset_index(drop=True)

        for _, row in df.iterrows():
            name      = row["member"]
            norm_name = name.lower().strip()
            if norm_name not in employee_month_data:
                employee_month_data[norm_name] = {"display": name, "team": row["team"]}
            employee_month_data[norm_name][label] = row

    return employee_month_data, thresholds


# ---------------------------------------------------------------------------
# Build per-metric section
# ---------------------------------------------------------------------------

def build_section(
    employee_month_data: dict,
    labels: list[str],
    thresholds: list[tuple[float, float]],
    metric: str,           # 'activity' | 'hours_red' | 'hours_orange' | 'manual' | 'break' | 'low20' | 'low30'
    severity_filter: str,  # 'red' | 'yellow' | 'orange'
    higher_is_worse: bool = False,
) -> list[dict]:
    """
    Build list of employee rows for a single violation section.
    Only includes employees present in ALL months and with 2+ violations.
    """
    rows = []

    for norm_name, data in employee_month_data.items():
        # Must be present in all months
        month_rows = [data.get(lbl) for lbl in labels]
        if any(r is None for r in month_rows):
            continue

        values: list[float] = []
        statuses: list[str] = []
        fmt_cells: list[str] = []

        for i, (row, lbl) in enumerate(zip(month_rows, labels)):
            pr, po = thresholds[i]

            if metric == "activity":
                val    = row.get("activity_pct", float("nan"))
                status = _classify(val, ACTIVITY_RED, ACTIVITY_YELLOW, "low")
                cell   = _fmt_pct(val, status)
            elif metric == "hours_red":
                val    = row.get("total_hours", float("nan"))
                status = _classify_hours(val, pr, po)
                # For low hours section only show red
                if status == "orange": status = "clean"
                cell   = _fmt_hours_val(val, status)
            elif metric == "hours_orange":
                val    = row.get("total_hours", float("nan"))
                status = _classify_hours(val, pr, po)
                if status == "red": status = "clean"
                cell   = _fmt_hours_val(val, status)
            elif metric == "manual":
                val    = row.get("manual_pct", float("nan"))
                status = _classify(val, MANUAL_RED, MANUAL_YELLOW, "high")
                cell   = _fmt_pct(val, status)
            elif metric == "break":
                val    = row.get("break_pct", float("nan"))
                status = _classify(val, BREAK_RED, BREAK_YELLOW, "high")
                cell   = _fmt_pct(val, status)
            elif metric == "low20":
                val    = row.get("low20_pct", float("nan"))
                status = _classify(val, LOW20_RED, LOW20_YELLOW, "high")
                cell   = _fmt_pct(val, status)
            elif metric == "low30":
                val    = row.get("low30_pct", float("nan"))
                status = _classify(val, LOW30_RED, LOW30_YELLOW, "high")
                cell   = _fmt_pct(val, status)
            else:
                val, status, cell = float("nan"), "clean", "—"

            values.append(val if not pd.isna(val) else None)
            statuses.append(status)
            fmt_cells.append(cell)

        # Count violations matching the severity filter
        if severity_filter == "red":
            violated = [s == "red" for s in statuses]
        elif severity_filter == "yellow":
            violated = [s == "yellow" for s in statuses]
        elif severity_filter == "orange":
            violated = [s == "orange" for s in statuses]
        else:
            violated = [s != "clean" for s in statuses]

        months_violated = sum(violated)
        if months_violated < 2:
            continue

        # Trend
        if metric in ("hours_red", "hours_orange"):
            trend_label, trend_class = _trend_hours(values, overwork=(metric == "hours_orange"))
        else:
            trend_label, trend_class = _trend(values, higher_is_worse=higher_is_worse)

        # Bad→Good→Bad override
        if _detect_bad_good_bad(statuses):
            trend_label, trend_class = "🔄 Bad→Good→Bad", "trend-bgb"

        status_last = statuses[-1]
        is_red_section = severity_filter in ("red", "orange")
        action = _action(status_last, months_violated) if is_red_section else _status_yellow(months_violated)

        rows.append({
            "employee":       data["display"],
            "team":           data["team"],
            "cells":          fmt_cells,
            "statuses":       statuses,
            "trend_label":    trend_label,
            "trend_class":    trend_class,
            "months_violated": months_violated,
            "status_last":    status_last,
            "action":         action,
            "is_red_section": is_red_section,
        })

    rows.sort(key=_score_sort)
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    return rows


def _status_yellow(months_violated: int) -> str:
    if months_violated == 3: return "Monitor closely"
    return "Escalate if continues"


# ---------------------------------------------------------------------------
# Executive Summary
# ---------------------------------------------------------------------------

def build_exec_summary(sections: list[dict]) -> dict:
    """Build executive summary data from all 12 sections."""
    critical = []
    high_priority = []
    multi_category: dict[str, int] = {}

    for sec in sections:
        rows = sec["rows"]
        if not rows:
            continue
        names = [r["employee"] for r in rows]
        entry = {
            "title":      sec["title"],
            "count":      len(rows),
            "top_names":  ", ".join(names[:3]) + ("..." if len(names) > 3 else ""),
            "is_red":     sec["is_red"],
        }
        if sec["is_red"]:
            critical.append(entry)
        else:
            high_priority.append(entry)

        for r in rows:
            n = r["employee"]
            multi_category[n] = multi_category.get(n, 0) + 1

    multi_violators = sorted(
        [(n, c) for n, c in multi_category.items() if c >= 2],
        key=lambda x: -x[1],
    )

    return {
        "critical":         critical,
        "high_priority":    high_priority,
        "multi_violators":  multi_violators,
    }


# ---------------------------------------------------------------------------
# Main context builder
# ---------------------------------------------------------------------------

def build_context(
    employee_month_data: dict,
    labels: list[str],
    thresholds: list[tuple[float, float]],
    start: date,
    end: date,
    sample: bool,
) -> dict:

    SECTION_DEFS = [
        # (id, title, metric, severity_filter, higher_is_worse, is_red)
        ("act_red",    "Activity Level Violations",            "activity",      "red",    False, True),
        ("act_yel",    "Activity Level Yellow Warnings",       "activity",      "yellow", False, False),
        ("ovr",        "Overwork Pattern: Hours Violations",   "hours_orange",  "orange", True,  False),
        ("low_hrs",    "Low Hours Violations",                 "hours_red",     "red",    False, True),
        ("man_red",    "Manual Time Violations",               "manual",        "red",    True,  True),
        ("man_yel",    "Manual Time Yellow Warnings",          "manual",        "yellow", True,  False),
        ("l20_red",    "Low Activity ≤20% Violations",         "low20",         "red",    True,  True),
        ("l20_yel",    "Low Activity ≤20% Warnings",           "low20",         "yellow", True,  False),
        ("l30_red",    "Low Activity ≤30% Violations",         "low30",         "red",    True,  True),
        ("l30_yel",    "Low Activity ≤30% Warnings",           "low30",         "yellow", True,  False),
        ("brk_red",    "Break Time Violations",                "break",         "red",    True,  True),
        ("brk_yel",    "Break Time Warnings",                  "break",         "yellow", True,  False),
    ]

    THRESHOLD_SUBTITLES = {
        "act_red":  "A < 35%",
        "act_yel":  "A 35–45%",
        "ovr":      f"H ≥ {thresholds[0][1]:.1f}h (prorated)",
        "low_hrs":  f"H < {thresholds[0][0]:.1f}h (prorated)",
        "man_red":  "M ≥ 10%",
        "man_yel":  "M 5–10%",
        "l20_red":  "≥ 15% of worked hours",
        "l20_yel":  "7.5–15% of worked hours",
        "l30_red":  "≥ 20% of worked hours",
        "l30_yel":  "10–20% of worked hours",
        "brk_red":  "B ≥ 12%",
        "brk_yel":  "B 10–12%",
    }

    sections = []
    for sec_id, title, metric, sev_filter, hiw, is_red in SECTION_DEFS:
        rows = build_section(
            employee_month_data, labels, thresholds,
            metric=metric, severity_filter=sev_filter, higher_is_worse=hiw,
        )
        sections.append({
            "id":       sec_id,
            "num":      len(sections) + 1,
            "title":    title,
            "subtitle": THRESHOLD_SUBTITLES[sec_id],
            "rows":     rows,
            "is_red":   is_red,
        })

    exec_summary = build_exec_summary(sections)
    period_label = f"Q1 {start.year}" if (start.month == 1 and end.month >= 3) else f"{start} to {end}"

    return {
        "report_title":    "Repeated Pattern Analysis Report",
        "period_label":    period_label,
        "date_range":      f"{start.strftime('%B %d, %Y')} — {end.strftime('%B %d, %Y')}",
        "labels":          labels,
        "sections":        sections,
        "exec_summary":    exec_summary,
        "total_analysed":  len(employee_month_data),
        "generated_at":    pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "is_sample":       sample,
        "thresholds":      thresholds,
    }


# ---------------------------------------------------------------------------
# Render + write
# ---------------------------------------------------------------------------

def render_report(context: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("pattern_analysis_template.html")
    return template.render(**context)


def write_report(html: str, start: date, end: date, sample: bool) -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    suffix   = "_sample" if sample else ""
    filename = f"{start.isoformat()}_to_{end.isoformat()}_pattern_analysis{suffix}.html"
    path     = DOCS_DIR / filename
    path.write_text(html, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate Q1 Pattern Analysis report.")
    parser.add_argument("--months", nargs=3, metavar="CSV", required=True)
    parser.add_argument("--labels", nargs=3, metavar="LABEL",
                        default=["Month 1", "Month 2", "Month 3"])
    parser.add_argument("--start",  required=True, help="Quarter start YYYY-MM-DD")
    parser.add_argument("--end",    required=True, help="Quarter end YYYY-MM-DD")
    parser.add_argument("--sample", action="store_true",
                        help="Run with sample employees for structure review")
    args = parser.parse_args()

    start     = date.fromisoformat(args.start)
    end       = date.fromisoformat(args.end)
    csv_paths = [Path(p) for p in args.months]

    for p in csv_paths:
        if not p.exists():
            print(f"ERROR: File not found: {p}", file=sys.stderr)
            sys.exit(1)

    print("=" * 60)
    print(f"Q1 Pattern Analysis: {start} to {end}")
    if args.sample:
        print("MODE: Sample employees only")
    print("=" * 60)

    employee_month_data, thresholds = load_all_months(csv_paths, args.labels, args.sample)
    print(f"Employees loaded:  {len(employee_month_data)}")
    for label, (pr, po) in zip(args.labels, thresholds):
        print(f"  {label}: red < {pr}h | orange ≥ {po}h")

    context   = build_context(employee_month_data, args.labels, thresholds, start, end, args.sample)

    for sec in context["sections"]:
        print(f"  Section {sec['num']:>2}: {sec['title']:<42} {len(sec['rows'])} employees")

    html      = render_report(context)
    docs_path = write_report(html, start, end, args.sample)
    print(f"Report written:    {docs_path}")

    import update_index as ui
    ui.regenerate_index()
    print(f"Index updated:     {DOCS_DIR / 'index.html'}")
    print("Done.")


if __name__ == "__main__":
    main()
