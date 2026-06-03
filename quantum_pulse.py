#!/usr/bin/env python3
"""
=============================================================================
 QUANTUM PULSE  -  Worldwide Quantum Ecosystem Intelligence Agent
 Owner: Dr. Shahaf Asban
=============================================================================

WHAT THIS DOES (plain English):
  1. Reads a list of sources (RSS feeds + JSON APIs) from config.py
  2. For each new item, decides which "section" it belongs to
       - Structured funding APIs  -> parsed directly, NO LLM needed
       - News / prose feeds        -> sent to a FREE model (Groq) for extraction
  3. Skips anything it has already seen (dedup, stored in seen.json)
  4. Writes a clean row into the matching Notion data source
  5. Logs what it did

HOW TO RUN:
  1. pip install -r requirements.txt
  2. Fill in your keys in config.py
  3. python quantum_pulse.py            (one run)
     python quantum_pulse.py --dry-run  (test: prints, writes nothing to Notion)

You do NOT need to understand all the code. The only file you edit is config.py.
=============================================================================
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

try:
    import feedparser
except ImportError:
    print("Missing 'feedparser'. Run:  pip install -r requirements.txt")
    sys.exit(1)

import config  # your settings live here

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

SEEN_FILE = os.path.join(os.path.dirname(__file__), "seen.json")


def log(msg):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def load_seen():
    """A set of URLs we've already processed, so we never duplicate."""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen), f, indent=0)


# ---------------------------------------------------------------------------
# STEP A - The FREE model call (Groq, OpenAI-SDK compatible)
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """You are the extraction engine for Quantum Pulse, a quantum-ecosystem
intelligence platform. You receive one news/feed item. Return ONLY a single valid JSON
object - no prose, no markdown, no code fences.

First decide if the item is genuinely about the QUANTUM ecosystem (quantum computing,
sensing, communication, materials, post-quantum cryptography, or enabling supply chain).
If it is NOT, return exactly: {"relevant": false}

If it IS relevant, return this exact shape:
{
  "relevant": true,
  "section": "fund | gov | comp | acad | supp | tal | std",
  "title": "<concise headline, max 90 chars>",
  "summary": "<2-3 sentence neutral synopsis>",
  "entity": ["<companies/agencies/institutions>"],
  "country": ["<region codes: US, EU, DE, NL, UK, FR, CN, JP...>"],
  "impact": "High | Medium | Low",
  "strategic_tags": ["<2-4 short tags>"]
}

Section meanings: fund=funding/tenders, gov=government/policy, comp=competitive/company moves,
acad=academic/research, supp=supply chain/enabling tech, tal=talent/org moves, std=standards/patents.

impact: High = sector-shaping; Medium = notable; Low = routine.
Be conservative. Never invent facts not present in the input."""


class QuotaExhausted(Exception):
    """Raised when the free model's daily limit is hit, so we stop cleanly."""
    pass


def call_free_model(title, summary, _attempt=1):
    """Send one item to the free model. Retries at most twice on rate-limit,
    then gives up for the whole run instead of looping forever."""
    headers = {
        "Authorization": f"Bearer {config.API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.MODEL,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"TITLE: {title}\n\nCONTENT: {summary}"},
        ],
    }
    try:
        r = requests.post(config.API_URL, headers=headers, json=payload, timeout=40)
        if r.status_code == 429:
            if _attempt >= 3:
                # We've retried twice and still blocked: the daily quota is
                # almost certainly gone. Stop the whole run cleanly.
                log("  ! Rate limit persists after retries - daily quota likely exhausted.")
                raise QuotaExhausted()
            log(f"  ! Rate limited. Waiting 20s (attempt {_attempt}/2)...")
            time.sleep(20)
            return call_free_model(title, summary, _attempt + 1)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except QuotaExhausted:
        raise
    except Exception as e:
        log(f"  ! Model call failed: {e}")
        return None


# ---------------------------------------------------------------------------
# STEP B - Writing a row to Notion
# ---------------------------------------------------------------------------

NOTION_VERSION = "2022-06-28"  # stable; works with data-source DB IDs


# We look up each database's real columns once, then remember them.
_SCHEMA_CACHE = {}


def _get_schema(data_source_id, headers):
    """Return {column_name: column_type} for a database, fetched once and cached.
    This lets us write to whatever the columns are ACTUALLY called, instead of
    guessing - so a column named 'Name' vs 'Title' can never block a write."""
    if data_source_id in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[data_source_id]
    try:
        r = requests.get(f"https://api.notion.com/v1/databases/{data_source_id}",
                         headers=headers, timeout=30)
        r.raise_for_status()
        props = r.json().get("properties", {})
        schema = {name: meta.get("type") for name, meta in props.items()}
    except Exception as e:
        log(f"  ! Could not read database schema: {e}")
        schema = {}
    _SCHEMA_CACHE[data_source_id] = schema
    return schema


def notion_create_row(data_source_id, item, dry_run=False):
    """Create one page (row), sending only columns that actually exist."""
    if dry_run:
        log(f"  [dry-run] would write to {data_source_id[:8]}...: {item['title']}")
        return True

    headers = {
        "Authorization": f"Bearer {config.NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    schema = _get_schema(data_source_id, headers)

    # Find the title column - it's whatever column has type "title"
    # (often called "Name" in Notion, sometimes "Title"). We write the
    # headline there regardless of what it's named.
    title_col = next((n for n, t in schema.items() if t == "title"), None)

    props = {}
    if title_col:
        props[title_col] = {"title": [{"text": {"content": item.get("title", "")[:200]}}]}

    # A helper: only add a column if it exists in this database.
    def add(col, value):
        if col in schema:
            props[col] = value

    add("Summary", {"rich_text": [{"text": {"content": item.get("summary", "")[:1900]}}]})
    add("Section", {"select": {"name": config.SECTION_LABELS.get(item["section"], "Other")}})
    add("Source URL", {"url": item.get("url") or None})
    add("Impact", {"select": {"name": item.get("impact", "Low")}})
    if item.get("entity"):
        add("Entity", {"multi_select": [{"name": e[:90]} for e in item["entity"][:8]]})
    if item.get("country"):
        add("Country / Region", {"multi_select": [{"name": c[:30]} for c in item["country"][:6]]})
    if item.get("strategic_tags"):
        add("Strategic Tag", {"multi_select": [{"name": t[:40]} for t in item["strategic_tags"][:4]]})
    if item.get("deadline"):
        add("Deadline", {"date": {"start": item["deadline"]}})
    if item.get("amount_value"):
        add("Amount", {"number": item["amount_value"]})

    payload = {"parent": {"database_id": data_source_id}, "properties": props}
    try:
        r = requests.post("https://api.notion.com/v1/pages",
                          headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        return True
    except Exception as e:
        body = getattr(e, "response", None)
        detail = body.text[:300] if body is not None else ""
        log(f"  ! Notion write failed: {e} {detail}")
        return False


# ---------------------------------------------------------------------------
# STEP C - Source readers
# ---------------------------------------------------------------------------

def read_rss(source):
    """Yield {title, summary, url, published} dicts from an RSS feed."""
    feed = feedparser.parse(source["url"])
    out = []
    for entry in feed.entries[: config.MAX_ITEMS_PER_SOURCE]:
        out.append({
            "title": entry.get("title", ""),
            "summary": (entry.get("summary", "") or entry.get("description", ""))[:1500],
            "url": entry.get("link", ""),
        })
    return out


def read_funding_api(source):
    """
    Structured funding sources: NO LLM needed. We map JSON fields directly.
    This is a generic template - tweak the field names per API in config.py.
    For APIs we haven't mapped yet, we fall back to treating results as prose.
    """
    try:
        r = requests.get(source["url"], timeout=30,
                         headers={"User-Agent": "QuantumPulse/1.0"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log(f"  ! API fetch failed for {source['name']}: {e}")
        return []

    items = data
    for key in source.get("results_path", []):  # drill into nested JSON
        items = items.get(key, []) if isinstance(items, dict) else []

    out = []
    fmap = source.get("field_map", {})
    for raw in (items or [])[: config.MAX_ITEMS_PER_SOURCE]:
        if not isinstance(raw, dict):
            continue
        out.append({
            "title": str(raw.get(fmap.get("title", "title"), ""))[:200],
            "summary": str(raw.get(fmap.get("summary", "description"), ""))[:1500],
            "url": str(raw.get(fmap.get("url", "url"), "")),
            "deadline": raw.get(fmap.get("deadline", "deadline")) or None,
            "amount_value": raw.get(fmap.get("amount", "amount")) or None,
            "_prestructured": True,  # marks it as funding, skip LLM
        })
    return out


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Test mode: print results, write nothing to Notion")
    args = parser.parse_args()

    if args.dry_run:
        log("DRY RUN - nothing will be written to Notion")

    seen = load_seen()
    new_count, skip_count, irrelevant_count = 0, 0, 0
    request_times = []  # for throttling under 30 req/min
    run_start = time.time()
    MAX_RUN_SECONDS = 45 * 60  # hard stop after 45 min, no matter what
    stop_reason = None

    for source in config.SOURCES:
        if stop_reason:
            break
        if not source.get("active", True):
            continue
        log(f"Reading source: {source['name']} ({source['type']})")

        if source["type"] == "rss":
            raw_items = read_rss(source)
        elif source["type"] == "funding_api":
            raw_items = read_funding_api(source)
        else:
            log(f"  ! Unknown source type: {source['type']}")
            continue

        for raw in raw_items:
            # Safety net: never let one run exceed the time budget.
            if time.time() - run_start > MAX_RUN_SECONDS:
                stop_reason = "time budget reached (45 min)"
                break

            url = raw.get("url", "")
            if not url or url in seen:
                skip_count += 1
                continue

            # --- Funding APIs: already structured, no model needed ---
            if raw.get("_prestructured"):
                item = {
                    "section": "fund",
                    "title": raw["title"],
                    "summary": raw["summary"],
                    "url": url,
                    "impact": "Medium",
                    "deadline": raw.get("deadline"),
                    "amount_value": raw.get("amount_value"),
                    "entity": [], "country": [], "strategic_tags": ["funding"],
                }
            else:
                # --- Prose sources: throttle, then call the free model ---
                now = time.time()
                request_times = [t for t in request_times if now - t < 60]
                if len(request_times) >= config.MAX_REQUESTS_PER_MIN:
                    wait = 60 - (now - request_times[0]) + 1
                    log(f"  Throttling {wait:.0f}s to respect free-tier limit...")
                    time.sleep(max(wait, 0))
                request_times.append(time.time())

                try:
                    parsed = call_free_model(raw["title"], raw["summary"])
                except QuotaExhausted:
                    stop_reason = "daily model quota exhausted"
                    break
                if not parsed or not parsed.get("relevant"):
                    irrelevant_count += 1
                    seen.add(url)  # remember, so we don't re-ask
                    continue
                item = parsed
                item["url"] = url
                item.setdefault("section", source.get("default_section", "comp"))

            # --- Route to correct Notion data source ---
            ds_id = config.DATA_SOURCE_IDS.get(item["section"])
            if not ds_id:
                log(f"  ! No data source configured for section '{item['section']}'")
                continue

            if notion_create_row(ds_id, item, dry_run=args.dry_run):
                new_count += 1
                seen.add(url)
                log(f"  + [{item['section']}] {item['title'][:70]}")

    if not args.dry_run:
        save_seen(seen)

    if stop_reason:
        log(f"Stopped early: {stop_reason}. Progress saved; will resume next run.")
    log("=" * 60)
    log(f"DONE. New: {new_count} | Skipped(seen): {skip_count} | "
        f"Filtered as irrelevant: {irrelevant_count}")
    log("=" * 60)


if __name__ == "__main__":
    main()
