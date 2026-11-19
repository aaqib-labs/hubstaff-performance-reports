---
name: month-end-report
description: >
  Runs the monthly Hubstaff Performance Report end to end with as little back and
  forth as possible: pulls time off, timesheets and activity from the Hubstaff MCP,
  pay types and HR profile notes from ClickUp, builds every input file, dry-runs the
  report, cross-checks every hours figure against Hubstaff, shows Aaqib one review
  pack, and publishes on his go. Also covers the mid-month (bi-weekly) run. Triggers
  on "@month-end", "/month-end-report", "run the month-end report", "generate the
  report for <month>", "update the live page for <month>", "run the bi-weekly report".
---

# Month-end Hubstaff Performance Report (@month-end)

The whole run, in order. CLAUDE.md holds the rules (thresholds, time-off categories,
Section 3 targets); this file holds the procedure. Aaqib is asked **twice** at most:
once for the review pack (step 9), once to publish (step 11). Everything else is done
without asking unless a step below says to stop.

**Confidential, public repo.** Pay types and HR notes go on the command line or into
gitignored files under `data/input/` only. Never commit anything under `data/input/`.
No pay figures anywhere. Leave messages and reasons from Hubstaff are never written out.

## 0. Set the period

- Month-end: `<start>` = 1st, `<end>` = last day of the month just closed. `<m1>`,
  `<m2>` = the two months before (Section 3 shows all three).
- Mid-month: `<start>`/`<end>` from the bi-weekly CSV name. Skip steps 3b, 5 and 7
  (no Section 3); everything else is the same.
- Pull folder: `data/input/hubstaff_pulls/<YYYY-MM>/` (gitignored). Org id: call
  `list_organizations` (WebLife = 572470).

## 1. Master CSV

Confirm `data/input/monthly/HS-<YYYY-MM>-master.csv` exists (mid-month:
`data/input/biweekly/HS-<start>_to_<end>.csv`). Note its file time: that is the
export time used for late leave approvals. If the file was copied or re-saved since
it was exported, ask Aaqib for the export date and pass `--csv-exported`.

## 2. Hubstaff pulls (MCP), saved byte-for-byte

Large responses spill to a tool-results file: `cp` it into the pull folder. If a page
comes back inline, save it with the Write tool exactly as returned, then check it
parses (`python3 -m json.tool <file> >/dev/null`). Never retype or edit JSON.

a. **Time off**, `get_organizations_organization_id_time_off_policies` →
   `data/input/timeoff/raw/TO-RAW-<start>_to_<end>_policies.json`.
b. **Time off requests**, `get_organizations_organization_id_time_off_requests` with
   `include: ["users","time_off_policies"]`, `page_limit: 500`, `starts_at` from
   `<start − 62 days>` to `<end + 1 day>` (this window also covers `<m1>` and `<m2>`).
   The API refuses responses over about 137 KB: split the window into date chunks of
   about six weeks (`..._requests_p1.json`, `_p2`, ...). Page with `page_start_id` when
   a `pagination` object comes back.
c. **Timesheets** for `<m2>`, `<m1>` and the report month,
   `get_organizations_organization_id_timesheets` with `date: {start, stop}` = the
   month → `<pull folder>/TS-<YYYY-MM>.json`. One call per month covers everyone who
   submits timesheets and includes names.
d. **Members**, `get_organizations_organization_id_members` with `include: ["users"]`,
   all pages → `<pull folder>/members_p<n>.json` (user id → name for everyone else).

## 3. Build time off

a. `python3 scripts/build_timeoff_csv.py --raw data/input/timeoff/raw/TO-RAW-<start>_to_<end>_*.json --start <start> --end <end> --out data/input/timeoff/TO-<start>_to_<end>.csv`
b. Month-end only: rebuild `<m1>` and `<m2>` from the **same** raw files (same command
   with their dates and `TO-<m>-01_to_<m-end>.csv` as out). Late approvals (e.g. leave
   approved on Nov 1 for August) only show this way; the report warns if an earlier
   month's file is older than this pull.
c. Note every WARN/ERROR for the review pack (e.g. 16h on one day = a request booked
   on the wrong day in Hubstaff).

## 4. Pay types (ClickUp)

List `901812760745`, field Salary Type (`4ecfdb16-4f10-4a2f-89ea-7c53aa957ad5`),
Hourly `9902cc89-7cfe-4bf9-888c-9b109d4c233e`, Salaried
`6be8afd5-74c7-425d-a6e7-2e4a835cf514` (`clickup_filter_tasks`, all pages). Names are
`"<Name> - HR"`: strip ` - HR`, skip offboarded/terminated. Keep the two lists in the
shell for `--salaried` / `--hourly` only.

## 5. Salaried status file

`data/input/salaried/salaried_status.csv` decides Section 3 and overrides the ClickUp
field. Source of truth: **Rasma's tracker** on ClickUp to-do 86eyuadqb (comment
1100510000260517, effective dates from the Hubstaff rate history). Each month:
- read the to-do for an updated list; add new movers (`moved`, date, 180) and fix
  changed dates. The tracker wins over letters and HR comments.
- compare the file with the freshly pulled Salary Type field (step 4). The run prints
  every person whose pay type the file overrides; the only expected ones are people
  whose move date is after the report month (e.g. Aaqib and Ounvin, Nov 1, show as
  Hourly for October). Anything else goes in the review pack.
- people whose effective date has now passed need nothing: the date does it.
Evidence column: the tracker comment id. New rows go in the review pack.

## 6. Dry run

```
python3 scripts/generate_biweekly_report.py --input <master CSV> --start <start> --end <end> \
  --leave data/input/timeoff/TO-<start>_to_<end>.csv --salaried "$SAL" --hourly "$HR" \
  [--exclude "..."] [--hr-context data/input/hr_context/HRC-<start>_to_<end>.json] --dry-run
```
Read the whole console output. Carry into the review pack: Unknown pay types, ClickUp
names with no row, names the status file could not match, late approvals, every
WARNING. New hires in their first month go in `--exclude` only if Aaqib said so in a
previous month's notes; otherwise list them in the pack.

## 7. Cross-check against Hubstaff

```
python3 scripts/verify_hours.py --start <start> --end <end> --pulls data/input/hubstaff_pulls/<YYYY-MM> --holiday <YYYY-MM>=8
```
(`--holiday` for each month with a paid US holiday: Labor Day = September.)
1. It prints the user ids with no timesheet. Pull
   `get_organizations_organization_id_activities_daily` for each month with
   `user_ids: [...]`, `page_limit: 300`, every page, into the pull folder, then
   run it again. Never save part-paged org-wide pages.
2. Any difference (any month, the report month included) = time edited after the
   export. Re-run with `--write-refresh`: the report then uses today's Hubstaff
   figure (Aaqib, 2026-11-19). Re-run until it prints `Differences: 0`.
Target: `Differences: 0`, then re-run the dry run. Never write "employees" anywhere: team members.

## 8. HR profile notes

For everyone in Top 15, Hours Violators, and every Section 3 row that is Serious,
Alert or has a 🔴 month: read HR profile comments and thread replies (list
`901812760745`) from one month before `<start>` to today. Use a subagent for this
and a second subagent to check each drafted note against its source (as on Nov 19).
Rules: CLAUDE.md step 6 (hours, activity, leave, availability only; reasons by
category; no pay; dates in Sri Lanka time; a fact taken from an assessment says so).
Write the drafts to `data/input/hr_context/HRC-<start>_to_<end>.json` so the dry run
shows them, and re-run step 6.

## 9. Review pack (ask once)

One message to Aaqib with:
- **The numbers:** counts for each section and Section 3 Serious/Alert names.
- **Cross-check result:** "N figures match Hubstaff", plus any differences.
- **New or changed rows** in the salaried status file, with evidence.
- **Open items:** Unknown pay types, unmatched names, late approvals, WARN lines.
- **Notes to approve:** one table (person, author, date, line).
Ask once: approve notes and publish? Apply edits he asks for without re-asking about
the rest.

## 10. (only if he edits) apply and re-dry-run

## 11. Publish on his go

Re-run step 6 without `--dry-run` (writes `docs/` and `docs/index.html`). Commit
`Report: Bi-Weekly <start> to <end>` (code changes in a separate `Feature:` commit)
and push. Give him the live link:
`https://aaqib-labs.github.io/hubstaff-performance-reports/<start>_to_<end>_biweekly_top_violators.html`

## After publishing

- If a People Ops prep session or IDS item depends on the report, send it a short
  summary of what changed (Section 3 names, new rules, open items).
- Record any new rule Aaqib gives in CLAUDE.md (the rule) and memory (the why).
