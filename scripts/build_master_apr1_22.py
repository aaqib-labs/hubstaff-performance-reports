#!/usr/bin/env python3
"""
Builds HS-2026-04-01_to_2026-04-22.csv (master table) from 4 Hubstaff export files.
Source files: data/input/staging/apr1_22_*.csv
Output: data/input/biweekly/HS-2026-04-01_to_2026-04-22.csv

Column derivation:
  Total Worked Hours     = act_brk_ttl "Time"  (includes break/lunch project time)
  Break Time             = act_brk_ttl "Total Break"
  Activity %             = act_brk_ttl "Average Activity"
  Total Manual Hours     = manual_hrs "Total Manual Hours"
  Low Activity Hours ≤20%= act20 "Time"  (0 if absent = no qualifying hours)
  Low Activity Hours ≤30%= act30 "Time"

Period: 2026-04-01 to 2026-04-22
  Working days in period : 16  (Apr 1–4, 7–11, 14–18, 21–22)
  Working days in April  : 22  (Apr 1–4, 7–11, 14–18, 21–25, 28–30)
  Prorated red threshold : (16/22) × 160 = 116.4h
  Prorated orange        : (16/22) × 200 = 145.5h
"""
import csv
import os
import pandas as pd

STAGING = "data/input/staging/"
OUTPUT  = "data/input/biweekly/HS-2026-04-01_to_2026-04-22.csv"

# ── Prorated hours thresholds ──────────────────────────────────────────────
WORKING_DAYS_PERIOD = 16
WORKING_DAYS_MONTH  = 22
PRORATED_RED    = round((WORKING_DAYS_PERIOD / WORKING_DAYS_MONTH) * 160, 2)  # 116.36
PRORATED_ORANGE = round((WORKING_DAYS_PERIOD / WORKING_DAYS_MONTH) * 200, 2)  # 145.45

# ── SLA thresholds (from data/reference/sla_violation_legend.md) ───────────
ACTIVITY_RED     = 35.0
ACTIVITY_YELLOW  = 45.0
BREAK_RED        = 12.0
BREAK_YELLOW     = 10.0
MANUAL_RED       = 10.0
MANUAL_YELLOW    =  5.0
LOW20_RED        = 15.0
LOW20_YELLOW     =  7.5
LOW30_RED        = 20.0
LOW30_YELLOW     = 10.0

TEAMS = {
    "Aaqib Hafeel":                  "Process Optimization Team, Task Agency",
    "Abdullah Shinwari":             "Catalog Team",
    "Adam Burdeshaw":                "CRM, Digital Product, Leadership, Platform and Engineering Team, VP - Systems - CRM Automation Product Owner",
    "Akram Khan":                    "Catalog Team, Digital Product",
    "Ali Asghar":                    "allintalent, Sales - BDR, Sales - Management",
    "Amjad Ali":                     "Catalog Team",
    "Andrés Victoriano":             "Venia Products  - All, VP - Customer Ops - Support Team",
    "Anna May Rubia":                "Media",
    "Bernard Valdenebro":            "Venia Products  - All, VP - Customer Ops - SDR",
    "Bihani Madushika":              "BI and Data Team, Digital Product, Labs - all",
    "Brayden Robinson":              "Media",
    "Carmen Santos":                 "Venia Products  - All, VP - Customer Ops - CAM",
    "Caryl Agamao":                  "Venia Products  - All, VP - Customer Ops - SDR",
    "Chathuranga Weerakoon":         "CRM, Digital Product, Labs - all",
    "Christine Mayol":               "Venia Products  - All, VP - Customer Ops - Support Team, WeAssist",
    "Darren Karunaratne":            "Labs - all, Venia Products  - All, VP - Customer Ops - Customer Relations",
    "Denise Marsha Elisa Moscare":   "VP - Customer Ops - Leads, VP - Customer Ops - SDR",
    "Dewmi Hathurusingha":           "Labs - all, Task Agency, Task Execution Team",
    "Dharshika Perera":              "Accounting, Labs - all",
    "Dr. Yashoda Velananda":         "CRM, Digital Product, Friday Solutions, Labs - all, Platform and Engineering Team",
    "Eden Schweyer":                 "Leadership, Venia Products  - All, VP - Customer Ops - Leads, VP - Customer Ops - SDR, VP - Systems - CRM Automation Product Owner, VP - VA/Contractor",
    "Erandi Bandaranayake":          "Labs - all, Venia Products  - All, VP - Customer Ops - Order Processing",
    "Farhanah Junainah Umpar":       "Venia Products  - All, VP - Customer Ops - SDR",
    "Farshad Ramsee":                "Labs - all, Media",
    "Fred Butson":                   "Framework Friday, Leadership, Sales - Management",
    "Hafiz Mudasir":                 "Amazon, International Team, Marketing- Labs, Team Lucas",
    "Hammad Rafique":                "Catalog Team",
    "Hasala Jayasuriya":             "Content_catalog_platform, Digital Product, Labs - all, Platform and Engineering Team",
    "Ibrahim Adeeb":                 "Accounting, FP&A",
    "Irene Padilla":                 "Accounting, WeAssist",
    "Jason Diaz":                    "Task Agency, Task Execution Team",
    "Jebby Rochelle":                "Framework Friday, Labs - all",
    "Jehu Graza":                    "Venia Products  - All, VP - Customer Ops - SDR",
    "Jesus Corral":                  "Venia Products  - All, VP - Customer Ops - CAM",
    "Joan Lopez":                    "Venia Products  - All, VP - Customer Ops - Support Team",
    "Jomal Mathew":                  "Catalog Team, Digital Product",
    "jorn wossner":                  "Leadership",
    "Kawya Samarasinghe":            "Design, Labs - all, Marketing- Labs, Media",
    "Kianna Xue":                    "Venia Products  - All, VP - Systems - CRM Automation Product Owner",
    "Krishanthiny Krishnaraj":       "AIT - Recruitment, allintalent, Labs - all",
    "Kristine Anne Dela Cruz":       "Venia Products  - All, VP - Customer Ops - SDR",
    "Kunchana Prabashwara":          "Design, Digital Product, Labs - all, Site Content",
    "Kushani Kalpage":               "allintalent, Labs - all",
    "Laci Burton":                   "Accounting, Leadership",
    "Laleesha Wijeratne":            "Catalog Team, Content_catalog_platform, Digital Product, Labs - all",
    "leora megan":                   "Labs - all, VP - Customer Ops - Customer Relations",
    "Lucas Robinson":                "Leadership, Team Lucas",
    "Ma Aubrey Sustento":            "Venia Products  - All, VP - Customer Ops - Support Team",
    "Mary Anne Soriano":             "Venia Products  - All, VP - Customer Ops - Support Team, WeAssist",
    "Melanie Joy Pecaña":            "Accounting, WeAssist",
    "Menara Kahatapitiya":           "allintalent",
    "Meredith Goostree":             "Venia Products  - All, VP - Customer Ops - CAM",
    "Modhuka Paranagama":            "BI and Data Team, Digital Product, Labs - all",
    "Monica Lopez":                  "Venia Products  - All, VP - Customer Ops - CAM",
    "Muhammad Usman":                "CRM, Digital Product",
    "Natalia Jayasundera":           "allintalent, HR, Labs - all",
    "Nawodya De Silva":              "Process Optimization Team, Task Agency",
    "Nireshwaran Aravinth":          "AIT - Recruitment, allintalent, Labs - all",
    "Nishantha Hettiarachchi":       "Digital Product, Labs - all",
    "Nouman Khan":                   "Catalog Team",
    "Ounvin Ranaweera":              "Labs - all, Venia Products  - All, VP - Customer Ops - Customer Relations",
    "Prajwal Kumar":                 "Marketing - Paid Media",
    "Ramez Sedra":                   "Content_catalog_platform, Digital Product, SEO Team, Site Content",
    "Rannie Belen":                  "Media",
    "Ransika Kalutharage":           "Brand & PR, Labs - all, Marketing- Labs, Media",
    "Rasma Rizwan":                  "allintalent, HR, Labs - all",
    "Rebecca Corona":                "VP - Customer Ops - Leads, VP - Customer Ops - Order Processing",
    "Reynalyn Gramatica":            "Framework Friday",
    "Rishonath Siva":                "Design, Labs - all, Media",
    "Saduka Sachintha":              "Amazon, Labs - all, Marketing- Labs, Marketing - Paid Media, Sales - RGC",
    "sanjula paulis":                "Labs - all, Media",
    "Sara Higgason":                 "VP - Customer Ops - Leads, VP - Customer Ops - Support Team",
    "Sarah Madoro":                  "Venia Products  - All, VP - Customer Ops - SDR",
    "Sarena Nicole Arokiasamy":      "Framework Friday",
    "Sasindee Wijeratne":            "Labs - all, Sales - RGC",
    "Saumya Sewwandi":               "Digital Product",
    "Sean Dehoedt":                  "Task Agency",
    "Shaarukshan Seralathan":        "Labs - all",
    "Shannon Woods":                 "Venia Products  - All, VP - Customer Ops - CAM, VP - Customer Ops - Leads",
    "Shehara Meadows":               "Content_catalog_platform, Digital Product, Labs - all, Site Content",
    "shenali edirisinghe":           "Amazon, Labs - all, Marketing- Labs, Team Lucas",
    "Shenallie Jayathillake":        "Labs - all, Venia Products  - All, VP - Customer Ops - Order Processing",
    "Shen Perera":                   "Labs - all, Task Agency, Task Execution Team",
    "Staffey Murugadas":             "Labs - all, Task Agency, Task Execution Team",
    "Subashi Silva":                 "Labs - all, Venia Products  - All, VP - Customer Ops - Order Processing",
    "Tashia Bernardus":              "Task Agency, Task Execution Team",
    "Tharusha Kulasinghe":           "Digital Product",
    "Thushan Fernando":              "Content_catalog_platform, Digital Product, Labs - all, Platform and Engineering Team",
    "Unaiza Imran":                  "Design, Sales - RGC",
    "Upeksha Liyanage":              "Digital Product, Labs - all, Platform and Engineering Team",
    "Vincent Deximo":                "Venia Products  - All, VP - Customer Ops - Support Team",
}


def fix_name(s):
    """Fix mojibake in names (CSV saved with wrong encoding)."""
    try:
        return s.encode('latin-1').decode('utf-8')
    except Exception:
        return s


def load_csv(path):
    """Load Hubstaff export CSV — data rows have extra trailing empty columns.
    Use csv module to trim each row to header length before handing to pandas."""
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader)
        n = len(headers)
        rows = [row[:n] for row in reader if any(v.strip() for v in row[:n])]
    df = pd.DataFrame(rows, columns=headers)
    df['Grouped by Member'] = df['Grouped by Member'].apply(fix_name)
    return df


def pct_str(val, total):
    if total == 0:
        return '0.0%'
    return f"{round(val / total * 100, 1)}%"


def evaluate_flags(total_hours, break_pct, manual_pct, low20_pct, low30_pct, activity_pct):
    """
    Evaluate SLA flags for one employee.
    Returns (legend_str, red_count, yellow_count, total_flags).
    Red overrides yellow for same metric.
    Break yellow (B⚠️) excluded from displayed counts per SLA rules.
    """
    parts = []
    red = 0
    yellow = 0

    # Activity
    if activity_pct < ACTIVITY_RED:
        parts.append("A🔴"); red += 1
    elif activity_pct < ACTIVITY_YELLOW:
        parts.append("A⚠️"); yellow += 1

    # Hours (red = below prorated red; orange = at/above prorated orange)
    if total_hours < PRORATED_RED:
        parts.append("H🔴"); red += 1
    elif total_hours >= PRORATED_ORANGE:
        parts.append("H🟠"); red += 1  # orange counts in red badge

    # Break %
    if break_pct >= BREAK_RED:
        parts.append("B🔴"); red += 1
    elif break_pct > BREAK_YELLOW:
        parts.append("B⚠️"); yellow += 1

    # Manual %
    if manual_pct >= MANUAL_RED:
        parts.append("M🔴"); red += 1
    elif manual_pct >= MANUAL_YELLOW:
        parts.append("M⚠️"); yellow += 1

    # Low Activity ≤20%
    if low20_pct >= LOW20_RED:
        parts.append("20🔴"); red += 1
    elif low20_pct >= LOW20_YELLOW:
        parts.append("20⚠️"); yellow += 1

    # Low Activity ≤30%
    if low30_pct >= LOW30_RED:
        parts.append("30🔴"); red += 1
    elif low30_pct >= LOW30_YELLOW:
        parts.append("30⚠️"); yellow += 1

    legend = ", ".join(parts) if parts else ""
    return legend, red, yellow, red + yellow


# ── Load source files ──────────────────────────────────────────────────────
act_brk = load_csv(f"{STAGING}apr1_22_act_brk_ttl.csv")
manual   = load_csv(f"{STAGING}apr1_22_manual_hrs.csv")
act20    = load_csv(f"{STAGING}apr1_22_act20.csv")
act30    = load_csv(f"{STAGING}apr1_22_act30.csv")

# Cast numeric columns
act_brk['Time']         = pd.to_numeric(act_brk['Time'],         errors='coerce')
act_brk['Total Break']  = pd.to_numeric(act_brk['Total Break'],  errors='coerce')
manual['Total Manual Hours'] = pd.to_numeric(manual['Total Manual Hours'], errors='coerce')
act20['Time'] = pd.to_numeric(act20['Time'], errors='coerce')
act30['Time'] = pd.to_numeric(act30['Time'], errors='coerce')

# ── Build base dataframe from act_brk (authoritative total hours + break + activity)
base = act_brk[['Grouped by Member', 'Time', 'Total Break', 'Average Activity']].copy()
base.columns = ['Member', 'Total Worked Hours', 'Break Time', 'Activity %']

# Manual hours: only need "Total Manual Hours" from manual_hrs
man = manual[['Grouped by Member', 'Total Manual Hours']].rename(
    columns={'Grouped by Member': 'Member'})
df = base.merge(man, on='Member', how='left')
df['Total Manual Hours'] = df['Total Manual Hours'].fillna(0.0)

# Low activity ≤20%
a20 = act20[['Grouped by Member', 'Time']].rename(
    columns={'Grouped by Member': 'Member', 'Time': 'Low Activity Hours (≤20%)'})
df = df.merge(a20, on='Member', how='left')
df['Low Activity Hours (≤20%)'] = df['Low Activity Hours (≤20%)'].fillna(0.0)

# Low activity ≤30%
a30 = act30[['Grouped by Member', 'Time']].rename(
    columns={'Grouped by Member': 'Member', 'Time': 'Low Activity Hours (≤30%)'})
df = df.merge(a30, on='Member', how='left')
df['Low Activity Hours (≤30%)'] = df['Low Activity Hours (≤30%)'].fillna(0.0)

# Teams
df['Team(s)'] = df['Member'].map(TEAMS)

# ── Calculate percentage columns ───────────────────────────────────────────
df['Break % of Total']      = df.apply(lambda r: pct_str(r['Break Time'],                 r['Total Worked Hours']), axis=1)
df['Manual % of Total']     = df.apply(lambda r: pct_str(r['Total Manual Hours'],         r['Total Worked Hours']), axis=1)
df['Low Activity % (≤20%)'] = df.apply(lambda r: pct_str(r['Low Activity Hours (≤20%)'], r['Total Worked Hours']), axis=1)
df['Low Activity % (≤30%)'] = df.apply(lambda r: pct_str(r['Low Activity Hours (≤30%)'], r['Total Worked Hours']), axis=1)

# ── Evaluate SLA flags ─────────────────────────────────────────────────────
def parse_pct(s):
    try:
        return float(str(s).replace('%', '').strip())
    except Exception:
        return 0.0

legends, reds, yellows, totals = [], [], [], []
for _, row in df.iterrows():
    act_pct    = parse_pct(row['Activity %'])
    brk_pct    = parse_pct(row['Break % of Total'])
    man_pct    = parse_pct(row['Manual % of Total'])
    low20_pct  = parse_pct(row['Low Activity % (≤20%)'])
    low30_pct  = parse_pct(row['Low Activity % (≤30%)'])
    total_hrs  = float(row['Total Worked Hours']) if row['Total Worked Hours'] else 0.0

    legend, red, yellow, total = evaluate_flags(
        total_hrs, brk_pct, man_pct, low20_pct, low30_pct, act_pct)
    legends.append(legend)
    reds.append(red)
    yellows.append(yellow)
    totals.append(total)

df['SLA Violation Legend'] = legends
df['Red Flag Count']       = reds
df['Yellow Flag Count']    = yellows
df['Total Flags']          = totals

# ── Final output ───────────────────────────────────────────────────────────
cols = [
    'Team(s)', 'Member', 'Activity %', 'Total Worked Hours',
    'Break Time', 'Break % of Total',
    'Total Manual Hours', 'Manual % of Total',
    'Low Activity Hours (≤20%)', 'Low Activity % (≤20%)',
    'Low Activity Hours (≤30%)', 'Low Activity % (≤30%)',
    'SLA Violation Legend', 'Red Flag Count', 'Yellow Flag Count', 'Total Flags',
]
df = df[cols].sort_values('Member').reset_index(drop=True)

os.makedirs("data/input/biweekly", exist_ok=True)
df.to_csv(OUTPUT, index=False)

print(f"Prorated red threshold   : {PRORATED_RED}h  ({WORKING_DAYS_PERIOD}/{WORKING_DAYS_MONTH} × 160)")
print(f"Prorated orange threshold: {PRORATED_ORANGE}h  ({WORKING_DAYS_PERIOD}/{WORKING_DAYS_MONTH} × 200)")
print(f"\nMaster table written → {OUTPUT}")
print(f"Total members: {len(df)}")

unmapped = df[df['Team(s)'].isna()]['Member'].tolist()
if unmapped:
    print(f"\n⚠️  Members with no team mapping: {unmapped}")
else:
    print("All members have team assignments ✓")

print("\n── Flag summary ──────────────────────────────────────────────────")
flagged = df[df['Total Flags'] > 0][['Member', 'Activity %', 'Total Worked Hours', 'SLA Violation Legend', 'Red Flag Count', 'Yellow Flag Count', 'Total Flags']]
print(f"Members with flags: {len(flagged)} / {len(df)}")
print(flagged.to_string(index=False))
