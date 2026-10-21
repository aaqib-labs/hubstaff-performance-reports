---
name: hubstaff-review
description: >
  Monthly People Ops Hubstaff review brief: a "Discuss today" list of at most 15
  bullets plus the detail behind it. Covers salaried staff against the 180h rule
  over the last 3 months, repeat SLA patterns (red in 2+ of 3 months), peer
  outliers, unapproved leave, and (on request) unusual-activity alerts. Triggers on
  "@hubstaff-review", "/hubstaff-review", "run the Hubstaff review", "who's under on
  hours", "salaried hours check", "prep the Hubstaff part of People Ops", or a request
  for one section ("@hubstaff-review salaried"). Read-only: it never posts or sends.
---

# Hubstaff review (@hubstaff-review)

Turns three months of Hubstaff data into a list People Ops can go through in about
five minutes (Jorn, People Ops 2 Oct 2026). All the maths is in
`scripts/hs_review.py`; this skill gathers the inputs and runs it.

**Confidential.** HR profile data (salary type, status) is read live from ClickUp
and passed on the command line only. Never write it to a file, never commit it,
never paste the brief anywhere except back to the user.

## 1. Pick the months

Default: the last three **complete** calendar months (on 21 Oct 2026 that is
Jul, Aug, Sep). Confirm with the user in one line if they named something else.

Check `data/input/monthly/HS-YYYY-MM-master.csv` exists for all three. If one is
missing, stop and say which. Those CSVs come from the hubstaff-master-table skill.
The MCP can't replace them: Hubstaff timesheets miss about a third of staff
(anyone without a payroll timesheet, including leadership and some salaried staff).

Note which `data/input/timeoff/TO-YYYY-MM-01_to_YYYY-MM-DD.csv` files exist for
those months. They let the script take approved unpaid leave out of the salaried
hours (Rasma's rule: count worked hours plus paid leave only).

## 2. Pull names from the ClickUp HR profiles

List `901812760745` (People Ops_all_teams). Use `clickup_filter_tasks` with
`subtasks: false`. Task names are `"<Name> - HR"`: strip the ` - HR`.

- **Salaried:** custom field `Salary Type` (`4ecfdb16-4f10-4a2f-89ea-7c53aa957ad5`)
  `=` `1` (Salaried). Drop tasks whose status is `offboarded` or `terminated`.
- **Offboarded:** `statuses: ["offboarded", "terminated"]`. Pass these as `--skip`.

Keep both lists in memory only.

## 3. Run the brief

```bash
python scripts/hs_review.py \
  --months data/input/monthly/HS-<m1>-master.csv data/input/monthly/HS-<m2>-master.csv data/input/monthly/HS-<m3>-master.csv \
  --salaried "<comma-separated salaried names>" \
  --skip "<comma-separated offboarded names>" \
  --leave <every TO csv that exists for those months>
```

One section only: add `--section salaried|patterns|peers|leave|unusual`.

## 4. Unusual activity (only when asked)

There are about 20 alerts a day, so pull the **last 7 days** only. Hubstaff MCP,
org `572470`: `get_organizations_organization_id_insights_unusual_activities` with
`time_slot: {start, stop}` (ISO, UTC) and `page_limit: 40`. Follow
`pagination.next_page_start_id` until it is absent. Each page spills to a
tool-results file: `cp` it byte for byte to
`data/input/hs_mcp/raw/UA-<start>_to_<stop>_p<N>.json` (gitignored). Never retype
JSON. If a short last page comes back inline, count its medium/high rows yourself
and say so in the brief.

For names, also pull `get_organizations_organization_id_members` with
`include: ["users"]`, `page_limit: 300` and copy it to
`data/input/hs_mcp/raw/MEMBERS.json`. Then rerun step 3 with
`--unusual <pages> --members data/input/hs_mcp/raw/MEMBERS.json`.

## 5. Hand it back

Show the brief as the script prints it. Don't re-rank, soften or add people. Then
add at most two lines for anything the script flagged as a data gap (missing
time-off file, salaried names not found in the CSVs).

## Rules baked into the script

| Check | Rule |
| --- | --- |
| Salaried hours | Target 180h a month, flag under 170h (Jorn's "within range"). Hours = Total Worked Hours − approved unpaid leave. Under in the latest month only = ⚠️ alert. Under in 2+ of 3 months = 🔴 serious. A one-off earlier month that recovered is not shown. |
| New joiners | No earlier months and under the floor = partial first month, listed but not flagged. |
| Leadership | The `leadership` peer group in `generate_peer_comparison.py` is listed but not ranked. |
| Repeat patterns | Standard SLA red (`utils.evaluate_flags`, full-month 160h/200h) in 2+ of the 3 months. Salaried staff are checked for hours in their own section, not here. |
| Peer outliers | More than 10 points of activity below their `PEER_GROUPS` average in the latest month. It makes the top list when that happened in 2+ months. |
| Unusual activity | Medium and high confidence only. `sustained_high_focus_time` is ignored. These are review signals, not findings. |

The 170h floor is a proposal until Jorn confirms it: `SALARIED_FLOOR` in the script.
