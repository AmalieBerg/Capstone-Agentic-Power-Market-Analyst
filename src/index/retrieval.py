"""Hybrid retrieval (U3.3) — vector-first.

The vector search over `chunks` is the relevance signal. Each chunk carries a
message_id that joins 1:1 to an event, so we attach each hit's structured event
(asset, MW, fuel, window) directly, then dedupe by asset — keeping the highest-
scoring window per unit. If the question names a zone (DE-LU/NO2/DK1) the search
is filtered to it.

Ranked/aggregate questions ("biggest outage") are NOT this module's job — those
belong to the structured agent tool (U7.1), which can ORDER BY capacity. This
module answers "what / why / which unit" by semantic relevance.

Pure helpers (detect_zones, merge_and_dedupe) are unit-tested offline; the SQL
searches run against Neon.
"""
from __future__ import annotations

import re

import config
from src.index import embeddings
from src.index.embeddings import to_pgvector



def detect_zones(question: str, known_zones: list[str]) -> list[str]:
    """Canonical zones explicitly named in the question. Empty = search all zones."""
    q = (question or "").lower()
    found: list[str] = []
    for zone in known_zones:
        aliases = config.zone_terms(zone, include_codes=True)   # codes OK: scanning a query
        if any(re.search(rf"(?<!\w){re.escape(a)}(?!\w)", q) for a in aliases):
            found.append(zone)
    return found


def search_chunks(conn, query_vec: list[float], zones=None, k: int = 24) -> list[dict]:
    """Cosine vector search over chunks (uses the HNSW index). Higher score = closer."""
    vec = to_pgvector(query_vec)
    zlist = list(zones) if zones else None
    sql = (
        "SELECT c.message_id, c.zone, c.content, m.url, m.title, "
        "       1 - (c.embedding <=> %s::vector) AS score "
        "FROM chunks c JOIN messages m ON m.id = c.message_id "
        "WHERE (%s::text[] IS NULL "
        "       OR c.zone = ANY(%s) "
        "       OR EXISTS (SELECT 1 FROM news_zone_tags t "
        "                  WHERE t.message_id = c.message_id AND t.zone = ANY(%s))) "
        "ORDER BY c.embedding <=> %s::vector "
        "LIMIT %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (vec, zlist, zlist, zlist, vec, k))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def events_for_messages(conn, message_ids: list[str]) -> dict[str, dict]:
    """Fetch events for the given source messages, keyed by source_id (== message id)."""
    if not message_ids:
        return {}
    sql = (
        "SELECT source_id, asset, zone, capacity_mw, fuel, start_ts, end_ts, source_url "
        "FROM events WHERE source_id = ANY(%s)"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (list(message_ids),))
        cols = [d[0] for d in cur.description]
        return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}


def search_events(conn, zones=None, active_on=None, limit: int = 8) -> list[dict]:
    """Structured query over events, capacity-ranked. For the U7.1 agent tool /
    'biggest outage' questions — not used by the relevance retriever below."""
    zlist = list(zones) if zones else None
    sql = (
        "SELECT e.source_id, e.asset, e.zone, e.capacity_mw, e.fuel, "
        "       e.start_ts, e.end_ts, e.source_url "
        "FROM events e "
        "WHERE (%s::text[] IS NULL OR e.zone = ANY(%s)) "
        "  AND (%s::timestamptz IS NULL OR "
        "       (e.start_ts <= %s AND (e.end_ts IS NULL OR e.end_ts >= %s))) "
        "ORDER BY e.capacity_mw DESC NULLS LAST "
        "LIMIT %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (zlist, zlist, active_on, active_on, active_on, limit))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def merge_and_dedupe(chunk_hits: list[dict], events_by_id: dict[str, dict], limit: int = 8) -> list[dict]:
    """Vector hits (pre-sorted best-first) with each one's event attached, deduped
    by asset (highest-scoring window per unit kept). Hits with no event (e.g. news)
    are kept as-is. One row per message; at most `limit` rows."""
    out: list[dict] = []
    seen_msgs: set[str] = set()
    seen_assets: set[str] = set()
    for h in chunk_hits:
        mid = h["message_id"]
        if mid in seen_msgs:
            continue
        seen_msgs.add(mid)
        ev = events_by_id.get(mid)
        asset = ev["asset"] if ev else None
        if asset is not None:
            if asset in seen_assets:
                continue          # collapse repeated windows of the same unit
            seen_assets.add(asset)
        out.append({
            "message_id": mid,
            "zone": h.get("zone"),
            "score": h.get("score"),
            "content": h.get("content"),
            "title": h.get("title"),
            "source_url": (ev or {}).get("source_url") or h.get("url"),
            "event": ev,
        })
        if len(out) >= limit:
            break
    return out


def retrieve(conn, question: str, k: int = 8, zone: str | None = None) -> list[dict]:
    """Vector-first hybrid retrieval for one question.

    zone set   -> filter to that zone (explicit selection: UI dropdown / eval).
    zone None  -> detect zone from the question text; if none named, search all
                  zones (pan-European relevance mode).
    """
    zones = [zone] if zone else (detect_zones(question, list(config.ZONES)) or None)
    query_vec = embeddings.embed_query(question)
    hits = search_chunks(conn, query_vec, zones=zones, k=k * 3)  # overfetch for dedupe
    events = events_for_messages(conn, [h["message_id"] for h in hits])
    return merge_and_dedupe(hits, events, limit=k)