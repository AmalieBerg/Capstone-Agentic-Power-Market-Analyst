"""U1.4: restore the frozen JSONL snapshot into a database.

Loads ./data/snapshot/*.jsonl into the schema (idempotent upserts), so a fresh
clone reproduces the exact eval corpus WITHOUT needing a Cohere key to re-embed.

Run from repo root:  python restore_snapshot.py
"""
from __future__ import annotations

import json
import os

from src.index import db

SNAP_DIR = os.path.join("data", "snapshot")


def _load(name: str) -> list[dict]:
    path = os.path.join(SNAP_DIR, f"{name}.jsonl")
    with open(path, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def restore() -> None:
    conn = db.get_connection()
    try:
        db.init_schema(conn)
        db.init_messages_schema(conn)
        db.init_news_zone_tags_schema(conn)

        msgs = _load("messages")
        print(f"messages       {db.upsert_messages(conn, msgs):6d}")

        chunks = _load("chunks")
        print(f"chunks         {db.upsert_chunks(conn, chunks):6d}")

        # events: reconstruct via the existing upsert path
        events = _load("events")
        with conn.cursor() as cur:
            for e in events:
                cur.execute(
                    "INSERT INTO events (id, source_id, asset, zone, capacity_mw, "
                    "fuel, start_ts, end_ts, source_url) VALUES "
                    "(%(id)s, %(source_id)s, %(asset)s, %(zone)s, %(capacity_mw)s, "
                    "%(fuel)s, %(start_ts)s, %(end_ts)s, %(source_url)s) "
                    "ON CONFLICT (id) DO NOTHING",
                    e,
                )
        conn.commit()
        print(f"events         {len(events):6d}")

        tags = _load("news_zone_tags")
        print(f"news_zone_tags {db.upsert_news_zone_tags(conn, [(t['message_id'], t['zone']) for t in tags]):6d}")

        outs = _load("entsoe_outages")
        with conn.cursor() as cur:
            for o in outs:
                raw = o["raw"] if isinstance(o["raw"], str) else json.dumps(o["raw"])
                cur.execute(
                    "INSERT INTO entsoe_outages (id, zone, raw) VALUES (%s, %s, %s) "
                    "ON CONFLICT (id) DO NOTHING",
                    (o["id"], o["zone"], raw),
                )
        conn.commit()
        print(f"entsoe_outages {len(outs):6d}")
    finally:
        conn.close()
    print(">> restore complete.")


if __name__ == "__main__":
    restore()