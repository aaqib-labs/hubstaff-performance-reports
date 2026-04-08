"""
WebLife Ventures — Friday Solutions Performance Report Generator
================================================================
Generates an HTML performance report from a TMetric activity summary CSV.

Usage:
    python scripts/generate_fs_report.py \
        --input data/input/activity_summary_20260301_20260324.csv \
        --start 2026-03-01 \
        --end 2026-03-24

TMetric CSV columns expected:
    Person, Total Time (HH:MM:SS), Manually Added (HH:MM:SS), Activity Level (0–1 decimal)

Metrics evaluated: Activity %, Total Hours, Manual % only.
Same SLA thresholds and scoring as the Hubstaff report.
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

REPO_ROOT     = Path(__file__).parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"

# SLA thresholds (same source of truth as Hubstaff report)
ACTIVITY_RED    = 35.0
ACTIVITY_YELLOW = 45.0
MANUAL_RED      = 10.0
MANUAL_YELLOW   =  5.0
HOURS_BASE         = 160.0
HOURS_OVERWORK_BASE = 200.0

SCORE_RED    = 10
SCORE_YELLOW =  3
SCORE_ORANGE =  7

MULTIPLIERS = {
    "A":        5,
    "M":        4,
    "H_red":    3,
    "H_orange": 2,
}



# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def _hms_to_hours(value) -> float:
    """Convert 'HH:MM:SS' or 'H:MM:SS' to decimal hours. Returns NaN on failure."""
    if pd.isna(value):
        return float("nan")
    parts = str(value).strip().split(":")
    try:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        return h + m / 60 + s / 3600
    except Exception:
        return float("nan")


def load_tmetric_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)
    df = df.dropna(how="all").reset_index(drop=True)

    df["member"]        = df["Person"].fillna("Unknown")
    df["total_hours"]   = df["Total Time"].apply(_hms_to_hours)
    df["manual_hours"]  = df["Manually Added"].apply(_hms_to_hours)
    df["activity_pct"]  = pd.to_numeric(df["Activity Level"], errors="coerce") * 100
    df["manual_pct"]    = (df["manual_hours"] / df["total_hours"] * 100).where(df["total_hours"] > 0)

    return df


# ---------------------------------------------------------------------------
# Flag evaluation (Activity, Hours, Manual only)
# ---------------------------------------------------------------------------

def evaluate_flags(row: pd.Series, prorated_red: float, prorated_orange: float) -> dict:
    flags = {}

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

    return flags


def calculate_score(flags: dict) -> float:
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
    """Return (red_or_orange_count, yellow_count). No B exclusion needed here."""
    red = sum(1 for s in flags.values() if s in ("red", "orange"))
    yellow = sum(1 for s in flags.values() if s == "yellow")
    return red, yellow


# ---------------------------------------------------------------------------
# Cell formatters
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


def fmt_manual(hours_val, pct_val, flag) -> str:
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

    rows_scored = []
    for _, row in df.iterrows():
        flags = evaluate_flags(row, prorated_red, prorated_orange)
        score = calculate_score(flags)
        red_count, yellow_count = count_flags(flags)
        rows_scored.append({
            "member":       row["member"],
            "activity_pct": row.get("activity_pct", float("nan")),
            "total_hours":  row.get("total_hours",  float("nan")),
            "manual_hours": row.get("manual_hours", float("nan")),
            "manual_pct":   row.get("manual_pct",   float("nan")),
            "flags":        flags,
            "score":        score,
            "red_count":    red_count,
            "yellow_count": yellow_count,
        })

    rows_scored.sort(key=lambda x: x["score"], reverse=True)

    table_rows = []
    for rank, r in enumerate(rows_scored, start=1):
        flags = r["flags"]
        table_rows.append({
            "rank":          rank,
            "member":        r["member"],
            "activity_cell": fmt_activity(r["activity_pct"], flags.get("A")),
            "hours_cell":    fmt_hours(r["total_hours"], flags.get("H")),
            "manual_cell":   fmt_manual(r["manual_hours"], r["manual_pct"], flags.get("M")),
            "flags_badge":   fmt_flags_badge(r["red_count"], r["yellow_count"]),
            "score":         f"{r['score']:.1f}",
            "row_class":     row_severity_class(r["score"]),
        })

    hours_violators = []
    for r in rows_scored:
        h = r["total_hours"]
        if not pd.isna(h) and h < prorated_red:
            shortfall = prorated_red - h
            hours_violators.append({
                "member":         r["member"],
                "hours_worked":   f"{h:.1f}h",
                "expected_hours": f"{prorated_red:.1f}h",
                "shortfall":      f"{shortfall:.1f}h",
                "other_flags":    fmt_flags_badge(r["red_count"], r["yellow_count"]),
            })
    hours_violators.sort(key=lambda x: float(x["hours_worked"].replace("h", "")))

    return {
        "report_title":          "Friday Solutions — Performance Report",
        "date_range":            f"{start.strftime('%B %d, %Y')} — {end.strftime('%B %d, %Y')}",
        "start_date":            start.isoformat(),
        "end_date":              end.isoformat(),
        "period_working_days":   count_working_days(start, end),
        "prorated_red":          f"{prorated_red:.1f}h",
        "prorated_orange":       f"{prorated_orange:.1f}h",
        "total_employees":       len(df),
        "total_flagged":         sum(1 for r in rows_scored if r["score"] > 0),
        "table_rows":            table_rows,
        "hours_violators":       hours_violators,
        "hours_violator_count":  len(hours_violators),
        "generated_at":          pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "thresh_activity_red":   f"< {ACTIVITY_RED:.0f}%",
        "thresh_activity_yellow":f"< {ACTIVITY_YELLOW:.0f}%",
        "thresh_hours_red":      f"< {prorated_red:.1f}h",
        "thresh_hours_orange":   f"≥ {prorated_orange:.1f}h",
        "thresh_manual_red":     f"≥ {MANUAL_RED:.0f}%",
        "thresh_manual_yellow":  f"≥ {MANUAL_YELLOW:.0f}%",
    }


# ---------------------------------------------------------------------------
# Render + write
# ---------------------------------------------------------------------------

def render_report(context: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("fs_report_template.html")
    return template.render(**context)


def write_report(html: str, start: date, end: date) -> Path:
    """Write report directly to /docs/. Returns docs_path."""
    folder_name = f"{start.isoformat()}_to_{end.isoformat()}"
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    docs_path = DOCS_DIR / f"{folder_name}_fs_report.html"
    docs_path.write_text(html, encoding="utf-8")
    return docs_path


def update_index():
    sys.path.insert(0, str(Path(__file__).parent))
    import update_index as ui
    ui.regenerate_index()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate Friday Solutions performance report.")
    parser.add_argument("--input",  required=True, help="Path to TMetric activity summary CSV")
    parser.add_argument("--start",  required=True, help="Period start date YYYY-MM-DD")
    parser.add_argument("--end",    required=True, help="Period end date YYYY-MM-DD")
    args = parser.parse_args()

    start    = date.fromisoformat(args.start)
    end      = date.fromisoformat(args.end)
    csv_path = Path(args.input)

    if not csv_path.exists():
        print(f"ERROR: Input file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    prorated_red, prorated_orange = calculate_prorated_thresholds(start, end)
    print_threshold_header(start, end, prorated_red, prorated_orange)

    print(f"Loading: {csv_path}")
    df = load_tmetric_csv(csv_path)
    print(f"Loaded {len(df)} employees.")

    context = build_report_data(df, prorated_red, prorated_orange, start, end)
    print(f"Employees flagged: {context['total_flagged']} / {context['total_employees']}")
    print(f"Hours violators:   {context['hours_violator_count']}")

    html = render_report(context)
    docs_path = write_report(html, start, end)
    print(f"Report written:    {docs_path}")

    update_index()
    print(f"Index updated:     {DOCS_DIR / 'index.html'}")
    print("Done.")


if __name__ == "__main__":
    main()
