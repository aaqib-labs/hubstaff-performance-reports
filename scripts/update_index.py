"""
WebLife Ventures — GitHub Pages Index Regenerator
==================================================
Scans /docs/ for all report HTML files and regenerates
/docs/index.html as an executive dashboard.

Can be called standalone:
    python scripts/update_index.py

Or imported by any report generation script after each run.
"""

import re
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR  = REPO_ROOT / "docs"

REPORT_TYPE_CONFIG = {
    "biweekly_top_violators": {
        "label":    "Bi-Weekly Top Violators",
        "short":    "Bi-Weekly",
        "color":    "#2563eb",
        "light":    "#dbeafe",
        "text":     "#1e40af",
        "icon":     "📊",
        "desc":     "SLA compliance · Top violators ranked by severity",
    },
    "fs_pattern_analysis": {
        "label":    "FS Pattern Analysis",
        "short":    "FS Pattern",
        "color":    "#ea580c",
        "light":    "#ffedd5",
        "text":     "#9a3412",
        "icon":     "🔍",
        "desc":     "Friday Solutions · Repeated violation patterns",
    },
    "fs_report": {
        "label":    "Friday Solutions",
        "short":    "Friday Solutions",
        "color":    "#d97706",
        "light":    "#fef3c7",
        "text":     "#92400e",
        "icon":     "⚡",
        "desc":     "TMetric data · Activity, hours, manual time",
    },
    "pattern_analysis": {
        "label":    "Q1 Pattern Analysis",
        "short":    "Pattern Analysis",
        "color":    "#059669",
        "light":    "#d1fae5",
        "text":     "#065f46",
        "icon":     "📈",
        "desc":     "3-month trends · Persistent & recurring violations",
    },
    "peer_comparison": {
        "label":    "Peer Comparison",
        "short":    "Peer Comparison",
        "color":    "#7c3aed",
        "light":    "#ede9fe",
        "text":     "#4c1d95",
        "icon":     "👥",
        "desc":     "Role-based benchmarking · Team averages & outliers",
    },
}

DEFAULT_CONFIG = {
    "label": "Report", "short": "Report",
    "color": "#6b7280", "light": "#f3f4f6", "text": "#374151",
    "icon": "📄", "desc": "",
}


def discover_reports() -> list[dict]:
    entries = []
    if not DOCS_DIR.exists():
        return entries
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
        generated_at = datetime.fromtimestamp(mtime).strftime("%b %d, %Y at %H:%M")
        entries.append({
            "period_label": period_label,
            "start_str":    start_str,
            "cfg":          cfg,
            "generated_at": generated_at,
            "docs_link":    html_file.name,
        })
    return entries


def build_html(entries: list[dict], updated_at: str) -> str:
    total = len(entries)
    by_type: dict[str, int] = {}
    for e in entries:
        lbl = e["cfg"]["short"]
        by_type[lbl] = by_type.get(lbl, 0) + 1

    # --- Hero stat chips ---
    chips = f'<div class="stat-chip"><span class="sc-num">{total}</span><span class="sc-lbl">Total Reports</span></div>'
    for lbl, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
        chips += f'<div class="stat-chip"><span class="sc-num">{cnt}</span><span class="sc-lbl">{lbl}</span></div>'

    # --- Report cards ---
    if not entries:
        cards = '<div class="empty">No reports generated yet. Run a report script to get started.</div>'
    else:
        cards = '<div class="grid">'
        for e in entries:
            cfg = e["cfg"]
            cards += f"""
            <a class="card" href="{e['docs_link']}">
              <div class="card-stripe" style="background:{cfg['color']};"></div>
              <div class="card-inner">
                <div class="card-head">
                  <span class="badge" style="background:{cfg['light']};color:{cfg['text']};">
                    {cfg['icon']}&nbsp; {cfg['label']}
                  </span>
                  <span class="card-arrow">→</span>
                </div>
                <div class="card-period">{e['period_label']}</div>
                <div class="card-desc">{cfg['desc']}</div>
                <div class="card-footer">
                  <span class="card-date">🕐 {e['generated_at']}</span>
                  <span class="card-cta" style="color:{cfg['color']};">View Report</span>
                </div>
              </div>
            </a>"""
        cards += '</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>WebLife Ventures — Performance Reports</title>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600;9..40,700;9..40,800&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'DM Sans', -apple-system, sans-serif;
      background: #f0f4f8;
      color: #1a202c;
      min-height: 100vh;
    }}

    /* ── Top nav ─────────────────────────────── */
    .nav {{
      background: #0f172a;
      padding: 0 40px;
      height: 52px;
      display: flex; align-items: center; justify-content: space-between;
      position: sticky; top: 0; z-index: 100;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }}
    .nav-brand {{
      font-size: 0.82rem; font-weight: 700;
      color: rgba(255,255,255,0.75); letter-spacing: 0.02em;
    }}
    .nav-badge {{
      font-size: 0.7rem; font-weight: 700;
      color: rgba(255,255,255,0.4);
      background: rgba(255,255,255,0.07);
      padding: 3px 10px; border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.1);
      letter-spacing: 0.06em; text-transform: uppercase;
    }}

    /* ── Hero ────────────────────────────────── */
    .hero {{
      background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #1d4ed8 100%);
      padding: 56px 40px 60px;
      position: relative; overflow: hidden;
    }}
    .hero::before {{
      content: '';
      position: absolute; inset: 0;
      background: radial-gradient(ellipse at 80% 50%, rgba(99,102,241,0.18) 0%, transparent 65%);
    }}
    .hero::after {{
      content: '';
      position: absolute; top: -80px; right: -80px;
      width: 400px; height: 400px; border-radius: 50%;
      background: rgba(255,255,255,0.03);
    }}
    .hero-inner {{ max-width: 1200px; margin: 0 auto; position: relative; }}
    .hero-eyebrow {{
      font-size: 0.72rem; font-weight: 700; letter-spacing: 0.16em;
      text-transform: uppercase; color: rgba(255,255,255,0.4);
      margin-bottom: 14px;
    }}
    .hero-title {{
      font-size: 2.6rem; font-weight: 800; color: #fff;
      line-height: 1.1; letter-spacing: -0.04em;
      margin-bottom: 10px;
    }}
    .hero-sub {{
      font-size: 0.94rem; color: rgba(255,255,255,0.5);
      margin-bottom: 44px; font-weight: 400;
    }}
    .stat-chips {{
      display: flex; flex-wrap: wrap; gap: 12px;
    }}
    .stat-chip {{
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.14);
      backdrop-filter: blur(8px);
      border-radius: 12px; padding: 14px 22px;
      display: flex; flex-direction: column; gap: 3px;
      min-width: 120px;
    }}
    .sc-num {{
      font-size: 1.7rem; font-weight: 800;
      color: #fff; line-height: 1; letter-spacing: -0.03em;
    }}
    .sc-lbl {{
      font-size: 0.72rem; font-weight: 600;
      color: rgba(255,255,255,0.5);
      text-transform: uppercase; letter-spacing: 0.07em;
    }}

    /* ── Content ─────────────────────────────── */
    .content {{
      max-width: 1200px; margin: 0 auto;
      padding: 40px 40px 72px;
    }}
    .content-header {{
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 24px;
    }}
    .content-title {{
      font-size: 1rem; font-weight: 700; color: #1a202c;
    }}
    .content-updated {{
      font-size: 0.78rem; color: #9ca3af;
    }}

    /* ── Cards grid ──────────────────────────── */
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 20px;
    }}

    .card {{
      background: #fff;
      border-radius: 14px;
      border: 1px solid #e5e7eb;
      overflow: hidden;
      box-shadow: 0 1px 4px rgba(0,0,0,0.05), 0 4px 16px rgba(0,0,0,0.04);
      text-decoration: none; color: inherit;
      display: flex; flex-direction: column;
      transition: transform 0.18s ease, box-shadow 0.18s ease;
    }}
    .card:hover {{
      transform: translateY(-3px);
      box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 12px 36px rgba(0,0,0,0.08);
    }}
    .card-stripe {{
      height: 5px; flex-shrink: 0;
    }}
    .card-inner {{
      padding: 22px 22px 18px;
      display: flex; flex-direction: column; gap: 14px; flex: 1;
    }}
    .card-head {{
      display: flex; align-items: center; justify-content: space-between;
    }}
    .badge {{
      display: inline-flex; align-items: center; gap: 5px;
      padding: 5px 12px; border-radius: 999px;
      font-size: 0.76rem; font-weight: 700;
      white-space: nowrap;
    }}
    .card-arrow {{
      font-size: 1.1rem; color: #d1d5db;
      transition: transform 0.18s, color 0.18s;
    }}
    .card:hover .card-arrow {{
      transform: translateX(4px); color: #6b7280;
    }}
    .card-period {{
      font-size: 1.25rem; font-weight: 800;
      color: #111827; line-height: 1.2; letter-spacing: -0.02em;
    }}
    .card-desc {{
      font-size: 0.8rem; color: #9ca3af;
      line-height: 1.5;
    }}
    .card-footer {{
      display: flex; align-items: center; justify-content: space-between;
      padding-top: 14px; margin-top: auto;
      border-top: 1px solid #f3f4f6;
    }}
    .card-date {{ font-size: 0.76rem; color: #9ca3af; }}
    .card-cta {{
      font-size: 0.82rem; font-weight: 700;
    }}

    /* ── Empty ───────────────────────────────── */
    .empty {{
      background: #fff; border: 2px dashed #e5e7eb;
      border-radius: 14px; padding: 64px;
      text-align: center; color: #9ca3af; font-size: 0.9rem;
    }}

    /* ── Footer ──────────────────────────────── */
    footer {{
      text-align: center; padding: 24px;
      font-size: 0.76rem; color: #9ca3af;
      border-top: 1px solid #e5e7eb;
      background: #fff;
    }}

    @media (max-width: 768px) {{
      .nav {{ padding: 0 20px; }}
      .hero {{ padding: 40px 20px 48px; }}
      .hero-title {{ font-size: 1.8rem; }}
      .content {{ padding: 28px 20px 48px; }}
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>

  <nav class="nav">
    <span class="nav-brand">WebLife Ventures &nbsp;·&nbsp; Performance Reports</span>
    <span class="nav-badge">Internal Use Only</span>
  </nav>

  <div class="hero">
    <div class="hero-inner">
      <div class="hero-eyebrow">WebLife Ventures &nbsp;·&nbsp; Workforce Intelligence</div>
      <h1 class="hero-title">Performance<br>Reports</h1>
      <p class="hero-sub">Hubstaff compliance · Auto-generated · Executive review</p>
      <div class="stat-chips">
        {chips}
      </div>
    </div>
  </div>

  <div class="content">
    <div class="content-header">
      <span class="content-title">All Reports — Newest First</span>
      <span class="content-updated">Updated {updated_at}</span>
    </div>
    {cards}
  </div>

  <footer>WebLife Ventures Performance Reporting System &nbsp;·&nbsp; {updated_at}</footer>

</body>
</html>"""


def regenerate_index():
    entries    = discover_reports()
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html       = build_html(entries, updated_at)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"index.html updated with {len(entries)} report(s).")


if __name__ == "__main__":
    regenerate_index()
