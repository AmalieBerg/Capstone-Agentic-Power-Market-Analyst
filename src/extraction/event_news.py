"""U7.2: event -> news enrichment (live lookup, not corpus-written).

Given a freshly extracted OutageEvent, builds a targeted Google News RSS
query from its asset + zone and links any matching articles into
event_news_links. This is a LIVE lookup, same freshness regime as U7.1's
numeric tool -- results are never written to `messages` or
`news_zone_tags`, so it works regardless of CORPUS_FROZEN.
"""
from __future__ import annotations
import logging
import re
import config
from src.index import db
from src.index.db import _event_id

log = logging.getLogger(__name__)


def build_event_news_query(asset: str, zone: str) -> str:
        # Structured events sometimes carry a raw EIC-code prefix
    # ("11T0-0000-0024-8 : Brunsbüttel") -- strip it, since codes
    # don't appear in journalistic text (same lesson as U2.2).
    clean_asset = re.sub(r"^\S+-\S+-\S+-\S+\s*:\s*", "", asset).strip()
    return f"{clean_asset} outage when:7d"


def fetch_event_news(query: str, limit: int = 5) -> list[dict]:
    """Live RSS fetch, same retry pattern as fetch_feed, but returns
    transient records instead of persisting to messages."""
    import feedparser
    import requests

    url = config._gnews(query)
    resp = None
    for attempt in (1, 2, 3):
        try:
            resp = requests.get(url, timeout=(5, 30))
            resp.raise_for_status()
            break
        except requests.RequestException as exc:
            log.warning("event-news fetch attempt %d failed: %s", attempt, exc)
    if resp is None:
        return []

    parsed = feedparser.parse(resp.content)
    out = []
    for entry in parsed.entries[:limit]:
        out.append({
            "url": entry.get("link"),
            "title": entry.get("title"),
            "source": "gnews",
            "published": entry.get("published"),
        })
    return out


def enrich_events_with_news(events: list, conn=None, limit: int = 5) -> int:
    """Entry point: call this right after extract_events() / upsert_events()
    in the extraction flow. Idempotent -- skips events already enriched."""
    own = conn is None
    conn = conn or db.get_connection()
    try:
        db.init_event_news_links_schema(conn)
        ids = [_event_id(e.source_id, e.asset) for e in events]  
        pending_ids = set(db.events_missing_news_links(conn, ids))
        rows = []
        for e in events:
            if e.source_id not in pending_ids:
                continue
            query = build_event_news_query(e.asset, e.zone)
            for article in fetch_event_news(query, limit=limit):
                if not article["url"]:
                    continue
                rows.append((_event_id(e.source_id, e.asset), article["url"], article["title"],
                 article["source"], article["published"]))
        n = db.upsert_event_news_links(conn, rows)
        log.info("enriched %d events -> %d news links", len(pending_ids), n)
        return n
    finally:
        if own:
            conn.close()