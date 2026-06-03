#!/usr/bin/env python3
"""
=============================================================================
 QUANTUM PULSE - Dashboard builder
 Owner: Dr. Shahaf Asban
-----------------------------------------------------------------------------
 Runs on each agent cycle. It:
   1. Pulls recent intelligence items from your Notion databases
   2. Fetches delayed stock quotes for public quantum companies (Finnhub)
   3. Writes a single self-contained dashboard file: docs/index.html
 GitHub Pages then serves that file at a public, shareable link.

 No server needed - it's a static page rebuilt every few hours by the agent.
=============================================================================
"""
import json
import os
from datetime import datetime, timedelta, timezone

import requests
import config

NOTION_VERSION = "2022-06-28"
NOTION_HEADERS = {
    "Authorization": f"Bearer {config.NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

# Public quantum-related tickers to track
TICKERS = ["IBM", "IONQ", "RGTI", "QBTS", "QUBT"]
FINNHUB_KEY = os.environ.get("FINNHUB_KEY", "")


def log(m):
    print(f"[dashboard] {m}", flush=True)


def fetch_recent_items(days=7, per_section=8):
    """Pull recent rows from each section DB for the feed."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    items = []
    for section, db_id in config.DATA_SOURCE_IDS.items():
        if not db_id or db_id.startswith("PASTE_"):
            continue
        try:
            r = requests.post(
                f"https://api.notion.com/v1/databases/{db_id}/query",
                headers=NOTION_HEADERS,
                json={"filter": {"timestamp": "created_time",
                                 "created_time": {"on_or_after": since}},
                      "sorts": [{"timestamp": "created_time", "direction": "descending"}],
                      "page_size": per_section},
                timeout=30)
            r.raise_for_status()
            for page in r.json().get("results", []):
                p = page.get("properties", {})
                items.append({
                    "section": config.SECTION_LABELS.get(section, section),
                    "title": _text(p.get("Title") or p.get("Name")),
                    "summary": _text(p.get("Summary")),
                    "impact": _select(p.get("Impact")),
                    "url": (p.get("Source URL") or {}).get("url", ""),
                })
        except Exception as e:
            log(f"  ! query {section} failed: {e}")
    return items


def _text(prop):
    if not prop:
        return ""
    arr = prop.get("title") or prop.get("rich_text") or []
    return "".join(t.get("plain_text", "") for t in arr)


def _select(prop):
    if not prop:
        return ""
    s = prop.get("select")
    return s.get("name", "") if s else ""


def fetch_quotes():
    """Get delayed quotes from Finnhub. Returns list of dicts."""
    out = []
    if not FINNHUB_KEY:
        log("  ! No FINNHUB_KEY set - skipping stock data")
        return out
    for t in TICKERS:
        try:
            r = requests.get("https://finnhub.io/api/v1/quote",
                             params={"symbol": t, "token": FINNHUB_KEY}, timeout=20)
            r.raise_for_status()
            d = r.json()
            price = d.get("c")          # current price
            pct = d.get("dp")           # percent change
            if price:
                out.append({"ticker": t, "price": price, "pct": pct or 0})
        except Exception as e:
            log(f"  ! quote {t} failed: {e}")
    return out


def build_html(items, quotes):
    """Assemble the self-contained dashboard page."""
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sec_color = {
        "Funding & Tenders": ("#5DCAA5", "#0F3D30"),
        "Competitive Intelligence": ("#AFA9EC", "#2A2358"),
        "Academic & Research": ("#F0997B", "#3A2218"),
        "Supply Chain & Enabling": ("#EF9F27", "#3A2A10"),
        "Government & Policy": ("#85B7EB", "#13243A"),
        "Talent & Org Moves": ("#ED93B1", "#3A1F2A"),
        "Standards & Patents": ("#97C459", "#23300F"),
    }

    feed_html = ""
    for it in items:
        col, bg = sec_color.get(it["section"], ("#AFA9EC", "#2A2358"))
        imp_col = "#F0997B" if it["impact"] == "High" else "#8B86B8"
        title = (it["title"] or "Untitled").replace("<", "&lt;")
        summ = (it["summary"] or "").replace("<", "&lt;")[:160]
        link = it["url"] or "#"
        feed_html += f"""<a href="{link}" target="_blank" style="text-decoration:none; display:block; background:#15123A; border:0.5px solid #2A2358; border-radius:10px; padding:11px 13px; margin-bottom:8px;">
<div style="display:flex; align-items:center; gap:7px; margin-bottom:4px; flex-wrap:wrap;">
<span style="font-size:10.5px; color:{col}; background:{bg}; padding:2px 8px; border-radius:6px;">{it['section']}</span>
<span style="font-size:10.5px; margin-left:auto; color:{imp_col};">&#9679; {it['impact'] or 'Low'}</span></div>
<p style="margin:0 0 2px; font-size:13.5px; font-weight:500; color:#F4F3FB;">{title}</p>
<p style="margin:0; font-size:12px; color:#8B86B8; line-height:1.45;">{summ}</p></a>"""
    if not feed_html:
        feed_html = '<p style="color:#8B86B8; font-size:13px;">No items captured this week yet.</p>'

    ticker_html = ""
    for i, q in enumerate(quotes):
        up = (q["pct"] or 0) >= 0
        c = "#5DCAA5" if up else "#F0997B"
        arrow = "+" if up else ""
        border = "border-bottom:0.5px solid #241F4D;" if i < len(quotes) - 1 else ""
        ticker_html += f"""<div style="display:flex; align-items:center; justify-content:space-between; padding:7px 0; font-size:13px; {border}">
<span style="font-family:monospace; color:#E8E6F5;">{q['ticker']}</span>
<span style="display:flex; gap:12px; align-items:center;"><span style="color:#B4B2C9;">${q['price']:.2f}</span>
<span style="min-width:54px; text-align:right; color:{c};">{arrow}{q['pct']:.2f}%</span></span></div>"""
    if not ticker_html:
        ticker_html = '<p style="color:#8B86B8; font-size:12px;">Stock data unavailable.</p>'

    high = sum(1 for it in items if it["impact"] == "High")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Quantum Pulse</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Questrial&display=swap" rel="stylesheet">
<style>
body{{margin:0; background:#0A0820; font-family:'Century Gothic','Questrial','Avenir Next','Avenir',sans-serif; color:#E8E6F5;}}
.wrap{{max-width:920px; margin:0 auto; padding:1.5rem 1rem 3rem;}}
.card{{background:#1A1640; border-radius:11px; padding:1rem 1.1rem;}}
a:hover{{border-color:#534AB7 !important;}}
@media(max-width:760px){{.grid{{grid-template-columns:1fr !important;}}}}
</style></head>
<body><div class="wrap">

<div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; margin-bottom:1.3rem;">
<div style="display:flex; align-items:center; gap:11px;">
<div style="width:48px; height:48px; border-radius:11px; background:#2A2358; display:flex; align-items:center; justify-content:center; color:#AFA9EC; font-size:27px;">&#9883;</div>
<div><p style="margin:0; font-size:28px; font-weight:700; letter-spacing:0.5px; color:#F4F3FB;">Quantum Pulse</p>
<p style="margin:2px 0 0; font-size:16px; font-weight:500; color:#AFA9EC;">Dr. Shahaf Asban &middot; <span style="color:#8B86B8;">worldwide quantum intelligence</span></p></div></div>
<span style="font-size:11px; color:#8B86B8;">&#128260; auto-refreshes &middot; updated {updated}</span></div>

<div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:10px; margin-bottom:1.3rem;">
<div class="card" style="padding:0.7rem 0.9rem;"><p style="margin:0; font-size:11px; color:#8B86B8;">Items this week</p><p style="margin:3px 0 0; font-size:21px; font-weight:500; color:#F4F3FB;">{len(items)}</p></div>
<div class="card" style="padding:0.7rem 0.9rem;"><p style="margin:0; font-size:11px; color:#8B86B8;">High-impact</p><p style="margin:3px 0 0; font-size:21px; font-weight:500; color:#F0997B;">{high}</p></div>
<div class="card" style="padding:0.7rem 0.9rem;"><p style="margin:0; font-size:11px; color:#8B86B8;">Tickers tracked</p><p style="margin:3px 0 0; font-size:21px; font-weight:500; color:#F4F3FB;">{len(quotes)}</p></div>
</div>

<div class="grid" style="display:grid; grid-template-columns:minmax(0,1fr) minmax(0,0.78fr); gap:14px; align-items:start;">
<div>
<p style="margin:0 0 8px; font-size:12px; color:#8B86B8;">Intelligence feed &middot; last 7 days</p>
{feed_html}
</div>
<div>
<div class="card">
<p style="margin:0 0 4px; font-size:12px; color:#8B86B8;">Public quantum movers</p>
<p style="margin:0 0 9px; font-size:10px; color:#5F5C7A;">delayed quotes &middot; not for trading</p>
{ticker_html}
</div>
</div>
</div>

<p style="margin-top:2rem; text-align:center; font-size:11px; color:#5F5C7A;">Quantum Pulse &middot; auto-generated every few hours &middot; built for Dr. Shahaf Asban</p>
</div></body></html>"""


def main():
    log("Building dashboard...")
    items = fetch_recent_items()
    log(f"  {len(items)} feed items")
    quotes = fetch_quotes()
    log(f"  {len(quotes)} stock quotes")
    html = build_html(items, quotes)
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w") as f:
        f.write(html)
    log("  wrote docs/index.html")


if __name__ == "__main__":
    main()
