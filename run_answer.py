"""Smoke-test answer generation (U4.1) against live Neon + LLM.

Run from the repo root:  python -u run_answer.py
Needs DATABASE_URL, COHERE_API_KEY, and GROQ_API_KEY (Gemini as fallback).
"""
from src.index import db
from src.generation import answer

QUESTIONS = [
    "What gas units are currently offline in DE-LU?",
    "Are there any outages affecting Nordic interconnectors?",
]

conn = db.get_connection()
try:
    for q in QUESTIONS:
        print(f"\nQ: {q}", flush=True)
        out = answer.answer_question(conn, q, k=6)
        print(out["answer"], flush=True)
        if out["citations"]:
            print("\nSources:", flush=True)
            for c in out["citations"]:
                where = c["source_url"] or f"(ENTSO-E structured outage, {c['zone']})"
                print(f"  [{c['index']}] {c['label']} — {where}", flush=True)
finally:
    conn.close()
print("\n>> done.", flush=True)