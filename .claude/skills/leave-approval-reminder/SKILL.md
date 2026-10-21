---
name: leave-approval-reminder
description: >
  Month-end nudge for unapproved Hubstaff time off. Pulls time-off requests via the
  Hubstaff MCP, finds every request still waiting for approval, matches each person to
  their approver from the ClickUp HR profile (Hiring Manager, then Oversight), and drafts
  one ClickUp DM per approver. Nothing is sent until the user says "go". Triggers on
  "@leave-reminder", "/leave-approval-reminder", "remind managers to approve leave",
  "who hasn't approved leave", "chase leave approvals", or the hubstaff-review brief's
  "reminders ready to send" line. Agreed at People Ops on 2 Oct 2026: send on the
  27th or 28th so approvers act before month end, and People Ops checks what's still
  outstanding on the 2nd.
---

# Leave approval reminder (@leave-reminder)

Unapproved leave is a gap: a request that is never approved can be deleted after
the time off is taken, leaving no record (People Ops, 2 Oct 2026). Hubstaff's own
team-lead notifications are switched off, so managers don't get told. This skill
does the telling.

**Send from Rasma's account.** Rasma asked for the reminder to come from her rather
than a shared account, so people don't ignore it. The ClickUp MCP sends as whoever is
connected. If that's not Rasma, say so in the preview and let the user decide.

**Never include leave reasons or messages.** The TO CSV doesn't carry them. Don't go
back to the raw JSON for them.

## 1. Pull time off for the month

Follow the month-end time-off steps in `CLAUDE.md` (Hubstaff MCP, org `572470`):
policies plus requests with `starts_at` from 62 days before the month start to the
day after month end, `include: ["users","time_off_policies"]`. `cp` the spilled
files byte for byte into `data/input/timeoff/raw/`. Then run:

```bash
python scripts/build_timeoff_csv.py --raw data/input/timeoff/raw/TO-RAW-<start>_to_<end>_*.json \
  --start <start> --end <end> --out data/input/timeoff/TO-<start>_to_<end>.csv
```

Run it on the 27th or 28th. Always use the whole month (the 1st to the last day),
so leave booked for the last few days is chased too. Rows with `status` other than
`approved` are the ones to chase. If there are none, say so and stop.

## 2. Find each person's approver

For each member with unapproved rows, read their HR profile in ClickUp list
`901812760745`: the task named `"<Member> - HR"` (use `clickup_search` or
`clickup_filter_tasks` and match the name). Use `clickup_get_task` with
`include: ["custom_fields"]` and read:

1. `Hiring Manager` (users field). This is the approver.
2. If that's empty, `Oversight` (users field).
3. If both are empty, put the person on a "no approver found, Rasma to chase" line.

Keep only the approver's name and email. Read nothing else from the profile.

## 3. Draft one DM per approver

Group the rows by approver. Draft a short message, for example:

> Hi <first name>, quick People Ops check before month end. These time-off requests
> in Hubstaff are still waiting for your approval:
> - <Member> — <policy name>, <dates>, <hours>h
> Could you approve or decline them before month end (<last day of the month, e.g. 31 Oct>)?
> You can do it here: https://app.hubstaff.com/organizations/572470/time_off_requests
> Unapproved requests can't be counted in the month-end hours. Thanks!

Always give the month-end date, never "the 2nd". Put dates as ranges (e.g. "14–15 Oct"). Don't comment on whether the leave is
reasonable. The approver decides that.

## 4. Preview, then send only on "go"

Show one table: Approver | People | Requests | Hours. Show each drafted message under
it, plus the "no approver found" line. Ask once whether to send. On an explicit
"go", send each DM with the `clickup-dm` skill (it finds or opens the DM channel).
Then report what was sent and to whom. Any edit to a message means a fresh preview.

Sending needs a new "go" each run. An earlier approval doesn't carry over.
