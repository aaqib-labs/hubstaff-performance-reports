# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## What This Repo Does

Automates bi-weekly workforce performance compliance reports for ~80–90 WebLife Ventures employees tracked via Hubstaff (plus Friday Solutions via TMetric). Reports are published as static HTML via GitHub Pages for internal executive review.

---

## Session Startup Checklist

At the start of every session, before doing anything else:

1. Read this file (`CLAUDE.md`)
2. Read `data/reference/sla_violation_legend.md` — authoritative threshold logic
3. Read `data/personnel/personnel_index.md` — authoritative team/role assignments
4. Check `data/input/` for any new master table CSV files
5. Execute whatever is asked

---

## Folder Structure

```
data/input/          Master table CSVs dropped here each cycle
data/personnel/      Personnel Index — authoritative role/team source
data/reference/      SLA thresholds and violation legend
scripts/             Python report generation scripts
templates/           Jinja2 HTML report templates
reports/             Archived reports by cycle: YYYY-MM-DD_to_YYYY-MM-DD/
docs/                GitHub Pages source — index.html + copied reports
CLAUDE.md            This file
```

**GitHub Pages serves from `/docs`.** Every generated report is both archived in `/reports/` and copied into `/docs/`. Never rename or remove the `/docs` folder.

---

## Recurring Bi-Weekly Workflow

When asked to "generate the bi-weekly report for [date range]":

1. Find the master table CSV in `data/input/`
2. Run `python scripts/generate_biweekly_report.py --input data/input/[FILE].csv --start YYYY-MM-DD --end YYYY-MM-DD`
3. Script outputs HTML to `reports/[start]_to_[end]/biweekly_top_violators.html`
4. Script copies report to `docs/` and updates `docs/index.html`
5. Commit with message: `Report: Bi-Weekly [start] to [end]`
6. Push to GitHub

If any data anomaly is detected (unexpected columns, missing data, parse errors), flag it before finalising.

---

## Master Table CSV — Column Reference

The input CSV always has these columns (Hubstaff export format):

| Column | Notes |
|--------|-------|
| `Team(s)` | Hubstaff team label — do NOT use for role matching; use personnel_index.md |
| `Member` | Employee name |
| `Activity %` | Keyboard/mouse engagement percentage |
| `Total Worked Hours` | Total logged hours in the period |
| `Break Time` | Raw break hours |
| `Break % of Total` | Break as % of total worked hours |
| `Total Manual Hours` | Manually entered hours |
| `Manual % of Total` | Manual as % of total worked hours |
| `Low Activity Hours (≤20%)` | Hours where activity ≤ 20% |
| `Low Activity % (≤20%)` | Low activity ≤20% as % of total worked hours |
| `Low Activity Hours (≤30%)` | Hours where activity ≤ 30% |
| `Low Activity % (≤30%)` | Low activity ≤30% as % of total worked hours |
| `SLA Violation Legend` | Pre-populated flag string — use as reference only |
| `Red Flag Count` | Pre-populated count — re-evaluate from raw data, do not trust blindly |
| `Yellow Flag Count` | Pre-populated count — re-evaluate from raw data |
| `Total Flags` | Pre-populated count — re-evaluate from raw data |

**Always re-evaluate all flags from raw data.** Pre-populated flag columns are for reference; the scripts are the authoritative source of flag logic.

**Important — H⚠️ in the pre-populated SLA column:** The upstream CSV builder adds a yellow hours warning (H⚠️) for employees slightly below 160h. Our system has NO yellow band for hours — only 🔴 red (below prorated threshold) and 🟠 orange (overwork). The script correctly ignores H⚠️ and re-evaluates hours as red or orange only. This is expected and correct — do not treat H⚠️ entries as anomalies.

---

## Threshold Logic

See `data/reference/sla_violation_legend.md` — this is the ONLY source of truth.

**Key rules:**
- NEVER guess or infer thresholds
- NEVER prorate thresholds that are explicitly provided — only auto-prorate when computing from a date range
- Red flag overrides yellow for the same metric — never show both
- Break yellow (B ⚠️) excluded from displayed flag count but included in severity score
- Hours SLA: strict red/orange only, no yellow band

**Auto-prorate hours thresholds from date range:**
```
prorated_red    = (working_days_in_period / working_days_in_full_month) × 160
prorated_orange = (working_days_in_period / working_days_in_full_month) × 200
```
Print both calculated thresholds to console before processing. Count Mon–Fri only (US holiday exclusion is a TODO until WebLife holiday calendar is provided).

---

## Personnel Index Rule

The `Team` column displayed in reports comes directly from the CSV's `Team(s)` column — the script does not do a personnel index lookup for team names.

The personnel index (`data/personnel/personnel_index.md`) is used for:
- Context when interpreting anomalies (e.g. role-appropriate low activity for executives)
- Confirming whether a name in the CSV maps to a known employee
- Flagging name mismatches between the CSV and the index (e.g. name changes, new hires not yet added)

If a name in the CSV does not match anyone in the index, flag it to Aaqib before finalising — do not silently skip or guess.

**Friday Solutions (FS-OPS):** Will have a separate dedicated report page. Do not include FS members in the standard bi-weekly Hubstaff report unless explicitly instructed.

---

## Formatting Standards

| Field | Format |
|-------|--------|
| Activity % | Whole number, e.g. `34%` |
| All other numeric values | 1 decimal place |
| All percentage fields | Always include `%` symbol |
| Break / Manual / Low Activity cells | `Xh (X.X%)` format |
| Flags badge | `🔴 2 ⚠️ 1` (B ⚠️ excluded from count) |
| Member name cells | No status emoji prefix |
| Empty / compliant cells | Leave blank — no "CLEAR" text |
| Violation indicators | Embedded in metric cells: `🔴 34%`, `⚠️ 8.3h (11.4%)` |

---

## Exclusions

No permanent exclusions. All employees in the master table are included in the initial report.
Cycle-specific exclusions (recently offboarded, new hires in grace period) are handled via a follow-up prompt after the initial report is generated. Never apply exclusions pre-emptively.

---

## Severity Scoring (for Top 15 ranking)

```
Base: Red = 10 pts | Yellow = 3 pts | Orange = 7 pts

Multipliers:
  A  Activity        → 5×
  M  Manual          → 4×
  H  Low Hours 🔴    → 3×
  H  Overwork 🟠     → 2×
  20 Low Act ≤20%    → 2×
  30 Low Act ≤30%    → 1.5×
  B  Break           → 1×

Score = sum of (base × multiplier) across all flags
```

---

## Git Conventions

- Always commit and push after generating reports
- Commit message format: `Report: Bi-Weekly YYYY-MM-DD to YYYY-MM-DD`
- Never leave uncommitted changes after a session
- Never force-push

---

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `scripts/generate_biweekly_report.py` | Full bi-weekly report generation |
| `scripts/update_index.py` | Regenerate `docs/index.html` from archived reports |
| `scripts/generate_pattern_analysis.py` | 3-month repeated pattern analysis (stub) |
| `scripts/generate_peer_comparison.py` | Role-based peer comparison (stub) |

---

## Report Structure

Each bi-weekly HTML report contains:

**Section 1 — Top 15 Violators**
Ranked by severity score. Columns: Rank, Member, Team, Activity %, Hours, Break %, Manual Hours, Low Act ≤20%, Low Act ≤30%, Flags, Score.

**Section 2 — Hours Violators**
All employees below the prorated hours threshold. Sorted ascending (worst first). Columns: Member, Team, Hours Worked, Expected Hours, Shortfall, Other Flags.

---

## About This Project

**Owner:** Aaqib Hafeel, Process Optimization Lead, WebLife Stores LLC (TA-PO)
**Cycle:** Bi-weekly
**Coverage:** ~80–90 employees across 5 ventures
**Data sources:** Hubstaff (all teams) + TMetric (Friday Solutions)
**Audience:** Executive review (Lucas Robinson, Jorn Wossner, department directors)
