"""Neon Postgres + pgvector data layer (C1/D9) — single store for the whole project.

Neon scales to zero when idle and auto-wakes (~sub-second) on the next query;
the retry in get_connection() absorbs that cold start so a waking DB never
surfaces an error.

Tables created here:
  - market_data    : tidy ENTSO-E time series (U1.1) — also read by the agent tool (U7.1)
  - entsoe_outages : structured generation-unit outages (U1.1), stored as JSONB
  - messages       : outage-message retrieval corpus (U1.2)
  - chunks         : embedded text chunks + pgvector HNSW index (U3.1)
  - events         : structured OutageEvent rows (U3.2)
"""
from __future__ import annotations

import hashlib

import config


def get_connection():
    """Return a psycopg connection to Neon, retrying through scale-to-zero wake."""
    import psycopg
    from tenacity import retry, stop_after_attempt, wait_fixed

    @retry(wait=wait_fixed(1), stop=stop_after_attempt(5), reraise=True)
    def _connect():
        return psycopg.connect(config.require("DATABASE_URL"))

    return _connect()


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
def init_market_schema(conn) -> None:
    """Create the market-data and outage tables (idempotent)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS market_data (
                zone   TEXT        NOT NULL,
                series TEXT        NOT NULL,
                ts     TIMESTAMPTZ NOT NULL,
                value  DOUBLE PRECISION,
                PRIMARY KEY (zone, series, ts)
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS entsoe_outages (
                id         TEXT PRIMARY KEY,
                zone       TEXT,
                revision   INT,
                fetched_at TIMESTAMPTZ DEFAULT now(),
                raw        JSONB
            );
            """
        )
    conn.commit()


def init_schema(conn) -> None:
    """Create the pgvector `chunks` table + HNSW index (U3.1) and the structured
    `events` table (U3.2). Idempotent."""
    dim = getattr(config, "EMBED_DIM", 1024)
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS chunks (
                id          TEXT PRIMARY KEY,
                message_id  TEXT REFERENCES messages(id),
                zone        TEXT,
                chunk_index INT,
                content     TEXT,
                embedding   vector({dim})
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw "
            "ON chunks USING hnsw (embedding vector_cosine_ops);"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id          TEXT PRIMARY KEY,
                source_id   TEXT REFERENCES messages(id),
                asset       TEXT,
                zone        TEXT,
                capacity_mw DOUBLE PRECISION,
                fuel        TEXT,
                start_ts    TIMESTAMPTZ,
                end_ts      TIMESTAMPTZ,
                source_url  TEXT
            );
            """
        )
    conn.commit()


# --------------------------------------------------------------------------- #
# Writes (idempotent)
# --------------------------------------------------------------------------- #
def upsert_market_data(conn, rows: list[tuple]) -> int:
    """Upsert (zone, series, ts, value) rows. Idempotent on the primary key."""
    if not rows:
        return 0
    sql = (
        "INSERT INTO market_data (zone, series, ts, value) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (zone, series, ts) DO UPDATE SET value = EXCLUDED.value"
    )
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)


_CANCELLED_STATUSES = {"cancelled", "withdrawn"}


def _build_outage_rows(zone: str, records) -> list[tuple]:
    """records -> [(id, zone, revision, raw_json)] for entsoe_outages.

    Dedup on a STABLE natural key (zone|unit|start|end) so revisions of the same
    physical outage collapse to one row instead of stacking. Cancelled/withdrawn
    disclosures are dropped (they are not live outages). `records` is an iterable
    of plain dicts whose values are already None or strings.
    """
    import json

    out: list[tuple] = []
    for rec in records:
        status = (rec.get("docstatus") or "").strip().lower()
        if status in _CANCELLED_STATUSES:
            continue
        unit = rec.get("production_resource_id") or rec.get("production_resource_name") or ""
        key = "|".join([zone, unit, rec.get("start") or "", rec.get("end") or ""])
        rid = hashlib.sha1(key.encode("utf-8")).hexdigest()
        try:
            revision = int(float(rec.get("revision") or 0))
        except (TypeError, ValueError):
            revision = 0
        out.append((rid, zone, revision, json.dumps(rec)))
    return out


def upsert_outages(conn, zone: str, df) -> int:
    """Store structured outage rows as JSONB. Dedupes revisions of the same
    outage to one row, drops cancelled disclosures, and keeps the latest revision."""
    if df is None or getattr(df, "empty", True):
        return 0
    import pandas as pd

    records = [
        {str(k): (None if pd.isna(v) else str(v)) for k, v in r.items()}
        for _, r in df.iterrows()
    ]
    rows = _build_outage_rows(zone, records)
    if not rows:
        return 0
    sql = (
        "INSERT INTO entsoe_outages (id, zone, revision, raw) "
        "VALUES (%s, %s, %s, %s::jsonb) "
        "ON CONFLICT (id) DO UPDATE SET "
        "raw = EXCLUDED.raw, revision = EXCLUDED.revision, fetched_at = now() "
        "WHERE EXCLUDED.revision >= entsoe_outages.revision"
    )
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)


# --------------------------------------------------------------------------- #
# Deterministic ids (idempotent re-runs for chunks/events)
# --------------------------------------------------------------------------- #
def _chunk_id(message_id: str, idx: int) -> str:
    return hashlib.sha1(f"{message_id}:{idx}".encode("utf-8")).hexdigest()


def _event_id(source_id: str, asset: str) -> str:
    return hashlib.sha1(f"{source_id}:{asset}".encode("utf-8")).hexdigest()


def _event_to_row(e) -> tuple:
    """OutageEvent -> events row tuple (column order matches upsert_events)."""
    return (
        _event_id(e.source_id, e.asset), e.source_id, e.asset, e.zone,
        e.capacity_mw, e.fuel, e.start, e.end, e.source_url,
    )


def upsert_chunks(conn, records: list[dict]) -> int:
    """Upsert chunk rows (U3.1). Each record: {message_id, zone, chunk_index,
    content, embedding(list[float])}. Idempotent on a (message_id, chunk_index) hash."""
    if not records:
        return 0
    from src.index.embeddings import to_pgvector

    sql = (
        "INSERT INTO chunks (id, message_id, zone, chunk_index, content, embedding) "
        "VALUES (%s, %s, %s, %s, %s, %s::vector) "
        "ON CONFLICT (id) DO UPDATE SET "
        "content = EXCLUDED.content, embedding = EXCLUDED.embedding"
    )
    rows = [
        (_chunk_id(r["message_id"], r["chunk_index"]), r["message_id"], r.get("zone"),
         r["chunk_index"], r["content"], to_pgvector(r["embedding"]))
        for r in records
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)


def upsert_events(conn, events: list) -> int:
    """Upsert OutageEvent rows (U2.1 output, U3.2 store). Idempotent on (source_id, asset)."""
    if not events:
        return 0
    sql = (
        "INSERT INTO events "
        "(id, source_id, asset, zone, capacity_mw, fuel, start_ts, end_ts, source_url) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET "
        "asset = EXCLUDED.asset, capacity_mw = EXCLUDED.capacity_mw, "
        "fuel = EXCLUDED.fuel, start_ts = EXCLUDED.start_ts, end_ts = EXCLUDED.end_ts, "
        "source_url = EXCLUDED.source_url"
    )
    rows = [_event_to_row(e) for e in events]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)

def init_news_zone_tags_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS news_zone_tags (
                message_id TEXT NOT NULL,
                zone TEXT NOT NULL,
                PRIMARY KEY (message_id, zone)
            )
        """)
    conn.commit()

def upsert_news_zone_tags(conn, pairs):
    if not pairs:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO news_zone_tags (message_id, zone) VALUES (%s, %s) "
            "ON CONFLICT (message_id, zone) DO NOTHING",
            pairs,
        )
    conn.commit()
    return len(pairs)


# --------------------------------------------------------------------------- #
# Reads (used by the agent tool, U7.1)
# --------------------------------------------------------------------------- #
def get_latest(conn, zone: str, series: str):
    """Most recent (ts, value) for a zone+series, or None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ts, value FROM market_data "
            "WHERE zone = %s AND series = %s ORDER BY ts DESC LIMIT 1",
            (zone, series),
        )
        return cur.fetchone()


# --------------------------------------------------------------------------- #
# Outage messages (U1.2) — the retrieval corpus (chunked/embedded in U3.1)
# --------------------------------------------------------------------------- #
def init_messages_schema(conn) -> None:
    """Create the messages table (idempotent). Text lives here in Neon at
    runtime; it is NOT committed to the repo (D4)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id           TEXT PRIMARY KEY,
                zone         TEXT,
                source       TEXT,
                url          TEXT,
                title        TEXT,
                body         TEXT,
                published_at TIMESTAMPTZ,
                fetched_at   TIMESTAMPTZ DEFAULT now()
            );
            """
        )
    conn.commit()


def upsert_messages(conn, records: list[dict]) -> int:
    """Upsert message records; idempotent on id, refreshes content on re-fetch."""
    if not records:
        return 0
    sql = (
        "INSERT INTO messages (id, zone, source, url, title, body, published_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET "
        "title = EXCLUDED.title, body = EXCLUDED.body, url = EXCLUDED.url, "
        "published_at = EXCLUDED.published_at, fetched_at = now()"
    )
    rows = [
        (r["id"], r.get("zone"), r.get("source"), r.get("url"),
         r.get("title"), r.get("body"), r.get("published_at"))
        for r in records
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)


def read_messages(conn, zones=None, limit=None):
    """Read outage messages (U1.2) for extraction (U2.1): id, zone, title, body, url."""
    sql = "SELECT id, zone, source, title, body, url, published_at FROM messages"
    params = []
    if zones:
        sql += " WHERE zone = ANY(%s)"
        params.append(list(zones))
    sql += " ORDER BY published_at DESC NULLS LAST"
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    
def read_entsoe_outages(conn, zones=None):
    """Read stored structured outages (id, zone, raw) for the message fallback."""
    sql = "SELECT id, zone, raw FROM entsoe_outages"
    params = ()
    if zones:
        sql += " WHERE zone = ANY(%s)"
        params = (list(zones),)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()