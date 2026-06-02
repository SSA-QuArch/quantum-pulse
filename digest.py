#!/usr/bin/env python3
"""
=============================================================================
 QUANTUM PULSE - Weekly Digest generator
 Owner: Dr. Shahaf Asban
-----------------------------------------------------------------------------
 Reads the items captured in the last 7 days across all seven section
 databases, asks the free model to draft a strategic briefing, and posts it
 as a new page in Notion under your chosen "Weekly Digest" parent page.

 Runs automatically every Monday via GitHub Actions. You can also run it by
 hand:  python digest.py
=============================================================================
"""
import json
import sys
from datetime import datetime, timedelta, timezone

import requests
import config

NOTION_VERSION = "2022-06-28"
NOTION_HEADERS = {
    "Authorization": f"Bearer {config.NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}


def log(m):
    print(f"[digest] {m}", flush=True)


def fetch_recent_items():
    """Query each section DB for pages created in the last 7 days."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    items = []
    for section, db_id in config.DATA_SOURCE_IDS.items():
        if not db_id or db_id.startswith("PASTE_"):
            continue
        url = f"https://api.notion.com/v1/databases/{db_id}/query"
        payload = {
            "filter": {"timestamp": "created_time",
                       "created_time": {"on_or_after": since}},
            "page_size": 50,
        }
        try:
            r = requests.post(url, headers=NOTION_HEADERS, json=payload, timeout=30)
            r.raise_for_status()
            for page in r.json().get("results", []):
                p = page.get("properties", {})
                items.append({
                    "section": section,
                    "title": _text(p.get("Title")),
                    "summary": _text(p.get("Summary")),
                    "impact": _select(p.get("Impact")),
                    "url": p.get("Source URL", {}).get("url", ""),
                })
        except Exception as e:
            log(f"  ! could not query {section}: {e}")
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


DIGEST_SYSTEM_PROMPT = """You are the editor of Quantum Pulse, writing the weekly intelligence digest
for Dr. Shahaf Asban and his leadership audience. You receive a JSON array of this week's
captured items. Produce a concise, strategic briefing in PLAIN TEXT with these sections in
this order:

TOP 3 STRATEGIC TAKEAWAYS
(3 lines - the "so what", not just the "what")

CLOSING SOON
(funding/tenders worth flagging this week)

COMPETITIVE MOVES
(notable raises, partnerships, milestones)

BREAKTHROUGH OF THE WEEK
(the single most significant research result and why it matters)

POLICY WATCH
(government / regulation / export-control items)

ONE TO WATCH
(a standards or supply-chain signal most readers would miss)

Rules: neutral analytical tone, no hype, every claim traceable to an input item.
If a section has no items, write "Nothing notable this week."
Keep the whole thing under 400 words."""


def draft_digest(items):
    payload = {
        "model": config.MODEL,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": DIGEST_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(items)[:12000]},
        ],
    }
    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                      headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                      json=payload, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def post_to_notion(text, n_items):
    import os
    parent = os.environ.get("DIGEST_PARENT_PAGE", "").strip()
    week = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"Quantum Pulse - Week of {week}"

    # Break the text into Notion paragraph blocks (max 2000 chars each)
    blocks = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": para[:1900]}}]},
        })
    blocks.append({
        "object": "block", "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text",
                     "text": {"content": f"Curated by Dr. Shahaf Asban · {n_items} items this week"}}]},
    })

    if not parent or parent.startswith("PASTE_"):
        log("No DIGEST_PARENT_PAGE set - printing digest instead of posting:")
        print("\n" + "=" * 60 + f"\n{title}\n" + "=" * 60 + f"\n{text}\n")
        return

    payload = {
        "parent": {"page_id": parent},
        "properties": {"title": [{"text": {"content": title}}]},
        "children": blocks[:90],
    }
    r = requests.post("https://api.notion.com/v1/pages",
                      headers=NOTION_HEADERS, json=payload, timeout=30)
    if r.status_code >= 300:
        log(f"  ! Notion post failed: {r.text[:300]}")
    else:
        log(f"  + posted digest page: {title}")


def main():
    log("Gathering this week's items...")
    items = fetch_recent_items()
    log(f"Found {len(items)} items in the last 7 days")
    if not items:
        log("Nothing captured this week - skipping digest.")
        return
    log("Drafting digest with the free model...")
    text = draft_digest(items)
    post_to_notion(text, len(items))
    log("Done.")


if __name__ == "__main__":
    main()
