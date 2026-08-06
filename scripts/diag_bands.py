"""Per-question guardrail diagnostic: shows top score, band, and outcome for every
gold question, so threshold/gate tuning is data-driven not guesswork.
Run: python diag_bands.py    (no server needed)"""
import json
from src.index import db, retrieval
from src.generation import answer as A

LOW = getattr(A, "RELEVANCE_LOW", 0.45)
HIGH = getattr(A, "RELEVANCE_HIGH", 0.62)

gold = [json.loads(l) for l in open("data/eval/gold.jsonl", encoding="utf-8")]
conn = db.get_connection()
try:
    print(f"bands: LOW={LOW}  HIGH={HIGH}\n")
    print(f"{'id':4} {'cat':18} {'must_ref':8} {'top':6} {'band':10} outcome")
    for g in gold:
        items = retrieval.retrieve(conn, g["question"], k=6, zone=g.get("zone"))
        scores = [i["score"] for i in items if i.get("score") is not None]
        top = max(scores) if scores else 0.0
        if not items or top < LOW:
            band, outcome = "LOW", "refuse (no LLM)"
        elif top < HIGH:
            band = "AMBIG"
            gate = A.passes_relevance_gate(g["question"], items, __import__("src.llm", fromlist=["complete"]).complete)
            outcome = "answer (gate YES)" if gate else "REFUSE (gate NO)"
        else:
            band, outcome = "HIGH", "answer"
        flag = ""
        # flag wrong outcomes
        if g["must_refuse"] and "answer" in outcome: flag = "  <-- WRONGLY ANSWERED"
        if not g["must_refuse"] and "refuse" in outcome.lower(): flag = "  <-- WRONGLY REFUSED"
        print(f"{g['id']:4} {g['category']:18} {str(g['must_refuse']):8} {top:.3f}  {band:10} {outcome}{flag}")
finally:
    conn.close()