"""Calibrate MIN_RELEVANCE: print top retrieval score for refusal vs answerable
questions, so the threshold can be set from data. Run: python calibrate_threshold.py"""
from src.index import db, retrieval

REFUSAL = [
    "What generation outages are currently affecting the Texas ERCOT grid?",
    "What is the current spot price of natural gas in Japan?",
    "What outages hit the Polish-German interconnector this week?",
    "Summarise the 2023 French nuclear availability crisis.",
    "What is Bitcoin's price today and how does it affect crypto mining electricity demand?",
]
ANSWERABLE = [
    "Why is the Tokke hydropower plant unavailable?",
    "What is the Neurath generation outage in DE-LU?",
    "What maintenance is planned on the DE-LU to DK1 interconnector?",
]

def top(conn, q):
    items = retrieval.retrieve(conn, q, k=6)
    scores = [i["score"] for i in items if i.get("score") is not None]
    return max(scores) if scores else 0.0

conn = db.get_connection()
try:
    print("=== REFUSAL questions (want LOW scores, below threshold) ===")
    rf = []
    for q in REFUSAL:
        s = top(conn, q); rf.append(s)
        print(f"  {s:.3f}  {q[:60]}")
    print("\n=== ANSWERABLE questions (want HIGH scores, above threshold) ===")
    an = []
    for q in ANSWERABLE:
        s = top(conn, q); an.append(s)
        print(f"  {s:.3f}  {q[:60]}")
    print(f"\nrefusal  max={max(rf):.3f}  mean={sum(rf)/len(rf):.3f}")
    print(f"answerable min={min(an):.3f}  mean={sum(an)/len(an):.3f}")
    gap_lo, gap_hi = max(rf), min(an)
    if gap_lo < gap_hi:
        print(f"\nSEPARABLE: set MIN_RELEVANCE between {gap_lo:.3f} and {gap_hi:.3f}")
        print(f"  suggested = {(gap_lo+gap_hi)/2:.3f}")
    else:
        print(f"\nOVERLAP: refusal max {gap_lo:.3f} >= answerable min {gap_hi:.3f}")
        print("  no clean threshold; refusals score as high as real questions.")
finally:
    conn.close()