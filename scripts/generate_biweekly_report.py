from __future__ import annotations

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

Time Off (--leave)
------------------
For a full calendar month, pass --leave <TO CSV> (built by build_timeoff_csv.py)
or an explicit --no-leave. With --leave, Section 2 rows expand to show the
time-off breakdown and a Section 3 Leave Summary is added.
Hubstaff Total Worked Hours already includes approved PAID time off and paid
holidays, but NOT unpaid leave (checked against Hubstaff activities_daily,
Oct 2026). So:
    Worked = Total Worked Hours − approved paid time off
Unapproved time off is shown but never counted. SLA flags are unchanged.

Pay type and leave-adjusted hours (--salaried / --hourly)
---------------------------------------------------------
Names come from the ClickUp HR profiles (Salary Type field) on the command
line and are never written to disk. Anyone in neither list is Unknown and is
counted as salaried.
    Salaried / Unknown: Counted = Worked + approved paid leave (= Total)
    Hourly:             Counted = Worked + approved paid leave + approved unpaid leave
                        (their pay is cut for unpaid leave, so they do not make it up;
                        People Ops, 11 Nov 2026)
    Shortfall = prorated 160h threshold − Counted (none when Counted reaches it)
A full-month run with --leave must pass --salaried/--hourly or --no-pay-type.

Salaried hours, last 3 months (Section 3, month-end only)
---------------------------------------------------------
Every salaried team member's Hubstaff total for this month and the two before
(from data/input/monthly/HS-YYYY-MM-master.csv), split into two tables:
    Moved from hourly to salaried: each person's target from the salaried
        status file (180h only where it was agreed, flagged under 170h; 160h
        otherwise), from the first full month after the move. Months before
        that count against 160h.
    Hired as salaried: target 160h.
Serious = under in 2+ of the 3 months; Alert = under in the latest month only.
Hours are the Hubstaff total (worked + approved paid leave); unpaid leave does
not count.

Salaried status file (--salaried-status, default data/input/salaried/salaried_status.csv,
gitignored): one row per person whose pay type is known from the HR profiles and
transition letters, until the People Ops tracker is in. Columns: member (Hubstaff
name), clickup_name, change, effective_date, target_hours, target_basis, evidence, notes.
    change = moved           Salaried from effective_date (Hourly before it)
             hired_salaried  Salaried, even if the ClickUp field is blank
             hourly          Hourly, even if the ClickUp field says Salaried
             agency          pay tag as ClickUp says; left out of Section 3
The file overrides the ClickUp Salary Type field everywhere in the report.

HR profile context (--hr-context)
---------------------------------
A local JSON (data/input/hr_context/HRC-<start>_to_<end>.json, gitignored) with
short notes from each flagged person's ClickUp HR profile about hours, activity
or leave, reviewed by Aaqib before use. Rows in Sections 1 and 2 expand to show
the notes and a link to the profile. Format:
    {"members": {"<Name>": {"profile_url": "https://app.clickup.com/t/<id>",
                            "notes": [{"author": "...", "date": "YYYY-MM-DD", "text": "..."}]}}}
Use --dry-run to write to a scratch path without touching docs/.
"""

import argparse
import calendar
import json
import os
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader

from utils import (
    calculate_prorated_thresholds,
    count_working_days,
    get_month_working_days,
    print_threshold_header,
    DOCS_DIR,
    get_exclusions,
    match_names,
    MOVED_TARGET, MOVED_FLOOR, HIRED_TARGET, HIRED_FLOOR, first_full_month, floor_for,
    salaried_status,
    FS_EXCLUSIONS, CE_HUBSTAFF_START,
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
# Month-end time off
# ---------------------------------------------------------------------------

HOURS_PER_DAY = 8.0
CATEGORY_PAID   = "Paid/Allocated"
CATEGORY_UNPAID = "Unpaid/Flex"

PAY_HOURLY   = "Hourly"
PAY_SALARIED = "Salaried"
PAY_UNKNOWN  = "Unknown"

# ClickUp HR profile name -> Hubstaff name, for confirmed renames only (Oct-Nov 2026).
PAY_NAME_ALIASES = {
    "Meredith Goostree": "Meredith Sands",
    "Hafiz Mudasir":     "Mudasir Amjad",
    "Rebecca Zelaya":    "Rebecca Corona",
}


def norm_name(name) -> str:
    """Lowercase, trim and collapse internal whitespace."""
    return " ".join(str(name).split()).lower()


def is_full_month(start: date, end: date) -> bool:
    last = calendar.monthrange(start.year, start.month)[1]
    return (start.day == 1 and end.year == start.year and end.month == start.month
            and end.day == last)


def fmt_h(hours: float) -> str:
    return f"{hours:.1f}h"


def fmt_hd(hours: float) -> str:
    """'16.0h (2.0d)' — days = hours / 8."""
    return f"{hours:.1f}h ({hours / HOURS_PER_DAY:.1f}d)"


def load_leave(path: Path) -> tuple[pd.DataFrame, str]:
    """Load the TO CSV and its pull timestamp (from the .meta.json sidecar)."""
    df = pd.read_csv(path, dtype={"member": str, "policy_name": str, "category": str,
                                  "status": str, "date": str})
    required = {"member", "request_id", "policy_name", "category", "status", "date", "hours"}
    missing = required - set(df.columns)
    if missing:
        print(f"ERROR: Time-off CSV is missing columns: {sorted(missing)}", file=sys.stderr)
        sys.exit(1)
    bad_status = set(df["status"]) - {"approved", "unapproved"}
    bad_cat    = set(df["category"]) - {CATEGORY_PAID, CATEGORY_UNPAID}
    if bad_status or bad_cat:
        print(f"ERROR: Unexpected status {bad_status or ''} / category {bad_cat or ''} "
              f"in time-off CSV", file=sys.stderr)
        sys.exit(1)
    df["date"] = df["date"].apply(date.fromisoformat)
    df["hours"] = df["hours"].astype(float)
    df["norm"] = df["member"].apply(norm_name)
    if "approved_at" in df.columns:
        df["approved_at"] = pd.to_datetime(df["approved_at"], utc=True, errors="coerce")
    else:
        # Older TO CSVs have no approval time: treat every approval as before the export
        df["approved_at"] = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns, UTC]")

    pulled_at = None
    meta = Path(str(path) + ".meta.json")
    if meta.exists():
        pulled_at = json.loads(meta.read_text(encoding="utf-8")).get("pulled_at")
    if not pulled_at:
        pulled_at = datetime.utcfromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        pulled_label = datetime.strptime(pulled_at, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        pulled_label = pulled_at
    return df, pulled_label


def _date_ranges(dates: list[date]) -> list[tuple[date, date]]:
    """Group sorted dates into runs; a gap made only of weekend days keeps a run going."""
    runs: list[list[date]] = []
    for d in sorted(dates):
        if runs:
            prev = runs[-1][1]
            gap = [prev + timedelta(days=i) for i in range(1, (d - prev).days)]
            if all(g.weekday() >= 5 for g in gap):
                runs[-1][1] = d
                continue
        runs.append([d, d])
    return [(a, b) for a, b in runs]


def _fmt_range(a: date, b: date) -> str:
    if a == b:
        return f"{a.strftime('%b')} {a.day}"
    if a.month == b.month:
        return f"{a.strftime('%b')} {a.day}–{b.day}"
    return f"{a.strftime('%b')} {a.day} – {b.strftime('%b')} {b.day}"


def build_leave_entries(rows: pd.DataFrame, detail: str) -> list[dict]:
    """One entry per contiguous run of days from the same request + status."""
    entries = []
    for (req_id, status), grp in rows.groupby(["request_id", "status"], sort=False):
        first = grp.iloc[0]
        late = bool(first.get("late", False))
        for a, b in _date_ranges(list(grp["date"])):
            in_run = grp[(grp["date"] >= a) & (grp["date"] <= b)]
            hours = float(in_run["hours"].sum())
            entries.append({
                "policy":      first["policy_name"] if detail == "full" else first["category"],
                "category":    first["category"],
                "dates":       _fmt_range(a, b),
                "sort_key":    a,
                "hours":       fmt_hd(hours),
                "hours_h":     fmt_h(hours),
                "hours_d":     f"{hours / HOURS_PER_DAY:.1f}d",
                "status":      status,
                "status_label": ("Approved after the Hubstaff export" if late else "Approved")
                                if status == "approved" else "Unapproved",
            })
    entries.sort(key=lambda e: (e["sort_key"], e["policy"]))
    return entries


def member_leave_figures(rows: pd.DataFrame, total_hours: float, detail: str,
                         pay: str | None = None) -> dict:
    """Per-member figures. Total already includes approved paid time off but not
    unpaid leave, so Worked = Total − approved paid. Counted adds approved
    unpaid leave back for hourly team members only."""
    approved   = float(rows.loc[rows["status"] == "approved", "hours"].sum())
    unapproved = float(rows.loc[rows["status"] == "unapproved", "hours"].sum())
    by_cat = {}
    for cat in (CATEGORY_PAID, CATEGORY_UNPAID):
        c = rows[rows["category"] == cat]
        by_cat[cat] = (float(c.loc[c["status"] == "approved", "hours"].sum()),
                       float(c.loc[c["status"] == "unapproved", "hours"].sum()))
    paid_appr, unpaid_appr = by_cat[CATEGORY_PAID][0], by_cat[CATEGORY_UNPAID][0]
    # Paid leave approved after the master CSV was exported is not in its Total
    late = rows["late"] if "late" in rows.columns else pd.Series(False, index=rows.index)
    late_paid = float(rows.loc[late & (rows["status"] == "approved")
                               & (rows["category"] == CATEGORY_PAID), "hours"].sum())
    has_total = not pd.isna(total_hours)
    worked = total_hours - (paid_appr - late_paid) if has_total else float("nan")
    unpaid_counted = unpaid_appr if pay == PAY_HOURLY else 0.0
    counted = total_hours + late_paid + unpaid_counted if has_total else float("nan")
    return {
        "approved":       approved,
        "unapproved":     unapproved,
        "by_cat":         by_cat,
        "paid_approved":  paid_appr,
        "late_paid":      late_paid,
        "worked":         worked,
        "counted":        counted,
        "total_fmt":      fmt_h(total_hours) if has_total else "—",
        "worked_fmt":     fmt_h(worked) if has_total else "—",
        "counted_fmt":    fmt_h(counted) if has_total else "—",
        "paid_fmt":       fmt_hd(paid_appr),
        "unpaid_counted_fmt": fmt_hd(unpaid_counted) if unpaid_counted else "",
        "approved_fmt":   fmt_hd(approved),
        "unapproved_fmt": fmt_hd(unapproved) if unapproved else "",
        "over_total":     has_total and paid_appr - late_paid > total_hours + 1e-9,
        "entries":        build_leave_entries(rows, detail) if len(rows) else [],
    }


def leave_tag(approved: float, unapproved: float) -> str:
    """Section 2 Time Off tag, e.g. '16.0h' or '11.0h + 8.0h unapproved'."""
    parts = []
    if approved:
        parts.append(fmt_h(approved))
    if unapproved:
        parts.append(f"{fmt_h(unapproved)} unapproved")
    return " + ".join(parts)


def leave_cell(approved: float, unapproved: float) -> str:
    """Section 3 cell, e.g. '16.0h (approved) · 8.0h (unapproved)'."""
    parts = []
    if approved:
        parts.append(f"{fmt_h(approved)} (approved)")
    if unapproved:
        parts.append(f"{fmt_h(unapproved)} (unapproved)")
    return " · ".join(parts)


def join_leave(leave_df: pd.DataFrame, df: pd.DataFrame, excluded: list[str]) -> pd.DataFrame:
    """Match leave rows to the (post-exclusion) master CSV. Stops on unmatched names."""
    excl = {norm_name(n) for n in excluded}
    csv_names = set(df["member"].apply(norm_name))

    is_excl = leave_df["norm"].isin(excl)
    dropped = leave_df[is_excl]
    if len(dropped):
        names = sorted(dropped["member"].unique())
        print(f"Time off: dropped {len(dropped)} row(s) / {dropped['hours'].sum():.1f}h for "
              f"{len(names)} excluded member(s): {', '.join(names)}")
    kept = leave_df[~is_excl]

    unmatched = sorted(kept.loc[~kept["norm"].isin(csv_names), "member"].unique())
    if unmatched:
        print("ERROR: These time-off members are not excluded and not in the master CSV:",
              file=sys.stderr)
        for n in unmatched:
            print(f"  - {n}", file=sys.stderr)
        print("Flag these to Aaqib — name mismatch or missing employee. Report NOT written.",
              file=sys.stderr)
        sys.exit(1)

    print(f"Time off: matched {kept['norm'].nunique()} member(s), {len(kept)} row(s), "
          f"{kept['hours'].sum():.1f}h")
    return kept


def resolve_pay_types(salaried: list[str], hourly: list[str], df: pd.DataFrame,
                      excluded_csv: list[str]) -> tuple[dict, list[str]]:
    """Map ClickUp Salary Type names to report members -> ({norm member: pay}, notes).
    Members in neither list are Unknown. Notes (counts, Unknowns, unmatched
    names) are printed at the end of the run."""
    salaried = [PAY_NAME_ALIASES.get(n, n) for n in salaried]
    hourly   = [PAY_NAME_ALIASES.get(n, n) for n in hourly]
    members = list(df["member"])
    sal_map, sal_un = match_names(salaried, members)
    hr_map,  hr_un  = match_names(hourly, members)
    pay = {norm_name(m): PAY_UNKNOWN for m in members}
    both = set(sal_map.values()) & set(hr_map.values())
    for m in sal_map.values():
        pay[norm_name(m)] = PAY_SALARIED
    for m in hr_map.values():
        pay[norm_name(m)] = PAY_HOURLY
    for m in both:
        pay[norm_name(m)] = PAY_UNKNOWN

    notes = []
    counts = {k: sum(1 for v in pay.values() if v == k) for k in (PAY_HOURLY, PAY_SALARIED, PAY_UNKNOWN)}
    notes.append(f"Pay type:          {counts[PAY_HOURLY]} Hourly, {counts[PAY_SALARIED]} Salaried, "
                 f"{counts[PAY_UNKNOWN]} Unknown (counted as salaried)")
    if both:
        notes.append(f"WARNING: In both the salaried and hourly lists (shown as Unknown): {', '.join(sorted(both))}")

    # ClickUp names with no report row: split out the ones that are simply excluded this run
    unmatched = sal_un + hr_un
    excl_map, still = match_names(unmatched, excluded_csv) if unmatched else ({}, [])
    unknown = sorted(m for m in members if pay[norm_name(m)] == PAY_UNKNOWN)
    if unknown:
        notes.append(f"Pay type Unknown (blank Salary Type or no ClickUp profile): {', '.join(unknown)}")
    if excl_map:
        notes.append(f"Pay type: {len(excl_map)} ClickUp name(s) belong to excluded members, ignored")
    if still:
        notes.append(f"Pay type: ClickUp names with no row in this report: {', '.join(sorted(still))}")
    return pay, notes


def load_hr_context(path: Path, df: pd.DataFrame) -> dict:
    """Load the reviewed HR profile notes -> {norm member: {"profile_url", "notes"}}."""
    data = json.loads(path.read_text(encoding="utf-8")).get("members", {})
    mapping, unmatched = match_names(list(data), list(df["member"]))
    out = {}
    for src, member in mapping.items():
        entry = data[src]
        notes = []
        for n in sorted(entry.get("notes", []), key=lambda n: n["date"]):
            d = date.fromisoformat(n["date"])
            notes.append({"author": n["author"], "text": n["text"],
                          "date_fmt": f"{d.strftime('%b')} {d.day}, {d.year}"})
        out[norm_name(member)] = {"profile_url": entry.get("profile_url", ""), "notes": notes}
    with_notes = sum(1 for v in out.values() if v["notes"])
    print(f"HR context:        {len(out)} member(s) loaded, {with_notes} with notes")
    if unmatched:
        print(f"WARNING: HR context names not in this report: {', '.join(unmatched)}")
    return out


LEADERSHIP_NAMES = {"lucas robinson", "jorn wossner", "adam burdeshaw", "eden schweyer",
                    "fred butson", "frederick butson"}
MONTHLY_DIR = REPO_ROOT / "data" / "input" / "monthly"


def month_starts_back(start: date, n: int = 3) -> list[date]:
    """The month of `start` and the n-1 months before it, oldest first."""
    out, y, m = [], start.year, start.month
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


SALARIED_DIR = REPO_ROOT / "data" / "input" / "salaried"


def load_hours_refresh() -> dict:
    """{(norm member, 'YYYY-MM'): (hours, csv_hours)} from hours_refresh.csv: earlier months'
    totals re-read from Hubstaff where time was edited after that month's CSV export."""
    path = SALARIED_DIR / "hours_refresh.csv"
    if not path.exists():
        return {}
    rdf = pd.read_csv(path, dtype=str).fillna("")
    return {(norm_name(r["member"]), r["month"]): (float(r["hours"]), r["csv_hours"])
            for _, r in rdf.iterrows()}


def load_month_leave(month: date) -> dict:
    """{norm member: (approved paid, approved unpaid, unapproved, late paid)} hours for a
    month, from data/input/timeoff/TO-<month>, or {} when that file is missing. Late paid =
    approved paid leave approved after that month's master CSV was exported (not in its Total)."""
    last = (date(month.year + (month.month == 12), month.month % 12 + 1, 1) - timedelta(days=1))
    path = REPO_ROOT / "data" / "input" / "timeoff" / f"TO-{month:%Y-%m-%d}_to_{last:%Y-%m-%d}.csv"
    if not path.exists():
        return {}
    ldf = pd.read_csv(path, dtype=str)
    ldf["hours"] = ldf["hours"].astype(float)
    csv_path = MONTHLY_DIR / f"HS-{month:%Y-%m}-master.csv"
    exported = (pd.Timestamp(datetime.utcfromtimestamp(csv_path.stat().st_mtime), tz="UTC")
                if csv_path.exists() else None)
    approved_at = (pd.to_datetime(ldf["approved_at"], utc=True, errors="coerce")
                   if "approved_at" in ldf.columns
                   else pd.Series(pd.NaT, index=ldf.index, dtype="datetime64[ns, UTC]"))
    ldf["late"] = (approved_at > exported) if exported is not None else False
    out = {}
    for name, g in ldf.groupby(ldf["member"].apply(norm_name)):
        appr = g[g["status"] == "approved"]
        paid = appr[appr["category"] == CATEGORY_PAID]
        out[name] = (float(paid["hours"].sum()),
                     float(appr.loc[appr["category"] == CATEGORY_UNPAID, "hours"].sum()),
                     float(g.loc[g["status"] != "approved", "hours"].sum()),
                     float(paid.loc[paid["late"].astype(bool), "hours"].sum()))
    return out


def month_leave_note(paid: float, unpaid: float, unapproved: float, late: float = 0.0) -> str:
    """Short line under a Section 3 month, e.g. 'incl. 8h paid leave · 64h leave not approved'."""
    def h(x):
        return f"{x:.1f}".rstrip("0").rstrip(".") + "h"
    parts = []
    if paid:
        parts.append(f"incl. {h(paid)} paid leave")
    if unpaid:
        parts.append(f"{h(unpaid)} unpaid leave")
    if unapproved:
        parts.append(f"{h(unapproved)} leave not approved")
    return " · ".join(parts)


def load_month_totals(month: date) -> dict | None:
    """{norm member: Total Worked Hours} from HS-YYYY-MM-master.csv, or None if missing."""
    path = MONTHLY_DIR / f"HS-{month:%Y-%m}-master.csv"
    if not path.exists():
        return None
    mdf = load_master_table(path)
    return {norm_name(r["member"]): r["total_hours"] for _, r in mdf.iterrows()
            if not pd.isna(r["total_hours"])}


def load_salaried_status(path: Path, members: list) -> tuple[dict, list]:
    """{norm Hubstaff name: {change, eff, target, floor, basis}} from the salaried status file."""
    sdf = pd.read_csv(path, dtype=str).fillna("")
    need = {"member", "change", "effective_date", "target_hours"}
    if need - set(sdf.columns):
        print(f"ERROR: {path} is missing columns {sorted(need - set(sdf.columns))}", file=sys.stderr)
        sys.exit(1)
    bad = sorted(set(sdf["change"]) - {"moved", "hired_salaried", "hourly", "agency"})
    if bad:
        print(f"ERROR: {path}: unknown change value(s) {bad}", file=sys.stderr)
        sys.exit(1)
    mmap, unmatched = match_names(list(sdf["member"]), members)
    out = {}
    for _, row in sdf.iterrows():
        if row["member"] not in mmap:
            continue
        eff = date.fromisoformat(row["effective_date"]) if row["effective_date"] else None
        if row["change"] == "moved" and not eff:
            print(f"ERROR: {path}: {row['member']} moved but has no effective_date", file=sys.stderr)
            sys.exit(1)
        target = float(row["target_hours"]) if row["target_hours"] else HIRED_TARGET
        out[norm_name(mmap[row["member"]])] = {
            "change": row["change"], "eff": eff, "target": target, "floor": floor_for(target),
            "basis": row.get("target_basis", ""),
        }
    notes = [f"Salaried status file: {path} ({len(out)} matched)"]
    if unmatched:
        notes.append(f"  Not in this report: {', '.join(unmatched)}")
    return out, notes


def build_salaried_section(rows_scored: list, start: date, end: date, pay_of, status: dict, hr_of,
                           current_totals: dict) -> dict:
    """Section 3: salaried team members over this month and the two before."""
    months = month_starts_back(start, 3)
    totals = []
    for i, m in enumerate(months):
        totals.append(current_totals if i == len(months) - 1 else load_month_totals(m))
    missing = [f"{m:%b %Y}" for m, t in zip(months, totals) if t is None]

    refresh = load_hours_refresh()
    leaves = [load_month_leave(m) for m in months]
    ce_names = {norm_name(n) for n in FS_EXCLUSIONS}
    groups = {"moved": [], "hired": []}
    for r in rows_scored:
        key = norm_name(r["member"])
        st = status.get(key) or {}
        if st.get("change") == "agency" or pay_of(r) != PAY_SALARIED:
            continue
        moved = st.get("change") == "moved"
        basis = "moved" if moved else "hired"
        target = st.get("target", HIRED_TARGET)
        start_full = first_full_month(st["eff"]) if st.get("eff") else None
        hours, floors, targets, cells = [], [], [], []
        for i, (m, t) in enumerate(zip(months, totals)):
            h = None if t is None else t.get(key)
            refreshed = ""
            if i < len(months) - 1 and (key, f"{m:%Y-%m}") in refresh:
                h, was = refresh[(key, f"{m:%Y-%m}")]
                refreshed = f"Hubstaff today; the {m:%b} CSV had {was}h (edited after the export)"
            lv = leaves[i].get(key, (0.0, 0.0, 0.0, 0.0))
            leave_note = month_leave_note(*lv)
            # Earlier months: add paid leave approved after that month's CSV export
            # (the current month already does this through the leave figures)
            if h is not None and i < len(months) - 1 and lv[3]:
                h += lv[3]
                refreshed = (refreshed + "; " if refreshed else "") + \
                    f"includes {lv[3]:.1f}h paid leave approved after the {m:%b} export"
            # Hired as salaried part-way through: earlier months were a different
            # arrangement, shown but not counted
            if not moved and start_full and m < start_full:
                cells.append({"text": "—" if h is None else f"{h:.1f}h", "ce_partial": False,
                              "under": False, "warn": False, "hourly_then": False,
                              "before_hire": True, "refreshed": refreshed, "leave": ""})
                hours.append(None); floors.append(HIRED_FLOOR); targets.append(HIRED_TARGET)
                continue
            # Centrifuse Engineers joined Hubstaff mid-August 2026: earlier months are partial
            ce_partial = key in ce_names and m < CE_HUBSTAFF_START
            if ce_partial:
                h = None
            before_move = moved and m < start_full
            m_target = HIRED_TARGET if before_move else target
            m_floor = HIRED_FLOOR if before_move else floor_for(m_target)
            hours.append(h)
            floors.append(m_floor)
            targets.append(m_target)
            cells.append({"text": "—" if h is None else f"{h:.1f}h", "ce_partial": ce_partial,
                          "under": h is not None and h < m_floor,
                          "warn": h is not None and m_floor <= h < m_target,
                          "hourly_then": before_move and target != HIRED_TARGET,
                          "before_hire": False, "refreshed": refreshed,
                          "leave": leave_note if h is not None and h < m_target else ""})
        under, sal_status = salaried_status(hours, floors)
        shorts = [t - h for h, f, t in zip(hours, floors, targets) if h is not None and h < f]
        note = ""
        if key in LEADERSHIP_NAMES:
            sal_status, note = None, "Leadership, not ranked"
        elif sal_status and all(h is None for h in hours[:-1]):
            sal_status, note = None, "First month, not ranked"
        groups[basis].append({
            "member": r["member"], "team": r["team"], "hr": hr_of(r),
            "since": f"{st['eff']:%b %-d, %Y}" if moved else "",
            "target": f"{target:.0f}h", "target_basis": st.get("basis", ""),
            "target_floor": f"{floor_for(target):.0f}h",
            "cells": cells, "under": under,
            "months_with_data": sum(1 for h in hours if h is not None),
            "avg_short": f"{sum(shorts) / len(shorts):.1f}h" if shorts else "",
            "status": sal_status, "note": note,
            "_sort": ({"Serious": 0, "Alert": 1}.get(sal_status, 2), -under,
                      -(sum(shorts) / len(shorts) if shorts else 0), r["member"].lower()),
        })
    for g in groups.values():
        g.sort(key=lambda x: x["_sort"])
    def split(g):
        return ([x for x in g if x["status"]],
                sorted([x for x in g if not x["status"]], key=lambda x: x["member"].lower()))
    moved_flag, moved_ok = split(groups["moved"])
    hired_flag, hired_ok = split(groups["hired"])
    return {
        "months": [f"{m:%b}" for m in months],
        "missing_months": missing,
        "moved_flagged": moved_flag, "moved_ok": moved_ok,
        "hired_flagged": hired_flag, "hired_ok": hired_ok,
        "moved_target": f"{MOVED_TARGET:.0f}h", "moved_floor": f"{MOVED_FLOOR:.0f}h",
        "hired_target": f"{HIRED_TARGET:.0f}h",
        "serious": sum(1 for x in moved_flag + hired_flag if x["status"] == "Serious"),
        "alert": sum(1 for x in moved_flag + hired_flag if x["status"] == "Alert"),
        "total": len(groups["moved"]) + len(groups["hired"]),
    }


def build_leave_summary(leave_df: pd.DataFrame, detail: str) -> dict:
    """Totals strip above Section 3 (raw numbers + bar widths for the template)."""
    def h(df, status):
        return float(df.loc[df["status"] == status, "hours"].sum())

    cats = []
    for c in (CATEGORY_PAID, CATEGORY_UNPAID):
        sub = leave_df[leave_df["category"] == c]
        a, u = h(sub, "approved"), h(sub, "unapproved")
        tot = a + u
        cats.append({
            "name": c, "css": "paid" if c == CATEGORY_PAID else "unpaid",
            "approved": fmt_h(a), "unapproved": fmt_h(u), "unapproved_raw": u,
            "a_pct": round(100 * a / tot, 1) if tot else 0,
            "u_pct": round(100 * u / tot, 1) if tot else 0,
        })

    policies = []
    if detail == "full":
        for (pol, cat), grp in leave_df.groupby(["policy_name", "category"]):
            a, u = h(grp, "approved"), h(grp, "unapproved")
            policies.append({"name": pol, "category": cat,
                             "css": "paid" if cat == CATEGORY_PAID else "unpaid",
                             "a": a, "u": u, "total": a + u,
                             "a_fmt": fmt_h(a) if a else "", "u_fmt": fmt_h(u) if u else ""})
        policies.sort(key=lambda p: -p["total"])
        top = max((p["total"] for p in policies), default=0) or 1
        for p in policies:
            p["a_pct"] = round(100 * p["a"] / top, 1)
            p["u_pct"] = round(100 * p["u"] / top, 1)
    return {"categories": cats, "policies": policies,
            "total_approved": fmt_h(h(leave_df, "approved")),
            "total_unapproved": fmt_h(h(leave_df, "unapproved"))}


# ---------------------------------------------------------------------------
# Report data assembly
# ---------------------------------------------------------------------------

def build_report_data(df: pd.DataFrame, prorated_red: float, prorated_orange: float,
                      start: date, end: date, leave_df: pd.DataFrame | None = None,
                      leave_detail: str = "full", leave_pulled: str = "",
                      pay_types: dict | None = None, hr_context: dict | None = None,
                      status: dict | None = None) -> dict:
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

    pay_enabled = pay_types is not None
    hr_enabled = hr_context is not None

    def hr_of(r):
        if not hr_enabled:
            return None
        return hr_context.get(norm_name(r["member"]), {"profile_url": "", "notes": []})

    def pay_of(r):
        if not pay_enabled:
            return None
        key = norm_name(r["member"])
        st = (status or {}).get(key)
        if st:
            if st["change"] == "moved":
                return PAY_SALARIED if st["eff"] and st["eff"] <= end else PAY_HOURLY
            if st["change"] == "hired_salaried":
                return PAY_SALARIED
            if st["change"] == "hourly":
                return PAY_HOURLY
        return pay_types.get(key, PAY_UNKNOWN)

    # Section 1: Top 15
    top15 = []
    for rank, r in enumerate(rows_scored[:15], start=1):
        flags = r["flags"]
        top15.append({
            "rank": rank,
            "member": r["member"],
            "team": r["team"],
            "pay": pay_of(r),
            "hr": hr_of(r),
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

    leave_enabled = leave_df is not None
    leave_by_member = {}
    if leave_enabled:
        for norm, grp in leave_df.groupby("norm"):
            leave_by_member[norm] = grp
    empty_leave = leave_df.iloc[0:0] if leave_enabled else None
    leave_warnings = []
    figures_cache = {}

    def figures_for(r):
        key = norm_name(r["member"])
        if key not in figures_cache:
            rows = leave_by_member.get(key, empty_leave)
            fig = member_leave_figures(rows, r["total_hours"], leave_detail, pay_of(r))
            if fig["over_total"]:
                leave_warnings.append(f"{r['member']}: approved paid time off {fig['paid_approved']:.1f}h "
                                      f"> Total Worked Hours {r['total_hours']:.1f}h")
            figures_cache[key] = fig
        return figures_cache[key]

    # Section 2: All Hours Violators (below prorated red threshold)
    hours_violators = []
    for r in rows_scored:
        h = r["total_hours"]
        if not pd.isna(h) and h < prorated_red:
            shortfall = prorated_red - h
            other_flags = fmt_flags_badge(r["red_count"], r["yellow_count"])
            entry = {
                "member": r["member"],
                "team": r["team"],
                "pay": pay_of(r),
                "hr": hr_of(r),
                "hours_worked": f"{h:.1f}h",
                "hours_raw": h,
                "expected_hours": f"{prorated_red:.1f}h",
                "shortfall": f"{shortfall:.1f}h",
                "other_flags": other_flags,
            }
            if leave_enabled:
                fig = figures_for(r)
                # Leave-adjusted shortfall: prorated 160h minus counted hours
                counted_short = prorated_red - fig["counted"]
                entry["shortfall"] = f"{counted_short:.1f}h" if counted_short > 0.05 else ""
                entry["leave"] = fig
                entry["time_off_tag"] = leave_tag(fig["approved"], fig["unapproved"])
                entry["tag_a"] = fmt_h(fig["approved"]) if fig["approved"] else ""
                entry["tag_u"] = fmt_h(fig["unapproved"]) if fig["unapproved"] else ""
            hours_violators.append(entry)
    # Sort ascending by hours (worst = least hours first)
    hours_violators.sort(key=lambda x: x["hours_raw"])

    # Section 3: Leave Summary (month-end only)
    leave_rows = []
    leave_summary = None
    if leave_enabled:
        for r in rows_scored:
            if norm_name(r["member"]) not in leave_by_member:
                continue
            fig = figures_for(r)
            pa, pu = fig["by_cat"][CATEGORY_PAID]
            ua, uu = fig["by_cat"][CATEGORY_UNPAID]
            leave_rows.append({
                "member":     r["member"],
                "team":       r["team"],
                "pay":        pay_of(r),
                "paid_cell":  leave_cell(pa, pu),
                "unpaid_cell": leave_cell(ua, uu),
                "total_cell": leave_cell(fig["approved"], fig["unapproved"]),
                "total_raw":  fig["approved"] + fig["unapproved"],
                "paid_a":     fmt_h(pa) if pa else "", "paid_u":   fmt_h(pu) if pu else "",
                "unpaid_a":   fmt_h(ua) if ua else "", "unpaid_u": fmt_h(uu) if uu else "",
                "tot_a":      fmt_h(fig["approved"]) if fig["approved"] else "",
                "tot_u":      fmt_h(fig["unapproved"]) if fig["unapproved"] else "",
                "leave":      fig,
            })
        leave_rows.sort(key=lambda x: (-x["total_raw"], x["member"].lower()))
        leave_summary = build_leave_summary(leave_df, leave_detail)

    # Section 3: Salaried hours over 3 months (month-end only, needs pay types)
    salaried = None
    if pay_enabled and is_full_month(start, end):
        current_totals = {norm_name(r["member"]): r["total_hours"]
                          + (figures_for(r)["late_paid"] if leave_enabled else 0.0)
                          for r in rows_scored if not pd.isna(r["total_hours"])}
        salaried = build_salaried_section(rows_scored, start, end, pay_of, status or {}, hr_of,
                                          current_totals)
        # Earlier months' time off must come from the same (latest) pull, or late
        # approvals are missed (Rasma's August, Nov 2026)
        for m in month_starts_back(start, 3)[:-1]:
            last = date(m.year + (m.month == 12), m.month % 12 + 1, 1) - timedelta(days=1)
            meta = REPO_ROOT / "data" / "input" / "timeoff" / f"TO-{m:%Y-%m-%d}_to_{last:%Y-%m-%d}.csv.meta.json"
            if not meta.exists():
                print(f"WARNING: no time-off file for {m:%b %Y}; Section 3 shows no leave for that month. "
                      f"Build it from the latest raw pull (build_timeoff_csv.py --start {m} --end {last}).")
                continue
            pulled = json.loads(meta.read_text(encoding="utf-8")).get("pulled_at", "")
            if leave_pulled and pulled and pulled[:10] < leave_pulled[:10]:
                print(f"WARNING: {m:%b %Y} time off was pulled {pulled[:10]}, before this month's pull "
                      f"({leave_pulled[:10]}). Rebuild it from the latest raw pull so late approvals count.")

    period_working_days = count_working_days(start, end)
    period_kind = "Month-end" if is_full_month(start, end) else "Mid-month"

    return {
        "report_title": "Hubstaff Performance Report",
        "period_kind": period_kind,
        "salaried": salaried,
        "leave_section_num": 4 if salaried else 3,
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
        # Month-end time off
        "leave_enabled": leave_enabled,
        "leave_detail": leave_detail,
        "leave_pulled": leave_pulled,
        "leave_rows": leave_rows,
        "leave_count": len(leave_rows),
        "leave_summary": leave_summary,
        "leave_warnings": leave_warnings,
        "pay_enabled": pay_enabled,
        "hr_enabled": hr_enabled,
        "covered_count": sum(1 for v in hours_violators if leave_enabled and not v["shortfall"]),
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

def write_report(html: str, start: date, end: date, out_dir: Path = DOCS_DIR) -> Path:
    """Write report to /docs/ (or out_dir for --dry-run). Returns the path."""
    folder_name = f"{start.isoformat()}_to_{end.isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    docs_filename = f"{folder_name}_biweekly_top_violators.html"
    docs_path = out_dir / docs_filename
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
    leave_group = parser.add_mutually_exclusive_group()
    leave_group.add_argument("--leave", default=None,
                             help="Time-off CSV from build_timeoff_csv.py (month-end reports)")
    leave_group.add_argument("--no-leave", action="store_true",
                             help="Explicitly skip time off on a full-month report")
    parser.add_argument("--leave-detail", choices=["full", "category"], default="full",
                        help="full = show exact Hubstaff policy names; category = Paid/Unpaid only")
    parser.add_argument("--salaried", default="",
                        help="Comma-separated names with Salary Type = Salaried in the ClickUp HR profiles")
    parser.add_argument("--hourly", default="",
                        help="Comma-separated names with Salary Type = Hourly in the ClickUp HR profiles")
    parser.add_argument("--no-pay-type", action="store_true",
                        help="Explicitly skip the Hourly/Salaried tag (everyone counted as salaried)")
    parser.add_argument("--salaried-status", default=None,
                        help="Who moved to salaried, when and on what target (default "
                             "data/input/salaried/salaried_status.csv when it exists; gitignored)")
    parser.add_argument("--no-salaried-status", action="store_true",
                        help="Do not read the salaried status file")
    parser.add_argument("--csv-exported", default=None,
                        help="When the master CSV was exported from Hubstaff (YYYY-MM-DD or ISO time, UTC). "
                             "Paid leave approved after it is not in Total Worked Hours. "
                             "Default: the CSV file's modified time")
    parser.add_argument("--hr-context", default=None,
                        help="Reviewed HR profile notes JSON (data/input/hr_context/, gitignored)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Write HTML to a scratch folder; do not touch docs/ or docs/index.html")
    parser.add_argument("--dry-run-dir", default=None,
                        help="Scratch folder for --dry-run (default: system temp dir)")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    csv_path = Path(args.input)

    if not csv_path.exists():
        print(f"ERROR: Input file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    # Month-end guard: a full calendar month must say whether time off is included
    if is_full_month(start, end) and not args.leave and not args.no_leave:
        print(f"ERROR: {start} to {end} is a full calendar month (month-end report).\n"
              f"       Pass --leave data/input/timeoff/TO-{start}_to_{end}.csv "
              f"(build it with scripts/build_timeoff_csv.py),\n"
              f"       or --no-leave to generate it without the time-off breakdown.",
              file=sys.stderr)
        sys.exit(2)

    split = lambda v: [x.strip() for x in v.split(",") if x.strip()]  # noqa: E731
    salaried_names, hourly_names = split(args.salaried), split(args.hourly)
    pay_given = bool(salaried_names or hourly_names)
    if pay_given and args.no_pay_type:
        print("ERROR: --no-pay-type cannot be combined with --salaried/--hourly", file=sys.stderr)
        sys.exit(2)
    if is_full_month(start, end) and args.leave and not pay_given and not args.no_pay_type:
        print("ERROR: Month-end report with time off needs the pay type for the leave-adjusted hours.\n"
              "       Pass --salaried \"...\" --hourly \"...\" (Salary Type from the ClickUp HR profiles),\n"
              "       or --no-pay-type to count everyone as salaried.", file=sys.stderr)
        sys.exit(2)

    leave_df = None
    leave_pulled = ""
    if args.leave:
        leave_path = Path(args.leave)
        if not leave_path.exists():
            print(f"ERROR: Time-off CSV not found: {leave_path}", file=sys.stderr)
            sys.exit(1)
        leave_df, leave_pulled = load_leave(leave_path)
        outside = leave_df[(leave_df["date"] < start) | (leave_df["date"] > end)]
        if len(outside):
            print(f"ERROR: {len(outside)} time-off row(s) fall outside {start} to {end} — "
                  f"wrong TO CSV for this period?", file=sys.stderr)
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

    # Cycle-specific exclusions passed via --exclude
    cycle_exclusions = [n.strip() for n in args.exclude.split(",") if n.strip()]

    all_exclusions = get_exclusions(start) + cycle_exclusions
    excluded_csv = []
    if all_exclusions:
        before = len(df)
        _excl_set = set(n.lower().strip() for n in all_exclusions)
        excluded_csv = list(df.loc[df["member"].apply(lambda n: str(n).lower().strip() in _excl_set), "member"])
        df = df[~df["member"].apply(lambda n: str(n).lower().strip() in _excl_set)].reset_index(drop=True)
        excluded_count = before - len(df)
        print(f"Excluded {excluded_count} employee(s): {', '.join(all_exclusions)}")
        print(f"Remaining: {len(df)} employees.")

    if leave_df is not None:
        leave_df = join_leave(leave_df, df, all_exclusions)
        if args.csv_exported:
            exported = pd.Timestamp(args.csv_exported)
            exported = exported.tz_localize("UTC") if exported.tzinfo is None else exported.tz_convert("UTC")
            src = "--csv-exported"
        else:
            exported = pd.Timestamp(datetime.utcfromtimestamp(csv_path.stat().st_mtime), tz="UTC")
            src = "CSV file time; pass --csv-exported to override"
        leave_df["late"] = (leave_df["status"] == "approved") & (leave_df["approved_at"] > exported)
        print(f"Master CSV exported: {exported:%Y-%m-%d %H:%M} UTC ({src})")
        for (m, cat), g in leave_df[leave_df["late"]].groupby(["member", "category"]):
            print(f"  Approved after the export: {m}, {g['hours'].sum():.1f}h {cat} "
                  f"(approved {g['approved_at'].max():%Y-%m-%d}); "
                  + ("not in Total, so not taken off Worked" if cat == CATEGORY_PAID
                     else "unpaid, no change"))

    pay_types, pay_notes = (resolve_pay_types(salaried_names, hourly_names, df, excluded_csv)
                            if pay_given else (None, []))

    status = {}
    st_path = (Path(args.salaried_status) if args.salaried_status
               else REPO_ROOT / "data" / "input" / "salaried" / "salaried_status.csv")
    if pay_given and not args.no_salaried_status:
        if st_path.exists():
            status, st_notes = load_salaried_status(st_path, list(df["member"]))
            pay_notes.extend(st_notes)
            changed = []
            for m in df["member"]:
                st = status.get(norm_name(m))
                if not st or st["change"] == "agency":
                    continue
                field = pay_types.get(norm_name(m), PAY_UNKNOWN)
                now = (PAY_HOURLY if st["change"] == "hourly"
                       or (st["change"] == "moved" and st["eff"] > end) else PAY_SALARIED)
                if field != now:
                    changed.append(f"{m} ({field} → {now})")
            if changed:
                pay_notes.append("  Pay type set by the status file, not the ClickUp field: "
                                 + ", ".join(changed))
        elif args.salaried_status:
            print(f"ERROR: Salaried status file not found: {st_path}", file=sys.stderr)
            sys.exit(1)
        else:
            pay_notes.append(f"WARNING: no salaried status file at {st_path}; "
                             "everyone salaried is shown as hired as salaried")

    hr_context = None
    if args.hr_context:
        hr_path = Path(args.hr_context)
        if not hr_path.exists():
            print(f"ERROR: HR context file not found: {hr_path}", file=sys.stderr)
            sys.exit(1)
        hr_context = load_hr_context(hr_path, df)

    # --- Step 3: Build report data ---
    context = build_report_data(df, prorated_red, prorated_orange, start, end,
                                leave_df=leave_df, leave_detail=args.leave_detail,
                                leave_pulled=leave_pulled, pay_types=pay_types,
                                hr_context=hr_context, status=status)
    print(f"Employees flagged: {context['total_flagged']} / {context['total_employees']}")
    print(f"Hours violators:   {context['hours_violator_count']}")
    if context["leave_enabled"]:
        print(f"Leave summary:     {context['leave_count']} member(s) with time off "
              f"(as of {leave_pulled}, detail={args.leave_detail})")
        if context["covered_count"]:
            print(f"Hours violators with no shortfall after leave (hourly, approved unpaid leave): "
                  f"{context['covered_count']}")
        for w in context["leave_warnings"]:
            print(f"WARNING: {w} (contradicts 'Total includes approved paid time off')")

    def print_pay_notes():
        for n in pay_notes:
            print(n)

    # --- Step 4: Render HTML ---
    html = render_report(context)

    # --- Step 5: Write output files ---
    if args.dry_run:
        out_dir = Path(args.dry_run_dir) if args.dry_run_dir else Path(tempfile.gettempdir()) / "hubstaff-dryrun"
        path = write_report(html, start, end, out_dir)
        print(f"DRY RUN — report written to: {path}")
        print("docs/ and docs/index.html NOT modified.")
        print_pay_notes()
        return

    docs_path = write_report(html, start, end)
    print(f"Report written:    {docs_path}")

    # --- Step 6: Update index ---
    update_index(start, end)
    print(f"Index updated:     {DOCS_DIR / 'index.html'}")
    print_pay_notes()
    print("Done.")


if __name__ == "__main__":
    main()
