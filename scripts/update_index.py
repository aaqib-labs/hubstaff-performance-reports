"""
WebLife Ventures — GitHub Pages Index Regenerator
==================================================
Scans /docs/ for all report HTML files and regenerates
/docs/index.html as an executive dashboard with live filtering.

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
        "label": "Bi-Weekly Top Violators",
        "short": "Bi-Weekly",
        "color": "#2563eb", "light": "#dbeafe", "text": "#1e40af",
        "icon":  "📊",
        "desc":  "SLA compliance · Top violators ranked by severity",
    },
    "fs_pattern_analysis": {
        "label": "FS Pattern Analysis",
        "short": "FS Pattern",
        "color": "#ea580c", "light": "#ffedd5", "text": "#9a3412",
        "icon":  "🔍",
        "desc":  "Friday Solutions · Repeated violation patterns",
    },
    "fs_report": {
        "label": "Friday Solutions",
        "short": "Friday Solutions",
        "color": "#d97706", "light": "#fef3c7", "text": "#92400e",
        "icon":  "⚡",
        "desc":  "TMetric data · Activity, hours, manual time",
    },
    "pattern_analysis": {
        "label": "Q1 Pattern Analysis",
        "short": "Pattern Analysis",
        "color": "#059669", "light": "#d1fae5", "text": "#065f46",
        "icon":  "📈",
        "desc":  "3-month trends · Persistent & recurring violations",
    },
    "peer_comparison": {
        "label": "Peer Comparison",
        "short": "Peer Comparison",
        "color": "#7c3aed", "light": "#ede9fe", "text": "#4c1d95",
        "icon":  "👥",
        "desc":  "Role-based benchmarking · Team averages & outliers",
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
        cfg = DEFAULT_CONFIG.copy()
        type_key = "report"
        for key, config in REPORT_TYPE_CONFIG.items():
            if key in type_stem:
                cfg = config
                type_key = key
                break
        mtime        = html_file.stat().st_mtime
        generated_at = datetime.fromtimestamp(mtime).strftime("%b %d, %Y at %H:%M")
        entries.append({
            "period_label": period_label,
            "start_str":    start_str,
            "end_str":      end_str,
            "type_key":     type_key,
            "cfg":          cfg,
            "generated_at": generated_at,
            "docs_link":    html_file.name,
        })
    return entries


def build_html(entries: list[dict], updated_at: str) -> str:
    total = len(entries)

    # Hero stat chips
    by_type: dict[str, int] = {}
    for e in entries:
        s = e["cfg"]["short"]
        by_type[s] = by_type.get(s, 0) + 1

    chips = f'<div class="stat-chip"><span class="sc-num">{total}</span><span class="sc-lbl">Total Reports</span></div>'
    for lbl, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
        chips += f'<div class="stat-chip"><span class="sc-num">{cnt}</span><span class="sc-lbl">{lbl}</span></div>'

    # Filter type pills
    type_keys_seen: list[tuple] = []
    seen_keys: set = set()
    for e in entries:
        k = e["type_key"]
        if k not in seen_keys:
            seen_keys.add(k)
            type_keys_seen.append((k, e["cfg"]["short"], e["cfg"]["color"], e["cfg"]["light"], e["cfg"]["text"]))

    type_pills = '<button class="type-pill active" data-type="all" onclick="filterType(this,\'all\')">All Reports</button>'
    for key, short, color, light, text in type_keys_seen:
        type_pills += (
            f'<button class="type-pill" data-type="{key}" onclick="filterType(this,\'{key}\')" '
            f'style="--pill-color:{color};--pill-light:{light};--pill-text:{text};">'
            f'{short}</button>'
        )

    # Date range bounds
    all_starts = [e["start_str"] for e in entries]
    all_ends   = [e["end_str"]   for e in entries]
    min_date   = min(all_starts) if all_starts else ""
    max_date   = max(all_ends)   if all_ends   else ""

    # Cards
    if not entries:
        cards_html = '<div class="empty">No reports generated yet.</div>'
    else:
        cards_html = '<div class="grid" id="cards-grid">'
        for e in entries:
            cfg = e["cfg"]
            cards_html += f"""
            <a class="card" href="{e['docs_link']}"
               data-type="{e['type_key']}"
               data-start="{e['start_str']}"
               data-end="{e['end_str']}">
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
        cards_html += '</div>'
        cards_html += '<div class="no-results" id="no-results" style="display:none;">No reports match your filters. <button onclick="clearFilters()">Clear filters</button></div>'

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
      background: #f0f4f8; color: #1a202c;
      min-height: 100vh; font-size: 15px;
    }}

    /* Nav */
    .nav {{
      background: #0f172a; padding: 0 40px; height: 52px;
      display: flex; align-items: center; justify-content: space-between;
      position: sticky; top: 0; z-index: 100;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }}
    .nav-brand {{ font-size: 0.82rem; font-weight: 700; color: rgba(255,255,255,0.75); }}
    .nav-badge {{
      font-size: 0.7rem; font-weight: 700; color: rgba(255,255,255,0.4);
      background: rgba(255,255,255,0.07); padding: 3px 10px; border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.1); letter-spacing: 0.06em; text-transform: uppercase;
    }}

    /* Hero */
    .hero {{
      background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #1d4ed8 100%);
      padding: 52px 40px 56px; position: relative; overflow: hidden;
    }}
    .hero::before {{
      content: ''; position: absolute; inset: 0;
      background: radial-gradient(ellipse at 80% 50%, rgba(99,102,241,0.18) 0%, transparent 65%);
    }}
    .hero::after {{
      content: ''; position: absolute; top: -80px; right: -80px;
      width: 400px; height: 400px; border-radius: 50%; background: rgba(255,255,255,0.03);
    }}
    .hero-inner {{ max-width: 1200px; margin: 0 auto; position: relative; }}
    .hero-eyebrow {{
      font-size: 0.72rem; font-weight: 700; letter-spacing: 0.16em;
      text-transform: uppercase; color: rgba(255,255,255,0.4); margin-bottom: 14px;
    }}
    .hero-title {{
      font-size: 2.6rem; font-weight: 800; color: #fff;
      line-height: 1.1; letter-spacing: -0.04em; margin-bottom: 10px;
    }}
    .hero-sub {{
      font-size: 0.9rem; color: rgba(255,255,255,0.5); margin-bottom: 40px;
    }}
    .stat-chips {{ display: flex; flex-wrap: wrap; gap: 12px; }}
    .stat-chip {{
      background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.14);
      border-radius: 12px; padding: 14px 22px;
      display: flex; flex-direction: column; gap: 3px; min-width: 110px;
    }}
    .sc-num {{ font-size: 1.7rem; font-weight: 800; color: #fff; line-height: 1; letter-spacing: -0.03em; }}
    .sc-lbl {{ font-size: 0.7rem; font-weight: 600; color: rgba(255,255,255,0.5); text-transform: uppercase; letter-spacing: 0.07em; }}

    /* Filter bar */
    .filter-bar {{
      background: #fff; border-bottom: 1px solid #e5e7eb;
      position: sticky; top: 52px; z-index: 90;
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }}
    .filter-inner {{
      max-width: 1200px; margin: 0 auto;
      padding: 14px 40px;
      display: flex; align-items: center; flex-wrap: wrap; gap: 16px;
    }}
    .filter-group {{
      display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    }}
    .filter-label {{
      font-size: 0.75rem; font-weight: 700; color: #9ca3af;
      text-transform: uppercase; letter-spacing: 0.07em; white-space: nowrap;
    }}
    .type-pill {{
      padding: 6px 14px; border-radius: 999px; border: 1.5px solid #e5e7eb;
      background: #fff; font-size: 0.8rem; font-weight: 600;
      color: #6b7280; cursor: pointer; font-family: inherit;
      transition: all 0.15s; white-space: nowrap;
    }}
    .type-pill:hover {{ border-color: #9ca3af; color: #374151; }}
    .type-pill.active {{
      background: var(--pill-color, #1a202c);
      border-color: var(--pill-color, #1a202c);
      color: #fff;
    }}
    .type-pill[data-type="all"].active {{ background: #1a202c; border-color: #1a202c; color: #fff; }}

    /* Date range */
    .date-group {{
      display: flex; align-items: center; gap: 8px;
      margin-left: auto;
    }}
    .date-input {{
      padding: 6px 12px; border-radius: 8px;
      border: 1.5px solid #e5e7eb; font-size: 0.8rem;
      font-family: inherit; color: #374151;
      background: #f9fafb; cursor: pointer;
      transition: border-color 0.15s;
    }}
    .date-input:focus {{ outline: none; border-color: #2563eb; background: #fff; }}
    .date-sep {{ font-size: 0.78rem; color: #9ca3af; }}
    .clear-btn {{
      padding: 6px 14px; border-radius: 8px;
      border: 1.5px solid #fecaca; background: #fff5f5;
      font-size: 0.78rem; font-weight: 700; color: #dc2626;
      cursor: pointer; font-family: inherit;
      transition: all 0.15s; display: none;
    }}
    .clear-btn:hover {{ background: #fee2e2; }}
    .clear-btn.visible {{ display: inline-flex; align-items: center; gap: 5px; }}

    /* Results summary */
    .content {{ max-width: 1200px; margin: 0 auto; padding: 32px 40px 72px; }}
    .content-header {{
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 20px;
    }}
    .results-count {{ font-size: 0.82rem; color: #6b7280; font-weight: 500; }}
    .results-count strong {{ color: #1a202c; }}
    .content-updated {{ font-size: 0.76rem; color: #9ca3af; }}

    /* Cards */
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 20px;
    }}
    .card {{
      background: #fff; border-radius: 14px; border: 1px solid #e5e7eb;
      overflow: hidden;
      box-shadow: 0 1px 4px rgba(0,0,0,0.05), 0 4px 16px rgba(0,0,0,0.04);
      text-decoration: none; color: inherit;
      display: flex; flex-direction: column;
      transition: transform 0.18s, box-shadow 0.18s, opacity 0.2s;
    }}
    .card:hover {{
      transform: translateY(-3px);
      box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 12px 36px rgba(0,0,0,0.08);
    }}
    .card.hidden {{ display: none; }}
    .card-stripe {{ height: 5px; flex-shrink: 0; }}
    .card-inner {{ padding: 22px 22px 18px; display: flex; flex-direction: column; gap: 14px; flex: 1; }}
    .card-head {{ display: flex; align-items: center; justify-content: space-between; }}
    .badge {{
      display: inline-flex; align-items: center; gap: 5px;
      padding: 5px 12px; border-radius: 999px;
      font-size: 0.76rem; font-weight: 700; white-space: nowrap;
    }}
    .card-arrow {{ font-size: 1.1rem; color: #d1d5db; transition: transform 0.18s, color 0.18s; }}
    .card:hover .card-arrow {{ transform: translateX(4px); color: #6b7280; }}
    .card-period {{ font-size: 1.25rem; font-weight: 800; color: #111827; letter-spacing: -0.02em; }}
    .card-desc {{ font-size: 0.8rem; color: #9ca3af; line-height: 1.5; }}
    .card-footer {{
      display: flex; align-items: center; justify-content: space-between;
      padding-top: 14px; margin-top: auto; border-top: 1px solid #f3f4f6;
    }}
    .card-date {{ font-size: 0.76rem; color: #9ca3af; }}
    .card-cta {{ font-size: 0.82rem; font-weight: 700; }}

    /* No results */
    .no-results {{
      text-align: center; padding: 48px 24px;
      background: #fff; border-radius: 14px;
      border: 2px dashed #e5e7eb; color: #9ca3af;
    }}
    .no-results button {{
      margin-top: 12px; padding: 8px 18px;
      background: #1a202c; color: #fff; border: none;
      border-radius: 8px; font-size: 0.82rem; font-weight: 600;
      cursor: pointer; font-family: inherit;
    }}

    .empty {{
      background: #fff; border: 2px dashed #e5e7eb; border-radius: 14px;
      padding: 64px; text-align: center; color: #9ca3af; font-size: 0.9rem;
    }}
    footer {{
      text-align: center; padding: 24px; font-size: 0.76rem;
      color: #9ca3af; border-top: 1px solid #e5e7eb; background: #fff;
    }}

    @media (max-width: 768px) {{
      .nav, .filter-inner, .hero, .content {{ padding-left: 20px; padding-right: 20px; }}
      .hero-title {{ font-size: 1.8rem; }}
      .grid {{ grid-template-columns: 1fr; }}
      .date-group {{ margin-left: 0; }}
      .filter-inner {{ flex-direction: column; align-items: flex-start; gap: 12px; }}
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
      <p class="hero-sub">Hubstaff compliance &nbsp;·&nbsp; Auto-generated &nbsp;·&nbsp; Executive review</p>
      <div class="stat-chips">{chips}</div>
    </div>
  </div>

  <!-- Filter bar -->
  <div class="filter-bar">
    <div class="filter-inner">
      <div class="filter-group">
        <span class="filter-label">Type</span>
        {type_pills}
      </div>
      <div class="date-group">
        <span class="filter-label">From</span>
        <input type="date" class="date-input" id="date-from" min="{min_date}" max="{max_date}" onchange="applyFilters()">
        <span class="date-sep">—</span>
        <span class="filter-label">To</span>
        <input type="date" class="date-input" id="date-to" min="{min_date}" max="{max_date}" onchange="applyFilters()">
        <button class="clear-btn" id="clear-btn" onclick="clearFilters()">✕ Clear</button>
      </div>
    </div>
  </div>

  <div class="content">
    <div class="content-header">
      <span class="results-count" id="results-count"><strong>{total}</strong> report{('s' if total != 1 else '')} found</span>
      <span class="content-updated">Updated {updated_at}</span>
    </div>
    {cards_html}
  </div>

  <footer>WebLife Ventures Performance Reporting System &nbsp;·&nbsp; {updated_at}</footer>

  <script>
    let activeType = 'all';

    function filterType(btn, type) {{
      activeType = type;
      document.querySelectorAll('.type-pill').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      applyFilters();
    }}

    function applyFilters() {{
      const from     = document.getElementById('date-from').value;
      const to       = document.getElementById('date-to').value;
      const clearBtn = document.getElementById('clear-btn');
      const cards    = document.querySelectorAll('.card');
      let visible    = 0;

      const hasFilter = activeType !== 'all' || from || to;
      clearBtn.classList.toggle('visible', hasFilter);

      cards.forEach(card => {{
        const typeMatch = activeType === 'all' || card.dataset.type === activeType;
        const start     = card.dataset.start;
        const end       = card.dataset.end;
        const fromMatch = !from || start >= from;
        const toMatch   = !to   || end   <= to;

        if (typeMatch && fromMatch && toMatch) {{
          card.classList.remove('hidden');
          visible++;
        }} else {{
          card.classList.add('hidden');
        }}
      }});

      const noun = visible === 1 ? 'report' : 'reports';
      document.getElementById('results-count').innerHTML =
        `<strong>${{visible}}</strong> ${{noun}} found`;

      const noResults = document.getElementById('no-results');
      if (noResults) noResults.style.display = visible === 0 ? 'block' : 'none';
    }}

    function clearFilters() {{
      activeType = 'all';
      document.getElementById('date-from').value = '';
      document.getElementById('date-to').value   = '';
      document.querySelectorAll('.type-pill').forEach((p, i) => {{
        p.classList.toggle('active', i === 0);
      }});
      applyFilters();
    }}
  </script>

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
