from __future__ import annotations

"""
WebLife Ventures — Friday Solutions Q1 Repeated Pattern Analysis
=================================================================
Identifies FS team members with 2+ month SLA violation patterns
across a full quarter, using TMetric CSV data.

Available metrics (TMetric only tracks 3):
  - Activity %   (Activity Level × 100)
  - Total Hours  (Total Time HH:MM:SS → decimal)
  - Manual %     (Manually Added / Total Time × 100)

6 Sections:
  1. Activity Red         (A < 35%)
  2. Activity Yellow      (A 35–45%)
  3. Overwork             (H ≥ 200h)
  4. Low Hours            (H < 160h)
  5. Manual Red           (M ≥ 10%)
  6. Manual Yellow        (M 5–10%)
  7. Executive Summary

Usage:
    python scripts/generate_fs_pattern_analysis.py \
        --months data/input/monthly/FS-2026-01-master.csv \
                 data/input/monthly/FS-2026-02-master.csv \
                 data/input/monthly/FS-2026-03-master.csv \
        --labels "January 2026" "February 2026" "March 2026" \
        --start 2026-01-01 --end 2026-03-31

Outputs:
    docs/<start>_to_<end>_fs_pattern_analysis.html
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
    DOCS_DIR,
    MANUAL_RED, MANUAL_YELLOW,
    calculate_prorated_thresholds,
)

REPO_ROOT     = Path(__file__).parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"

STATUS_ICON = {"red": "🔴", "orange": "🟠", "yellow": "⚠️", "clean": "✅"}


# ---------------------------------------------------------------------------
# TMetric CSV loader
# ---------------------------------------------------------------------------

def _hms_to_hours(value) -> float:
    """Convert 'HH:MM:SS' to decimal hours."""
    if pd.isna(value):
        return float("nan")
    parts = str(value).strip().split(":")
    try:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        return h + m / 60 + s / 3600
    except Exception:
        return float("nan")


def load_fs_csv(csv_path: Path) -> pd.DataFrame:
    """Load and parse a TMetric activity summary CSV."""
    df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)
    df = df.dropna(how="all").reset_index(drop=True)

    df["member"]       = df["Person"].fillna("Unknown")
    df["total_hours"]  = df["Total Time"].apply(_hms_to_hours)
    df["manual_hours"] = df["Manually Added"].apply(_hms_to_hours)
    df["activity_pct"] = pd.to_numeric(df["Activity Level"], errors="coerce") * 100
    df["manual_pct"]   = (df["manual_hours"] / df["total_hours"] * 100).where(df["total_hours"] > 0)

    return df


def _month_dates(csv_path: Path) -> tuple[date, date]:
    """Derive first and last day of month from filename FS-YYYY-MM-master.csv."""
    stem  = csv_path.stem          # e.g. FS-2026-01-master
    parts = stem.split("-")        # ['FS', '2026', '01', 'master']
    year, month = int(parts[1]), int(parts[2])
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

def _classify_activity(val: float) -> str:
    if pd.isna(val): return "clean"
    if val < ACTIVITY_RED:    return "red"
    if val < ACTIVITY_YELLOW: return "yellow"
    return "clean"


def _classify_hours(val: float, pr: float, po: float) -> str:
    if pd.isna(val): return "clean"
    if val < pr:     return "red"
    if val >= po:    return "orange"
    return "clean"


def _classify_manual(val: float) -> str:
    if pd.isna(val): return "clean"
    if val >= MANUAL_RED:    return "red"
    if val >= MANUAL_YELLOW: return "yellow"
    return "clean"


def _fmt_pct(val: float, status: str) -> str:
    if pd.isna(val): return "—"
    return f"{val:.1f}% {STATUS_ICON.get(status, '')}".strip()


def _fmt_hours_val(val: float, status: str) -> str:
    if pd.isna(val): return "—"
    return f"{val:.1f}h {STATUS_ICON.get(status, '')}".strip()


def _fmt_pct_hours(pct: float, hrs: float, status: str) -> str:
    if pd.isna(pct): return "—"
    hrs_str = f"{hrs:.1f}h" if not pd.isna(hrs) else "—"
    return f"{pct:.1f}% ({hrs_str}) {STATUS_ICON.get(status, '')}".strip()


def _trend(values: list, higher_is_worse: bool = False) -> tuple[str, str]:
    present = [v for v in values if v is not None and not pd.isna(v)]
    if len(present) < 2:
        return "➡️ Flat", "trend-stable"
    delta = present[-1] - present[0]
    if abs(delta) < 5.0:
        return "➡️ Flat", "trend-stable"
    if higher_is_worse:
        return ("⬆️ Worsening", "trend-up") if delta > 0 else ("⬇️ Improving", "trend-down")
    else:
        return ("⬆️ Worsening", "trend-up") if delta < 0 else ("⬇️ Improving", "trend-down")


def _trend_hours(values: list, overwork: bool = False) -> tuple[str, str]:
    present = [v for v in values if v is not None and not pd.isna(v)]
    if len(present) < 2:
        return "➡️ Flat", "trend-stable"
    delta = present[-1] - present[0]
    if abs(delta) < 15:
        return "➡️ Flat", "trend-stable"
    if overwork:
        return ("⬆️ Worsening", "trend-up") if delta > 0 else ("⬇️ Improving", "trend-down")
    else:
        return ("⬆️ Worsening", "trend-up") if delta < 0 else ("⬇️ Improving", "trend-down")


def _detect_bad_good_bad(statuses: list) -> bool:
    if len(statuses) != 3: return False
    s1, s2, s3 = statuses
    v = lambda s: s in ("red", "yellow", "orange")
    return v(s1) and not v(s2) and v(s3)


def _action(status_last: str, months_violated: int) -> str:
    if status_last == "red" and months_violated == 3:   return "Immediate escalation"
    if status_last == "red":                            return "Executive review"
    if months_violated == 3:                            return "Monitor closely"
    return "Escalate if continues"


def _score_sort(row: dict) -> tuple:
    sev = {"red": 3, "orange": 2, "yellow": 1, "clean": 0}
    return (-row["months_violated"], -sev.get(row["status_last"], 0), row["employee"].lower())


# ---------------------------------------------------------------------------
# Load all months
# ---------------------------------------------------------------------------

def load_all_months(
    csv_paths: list[Path],
    labels: list[str],
) -> tuple[dict, list[tuple[float, float]]]:
    employee_data: dict = {}
    thresholds: list    = []

    for csv_path, label in zip(csv_paths, labels):
        month_start, month_end = _month_dates(csv_path)
        pr, po = calculate_prorated_thresholds(month_start, month_end)
        thresholds.append((pr, po))

        df = load_fs_csv(csv_path)
        for _, row in df.iterrows():
            name      = row["member"]
            norm_name = name.lower().strip()
            if norm_name not in employee_data:
                employee_data[norm_name] = {"display": name, "team": "Friday Solutions"}
            employee_data[norm_name][label] = row

    return employee_data, thresholds


# ---------------------------------------------------------------------------
# Build section
# ---------------------------------------------------------------------------

def build_section(
    employee_data: dict,
    labels: list[str],
    thresholds: list,
    metric: str,
    severity_filter: str,
    higher_is_worse: bool = False,
) -> list[dict]:
    rows = []

    for norm_name, data in employee_data.items():
        month_rows = [data.get(lbl) for lbl in labels]
        if any(r is None for r in month_rows):
            continue   # must be present in all 3 months

        values, statuses, cells = [], [], []

        for i, row in enumerate(month_rows):
            pr, po = thresholds[i]

            if metric == "activity":
                val    = row.get("activity_pct", float("nan"))
                status = _classify_activity(val)
                cell   = _fmt_pct(val, status)

            elif metric == "hours_red":
                val    = row.get("total_hours", float("nan"))
                status = _classify_hours(val, pr, po)
                if status == "orange": status = "clean"
                cell   = _fmt_hours_val(val, status)

            elif metric == "hours_orange":
                val    = row.get("total_hours", float("nan"))
                status = _classify_hours(val, pr, po)
                if status == "red": status = "clean"
                cell   = _fmt_hours_val(val, status)

            elif metric == "manual":
                val    = row.get("manual_pct", float("nan"))
                hrs    = row.get("manual_hours", float("nan"))
                status = _classify_manual(val)
                cell   = _fmt_pct_hours(val, hrs, status)

            else:
                val, status, cell = float("nan"), "clean", "—"

            values.append(val if not pd.isna(val) else None)
            statuses.append(status)
            cells.append(cell)

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

        if metric in ("hours_red", "hours_orange"):
            trend_label, trend_class = _trend_hours(values, overwork=(metric == "hours_orange"))
        else:
            trend_label, trend_class = _trend(values, higher_is_worse=higher_is_worse)

        if _detect_bad_good_bad(statuses):
            trend_label, trend_class = "🔄 Bad→Good→Bad", "trend-bgb"

        status_last = statuses[-1]
        is_red = severity_filter in ("red", "orange")
        action  = _action(status_last, months_violated) if is_red else (
            "Monitor closely" if months_violated == 3 else "Escalate if continues"
        )

        rows.append({
            "employee":        data["display"],
            "team":            data["team"],
            "cells":           cells,
            "statuses":        statuses,
            "trend_label":     trend_label,
            "trend_class":     trend_class,
            "months_violated": months_violated,
            "status_last":     status_last,
            "action":          action,
            "is_red_section":  is_red,
        })

    rows.sort(key=_score_sort)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# ---------------------------------------------------------------------------
# Executive summary
# ---------------------------------------------------------------------------

def build_exec_summary(sections: list[dict]) -> dict:
    critical: list = []
    high_priority: list = []
    multi: dict = {}
    for sec in sections:
        if not sec["rows"]: continue
        names = [r["employee"] for r in sec["rows"]]
        entry = {
            "title":     sec["title"],
            "count":     len(sec["rows"]),
            "top_names": ", ".join(names[:3]) + ("..." if len(names) > 3 else ""),
            "is_red":    sec["is_red"],
        }
        (critical if sec["is_red"] else high_priority).append(entry)
        for r in sec["rows"]:
            multi[r["employee"]] = multi.get(r["employee"], 0) + 1

    return {
        "critical":        critical,
        "high_priority":   high_priority,
        "multi_violators": sorted([(n, c) for n, c in multi.items() if c >= 2], key=lambda x: -x[1]),
    }


# ---------------------------------------------------------------------------
# Build context
# ---------------------------------------------------------------------------

def build_context(
    employee_data: dict,
    labels: list[str],
    thresholds: list,
    start: date,
    end: date,
) -> dict:

    SECTION_DEFS = [
        ("act_red",  "Activity Level Violations",      "activity",      "red",    False, True),
        ("act_yel",  "Activity Level Yellow Warnings",  "activity",      "yellow", False, False),
        ("ovr",      "Overwork Pattern: Hours",         "hours_orange",  "orange", True,  False),
        ("low_hrs",  "Low Hours Violations",             "hours_red",     "red",    False, True),
        ("man_red",  "Manual Time Violations",           "manual",        "red",    True,  True),
        ("man_yel",  "Manual Time Yellow Warnings",      "manual",        "yellow", True,  False),
    ]

    SUBTITLES = {
        "act_red":  "A < 35%",
        "act_yel":  "A 35–45%",
        "ovr":      f"H ≥ {thresholds[0][1]:.0f}h",
        "low_hrs":  f"H < {thresholds[0][0]:.0f}h",
        "man_red":  "M ≥ 10%",
        "man_yel":  "M 5–10%",
    }

    sections = []
    for sec_id, title, metric, sev_filter, hiw, is_red in SECTION_DEFS:
        rows = build_section(employee_data, labels, thresholds, metric, sev_filter, hiw)
        sections.append({
            "id":       sec_id,
            "num":      len(sections) + 1,
            "title":    title,
            "subtitle": SUBTITLES[sec_id],
            "rows":     rows,
            "is_red":   is_red,
        })

    period_label = f"Q1 {start.year}" if (start.month == 1 and end.month >= 3) else f"{start} to {end}"

    return {
        "report_title":   "Friday Solutions — Q1 Pattern Analysis",
        "period_label":   period_label,
        "date_range":     f"{start.strftime('%B %d, %Y')} — {end.strftime('%B %d, %Y')}",
        "labels":         labels,
        "sections":       sections,
        "exec_summary":   build_exec_summary(sections),
        "total_analysed": len(employee_data),
        "generated_at":   pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "is_sample":      False,
    }


# ---------------------------------------------------------------------------
# Render + write
# ---------------------------------------------------------------------------

def render_report(context: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    return env.get_template("pattern_analysis_template.html").render(**context)


def write_report(html: str, start: date, end: date) -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCS_DIR / f"{start.isoformat()}_to_{end.isoformat()}_fs_pattern_analysis.html"
    path.write_text(html, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate Friday Solutions Q1 pattern analysis.")
    parser.add_argument("--months", nargs=3, metavar="CSV", required=True)
    parser.add_argument("--labels", nargs=3, metavar="LABEL",
                        default=["Month 1", "Month 2", "Month 3"])
    parser.add_argument("--start",  required=True, help="Quarter start YYYY-MM-DD")
    parser.add_argument("--end",    required=True, help="Quarter end YYYY-MM-DD")
    args = parser.parse_args()

    start     = date.fromisoformat(args.start)
    end       = date.fromisoformat(args.end)
    csv_paths = [Path(p) for p in args.months]

    for p in csv_paths:
        if not p.exists():
            print(f"ERROR: File not found: {p}", file=sys.stderr)
            sys.exit(1)

    print("=" * 60)
    print(f"FS Q1 Pattern Analysis: {start} to {end}")
    print("=" * 60)

    employee_data, thresholds = load_all_months(csv_paths, args.labels)
    print(f"Members loaded:        {len(employee_data)}")
    for label, (pr, po) in zip(args.labels, thresholds):
        print(f"  {label}: red < {pr:.0f}h | orange ≥ {po:.0f}h")

    context = build_context(employee_data, args.labels, thresholds, start, end)
    for sec in context["sections"]:
        print(f"  Section {sec['num']}: {sec['title']:<38} {len(sec['rows'])} members")

    html      = render_report(context)
    docs_path = write_report(html, start, end)
    print(f"Report written:        {docs_path}")

    import update_index as ui
    ui.regenerate_index()
    print(f"Index updated:         {DOCS_DIR / 'index.html'}")
    print("Done.")


if __name__ == "__main__":
    main()
