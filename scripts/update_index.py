"""
WebLife Ventures — GitHub Pages Index Regenerator
==================================================
Scans /reports/ for all cycle subfolders and HTML reports,
then regenerates /docs/index.html as a clean dashboard (newest first).

Can be called standalone:
    python scripts/update_index.py

Or imported by generate_biweekly_report.py after each report generation.
"""

import re
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
REPORTS_DIR = REPO_ROOT / "reports"
DOCS_DIR = REPO_ROOT / "docs"

# Maps filename prefixes to human-readable report type labels
REPORT_TYPE_MAP = {
    "biweekly_top_violators": "Bi-Weekly Top Violators",
    "fs_report": "Friday Solutions",
    "pattern_analysis": "3-Month Pattern Analysis",
    "peer_comparison": "Role-Based Peer Comparison",
}

INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>WebLife Ventures — Performance Reports</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #f5f6f8;
      color: #1a1a2e;
      padding: 40px 24px;
    }}
    .container {{ max-width: 900px; margin: 0 auto; }}
    header {{
      border-bottom: 3px solid #2d5be3;
      padding-bottom: 20px;
      margin-bottom: 32px;
    }}
    header h1 {{
      font-size: 1.8rem;
      font-weight: 700;
      color: #1a1a2e;
    }}
    header p {{
      color: #666;
      margin-top: 6px;
      font-size: 0.9rem;
    }}
    .empty-state {{
      background: #fff;
      border: 2px dashed #d0d5dd;
      border-radius: 8px;
      padding: 48px;
      text-align: center;
      color: #888;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    }}
    thead {{ background: #2d5be3; color: #fff; }}
    thead th {{
      padding: 12px 16px;
      text-align: left;
      font-size: 0.85rem;
      font-weight: 600;
      letter-spacing: 0.03em;
    }}
    tbody tr {{ border-bottom: 1px solid #f0f0f0; }}
    tbody tr:last-child {{ border-bottom: none; }}
    tbody tr:hover {{ background: #f7f9ff; }}
    tbody td {{
      padding: 12px 16px;
      font-size: 0.9rem;
      vertical-align: middle;
    }}
    .period {{ font-weight: 600; color: #1a1a2e; }}
    .report-type {{
      display: inline-block;
      background: #eef2ff;
      color: #2d5be3;
      padding: 2px 10px;
      border-radius: 12px;
      font-size: 0.8rem;
      font-weight: 500;
    }}
    .link-cell a {{
      color: #2d5be3;
      text-decoration: none;
      font-weight: 500;
    }}
    .link-cell a:hover {{ text-decoration: underline; }}
    .generated {{ color: #888; font-size: 0.82rem; }}
    footer {{
      margin-top: 32px;
      text-align: center;
      color: #aaa;
      font-size: 0.8rem;
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>WebLife Ventures — Performance Reports</h1>
      <p>Bi-weekly Hubstaff compliance reports · Auto-generated · Internal use only</p>
    </header>

    {table_html}

    <footer>
      Index last updated: {updated_at} &nbsp;·&nbsp; WebLife Ventures
    </footer>
  </div>
</body>
</html>
"""


def discover_reports() -> list[dict]:
    """
    Scan /reports/<cycle_folder>/*.html and return a list of report dicts,
    sorted newest first.
    """
    entries = []

    if not REPORTS_DIR.exists():
        return entries

    # Match folder names like: 2026-03-01_to_2026-03-11
    folder_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})$")

    for cycle_dir in sorted(REPORTS_DIR.iterdir(), reverse=True):
        if not cycle_dir.is_dir():
            continue
        m = folder_pattern.match(cycle_dir.name)
        if not m:
            continue

        start_str, end_str = m.group(1), m.group(2)
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m-%d")
            end_dt = datetime.strptime(end_str, "%Y-%m-%d")
        except ValueError:
            continue

        period_label = (
            f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"
        )

        for html_file in sorted(cycle_dir.glob("*.html"), reverse=True):
            # Determine report type from filename
            stem = html_file.stem
            report_type = "Report"
            for key, label in REPORT_TYPE_MAP.items():
                if key in stem:
                    report_type = label
                    break

            # The docs link uses the flat filename convention
            docs_filename = f"{cycle_dir.name}_{html_file.name}"
            docs_link = docs_filename  # relative link within /docs/

            # Get file modification time as "generated at"
            mtime = html_file.stat().st_mtime
            generated_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")

            entries.append({
                "period_label": period_label,
                "start_str": start_str,
                "report_type": report_type,
                "generated_at": generated_at,
                "docs_link": docs_link,
                "filename": html_file.name,
            })

    return entries


def build_table_html(entries: list[dict]) -> str:
    if not entries:
        return (
            '<div class="empty-state">'
            "<p>No reports generated yet.</p>"
            "<p>Run the bi-weekly report script to generate the first report.</p>"
            "</div>"
        )

    rows = []
    for e in entries:
        row = (
            f'<tr>'
            f'<td class="period">{e["period_label"]}</td>'
            f'<td><span class="report-type">{e["report_type"]}</span></td>'
            f'<td class="generated">{e["generated_at"]}</td>'
            f'<td class="link-cell"><a href="{e["docs_link"]}">View Report &rarr;</a></td>'
            f'</tr>'
        )
        rows.append(row)

    rows_html = "\n      ".join(rows)
    return f"""<table>
    <thead>
      <tr>
        <th>Cycle Period</th>
        <th>Report Type</th>
        <th>Generated</th>
        <th>Link</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>"""


def regenerate_index():
    """Main entry point — discovers reports and writes docs/index.html."""
    entries = discover_reports()
    table_html = build_table_html(entries)
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = INDEX_TEMPLATE.format(
        table_html=table_html,
        updated_at=updated_at,
    )

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    index_path = DOCS_DIR / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(f"index.html updated with {len(entries)} report(s).")


if __name__ == "__main__":
    regenerate_index()
