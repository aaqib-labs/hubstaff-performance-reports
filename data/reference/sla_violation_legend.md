# SLA Violation Legend — Authoritative Threshold Reference

## Metric Notation

| Code | Metric |
|------|--------|
| A    | Activity % |
| H    | Total Worked Hours |
| B    | Break % of Total Worked Hours |
| M    | Manual % of Total Worked Hours |
| 20   | Low Activity Hours ≤20% (as % of total worked hours) |
| 30   | Low Activity Hours ≤30% (as % of total worked hours) |

---

## Violation Thresholds

| Metric | Red 🔴 Critical       | Yellow ⚠️ Warning        | Orange 🟠 Investigate   |
|--------|-----------------------|--------------------------|--------------------------|
| A      | < 35%                 | < 45%                    | —                        |
| H      | < 160h (full month)   | — (no yellow for hours)  | ≥ 200h (full month)      |
| B      | ≥ 12%                 | > 10% and < 12%          | —                        |
| M      | ≥ 10%                 | ≥ 5%                     | —                        |
| 20     | ≥ 15% of worked hours | ≥ 7.5% of worked hours   | —                        |
| 30     | ≥ 20% of worked hours | ≥ 10% of worked hours    | —                        |

**Hours SLA is strict — no yellow band. An employee is either compliant (≥ 160h) or red (< 160h). Orange flags overwork (≥ 200h).**

---

## Critical Rules

1. Red flags ALWAYS take precedence over yellow for the same metric
2. NEVER prorate or modify thresholds that are explicitly provided — only auto-prorate when computing from a date range
3. Yellow break flags (B ⚠️) ARE included in displayed total flag counts
4. One metric = one flag maximum (red overrides yellow; never both for same metric)
5. All employees in the master table are included — no permanent exclusions
6. Cycle-specific exclusions (offboarded staff, new hires in grace period) are handled via follow-up prompt after initial report generation

---

## Violation Priority Hierarchy (highest to lowest weight)

1. Activity % (A)
2. Manual Hours (M)
3. Overwork — Hours (H ≥ 200h) 🟠
4. Low Hours (H < prorated threshold) 🔴
5. Low Activity ≤20% (metric: 20)
6. Low Activity ≤30% (metric: 30)
7. Break Time (B)

---

## Severity Scoring System

Used to rank employees for Top 15 selection. Documented here for transparency.

```
Base points:
  Red (🔴)    = 10 pts
  Yellow (⚠️) =  3 pts
  Orange (🟠) =  7 pts

Metric multipliers (reflecting priority hierarchy):
  A  (Activity %)        → 5×
  M  (Manual %)          → 4×
  H  (Low Hours 🔴)      → 3×
  H  (Overwork 🟠)       → 2×
  20 (Low Act ≤20%)      → 2×
  30 (Low Act ≤30%)      → 1.5×
  B  (Break %)           → 1×

Score = sum of (base_pts × multiplier) for each flag

Examples:
  A red + M yellow + H red = (10×5) + (3×4) + (10×3) = 50 + 12 + 30 = 92
  A yellow only            = 3×5 = 15
```

Break time (B) contributes to the score but is excluded from the displayed flag count badge.

---

## Hours Thresholds — Prorated for Partial Periods

**Base benchmarks:** 160h/month (full-time target) | 200h/month (overwork cap)

**Working days calculation:**
- Count Monday–Friday only
- US holidays on the WebLife calendar are excluded (TODO: WebLife holiday calendar not yet provided — currently Mon–Fri only)
- Do NOT assume 20 working days as a fixed base — count the actual calendar

**Formulas:**
```
prorated_red    = (working_days_in_period / total_working_days_in_month) × 160
prorated_orange = (working_days_in_period / total_working_days_in_month) × 200
```

**Script behavior:**
1. Auto-counts working days in the `[start, end]` period
2. Auto-counts total working days in the calendar month of `start`
3. Calculates both prorated thresholds and prints to console before processing
4. Flags anyone below prorated red in Section 2 (Hours Violators)
5. Flags anyone at/above prorated orange as overwork

---

## Formatting Standards

| Field                    | Format                        |
|--------------------------|-------------------------------|
| Activity %               | Round to whole number, e.g. `34%` |
| All other numeric values | 1 decimal place               |
| Percentage symbols       | Always included               |
| Break / Manual / Low Act | `Xh (X.X%)` format            |
| Flags badge              | `🔴 2 ⚠️ 1` (B ⚠️ excluded from count) |
| Member name cells        | No status emoji prefix        |
| Empty/compliant cells    | Leave blank (no "CLEAR" text) |
| Violation indicators     | Embedded in metric cells, e.g. `🔴 34%`, `⚠️ 8.3h (11.4%)` |

---

## Document Version

**Version:** 1.1
**Last Updated:** 2026-03-25
**Source:** Derived from Hubstaff SLA Violation Legend v1.0 (November 10, 2025)
