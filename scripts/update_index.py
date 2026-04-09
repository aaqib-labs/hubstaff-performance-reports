"""
WebLife Ventures — GitHub Pages Index Regenerator
==================================================
Scans /docs/ for all report HTML files and regenerates
/docs/index.html as a card-based dashboard (newest first).

Can be called standalone:
    python scripts/update_index.py

Or imported by any report generation script after each run.
"""

import re
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR  = REPO_ROOT / "docs"

# Report type config: label, accent colour, icon
REPORT_TYPE_CONFIG = {
    "biweekly_top_violators": {
        "label": "Bi-Weekly Top Violators",
        "color": "#1d4ed8",
        "bg":    "#eff6ff",
        "icon":  "📊",
    },
    "fs_report": {
        "label": "Friday Solutions",
        "color": "#d97706",
        "bg":    "#fffbeb",
        "icon":  "⚡",
    },
    "fs_pattern_analysis": {
        "label": "FS Pattern Analysis",
        "color": "#ea580c",
        "bg":    "#fff7ed",
        "icon":  "🔍",
    },
    "pattern_analysis": {
        "label": "Q1 Pattern Analysis",
        "color": "#16a34a",
        "bg":    "#f0fdf4",
        "icon":  "📈",
    },
    "peer_comparison": {
        "label": "Peer Comparison",
        "color": "#7c3aed",
        "bg":    "#f5f3ff",
        "icon":  "👥",
    },
}

DEFAULT_CONFIG = {
    "label": "Report",
    "color": "#6b7280",
    "bg":    "#f9fafb",
    "icon":  "📄",
}

INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>WebLife Ventures — Performance Reports</title>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600;9..40,700;9..40,800&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background: #f7fafc;
      color: #1a202c;
      font-size: 15px;
      line-height: 1.6;
      min-height: 100vh;
    }}

    /* ---- Hero ---- */
    .hero {{
      background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 60%, #1d4ed8 100%);
      padding: 48px 40px 44px;
      position: relative; overflow: hidden;
    }}
    .hero::after {{
      content: ''; position: absolute; top: -60px; right: -60px;
      width: 340px; height: 340px; border-radius: 50%;
      background: rgba(255,255,255,0.04); pointer-events: none;
    }}
    .hero::before {{
      content: ''; position: absolute; bottom: -80px; right: 160px;
      width: 220px; height: 220px; border-radius: 50%;
      background: rgba(255,255,255,0.03); pointer-events: none;
    }}
    .hero-inner {{ max-width: 1200px; margin: 0 auto; }}
    .hero-brand {{
      font-size: 0.72rem; font-weight: 700; letter-spacing: 0.14em;
      text-transform: uppercase; color: rgba(255,255,255,0.45); margin-bottom: 10px;
    }}
    .hero h1 {{
      font-size: 2.2rem; font-weight: 800; color: #fff;
      line-height: 1.15; letter-spacing: -0.03em; margin-bottom: 10px;
    }}
    .hero-sub {{
      font-size: 0.9rem; color: rgba(255,255,255,0.55); font-weight: 400;
    }}

    /* ---- Stats bar ---- */
    .stats-bar {{
      background: #fff;
      border-bottom: 1px solid #e2e8f0;
      padding: 0;
    }}
    .stats-inner {{
      max-width: 1200px; margin: 0 auto;
      display: flex; flex-wrap: wrap;
    }}
    .stat-item {{
      padding: 18px 32px;
      border-right: 1px solid #e2e8f0;
      display: flex; flex-direction: column; gap: 2px;
      min-width: 160px;
    }}
    .stat-item:last-child {{ border-right: none; }}
    .stat-num {{
      font-size: 1.6rem; font-weight: 800;
      line-height: 1; letter-spacing: -0.03em; color: #1a202c;
    }}
    .stat-lbl {{
      font-size: 0.74rem; font-weight: 600; color: #9ca3af;
      text-transform: uppercase; letter-spacing: 0.06em;
    }}

    /* ---- Content ---- */
    .content {{
      max-width: 1200px; margin: 0 auto;
      padding: 36px 40px 60px;
    }}
    .section-title {{
      font-size: 0.74rem; font-weight: 700; color: #9ca3af;
      text-transform: uppercase; letter-spacing: 0.09em;
      margin-bottom: 16px;
    }}

    /* ---- Cards grid ---- */
    .cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
      gap: 16px;
    }}

    .report-card {{
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
      transition: box-shadow 0.15s, transform 0.15s;
      display: flex; flex-direction: column;
      text-decoration: none; color: inherit;
    }}
    .report-card:hover {{
      box-shadow: 0 8px 24px rgba(0,0,0,0.10);
      transform: translateY(-2px);
    }}
    .card-accent {{
      height: 4px;
      border-radius: 12px 12px 0 0;
    }}
    .card-body {{
      padding: 20px 22px;
      flex: 1; display: flex; flex-direction: column; gap: 12px;
    }}
    .card-top {{
      display: flex; align-items: flex-start;
      justify-content: space-between; gap: 12px;
    }}
    .type-badge {{
      display: inline-flex; align-items: center; gap: 6px;
      padding: 4px 12px; border-radius: 999px;
      font-size: 0.76rem; font-weight: 700;
      white-space: nowrap;
    }}
    .card-icon {{
      font-size: 1.4rem; flex-shrink: 0; margin-top: 2px;
    }}
    .card-period {{
      font-size: 1.15rem; font-weight: 800;
      color: #1a202c; letter-spacing: -0.01em;
      line-height: 1.3;
    }}
    .card-meta {{
      display: flex; align-items: center; gap: 8px;
      font-size: 0.78rem; color: #9ca3af;
    }}
    .card-dot {{ color: #d1d5db; }}
    .card-footer {{
      padding: 14px 22px;
      background: #f8fafc;
      border-top: 1px solid #edf2f7;
      display: flex; align-items: center; justify-content: space-between;
    }}
    .view-btn {{
      display: inline-flex; align-items: center; gap: 6px;
      font-size: 0.84rem; font-weight: 700;
      color: #1d4ed8;
      text-decoration: none;
    }}
    .view-btn:hover {{ text-decoration: underline; }}
    .view-arrow {{
      font-size: 1rem; transition: transform 0.15s;
    }}
    .report-card:hover .view-arrow {{ transform: translateX(3px); }}

    /* ---- Empty state ---- */
    .empty-state {{
      background: #fff; border: 2px dashed #e2e8f0;
      border-radius: 12px; padding: 60px; text-align: center;
      color: #9ca3af; font-size: 0.9rem;
    }}

    /* ---- Footer ---- */
    footer {{
      text-align: center; padding: 28px;
      font-size: 0.78rem; color: #9ca3af;
      border-top: 1px solid #e2e8f0;
    }}

    @media (max-width: 768px) {{
      .hero {{ padding: 32px 20px; }}
      .hero h1 {{ font-size: 1.6rem; }}
      .content {{ padding: 24px 16px 48px; }}
      .cards-grid {{ grid-template-columns: 1fr; }}
      .stat-item {{ min-width: 120px; padding: 14px 20px; }}
    }}
  </style>
</head>
<body>

  <div class="hero">
    <div class="hero-inner">
      <div class="hero-brand">WebLife Ventures &nbsp;·&nbsp; Internal Use Only</div>
      <h1>Performance Reports</h1>
      <p class="hero-sub">Hubstaff compliance reports &nbsp;·&nbsp; Auto-generated &nbsp;·&nbsp; Executive review</p>
    </div>
  </div>

  <div class="stats-bar">
    <div class="stats-inner">
      {stats_html}
    </div>
  </div>

  <div class="content">
    <div class="section-title">All Reports — Newest First</div>
    {cards_html}
  </div>

  <footer>
    Index last updated: {updated_at} &nbsp;·&nbsp; WebLife Ventures
  </footer>

</body>
</html>
"""


def discover_reports() -> list[dict]:
    """Scan /docs/ for report HTML files, return sorted newest first."""
    entries = []
    if not DOCS_DIR.exists():
        return entries

    file_pattern = re.compile(r"^(\d{{4}}-\d{{2}}-\d{{2}})_to_(\d{{4}}-\d{{2}}-\d{{2}})_(.+)\.html$")
    file_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})_(.+)\.html$")

    for html_file in sorted(DOCS_DIR.glob("*.html"), reverse=True):
        if html_file.name == "index.html":
            continue
        m = file_pattern.match(html_file.name)
        if not m:
            continue

        start_str, end_str, type_stem = m.group(1), m.group(2), m.group(3)
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m-%d")
            end_dt   = datetime.strptime(end_str,   "%Y-%m-%d")
        except ValueError:
            continue

        period_label = f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"

        cfg = DEFAULT_CONFIG
        for key, config in REPORT_TYPE_CONFIG.items():
            if key in type_stem:
                cfg = config
                break

        mtime        = html_file.stat().st_mtime
        generated_at = datetime.fromtimestamp(mtime).strftime("%b %d, %Y · %H:%M")

        entries.append({
            "period_label": period_label,
            "start_str":    start_str,
            "type_label":   cfg["label"],
            "type_color":   cfg["color"],
            "type_bg":      cfg["bg"],
            "icon":         cfg["icon"],
            "generated_at": generated_at,
            "docs_link":    html_file.name,
        })

    return entries


def build_stats_html(entries: list[dict]) -> str:
    total = len(entries)
    by_type: dict[str, int] = {}
    for e in entries:
        by_type[e["type_label"]] = by_type.get(e["type_label"], 0) + 1

    items = [f'<div class="stat-item"><div class="stat-num">{total}</div><div class="stat-lbl">Total Reports</div></div>']
    for label, count in sorted(by_type.items(), key=lambda x: -x[1]):
        items.append(
            f'<div class="stat-item"><div class="stat-num">{count}</div>'
            f'<div class="stat-lbl">{label}</div></div>'
        )
    return "\n".join(items)


def build_cards_html(entries: list[dict]) -> str:
    if not entries:
        return (
            '<div class="empty-state">'
            '<p>No reports generated yet.</p>'
            '<p style="margin-top:8px;">Run a report script to generate the first report.</p>'
            '</div>'
        )

    cards = []
    for e in entries:
        card = f"""
        <a class="report-card" href="{e['docs_link']}">
          <div class="card-accent" style="background:{e['type_color']};"></div>
          <div class="card-body">
            <div class="card-top">
              <div>
                <span class="type-badge" style="background:{e['type_bg']};color:{e['type_color']};">
                  {e['icon']} {e['type_label']}
                </span>
              </div>
            </div>
            <div class="card-period">{e['period_label']}</div>
            <div class="card-meta">
              <span>Generated</span>
              <span class="card-dot">·</span>
              <span>{e['generated_at']}</span>
            </div>
          </div>
          <div class="card-footer">
            <span class="view-btn">
              View Report <span class="view-arrow">→</span>
            </span>
          </div>
        </a>"""
        cards.append(card)

    return f'<div class="cards-grid">{"".join(cards)}</div>'


def regenerate_index():
    """Main entry point — discovers reports and writes docs/index.html."""
    entries     = discover_reports()
    stats_html  = build_stats_html(entries)
    cards_html  = build_cards_html(entries)
    updated_at  = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = INDEX_TEMPLATE.format(
        stats_html=stats_html,
        cards_html=cards_html,
        updated_at=updated_at,
    )

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    index_path = DOCS_DIR / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(f"index.html updated with {len(entries)} report(s).")


if __name__ == "__main__":
    regenerate_index()
