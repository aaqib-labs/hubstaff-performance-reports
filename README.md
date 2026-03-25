# WebLife Ventures — Bi-Weekly Performance Reporting System

Automated bi-weekly workforce performance compliance reports for ~80–90 employees tracked via Hubstaff. Reports are published as static HTML via GitHub Pages for internal executive review.

---

## Folder Structure

```
data/input/          Drop master table CSVs here each cycle
data/personnel/      Personnel Index — authoritative role/team source
data/reference/      SLA thresholds and violation legend
scripts/             Python report generation scripts
templates/           Jinja2 HTML report templates
reports/             Archived reports by cycle (YYYY-MM-DD_to_YYYY-MM-DD)
docs/                GitHub Pages source — served as the public URL
CLAUDE.md            Instructions for Claude Code AI assistant
```

---

## Setup

```bash
pip install -r requirements.txt
```

---

## Generating a Bi-Weekly Report

1. Drop the master table CSV into `data/input/`
2. Run:

```bash
python scripts/generate_biweekly_report.py \
  --input data/input/YOUR_FILE.csv \
  --start 2026-03-01 \
  --end 2026-03-11
```

The script will:
- Auto-calculate prorated hours thresholds and print them to console
- Generate the HTML report in `reports/2026-03-01_to_2026-03-11/`
- Copy it to `docs/` and update the index page
- Tell you what to commit

3. Commit and push:

```bash
git add .
git commit -m "Report: Bi-Weekly 2026-03-01 to 2026-03-11"
git push
```

---

## Updating the Personnel Index

Edit `data/personnel/personnel_index.md` to add/remove/update employees.
The index is the authoritative source for team codes and job titles — Hubstaff's own team labels are not used for role matching.

---

## Adding Cycle Exclusions

Do NOT pre-emptively exclude anyone from the initial report run.
After the report is generated, use a follow-up prompt to Claude Code:

> "Exclude [Name] from the report — they were offboarded on [date]."

Claude will re-run the relevant section with the exclusion applied.

---

## GitHub Pages

Once the repo is published, reports are available at:

```
https://[your-github-username].github.io/[repo-name]/
```

Configure GitHub Pages to serve from the `/docs` folder in your repo settings.

---

## SLA Thresholds

See `data/reference/sla_violation_legend.md` for the full threshold reference.
Quick summary:

| Metric | Red | Yellow | Orange |
|--------|-----|--------|--------|
| Activity % | < 35% | < 45% | — |
| Hours | < 160h (prorated) | — | ≥ 200h (prorated) |
| Break % | ≥ 12% | > 10% | — |
| Manual % | ≥ 10% | ≥ 5% | — |
| Low Act ≤20% | ≥ 15% | ≥ 7.5% | — |
| Low Act ≤30% | ≥ 20% | ≥ 10% | — |
