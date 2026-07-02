"""U2.2: tag news items to in-scope bidding zones by keyword scan.

Asset-level linking was evaluated and descoped: REMIT/ENTSO-E asset identifiers
(e.g. '11T0-0000-0024-8 : Brunsbüttel') do not appear in journalistic text, so
an asset-name join yields 0 matches. News is associated to events at the ZONE
level; semantic retrieval surfaces news without explicit asset links.
"""
from __future__ import annotations
import logging, re
import config
from src.index import db

log = logging.getLogger(__name__)
NEWS_SOURCES = {"gnews", "clew", "guardian"}


def _zones_for_text(text: str) -> set[str]:
    blob = (text or "").lower()
    hits = set()
    for zone in config.GEO_TERMS:
        terms = config.zone_terms(zone, include_codes=False)   # safe: no short codes
        if any(re.search(rf"\b{re.escape(t)}\b", blob) for t in terms):
            hits.add(zone)
    return hits


def tag_news_zones(conn=None) -> int:
    own = conn is None
    conn = conn or db.get_connection()
    try:
        db.init_news_zone_tags_schema(conn)
        news = [m for m in db.read_messages(conn) if m.get("source") in NEWS_SOURCES]
        pairs = set()
        for m in news:
            zones = _zones_for_text(f"{m.get('title','')} {m.get('body','')}")                     # keep feed's own zone as baseline
            pairs |= {(m["id"], z) for z in zones if z in config.ZONES}
        n = db.upsert_news_zone_tags(conn, list(pairs))
        log.info("tagged %d news items -> %d (item,zone) pairs", len(news), n)
        return n
    finally:
        if own:
            conn.close()