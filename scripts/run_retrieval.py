"""Smoke-test hybrid retrieval (U3.3) against live Neon — verbose/diagnostic.

Run from the repo root:  python -u run_retrieval.py
Needs DATABASE_URL + COHERE_API_KEY.
"""
import sys
import traceback


def say(*a):
    print(*a, flush=True)


say(">> starting; importing modules...")
try:
    from src.index import db, retrieval
    from src.index import embeddings
except Exception:
    traceback.print_exc()
    sys.exit(1)

say(">> connecting to Neon (may take ~1s if the DB is waking)...")
try:
    conn = db.get_connection()
except Exception:
    traceback.print_exc()
    sys.exit(1)

say(">> connected. counting rows...")
try:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks")
        n_chunks = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM events")
        n_events = cur.fetchone()[0]
    say(f">> chunks={n_chunks}  events={n_events}")
except Exception:
    traceback.print_exc()
    conn.close()
    sys.exit(1)

say(">> embedding a test query via Cohere (this is the slow step)...")
try:
    v = embeddings.embed_query("test")
    say(f">> embed OK, dim={len(v)}")
except Exception:
    traceback.print_exc()
    conn.close()
    sys.exit(1)

QUESTIONS = [
    "what's down in DE-LU right now?",
    "biggest outage in the Nordics",
    "Boxberg",
]

try:
    for q in QUESTIONS:
        say(f"\nQ: {q}")
        items = retrieval.retrieve(conn, q, k=5)
        say(f"   ({len(items)} results)")
        for item in items:
            ev = item["event"]
            tag = f"{ev['asset']} ({ev['capacity_mw']} MW, {ev['fuel']})" if ev else "(text-only)"
            score = f"{item['score']:.3f}" if item["score"] is not None else "  -  "
            say(f"   [{item['zone']:<6}] score={score}  {tag}")
except Exception:
    traceback.print_exc()
finally:
    conn.close()
say("\n>> done.")