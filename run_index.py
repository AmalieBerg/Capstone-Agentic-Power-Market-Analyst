"""Index the corpus (U3.1 + U3.2), incrementally.

U3.1: chunk + embed messages that aren't already in `chunks`.
U3.2: events come from two paths -
  (a) ENTSO-E structured outages -> mapped directly (NO LLM, always refreshed)
  (b) free-text messages (UMM / news) -> LLM extraction, NEW messages only

Run from the repo root:  python -u run_index.py
"""
import config
from src.index import db
from src.index.chunking import chunk_text
from src.index.embeddings import embed_documents
from src.extraction.events import extract_events, events_from_structured_outages
from src import llm
from src.extraction.news_tags import tag_news_zones
from src.extraction.event_news import enrich_events_with_news


conn = db.get_connection()
db.init_schema(conn)

rows = db.read_messages(conn)
print(f"{len(rows)} messages in corpus", flush=True)

with conn.cursor() as cur:
    cur.execute("SELECT DISTINCT message_id FROM chunks")
    chunked = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT DISTINCT source_id FROM events")
    evented = {r[0] for r in cur.fetchall()}

# ---- U3.1: chunk + embed NEW messages only ----
new_msgs = [m for m in rows if m["id"] not in chunked]
records = []
for m in new_msgs:
    text = "\n".join(p for p in (m.get("title"), m.get("body")) if p)
    for i, piece in enumerate(chunk_text(
        text, getattr(config, "CHUNK_SIZE", 1000), getattr(config, "CHUNK_OVERLAP", 200)
    )):
        records.append({"message_id": m["id"], "zone": m.get("zone"),
                        "chunk_index": i, "content": piece})
if records:
    vectors = embed_documents([r["content"] for r in records])
    for r, v in zip(records, vectors):
        r["embedding"] = v
    print(f"{db.upsert_chunks(conn, records)} chunks embedded ({len(new_msgs)} new messages)", flush=True)
else:
    print("no new messages to embed", flush=True)

# ---- U3.2 (a): structured ENTSO-E outages -> events, NO LLM ----
struct_rows = db.read_entsoe_outages(conn)          # (id, zone, raw)
struct_events = events_from_structured_outages(struct_rows)
print(f"{db.upsert_events(conn, struct_events)} structured events upserted (no LLM)", flush=True)

# ---- U3.2 (b): free-text messages -> LLM extraction, NEW only ----
OUTAGE_SOURCES = {"nordpool_umm", "iip_de"}   # free-text sources that ARE outages
struct_ids = {e.source_id for e in struct_events}
free_text = [
    m for m in rows
    if m.get("source") in OUTAGE_SOURCES
    and m["id"] not in struct_ids
    and m["id"] not in evented
]
if free_text:
    events, failures = extract_events(free_text, llm.complete)
    print(f"{db.upsert_events(conn, events)} free-text events via LLM, "
          f"{len(failures)} failures ({len(free_text)} messages)", flush=True)
else:
    print("no new free-text messages to extract", flush=True)

print(f"{tag_news_zones(conn)} news zone-tag pairs", flush=True)

# ---- U7.2: event -> news enrichment, live lookup, idempotent ----
all_events = struct_events + (events if free_text else [])
n_links = enrich_events_with_news(all_events, conn=conn)
print(f"{n_links} event-news links added", flush=True)

conn.close()
print(">> done.", flush=True)