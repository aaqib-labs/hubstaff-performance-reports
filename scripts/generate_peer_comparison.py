"""
WebLife Ventures — Role-Based Peer Comparison Report (STUB)
===========================================================
This script will compare flagged employees against their same-role
or same-team peers to determine whether a violation is an individual
anomaly or a team-wide pattern.

Usage (planned):
    python scripts/generate_peer_comparison.py \
        --input data/input/master_table.csv \
        --start 2026-03-01 \
        --end 2026-03-11

TODO: Full implementation
---------------------------------------------------------------------
Logic to implement:
  1. Load master table CSV (same format as generate_biweekly_report.py)
  2. Load data/personnel/personnel_index.md to get team codes for all members
  3. Group all employees by team_code (from personnel index, not Hubstaff labels)
  4. For each team group, calculate:
     - Team average Activity %
     - Team average Hours
     - Team average Break %
     - Team average Manual %
  5. For each flagged employee:
     - Compare their metrics to team averages
     - If their Activity is low but team average is also low → may be
       role-appropriate (e.g., executives, meeting-heavy roles)
     - If their metrics are outliers vs. peers → stronger signal
  6. Generate HTML report:
     - Section 1: Peer comparison table per team (members vs. team avg)
     - Section 2: Individual outlier summary (metric deviation from team avg)
     - Section 3: Teams with systemic issues (majority of team flagged)
  7. Include role-based exception notes from personnel_index.md
  8. Output to /reports/[date-range]/peer_comparison.html
  9. Copy to /docs/ and update /docs/index.html

Key consideration: executives and meeting-heavy roles will naturally show
low Activity %. These should be noted but not suppressed — the report
should surface them with context, not hide them.
---------------------------------------------------------------------
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def main():
    parser = argparse.ArgumentParser(
        description="Generate role-based peer comparison report (stub — not yet implemented)."
    )
    parser.add_argument(
        "--input",
        required=True,
        metavar="CSV",
        help="Path to master table CSV",
    )
    parser.add_argument("--start", required=True, help="Period start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Period end date YYYY-MM-DD")
    args = parser.parse_args()

    csv_path = Path(args.input)
    if not csv_path.exists():
        print(f"ERROR: File not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    print("Peer Comparison report generation is not yet implemented.")
    print(f"Input: {csv_path}")
    print(f"Period: {args.start} to {args.end}")
    print("See TODO block in this script for planned logic.")

    # Placeholder output
    date_range = f"{args.start}_to_{args.end}"
    output_dir = REPO_ROOT / "reports" / date_range
    output_dir.mkdir(parents=True, exist_ok=True)
    placeholder_path = output_dir / "peer_comparison.html"
    placeholder_path.write_text(
        "<html><body><h1>Peer Comparison — Coming Soon</h1>"
        "<p>This report type is not yet implemented.</p></body></html>",
        encoding="utf-8",
    )
    print(f"Placeholder written to: {placeholder_path}")


if __name__ == "__main__":
    main()
