"""
fetch_jobs.py — Government Jobs Auto-poster
Fetches RSS feeds, deduplicates, optionally generates AI descriptions,
and writes a fully static index.html to docs/
"""

import feedparser
import json
import os
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SITE_TITLE = "SarkariNaukri.live"
SITE_TAGLINE = "Latest Government Jobs — Updated Every 6 Hours"

# Add / remove feeds freely. 'label' shows as a tag on the card.
FEEDS = [
    {
        "url": "https://www.sarkariresult.com/feed/",
        "label": "Sarkari Result",
        "color": "blue",
    },
    {
        "url": "https://www.naukri.com/rss/jobs/government-jobs",
        "label": "Naukri Govt",
        "color": "green",
    },
    {
        "url": "https://www.freejobalert.com/feed/",
        "label": "FreeJobAlert",
        "color": "orange",
    },
    {
        "url": "https://sarkariresults.io/feed/",
        "label": "Sarkari Results",
        "color": "purple",
    },
    # ─── Add more feeds below ─────────────────────────────────────────────
    # {"url": "YOUR_RSS_URL", "label": "Source Name", "color": "red"},
]

MAX_JOBS_PER_FEED = 25      # max entries to pull per feed
MAX_TOTAL_JOBS    = 120     # cap on total cards shown
USE_GEMINI        = False   # set True + add GEMINI_KEY secret to enable AI descriptions

# ─── OPTIONAL: GEMINI AI DESCRIPTIONS ────────────────────────────────────────

def gemini_describe(title: str) -> str:
    """Generate a short SEO description using Gemini Flash (free tier)."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_KEY"])
        model = genai.GenerativeModel("gemini-1.5-flash")
        result = model.generate_content(
            f"Write a 1-sentence plain-English description (max 120 chars) "
            f"for this Indian government job notification: '{title}'. "
            f"No emojis. No markdown."
        )
        return result.text.strip()[:150]
    except Exception as e:
        print(f"[Gemini] Skipped — {e}")
        return ""

# ─── FETCH ───────────────────────────────────────────────────────────────────

def clean_html(raw: str) -> str:
    """Strip HTML tags from summary text."""
    return re.sub(r"<[^>]+>", " ", raw or "").strip()[:220]

def fingerprint(title: str) -> str:
    """Simple dedup key — lowercase, strip numbers and common words."""
    s = re.sub(r"\d+", "", title.lower())
    s = re.sub(r"\b(recruitment|notification|vacancy|post|for|the|of|in)\b", "", s)
    return hashlib.md5(s.encode()).hexdigest()[:12]

def fetch_all_feeds() -> list[dict]:
    seen_fps = set()
    jobs = []

    for feed_cfg in FEEDS:
        url   = feed_cfg["url"]
        label = feed_cfg["label"]
        color = feed_cfg.get("color", "blue")

        print(f"[Fetch] {label} — {url}")
        try:
            feed = feedparser.parse(url, agent="Mozilla/5.0 (compatible; GovJobsBot/1.0)")
        except Exception as e:
            print(f"  ⚠ Error: {e}")
            continue

        count = 0
        for entry in feed.entries:
            if count >= MAX_JOBS_PER_FEED:
                break

            title = (entry.get("title") or "").strip()
            if not title:
                continue

            fp = fingerprint(title)
            if fp in seen_fps:
                continue
            seen_fps.add(fp)

            # Parse date
            pub = entry.get("published_parsed") or entry.get("updated_parsed")
            if pub:
                dt = datetime(*pub[:6], tzinfo=timezone.utc)
                date_str  = dt.strftime("%d %b %Y")
                date_iso  = dt.isoformat()
                days_ago  = (datetime.now(timezone.utc) - dt).days
            else:
                date_str  = "Recent"
                date_iso  = ""
                days_ago  = 999

            summary = clean_html(entry.get("summary") or entry.get("description") or "")
            link    = entry.get("link", "#")

            # Optionally enrich with Gemini
            ai_desc = ""
            if USE_GEMINI and not summary:
                ai_desc = gemini_describe(title)

            jobs.append({
                "title":    title,
                "link":     link,
                "date":     date_str,
                "date_iso": date_iso,
                "days_ago": days_ago,
                "summary":  ai_desc or summary,
                "source":   label,
                "color":    color,
            })
            count += 1

        print(f"  ✓ {count} jobs fetched")

    # Sort newest first
    jobs.sort(key=lambda x: x["days_ago"])
    return jobs[:MAX_TOTAL_JOBS]

# ─── HTML GENERATION ─────────────────────────────────────────────────────────

BADGE_COLORS = {
    "blue":   ("#1d4ed8", "#dbeafe"),
    "green":  ("#15803d", "#dcfce7"),
    "orange": ("#c2410c", "#ffedd5"),
    "purple": ("#7e22ce", "#f3e8ff"),
    "red":    ("#b91c1c", "#fee2e2"),
    "gray":   ("#374151", "#f3f4f6"),
}

def badge_style(color: str) -> str:
    fg, bg = BADGE_COLORS.get(color, BADGE_COLORS["gray"])
    return f"background:{bg};color:{fg}"

def is_new(days_ago: int) -> bool:
    return days_ago <= 3

def job_card(job: dict, idx: int) -> str:
    new_badge = '<span class="new-badge">NEW</span>' if is_new(job["days_ago"]) else ""
    summary   = f'<p class="card-summary">{job["summary"]}</p>' if job["summary"] else ""
    return f"""
    <a class="card" href="{job['link']}" target="_blank" rel="noopener" style="animation-delay:{idx*0.04:.2f}s">
      <div class="card-header">
        <span class="source-badge" style="{badge_style(job['color'])}">{job['source']}</span>
        {new_badge}
        <span class="card-date">{job['date']}</span>
      </div>
      <h3 class="card-title">{job['title']}</h3>
      {summary}
      <span class="apply-link">View &amp; Apply →</span>
    </a>"""

def build_html(jobs: list[dict]) -> str:
    updated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    total   = len(jobs)
    cards   = "\n".join(job_card(j, i) for i, j in enumerate(jobs))

    # Unique sources for filter buttons
    sources = sorted(set(j["source"] for j in jobs))
    filter_btns = '\n'.join(
        f'<button class="filter-btn" data-source="{s}">{s}</button>'
        for s in sources
    )

    return f"""<!DOCTYPE html>
<html lang="hi-IN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="Latest Sarkari Naukri — Government job notifications updated every 6 hours. SSC, Railway, Bank, UPSC, State PSC and more.">
  <meta property="og:title" content="{SITE_TITLE}">
  <meta property="og:description" content="{SITE_TAGLINE}">
  <meta name="theme-color" content="#0f172a">
  <title>{SITE_TITLE} — {SITE_TAGLINE}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans:wght@400;600&display=swap">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg:       #0f172a;
      --surface:  #1e293b;
      --surface2: #263144;
      --accent:   #f97316;
      --accent2:  #fb923c;
      --text:     #f1f5f9;
      --muted:    #94a3b8;
      --border:   #334155;
      --radius:   10px;
    }}

    body {{
      font-family: 'Inter', 'Noto Sans', sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      line-height: 1.6;
    }}

    /* ── HEADER ── */
    header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 60%, #0c1a3a 100%);
      border-bottom: 1px solid var(--border);
      padding: 2rem 1rem 1.5rem;
      text-align: center;
      position: relative;
      overflow: hidden;
    }}
    header::before {{
      content: '';
      position: absolute;
      inset: 0;
      background: radial-gradient(ellipse 60% 80% at 50% -10%, rgba(249,115,22,0.18) 0%, transparent 70%);
      pointer-events: none;
    }}
    .site-eyebrow {{
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 0.5rem;
    }}
    .site-title {{
      font-size: clamp(1.8rem, 5vw, 2.8rem);
      font-weight: 700;
      letter-spacing: -0.02em;
      color: #fff;
    }}
    .site-title span {{ color: var(--accent); }}
    .site-tagline {{
      color: var(--muted);
      font-size: 0.92rem;
      margin-top: 0.4rem;
    }}
    .header-stats {{
      display: flex;
      gap: 1.5rem;
      justify-content: center;
      margin-top: 1.2rem;
      flex-wrap: wrap;
    }}
    .stat {{
      background: rgba(255,255,255,0.05);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.3rem 0.8rem;
      font-size: 0.8rem;
      color: var(--muted);
    }}
    .stat strong {{ color: var(--text); }}

    /* ── CONTROLS ── */
    .controls {{
      max-width: 1200px;
      margin: 1.5rem auto 0;
      padding: 0 1rem;
      display: flex;
      gap: 0.75rem;
      flex-wrap: wrap;
      align-items: center;
    }}
    .search-box {{
      flex: 1;
      min-width: 200px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 0.55rem 1rem;
      color: var(--text);
      font-size: 0.9rem;
      outline: none;
      transition: border-color 0.2s;
    }}
    .search-box:focus {{ border-color: var(--accent); }}
    .search-box::placeholder {{ color: var(--muted); }}

    .filter-btn {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 0.45rem 0.9rem;
      color: var(--muted);
      font-size: 0.8rem;
      cursor: pointer;
      transition: all 0.18s;
      white-space: nowrap;
    }}
    .filter-btn:hover, .filter-btn.active {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }}
    .filter-btn[data-source="all"] {{ font-weight: 600; }}

    /* ── GRID ── */
    .grid-wrap {{
      max-width: 1200px;
      margin: 1.5rem auto 3rem;
      padding: 0 1rem;
    }}
    .results-count {{
      font-size: 0.82rem;
      color: var(--muted);
      margin-bottom: 1rem;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 1rem;
    }}

    /* ── CARD ── */
    .card {{
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.1rem 1.2rem;
      text-decoration: none;
      color: inherit;
      transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s;
      animation: fadeUp 0.4s ease both;
    }}
    @keyframes fadeUp {{
      from {{ opacity: 0; transform: translateY(12px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}
    .card:hover {{
      transform: translateY(-3px);
      border-color: var(--accent);
      box-shadow: 0 8px 24px rgba(249,115,22,0.12);
    }}
    .card-header {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      flex-wrap: wrap;
    }}
    .source-badge {{
      font-size: 0.7rem;
      font-weight: 600;
      padding: 0.15rem 0.55rem;
      border-radius: 4px;
      letter-spacing: 0.02em;
    }}
    .new-badge {{
      font-size: 0.65rem;
      font-weight: 700;
      background: var(--accent);
      color: #fff;
      padding: 0.12rem 0.45rem;
      border-radius: 4px;
      letter-spacing: 0.06em;
    }}
    .card-date {{
      margin-left: auto;
      font-size: 0.72rem;
      color: var(--muted);
    }}
    .card-title {{
      font-size: 0.92rem;
      font-weight: 600;
      color: var(--text);
      line-height: 1.45;
    }}
    .card-summary {{
      font-size: 0.8rem;
      color: var(--muted);
      line-height: 1.5;
    }}
    .apply-link {{
      margin-top: auto;
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--accent);
    }}

    /* ── FOOTER ── */
    footer {{
      text-align: center;
      padding: 2rem 1rem;
      border-top: 1px solid var(--border);
      color: var(--muted);
      font-size: 0.8rem;
    }}
    footer a {{ color: var(--accent); text-decoration: none; }}

    /* ── EMPTY STATE ── */
    .empty {{
      text-align: center;
      padding: 4rem 1rem;
      color: var(--muted);
      display: none;
    }}
    .empty.show {{ display: block; }}

    @media (max-width: 480px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}

    @media (prefers-reduced-motion: reduce) {{
      .card {{ animation: none; }}
    }}
  </style>
</head>
<body>

<header>
  <p class="site-eyebrow">🇮🇳 India Government Jobs Portal</p>
  <h1 class="site-title">Sarkari<span>Naukri</span>.live</h1>
  <p class="site-tagline">{SITE_TAGLINE}</p>
  <div class="header-stats">
    <span class="stat"><strong>{total}</strong> jobs listed</span>
    <span class="stat">Updated <strong>{updated}</strong></span>
    <span class="stat"><strong>{len(sources)}</strong> sources</span>
  </div>
</header>

<div class="controls">
  <input class="search-box" type="search" id="search" placeholder="Search jobs, departments, locations…" autocomplete="off">
  <button class="filter-btn active" data-source="all">All Sources</button>
  {filter_btns}
</div>

<div class="grid-wrap">
  <p class="results-count" id="count">{total} jobs found</p>
  <div class="grid" id="grid">
    {cards}
  </div>
  <div class="empty" id="empty">
    <p style="font-size:2rem">🔍</p>
    <p>No jobs match your search. Try different keywords.</p>
  </div>
</div>

<footer>
  Auto-updated every 6 hours via GitHub Actions &nbsp;·&nbsp;
  Jobs sourced from official portals &nbsp;·&nbsp;
  <a href="https://github.com" target="_blank">View on GitHub</a>
</footer>

<script>
  const cards   = [...document.querySelectorAll('.card')];
  const grid    = document.getElementById('grid');
  const countEl = document.getElementById('count');
  const emptyEl = document.getElementById('empty');
  let activeSource = 'all';
  let searchVal    = '';

  function filterCards() {{
    let visible = 0;
    cards.forEach(card => {{
      const title  = card.querySelector('.card-title').textContent.toLowerCase();
      const summ   = (card.querySelector('.card-summary') || {{}}).textContent?.toLowerCase() || '';
      const src    = card.querySelector('.source-badge').textContent;
      const matchS = activeSource === 'all' || src === activeSource;
      const matchQ = !searchVal || title.includes(searchVal) || summ.includes(searchVal);
      card.style.display = matchS && matchQ ? '' : 'none';
      if (matchS && matchQ) visible++;
    }});
    countEl.textContent = visible + ' jobs found';
    emptyEl.classList.toggle('show', visible === 0);
  }}

  document.getElementById('search').addEventListener('input', e => {{
    searchVal = e.target.value.toLowerCase().trim();
    filterCards();
  }});

  document.querySelectorAll('.filter-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeSource = btn.dataset.source;
      filterCards();
    }});
  }});
</script>
</body>
</html>"""

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("  Govt Jobs Auto-poster — Fetching feeds…")
    print("=" * 50)

    jobs = fetch_all_feeds()
    print(f"\n[Total] {len(jobs)} unique jobs collected")

    out_dir = Path(__file__).parent.parent / "docs"
    out_dir.mkdir(exist_ok=True)

    html = build_html(jobs)
    out_path = out_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")

    print(f"[Done]  Written → {out_path}")
    print(f"        Site updated at {datetime.now().strftime('%Y-%m-%d %H:%M')}")

if __name__ == "__main__":
    main()
