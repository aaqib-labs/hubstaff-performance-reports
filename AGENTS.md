# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

---

## What This Repo Does

Automates bi-weekly workforce performance compliance reports for ~80–90 WebLife Ventures employees tracked via Hubstaff, including Centrifuse Engineers (CE). CE moved from TMetric to Hubstaff in mid-August 2026; TMetric is no longer used. Reports are published as static HTML via GitHub Pages for internal executive review.

---

## Session Startup Checklist

At the start of every session, before doing anything else:

1. Read this file (`AGENTS.md`)
2. Read `data/reference/sla_violation_legend.md` — authoritative threshold logic
3. Read `data/personnel/personnel_index.md` — authoritative team/role assignments
4. Check `data/input/` for any new master table CSV files
5. Execute whatever is asked

---

## Folder Structure

```
data/input/
  monthly/           Full calendar month CSVs      → HS-YYYY-MM-master.csv
  biweekly/          Partial/bi-weekly period CSVs → HS-YYYY-MM-DD_to_YYYY-MM-DD.csv
                                                     CE-YYYY-MM-DD_to_YYYY-MM-DD.csv
  timeoff/           Month-end time off            → TO-YYYY-MM-DD_to_YYYY-MM-DD.csv (+ .meta.json)
    raw/             Raw Hubstaff MCP JSON         → TO-RAW-YYYY-MM-DD_to_YYYY-MM-DD_<part>.json
                     (gitignored — contains free-text leave reasons; never commit)
data/personnel/      Personnel Index — authoritative role/team source
data/reference/      SLA thresholds and violation legend
scripts/             Python report generation scripts
  utils.py           Shared helpers (working-days, proration) — import from here
templates/           Jinja2 HTML report templates
docs/                GitHub Pages source — index.html + all report HTML files
AGENTS.md            This file
```

**File naming conventions (strictly enforced):**

*CSV inputs (`data/input/`):*
| Type | Format | Example |
|------|--------|---------|
| Hubstaff full month | `HS-YYYY-MM-master.csv` | `HS-2026-03-master.csv` |
| Hubstaff bi-weekly | `HS-YYYY-MM-DD_to_YYYY-MM-DD.csv` | `HS-2026-03-01_to_2026-03-24.csv` |
| Centrifuse Engineers (CE) — legacy TMetric, pre-Sep 2026 only | `CE-YYYY-MM-DD_to_YYYY-MM-DD.csv` | `CE-2026-05-01_to_2026-05-19.csv` |
| Time off (per-day, built by script) | `timeoff/TO-YYYY-MM-DD_to_YYYY-MM-DD.csv` | `timeoff/TO-2026-09-01_to_2026-09-30.csv` |
| Time off raw MCP pull | `timeoff/raw/TO-RAW-YYYY-MM-DD_to_YYYY-MM-DD_<part>.json` | `..._policies.json`, `..._requests_p1.json` |

*HTML outputs (`docs/`):*
| Type | Format | Example |
|------|--------|---------|
| Hubstaff bi-weekly | `YYYY-MM-DD_to_YYYY-MM-DD_biweekly_top_violators.html` | `2026-03-01_to_2026-03-24_biweekly_top_violators.html` |
| Centrifuse Engineers (CE) — legacy, pre-Sep 2026 only | `YYYY-MM-DD_to_YYYY-MM-DD_ce_report.html` | `2026-03-01_to_2026-03-24_ce_report.html` |
| Pattern Analysis (HS) | `YYYY-MM-DD_to_YYYY-MM-DD_pattern_analysis.html` | `2026-01-01_to_2026-03-31_pattern_analysis.html` |
| Pattern Analysis (CE) | `YYYY-MM-DD_to_YYYY-MM-DD_ce_pattern_analysis.html` | `2026-01-01_to_2026-03-31_ce_pattern_analysis.html` |
| Peer Comparison | `YYYY-MM-DD_to_YYYY-MM-DD_peer_comparison.html` | `2026-03-01_to_2026-03-31_peer_comparison.html` |

Note: HTML outputs use date-range prefix + report-type suffix. No `HS-`/`CE-` prefix on outputs — the suffix identifies the source/type. This is by design so `update_index.py` can parse them consistently.

**GitHub Pages serves from `/docs`.** All generated reports are written directly to `/docs/` — there is no separate `/reports/` archive folder. Never rename or remove the `/docs` folder.

---

## Recurring Bi-Weekly Workflow

When asked to "generate the bi-weekly report for [date range]":

1. Find the master table CSV in `data/input/biweekly/`
2. Run `python scripts/generate_biweekly_report.py --input data/input/biweekly/[FILE].csv --start YYYY-MM-DD --end YYYY-MM-DD`
3. Script writes HTML directly to `docs/[start]_to_[end]_biweekly_top_violators.html` and updates `docs/index.html`
4. Commit with message: `Report: Bi-Weekly [start] to [end]`
5. Push to GitHub

If any data anomaly is detected (unexpected columns, missing data, parse errors), flag it before finalising.

---

## Month-End Workflow (full calendar month, with time off)

A full-month run (`--start` = 1st, `--end` = last day) **must** pass `--leave <TO CSV>` or an explicit `--no-leave` — the script exits otherwise.

1. Confirm `data/input/monthly/HS-YYYY-MM-master.csv` exists.
2. Pull time off from the Hubstaff MCP (`list_organizations` → org id, then `call_endpoint`):
   - `get_organizations_organization_id_time_off_policies` → save as `data/input/timeoff/raw/TO-RAW-<start>_to_<end>_policies.json`
   - `get_organizations_organization_id_time_off_requests` with `starts_at: {start: <start − 62 days>T00:00:00Z, stop: <end + 1 day>T00:00:00Z}`, `include: ["users","time_off_policies"]`, `page_limit: 500` → `..._requests_p1.json` (page with `page_start_id` if a `pagination` object comes back or exactly 500 rows return)
   - Large responses spill to a tool-results file — `cp` it byte-for-byte. Never retype JSON.
3. `python scripts/build_timeoff_csv.py --raw data/input/timeoff/raw/TO-RAW-<start>_to_<end>_*.json --start <start> --end <end> --out data/input/timeoff/TO-<start>_to_<end>.csv` — review every WARN/ERROR with Aaqib before going on.
4. `python scripts/generate_biweekly_report.py --input data/input/monthly/HS-YYYY-MM-master.csv --start YYYY-MM-01 --end YYYY-MM-DD --leave data/input/timeoff/TO-YYYY-MM-01_to_YYYY-MM-DD.csv --dry-run` and check it.
5. Re-run without `--dry-run`.
6. Commit `Report: Bi-Weekly YYYY-MM-01 to YYYY-MM-DD` and push.

**Time-off rules:**
- Two categories from the **policy-level** `paid` flag (never the request-level one): Paid/Allocated and Unpaid/Flex. The exact Hubstaff policy name is always shown (unless `--leave-detail category`).
- Unapproved (submitted) requests are shown and labelled `(unapproved)`; denied/cancelled are dropped.
- `Total Worked Hours` already includes approved time off → **Hours Worked = Total − approved time off**. Unapproved is never subtracted. SLA flags are unchanged.
- Leave messages/reasons are never written to the TO CSV, the report or any committed file.
- Time-off names that are not excluded and not in the master CSV stop the run — flag them to Aaqib, don't guess.
- `--leave-detail full|category` (default `full`; decided 2026-10-02 to publish exact policy names for now).

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
Print both calculated thresholds to console before processing. Count Mon–Fri only.

**Holiday handling:** Do NOT attempt to subtract US holidays from working-day counts. Hubstaff already includes approved time-off and holiday hours in the employee's `Total Worked Hours` figure. The raw CSV total is the authoritative hours count — no further adjustment is needed.

---

## Personnel Index Rule

The `Team` column displayed in reports comes directly from the CSV's `Team(s)` column — the script does not do a personnel index lookup for team names.

The personnel index (`data/personnel/personnel_index.md`) is used for:
- Context when interpreting anomalies (e.g. role-appropriate low activity for executives)
- Confirming whether a name in the CSV maps to a known employee
- Flagging name mismatches between the CSV and the index (e.g. name changes, new hires not yet added)

If a name in the CSV does not match anyone in the index, flag it to Aaqib before finalising — do not silently skip or guess.

**Centrifuse Engineers (CE):** CE track in Hubstaff (moved from TMetric in mid-August 2026). For report periods starting 2026-09-01 or later, include CE in the whole Hubstaff report like any other team — only contractors and offboarded staff are excluded. Periods before September 2026 keep the old exclusion (`FS_EXCLUSIONS`) and are not regenerated. The separate CE report is retired from September 2026. In code: `get_exclusions(start)` in `utils.py` returns `PERMANENT_EXCLUSIONS`, plus `FS_EXCLUSIONS` only when `start < CE_HUBSTAFF_START` (2026-09-01). All report scripts use it — never add `FS_EXCLUSIONS` directly.

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

**Permanent exclusions (always applied automatically by the script):**
- **Contractors** — all personnel listed under the Contractors section of `data/personnel/personnel_index.md`
- **Resigned personnel** — add to the `PERMANENT_EXCLUSIONS` list in `scripts/utils.py` as they are confirmed offboarded (offboarded CE go here too, not in `FS_EXCLUSIONS`)
- **Centrifuse Engineers before 2026-09-01** — `FS_EXCLUSIONS`, applied by `get_exclusions(start)` only for periods starting before September 2026

**Cycle-specific exclusions** (new hires in grace period, etc.) are passed via `--exclude "Name 1,Name 2"` after the initial report is generated.

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
- Commit message formats:
  - Bi-weekly: `Report: Bi-Weekly YYYY-MM-DD to YYYY-MM-DD`
  - Pattern Analysis: `Report: Q1 Pattern Analysis YYYY-MM-DD to YYYY-MM-DD`
  - CE Pattern Analysis: `Report: CE Q1 Pattern Analysis YYYY-MM-DD to YYYY-MM-DD`
  - Centrifuse Engineers: `Report: Centrifuse Engineers YYYY-MM-DD to YYYY-MM-DD`
  - Peer Comparison: `Report: Peer Comparison YYYY-MM`
- Never leave uncommitted changes after a session
- Never force-push

---

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `scripts/utils.py` | Shared helpers — working-days, proration, SLA thresholds, flag evaluation, exclusion lists. Import from here, never duplicate. |
| `scripts/generate_biweekly_report.py` | Hubstaff bi-weekly + month-end report generation (`--leave`, `--no-leave`, `--leave-detail`, `--dry-run`) |
| `scripts/build_timeoff_csv.py` | Raw Hubstaff time-off JSON → per-day TO CSV for the month-end report |
| `scripts/generate_ce_report.py` | Legacy — Centrifuse Engineers TMetric report (periods before Sep 2026 only; retired) |
| `scripts/generate_pattern_analysis.py` | Quarterly repeated pattern analysis — fully implemented |
| `scripts/update_index.py` | Regenerate `docs/index.html` from all reports in `/docs/` |
| `scripts/generate_peer_comparison.py` | Role-based peer comparison — fully implemented |
| `scripts/generate_ce_pattern_analysis.py` | Legacy — Centrifuse Engineers pattern analysis on TMetric data (pre-Sep 2026; retired) |

---

## Report Structure

Each bi-weekly HTML report contains:

**Section 1 — Top 15 Violators**
Ranked by severity score. Columns: Rank, Member, Team, Activity %, Hours, Break %, Manual Hours, Low Act ≤20%, Low Act ≤30%, Flags, Score.

**Section 2 — Hours Violators**
All employees below the prorated hours threshold. Sorted ascending (worst first). Columns: Member, Team, Hours Worked, Expected Hours, Shortfall, Other Flags.
Month-end (`--leave`): the hours column becomes Total Hours, a Time Off tag column is added, and each row expands to show Total Hours (Hubstaff) = Hours Worked + Time Off (approved) plus the leave entries.

**Section 3 — Leave Summary (month-end only, `--leave`)**
Everyone with time off (approved or unapproved), sorted by total time off. Columns: Member, Team, Paid/Allocated, Unpaid/Flex, Total. Totals strip by category and by exact policy; header shows "Time off as of <pull timestamp>". Rows expand like Section 2; Expand all / Collapse all per section; print expands everything.

---

## Peer Comparison Workflow

When asked to "generate the peer comparison report for [month]":

1. Confirm the monthly CSV is in `data/input/monthly/`
2. Run:
```
python scripts/generate_peer_comparison.py \
  --input data/input/monthly/HS-YYYY-MM-master.csv \
  --start YYYY-MM-01 --end YYYY-MM-DD
```
3. Script writes HTML to `docs/[start]_to_[end]_peer_comparison.html` and updates `docs/index.html`
4. Commit with message: `Report: Peer Comparison YYYY-MM`
5. Push to GitHub

**How to prompt for this report:**
> "Generate the peer comparison report for March 2026"

**Peer Comparison — Key Rules:**
- 18 hardcoded peer groups defined in `scripts/generate_peer_comparison.py` → `PEER_GROUPS`
- Groups are defined by role/function, NOT Hubstaff team labels
- Manager listed first in each group table with blue `Manager` badge
- Variance column = employee Activity % minus team average Activity %
- Peer Outlier = employee is >10pp below team average BUT has no SLA flag (amber row highlight)
- New hires flagged with green `New Hire` badge (list in `NEW_HIRES` set in script)
- Team Average row at bottom of each table — dark charcoal background for visibility
- Pill-styled metric cells: red/orange/yellow filled for violations, gray for clean
- CE members: excluded before September 2026 (separate CE reports); from 2026-09-01 they get their own peer group (approved by Aaqib)
- Contractors excluded (PERMANENT_EXCLUSIONS in utils.py)
- **To update peer groups** (new hires, team changes, resignations): edit `PEER_GROUPS` list in `generate_peer_comparison.py`

**HTML output naming:** `YYYY-MM-DD_to_YYYY-MM-DD_peer_comparison.html`

---

## Repeated Pattern Analysis Workflow

When asked to "generate the Q1 / quarterly pattern analysis report":

1. Confirm 3 full monthly CSVs are in `data/input/monthly/`
2. Run:
```
python scripts/generate_pattern_analysis.py \
  --months data/input/monthly/HS-YYYY-MM-master.csv \
           data/input/monthly/HS-YYYY-MM-master.csv \
           data/input/monthly/HS-YYYY-MM-master.csv \
  --labels "Month1 YYYY" "Month2 YYYY" "Month3 YYYY" \
  --start YYYY-MM-DD --end YYYY-MM-DD
```
3. Script writes HTML to `docs/[start]_to_[end]_pattern_analysis.html` and updates `docs/index.html`
4. Commit with message: `Report: Q1 Pattern Analysis YYYY-MM-DD to YYYY-MM-DD`
5. Push to GitHub

**How to prompt for this report:**
> "Generate the Q1 pattern analysis report for January, February and March 2026"
> "Create the repeated pattern analysis for [Month1], [Month2], [Month3] [Year]"

**Pattern Analysis — Key Rules:**
- Only includes employees present in **all 3 months** — partial quarter employees excluded
- 10 sections: Activity Red, Activity Yellow, Overwork, Low Hours, Manual Red, Manual Yellow, Low Act ≤20% Red, Low Act ≤20% Yellow, Low Act ≤30% Red, Low Act ≤30% Yellow
- An employee appears in a section only if they have **2+ months** of violations of that specific severity for that metric
- Centrifuse Engineers: excluded (FS_EXCLUSIONS in utils.py) only for quarters starting before 2026-09-01; included from Q4 2026 onward
- Contractors excluded (PERMANENT_EXCLUSIONS list in utils.py)
- Hours thresholds for full months: red < 160h, orange ≥ 200h (no proration needed)
- Manual, Low Act ≤20%, Low Act ≤30% cells display as `XX.X% (Xh)` format
- Use `--sample` flag first to preview structure with 10 employees before running full report

---

## About This Project

**Owner:** Aaqib Hafeel, Process Optimization Lead, WebLife Stores LLC (TA-PO)
**Cycle:** Bi-weekly
**Coverage:** ~80–90 employees across 5 ventures
**Data sources:** Hubstaff (all teams, including Centrifuse Engineers since mid-August 2026). TMetric is no longer used.
**Audience:** Executive review (Lucas Robinson, Jorn Wossner, department directors)
