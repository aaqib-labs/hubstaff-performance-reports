from __future__ import annotations

"""
WebLife Ventures — Q2 Combined Pattern Analysis (HS + Friday Solutions)
=======================================================================
Merges Hubstaff (HS) and TMetric/Friday Solutions (FS) monthly data into a
single repeated-pattern report for a full quarter.

HS employees are evaluated on all 10 metric sections.
FS employees are evaluated on Activity, Hours, and Manual only — they
naturally skip Low Act ≤20%, Low Act ≤30% sections since TMetric does not
track those metrics (NaN → clean on those sections).

Usage:
    python scripts/generate_combined_pattern_analysis.py \
        --hs-months data/input/monthly/HS-2026-04-master.csv \
                    data/input/monthly/HS-2026-05-master.csv \
                    data/input/monthly/HS-2026-06-master.csv \
        --fs-months data/input/monthly/FS-2026-04-master.csv \
                    data/input/monthly/FS-2026-05-master.csv \
                    data/input/monthly/FS-2026-06-master.csv \
        --labels "April 2026" "May 2026" "June 2026" \
        --start 2026-04-01 --end 2026-06-30

Outputs:
    docs/<start>_to_<end>_pattern_analysis.html   (replaces HS-only version)
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

STATUS_ICON = {"red": "🔴", "orange": "🟠", "yellow": "⚠️", "clean": "✅"}


# ---------------------------------------------------------------------------
# Helpers shared with generate_pattern_analysis.py
# ---------------------------------------------------------------------------

def _month_dates(csv_path: Path) -> tuple[date, date]:
    stem  = csv_path.stem
    parts = stem.split("-")
    year, month = int(parts[1]), int(parts[2])
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _hms_to_hours(value) -> float:
    if pd.isna(value):
        return float("nan")
    parts = str(value).strip().split(":")
    try:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        return h + m / 60 + s / 3600
    except Exception:
        return float("nan")


def _classify(value: float, red_thresh, yellow_thresh, direction: str = "low") -> str:
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
    if pd.isna(value):            return "clean"
    if value < prorated_red:      return "red"
    if value >= prorated_orange:  return "orange"
    return "clean"


def _fmt_pct(value: float, status: str) -> str:
    if pd.isna(value): return "—"
    return f"{value:.1f}% {STATUS_ICON.get(status, '')}".strip()


def _fmt_pct_hours(pct: float, hrs: float, status: str) -> str:
    if pd.isna(pct): return "—"
    hrs_str = f"{hrs:.1f}h" if not pd.isna(hrs) else "—"
    return f"{pct:.1f}% ({hrs_str}) {STATUS_ICON.get(status, '')}".strip()


def _fmt_hours_val(value: float, status: str) -> str:
    if pd.isna(value): return "—"
    return f"{value:.1f}h {STATUS_ICON.get(status, '')}".strip()


def _trend(values: list, higher_is_worse: bool = False) -> tuple[str, str]:
    present = [v for v in values if v is not None]
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


def _detect_bad_good_bad(statuses: list) -> bool:
    if len(statuses) != 3: return False
    s1, s2, s3 = statuses
    if any(s is None for s in (s1, s2, s3)): return False
    v = lambda s: s in ("red", "yellow", "orange")
    return v(s1) and (not v(s2)) and v(s3)


def _action(status_last: str, months_violated: int) -> str:
    if status_last == "red" and months_violated == 3: return "Immediate escalation"
    if status_last == "red":                          return "Executive review"
    if months_violated == 3:                          return "Monitor closely"
    return "Escalate if continues"


def _status_yellow(months_violated: int) -> str:
    return "Monitor closely" if months_violated == 3 else "Escalate if continues"


def _score_sort(row: dict) -> tuple:
    severity_map = {"red": 3, "orange": 2, "yellow": 1, "clean": 0}
    return (-row["months_violated"], -severity_map.get(row.get("status_last", "clean"), 0), row["employee"].lower())


# ---------------------------------------------------------------------------
# Load HS months
# ---------------------------------------------------------------------------

def load_hs_months(
    csv_paths: list[Path],
    labels: list[str],
    employee_data: dict,
    thresholds: list,
) -> None:
    all_exclusions = set(n.lower() for n in PERMANENT_EXCLUSIONS + FS_EXCLUSIONS)

    for csv_path, label in zip(csv_paths, labels):
        month_start, month_end = _month_dates(csv_path)
        pr, po = calculate_prorated_thresholds(month_start, month_end)
        if not thresholds:
            thresholds.append((pr, po))
        elif label not in [l for l, _ in thresholds] if isinstance(thresholds[0], tuple) else False:
            pass

        df = load_master_table(csv_path)
        df = df[~df["member"].apply(lambda n: n.lower() in all_exclusions)].reset_index(drop=True)

        for _, row in df.iterrows():
            name      = row["member"]
            norm_name = name.lower().strip()
            if norm_name not in employee_data:
                employee_data[norm_name] = {"display": name, "team": row["team"], "source": "hs"}
            employee_data[norm_name][label] = row


# ---------------------------------------------------------------------------
# Load FS months
# ---------------------------------------------------------------------------

def _make_fs_row(person_row: pd.Series) -> dict:
    """Convert a TMetric CSV row to the same field schema used by HS rows."""
    total_h  = _hms_to_hours(person_row.get("Total Time"))
    manual_h = _hms_to_hours(person_row.get("Manually Added"))
    act_pct  = pd.to_numeric(person_row.get("Activity Level"), errors="coerce")
    if not pd.isna(act_pct):
        act_pct = act_pct * 100

    manual_pct = (manual_h / total_h * 100) if (total_h and total_h > 0) else float("nan")

    return {
        "member":        person_row.get("Person", "Unknown"),
        "team":          "Friday Solutions",
        "activity_pct":  act_pct,
        "total_hours":   total_h,
        "manual_hours":  manual_h,
        "manual_pct":    manual_pct,
        # FS has no break or low-activity data — NaN means clean on those sections
        "break_pct":     float("nan"),
        "low20_pct":     float("nan"),
        "low20_hours":   float("nan"),
        "low30_pct":     float("nan"),
        "low30_hours":   float("nan"),
    }


def load_fs_months(
    csv_paths: list[Path],
    labels: list[str],
    employee_data: dict,
) -> None:
    # FS_EXCLUSIONS exists to keep FS members OUT of HS reports — don't apply here.
    # Only exclude PERMANENT_EXCLUSIONS (terminated HS-side staff, contractors).
    fs_exclusions_lower = set(n.lower() for n in PERMANENT_EXCLUSIONS)

    for csv_path, label in zip(csv_paths, labels):
        df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
        df.columns = [c.strip() for c in df.columns]
        df = df.map(lambda x: x.strip() if isinstance(x, str) else x)
        df = df.dropna(subset=["Person"]).reset_index(drop=True)

        for _, person_row in df.iterrows():
            name      = str(person_row.get("Person", "")).strip()
            norm_name = name.lower()
            if norm_name in fs_exclusions_lower:
                continue
            if not name:
                continue

            fs_row = _make_fs_row(person_row)

            if norm_name not in employee_data:
                employee_data[norm_name] = {"display": name, "team": "Friday Solutions", "source": "fs"}
            employee_data[norm_name][label] = fs_row


# ---------------------------------------------------------------------------
# Build per-metric section
# ---------------------------------------------------------------------------

def build_section(
    employee_data: dict,
    labels: list[str],
    thresholds: list[tuple[float, float]],
    metric: str,
    severity_filter: str,
    higher_is_worse: bool = False,
) -> list[dict]:
    rows = []

    for norm_name, data in employee_data.items():
        month_rows = [data.get(lbl) for lbl in labels]
        if any(r is None for r in month_rows):
            continue

        values, statuses, fmt_cells = [], [], []

        for i, row in enumerate(month_rows):
            pr, po = thresholds[i]

            def _get(field):
                if isinstance(row, dict):
                    return row.get(field, float("nan"))
                try:
                    return row.get(field, float("nan"))
                except Exception:
                    return float("nan")

            if metric == "activity":
                val    = _get("activity_pct")
                status = _classify(val, ACTIVITY_RED, ACTIVITY_YELLOW, "low")
                cell   = _fmt_pct(val, status)
            elif metric == "hours_red":
                val    = _get("total_hours")
                status = _classify_hours(val, pr, po)
                if status == "orange": status = "clean"
                cell   = _fmt_hours_val(val, status)
            elif metric == "hours_orange":
                val    = _get("total_hours")
                status = _classify_hours(val, pr, po)
                if status == "red": status = "clean"
                cell   = _fmt_hours_val(val, status)
            elif metric == "manual":
                val  = _get("manual_pct")
                hrs  = _get("manual_hours")
                status = _classify(val, MANUAL_RED, MANUAL_YELLOW, "high")
                cell   = _fmt_pct_hours(val, hrs, status)
            elif metric == "break":
                val    = _get("break_pct")
                status = _classify(val, BREAK_RED, BREAK_YELLOW, "high")
                cell   = _fmt_pct(val, status)
            elif metric == "low20":
                val  = _get("low20_pct")
                hrs  = _get("low20_hours")
                status = _classify(val, LOW20_RED, LOW20_YELLOW, "high")
                cell   = _fmt_pct_hours(val, hrs, status)
            elif metric == "low30":
                val  = _get("low30_pct")
                hrs  = _get("low30_hours")
                status = _classify(val, LOW30_RED, LOW30_YELLOW, "high")
                cell   = _fmt_pct_hours(val, hrs, status)
            else:
                val, status, cell = float("nan"), "clean", "—"

            values.append(val if not pd.isna(val) else None)
            statuses.append(status)
            fmt_cells.append(cell)

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

        status_last    = statuses[-1]
        is_red_section = severity_filter in ("red", "orange")
        action = _action(status_last, months_violated) if is_red_section else _status_yellow(months_violated)

        rows.append({
            "employee":        data["display"],
            "team":            data.get("team", "—"),
            "cells":           fmt_cells,
            "statuses":        statuses,
            "trend_label":     trend_label,
            "trend_class":     trend_class,
            "months_violated": months_violated,
            "status_last":     status_last,
            "action":          action,
            "is_red_section":  is_red_section,
        })

    rows.sort(key=_score_sort)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# ---------------------------------------------------------------------------
# Executive summary
# ---------------------------------------------------------------------------

def build_exec_summary(sections: list[dict]) -> dict:
    critical, high_priority = [], []
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
# Build full context
# ---------------------------------------------------------------------------

def build_context(
    employee_data: dict,
    labels: list[str],
    thresholds: list[tuple[float, float]],
    start: date,
    end: date,
) -> dict:

    SECTION_DEFS = [
        ("act_red",  "Activity Level Violations",           "activity",     "red",    False, True),
        ("act_yel",  "Activity Level Yellow Warnings",      "activity",     "yellow", False, False),
        ("ovr",      "Overwork Pattern: Hours Violations",  "hours_orange", "orange", True,  False),
        ("low_hrs",  "Low Hours Violations",                "hours_red",    "red",    False, True),
        ("man_red",  "Manual Time Violations",              "manual",       "red",    True,  True),
        ("man_yel",  "Manual Time Yellow Warnings",         "manual",       "yellow", True,  False),
        ("l20_red",  "Low Activity ≤20% Violations",        "low20",        "red",    True,  True),
        ("l20_yel",  "Low Activity ≤20% Warnings",          "low20",        "yellow", True,  False),
        ("l30_red",  "Low Activity ≤30% Violations",        "low30",        "red",    True,  True),
        ("l30_yel",  "Low Activity ≤30% Warnings",          "low30",        "yellow", True,  False),
    ]

    SUBTITLES = {
        "act_red":  "A < 35%",
        "act_yel":  "A 35–45%",
        "ovr":      f"H ≥ {thresholds[0][1]:.0f}h",
        "low_hrs":  f"H < {thresholds[0][0]:.0f}h",
        "man_red":  "M ≥ 10%",
        "man_yel":  "M 5–10%",
        "l20_red":  "≥ 15% of worked hours",
        "l20_yel":  "7.5–15% of worked hours",
        "l30_red":  "≥ 20% of worked hours",
        "l30_yel":  "10–20% of worked hours",
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

    # Quarter label
    if start.month == 4 and end.month >= 6:
        period_label = f"Q2 {start.year}"
    elif start.month == 1 and end.month >= 3:
        period_label = f"Q1 {start.year}"
    elif start.month == 7 and end.month >= 9:
        period_label = f"Q3 {start.year}"
    elif start.month == 10 and end.month >= 12:
        period_label = f"Q4 {start.year}"
    else:
        period_label = f"{start} to {end}"

    return {
        "report_title":   "Repeated Pattern Analysis Report",
        "period_label":   period_label,
        "date_range":     f"{start.strftime('%B %d, %Y')} — {end.strftime('%B %d, %Y')}",
        "labels":         labels,
        "sections":       sections,
        "exec_summary":   build_exec_summary(sections),
        "total_analysed": len(employee_data),
        "generated_at":   pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "is_sample":      False,
        "thresholds":     thresholds,
    }


# ---------------------------------------------------------------------------
# Render + write
# ---------------------------------------------------------------------------

def render_report(context: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    return env.get_template("pattern_analysis_template.html").render(**context)


def write_report(html: str, start: date, end: date) -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCS_DIR / f"{start.isoformat()}_to_{end.isoformat()}_pattern_analysis.html"
    path.write_text(html, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate combined HS + FS Q2 pattern analysis.")
    parser.add_argument("--hs-months", nargs=3, metavar="CSV", required=True,
                        help="Three monthly Hubstaff CSVs (HS-YYYY-MM-master.csv)")
    parser.add_argument("--fs-months", nargs=3, metavar="CSV", required=True,
                        help="Three monthly Friday Solutions CSVs (FS-YYYY-MM-master.csv)")
    parser.add_argument("--labels",   nargs=3, metavar="LABEL",
                        default=["Month 1", "Month 2", "Month 3"])
    parser.add_argument("--start",    required=True, help="Quarter start YYYY-MM-DD")
    parser.add_argument("--end",      required=True, help="Quarter end YYYY-MM-DD")
    args = parser.parse_args()

    start     = date.fromisoformat(args.start)
    end       = date.fromisoformat(args.end)
    hs_paths  = [Path(p) for p in args.hs_months]
    fs_paths  = [Path(p) for p in args.fs_months]

    for p in hs_paths + fs_paths:
        if not p.exists():
            print(f"ERROR: File not found: {p}", file=sys.stderr)
            sys.exit(1)

    print("=" * 60)
    print(f"Q2 Combined Pattern Analysis: {start} to {end}")
    print("=" * 60)

    employee_data: dict = {}
    thresholds: list    = []

    # Load HS months first (thresholds come from HS month dates)
    for csv_path, label in zip(hs_paths, args.labels):
        month_start, month_end = _month_dates(csv_path)
        pr, po = calculate_prorated_thresholds(month_start, month_end)
        thresholds.append((pr, po))

    load_hs_months(hs_paths, args.labels, employee_data, [])
    hs_count = len(employee_data)
    print(f"HS employees loaded:   {hs_count}")

    load_fs_months(fs_paths, args.labels, employee_data)
    fs_count = len(employee_data) - hs_count
    print(f"FS employees loaded:   {fs_count}")
    print(f"Total combined:        {len(employee_data)}")

    for label, (pr, po) in zip(args.labels, thresholds):
        print(f"  {label}: red < {pr:.0f}h | orange ≥ {po:.0f}h")

    context = build_context(employee_data, args.labels, thresholds, start, end)

    for sec in context["sections"]:
        print(f"  Section {sec['num']:>2}: {sec['title']:<42} {len(sec['rows'])} employees")

    html      = render_report(context)
    docs_path = write_report(html, start, end)
    print(f"Report written:        {docs_path}")

    import update_index as ui
    ui.regenerate_index()
    print(f"Index updated:         {DOCS_DIR / 'index.html'}")
    print("Done.")


if __name__ == "__main__":
    main()
