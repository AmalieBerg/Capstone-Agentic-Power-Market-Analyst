"""Central configuration: env vars, seeds, domain constants.

Designed to import cleanly with NO secrets set, so CI stays green before
secrets are configured. Secrets are read tolerantly here and validated only
at point of use via require().
"""
from __future__ import annotations

import os
import random
import urllib.parse as _url

from dotenv import load_dotenv

load_dotenv()

# --- Reproducibility (U0.1) ---
SEED = 42


def set_seeds(seed: int = SEED) -> None:
    """Set deterministic seeds for chunking / eval sampling."""
    random.seed(seed)
    try:
        import numpy as np  # optional
        np.random.seed(seed)
    except ImportError:
        pass


# --- Secrets (read tolerantly; do NOT crash at import) ---
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ENTSOE_API_TOKEN = os.getenv("ENTSOE_API_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")  # Neon
GUARDIAN_API_KEY = os.getenv("GUARDIAN_API_KEY")  # Sprint 2


def require(name: str) -> str:
    """Fetch a required env var or raise (called at use-time, not import-time)."""
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


# --- Bidding zones in scope (D2) ---
# entsoe-py Area enum names + EIC codes. VERIFY against entsoe-py's Area enum.
ZONES = {
    "DE-LU": {
        "entsoe_area": "DE_LU",
        "eic": "10Y1001A1001A82H",          # bidding zone — used by ENTSO-E queries
        "match_eics": [                       # TSO control areas — used to tag IIP feed content
            "10YDE-VE-------2",   # 50Hertz
            "10YDE-RWENET---I",   # Amprion
            "10YDE-EON------1",   # TenneT DE
            "10YDE-ENBW-----N",   # TransnetBW
        ],
    },
    "DK1": {"entsoe_area": "DK_1", "eic": "10YDK-1--------W"},
    "NO2": {"entsoe_area": "NO_2", "eic": "10YNO-2--------T"},
}

# Zone keyword map for news tagging (U2.2) — country/TSO names, NOT EICs,
# because journalistic text never uses REMIT asset codes.
ZONE_KEYWORDS = {
    "DE-LU": ["german", "germany", "deutschland", "luxembourg",
              "50hertz", "amprion", "tennet", "transnetbw", "bundesnetzagentur"],
    "DK1":   ["denmark", "danish", "danmark", "jutland", "energinet"],
    "NO2":   ["norway", "norwegian", "norge", "statnett"],
}

# --- Retrieval / chunking (deterministic) ---
TOP_K = 6

# --- Embeddings (D11) — Cohere ---
EMBED_DOC_INPUT_TYPE = "search_document"    # embedding corpus chunks
EMBED_QUERY_INPUT_TYPE = "search_query"     # embedding user questions

# --- LLM fallback chain (D10) ---
LLM_PRIMARY = {"provider": "groq", "model": "llama-3.3-70b-versatile"}
LLM_FALLBACK = {"provider": "gemini", "model": "gemini-2.5-flash"}

# --- Frozen eval snapshot window (U1.4) — single source of truth ---
SNAPSHOT_START = "2026-06-15"   # YYYY-MM-DD
SNAPSHOT_END   = "2026-06-22"

# --- U1.4 corpus freeze ---
# When True, live ingestion is blocked; the corpus is the frozen snapshot.
# Set False only to deliberately rebuild the corpus before re-freezing.
CORPUS_FROZEN = True

def _nordpool(eic: str) -> str:
    return (
        "https://ummrss.nordpoolgroup.com/messages/"
        "?messageTypes=1&messageTypes=2&messageTypes=3&messageTypes=4"
        f"&areas={eic}"
        "&publicationStartDate=1969-12-31T23%3A00%3A00.000Z"
        f"&eventStartDate={SNAPSHOT_START}T22%3A00%3A00.000Z"
        f"&eventStopDate={SNAPSHOT_END}T21%3A59%3A59.999Z"
        "&limit=100"
    )


# --- Outage message feeds (U1.2) ---
# RSS/Atom feeds of REMIT Urgent Market Messages (UMM). SET real feed URLs and
# tag each with the zone(s) it covers. If left empty, ingestion falls back to
# rendering the ENTSO-E structured outages (from U1.1) as text messages, so the
# retrieval corpus exists even before an external feed is wired.
OUTAGE_FEEDS = [
    {
        "zone": "NO2",
        "source": "nordpool_umm",
        "url": (
            "https://ummrss.nordpoolgroup.com/messages/"
            "?messageTypes=1&messageTypes=2&messageTypes=3&messageTypes=4"
            "&areas=10YNO-2--------T"
            "&publicationStartDate=1969-12-31T23%3A00%3A00.000Z"
            "&eventStartDate=2026-06-15T22%3A00%3A00.000Z"
            "&eventStopDate=2026-06-22T21%3A59%3A59.999Z"
            "&limit=100"
        ),
    },
    {
        "zone": "DK1",
        "source": "nordpool_umm",
        "url": (
            "https://ummrss.nordpoolgroup.com/messages/"
            "?messageTypes=1&messageTypes=2&messageTypes=3&messageTypes=4"
            "&areas=10YDK-1--------W"
            "&publicationStartDate=1969-12-31T23%3A00%3A00.000Z"
            "&eventStartDate=2026-06-15T22%3A00%3A00.000Z"
            "&eventStopDate=2026-06-22T21%3A59%3A59.999Z"
            "&limit=100"
        ),
    },
    {
        "zone": "DE-LU",
        "source": "nordpool_umm",
        "url": (
            "https://ummrss.nordpoolgroup.com/messages/"
            "?messageTypes=1&messageTypes=2&messageTypes=3&messageTypes=4"
            "&areas=10Y1001A1001A82H"
            "&publicationStartDate=1969-12-31T23%3A00%3A00.000Z"
            "&eventStartDate=2026-06-15T22%3A00%3A00.000Z"
            "&eventStopDate=2026-06-22T21%3A59%3A59.999Z"
            "&limit=100"
        ),
    },
    {"format": "remit_xml", "zone_from": "content", "source": "iip_de",
     "url": "https://platform.inside-information.de/electricity/electricity/atom"},
]

# --- Index settings (U3.1) ---
EMBED_MODEL = "embed-multilingual-v3.0"   # 1024-dim; corpus is EN/DE/NO/DK
EMBED_DIM = 1024
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# --- News feeds (U1.3) ---
# Query-scoped news for retrieval context. Metadata + snippet only for RSS
# sources (D4 licensing); Guardian's open licence permits full bodyText.
# Routed through fetch_feed -> upsert_messages with source-tagging; NOT run
# through extract_events (that is U2.2's job).

def _gnews(query: str) -> str:
    q = _url.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

NEWS_FEEDS = [
    {"zone": "DE-LU", "source": "gnews", "url": _gnews("German electricity power market plant outage when:7d")},
    {"zone": "DK1",   "source": "gnews", "url": _gnews("Denmark electricity OR wind power OR Nord Pool when:7d")},
    {"zone": "NO2",   "source": "gnews", "url": _gnews("Norway electricity power price hydropower when:7d")},
    {"zone": "DE-LU", "source": "clew",  "url": "https://www.cleanenergywire.org/rss.xml"},
    # Guardian: full-text, snapshot-windowed, content-zone tagged by query
    {"zone": "DE-LU", "source": "guardian", "format": "guardian", "query": "Germany energy", "section": "environment"},
    {"zone": "DK1",   "source": "guardian", "format": "guardian", "query": "Denmark electricity wind"},
    {"zone": "NO2",   "source": "guardian", "format": "guardian", "query": "Norway electricity power"},
]