"""
=============================================================================
 CONFIG  -  your settings
=============================================================================
 Secrets (keys/tokens/IDs) come from GitHub Secrets when running on GitHub,
 and fall back to values pasted here when running on your own machine.
 You normally do NOT need to edit this file for GitHub - you'll paste your
 secrets into GitHub's Secrets vault instead (we'll do that together).
=============================================================================
"""
import os

# -----------------------------------------------------------------------------
# 1) KEYS  -  read from GitHub Secrets (environment), else use the pasted value
# -----------------------------------------------------------------------------

# Get a FREE key (no credit card) at https://console.groq.com  -> API Keys
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "gsk_PASTE_YOUR_GROQ_KEY_HERE")

# Get at https://www.notion.so/my-integrations -> New integration -> copy secret
# IMPORTANT: open each database in Notion -> ••• -> Connections -> add your integration
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "secret_PASTE_YOUR_NOTION_TOKEN_HERE")

# Which free model to use. The 70B is smartest; switch to the 8B if you hit limits.
MODEL = os.environ.get("MODEL", "llama-3.3-70b-versatile")   # or "llama-3.1-8b-instant"


# -----------------------------------------------------------------------------
# 2) NOTION DATA SOURCE IDs  -  one per section
# -----------------------------------------------------------------------------
# These also read from GitHub Secrets first, else the pasted value.
# How to find an ID: open the database as a full page in your browser. The URL
# looks like  notion.so/<workspace>/<THIS_32_CHAR_ID>?v=...
# Copy the 32-character ID (the part before the '?').
DATA_SOURCE_IDS = {
    "fund": os.environ.get("DB_FUND", "PASTE_FUNDING_DB_ID"),
    "gov":  os.environ.get("DB_GOV",  "PASTE_GOVERNMENT_DB_ID"),
    "comp": os.environ.get("DB_COMP", "PASTE_COMPETITIVE_DB_ID"),
    "acad": os.environ.get("DB_ACAD", "PASTE_ACADEMIC_DB_ID"),
    "supp": os.environ.get("DB_SUPP", "PASTE_SUPPLYCHAIN_DB_ID"),
    "tal":  os.environ.get("DB_TAL",  "PASTE_TALENT_DB_ID"),
    "std":  os.environ.get("DB_STD",  "PASTE_STANDARDS_DB_ID"),
}

# Human-readable labels written into the Notion "Section" select property
SECTION_LABELS = {
    "fund": "Funding & Tenders",
    "gov":  "Government & Policy",
    "comp": "Competitive Intelligence",
    "acad": "Academic & Research",
    "supp": "Supply Chain & Enabling",
    "tal":  "Talent & Org Moves",
    "std":  "Standards & Patents",
}


# -----------------------------------------------------------------------------
# 3) LIMITS  -  free-tier safety
# -----------------------------------------------------------------------------
MAX_REQUESTS_PER_MIN = 25      # stay under Groq's 30/min free limit
MAX_ITEMS_PER_SOURCE = 25      # don't process an entire feed history each run


# -----------------------------------------------------------------------------
# 4) SOURCES  -  what the agent monitors. Start small, expand later.
# -----------------------------------------------------------------------------
# type "rss"          -> prose, goes through the free model
# type "funding_api"  -> structured JSON, mapped directly (no model)
#
# For funding_api you map the JSON field names so we read them correctly:
#   results_path : list of keys to drill into the response to reach the array
#   field_map    : which JSON field is the title / deadline / amount / url
SOURCES = [

    # ---- Academic (RSS, easy, high signal) ----
    {"name": "arXiv quant-ph", "type": "rss", "active": True,
     "url": "http://export.arxiv.org/rss/quant-ph", "default_section": "acad"},

    # ---- Competitive: a curated Google News query (RSS) ----
    {"name": "News: quantum funding/partnerships", "type": "rss", "active": True,
     "url": "https://news.google.com/rss/search?q=quantum+computing+(funding+OR+raises+OR+partnership)&hl=en-US&gl=US&ceid=US:en",
     "default_section": "comp"},

    # ---- Supply chain signal (RSS news query) ----
    {"name": "News: quantum supply chain", "type": "rss", "active": True,
     "url": "https://news.google.com/rss/search?q=quantum+(cryogenic+OR+photonics+OR+%22control+electronics%22)&hl=en-US&gl=US&ceid=US:en",
     "default_section": "supp"},

    # ---- Talent signal (RSS news query) ----
    {"name": "News: quantum talent moves", "type": "rss", "active": True,
     "url": "https://news.google.com/rss/search?q=quantum+(appoints+OR+hires+OR+%22chief+scientist%22)&hl=en-US&gl=US&ceid=US:en",
     "default_section": "tal"},

    # ---- Government / policy (RSS news query) ----
    {"name": "News: quantum policy", "type": "rss", "active": True,
     "url": "https://news.google.com/rss/search?q=quantum+(policy+OR+%22export+control%22+OR+strategy+OR+NIST)&hl=en-US&gl=US&ceid=US:en",
     "default_section": "gov"},

    # ---- Company press feeds (add the ones that publish RSS) ----
    # {"name": "IonQ press", "type": "rss", "active": True,
    #  "url": "https://ionq.com/news/rss.xml", "default_section": "comp"},

    # ---- Funding API example (structured, no model) ----
    # Grants.gov has a public search API; below is the SHAPE to fill in.
    # {"name": "Grants.gov quantum", "type": "funding_api", "active": False,
    #  "url": "https://api.grants.gov/v1/api/search2?keyword=quantum",
    #  "results_path": ["data", "oppHits"],
    #  "field_map": {"title": "title", "summary": "agencyName",
    #                "url": "id", "deadline": "closeDate"}},

]
