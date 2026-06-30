"""U1.4: freeze the corpus to a versioned JSONL snapshot.

Exports the five tables that constitute the frozen eval corpus:
  messages, chunks (with embeddings), events, news_zone_tags, entsoe_outages

Run from repo root:  python export_snapshot.py
Writes to ./data/snapshot/*.jsonl and prints per-file + total size.
"""
from __future__ import annotations

import datetime as _dt
import json
import os

from src.index import db

OUT_DIR = os.path.join("data", "snapshot")

# table -> SELECT. Order columns explicitly so the JSONL schema is stable.
TABLES = {
    "messages":       "SELECT id, zone, source, title, body, url, published_at FROM messages",
    "chunks":         "SELECT id, message_id, zone, chunk_index, content, embedding FROM chunks",
    "events":         "SELECT id, source_id, asset, zone, capacity_mw, fuel, start_ts, end_ts, source_url FROM events",
    "news_zone_tags": "SELECT message_id, zone FROM news_zone_tags",
    "entsoe_outages": "SELECT id, zone, raw FROM entsoe_outages",
}


def _default(o):
    """JSON-serialise datetimes and anything exotic."""
    if isinstance(o, (_dt.datetime, _dt.date)):
        return o.isoformat()
    # pgvector may come back as a string or a list depending on driver
    return str(o)


def _normalise_embedding(val):
    """Embeddings may arrive as list[float] or as a '[0.1,0.2,...]' string."""
    if val is None or isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except ValueError:
            return val
    return val


def export() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    conn = db.get_connection()
    manifest = {"frozen_at": _dt.datetime.utcnow().isoformat() + "Z",
                "event_window": ["2026-06-15", "2026-06-22"], "tables": {}}
    total = 0
    try:
        for name, sql in TABLES.items():
            path = os.path.join(OUT_DIR, f"{name}.jsonl")
            with conn.cursor() as cur:
                cur.execute(sql)
                cols = [d[0] for d in cur.description]
                n = 0
                with open(path, "w", encoding="utf-8") as fh:
                    for r in cur.fetchall():
                        row = dict(zip(cols, r))
                        if "embedding" in row:
                            row["embedding"] = _normalise_embedding(row["embedding"])
                        fh.write(json.dumps(row, default=_default, ensure_ascii=False) + "\n")
                        n += 1
            size = os.path.getsize(path)
            total += size
            manifest["tables"][name] = {"rows": n, "bytes": size}
            print(f"{name:16s} {n:6d} rows   {size/1_048_576:7.2f} MB")
    finally:
        conn.close()

    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    print("-" * 40)
    print(f"{'TOTAL':16s}          {total/1_048_576:7.2f} MB")
    print(f"manifest -> {os.path.join(OUT_DIR, 'manifest.json')}")


if __name__ == "__main__":
    export()