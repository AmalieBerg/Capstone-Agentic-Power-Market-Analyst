"""U8.2: evaluate the RAG system against the frozen gold set.

Hits the live /chat endpoint (real deployed path). For each gold question runs
TWO passes — explicit zone (tests the query-time filter) and inferred zone
(tests chat UX) — and scores:

  - refusal_correct : did `refused` match must_refuse
  - citation_hit    : did any gold_message_id appear in returned citations (recall)
  - fact_match      : fraction of expected_facts present in the answer text
  - groundedness    : LLM-judged (answer supported by returned snippets) [optional]
  - latency         : per-request wall-clock; reports p50/p95

Usage:
  python run_eval.py                         # in-process judge off, explicit+inferred
  python run_eval.py --url http://127.0.0.1:8000
  python run_eval.py --judge                 # enable LLM groundedness judge
  python run_eval.py --gold data/eval/gold.jsonl
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import defaultdict

import requests


def load_gold(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def ask(url: str, question: str, zone: str | None, k: int = 6) -> tuple[dict, float]:
    payload = {"question": question, "k": k}
    if zone is not None:
        payload["zone"] = zone
    t0 = time.perf_counter()
    r = requests.post(f"{url}/chat", json=payload, timeout=60)
    dt = time.perf_counter() - t0
    r.raise_for_status()
    return r.json(), dt


def score_facts(answer: str, facts: list[str]) -> float:
    if not facts:
        return 1.0
    a = (answer or "").lower()
    hits = sum(1 for f in facts if f.lower() in a)
    return hits / len(facts)


def citation_hit(resp: dict, gold_ids: list[str]) -> bool:
    if not gold_ids:
        return True  # n/a for refusals
    got = {c.get("message_id") for c in resp.get("citations", [])}
    got |= {s.get("message_id") for s in resp.get("snippets", [])}
    return any(g in got for g in gold_ids)


def judge_groundedness(question: str, answer: str, snippets: list[dict]) -> float | None:
    """LLM-as-judge: is the answer supported by the retrieved snippets? 0..1."""
    try:
        from src import llm
    except Exception:
        return None
    ctx = "\n".join(f"[{s.get('index')}] {s.get('snippet','')}" for s in snippets)
    prompt = (
        "You are grading a RAG answer for GROUNDEDNESS only. Given the SOURCES and "
        "the ANSWER, respond with a single number 0.0-1.0: 1.0 if every claim in the "
        "answer is supported by the sources, 0.0 if the answer is unsupported or "
        "fabricated. Respond with ONLY the number.\n\n"
        f"SOURCES:\n{ctx}\n\nANSWER:\n{answer}\n\nGroundedness (0.0-1.0):"
    )
    try:
        raw = llm.complete(prompt)
        m = __import__("re").search(r"[01](?:\.\d+)?", raw)
        return float(m.group(0)) if m else None
    except Exception:
        return None


def run(url: str, gold: list[dict], mode: str, judge: bool) -> dict:
    """mode: 'explicit' passes gold zone; 'inferred' passes no zone."""
    rows = []
    for g in gold:
        zone = g.get("zone") if mode == "explicit" else None
        try:
            resp, dt = ask(url, g["question"], zone)
        except Exception as e:
            rows.append({"id": g["id"], "category": g["category"], "error": str(e)})
            continue
        refused = bool(resp.get("refused"))
        rec = {
            "id": g["id"],
            "category": g["category"],
            "latency": dt,
            "refusal_correct": refused == bool(g["must_refuse"]),
            "citation_hit": citation_hit(resp, g["gold_message_ids"]),
            "fact_match": 1.0 if g["must_refuse"] else score_facts(resp.get("answer", ""), g["expected_facts"]),
            "refused": refused,
        }
        if judge and not g["must_refuse"] and not refused:
            rec["groundedness"] = judge_groundedness(
                g["question"], resp.get("answer", ""), resp.get("snippets", []))
        rows.append(rec)
    return summarize(rows, mode)


def summarize(rows: list[dict], mode: str) -> dict:
    ok = [r for r in rows if "error" not in r]
    errs = [r for r in rows if "error" in r]
    lat = [r["latency"] for r in ok]

    def frac(key):
        vals = [r[key] for r in ok if key in r]
        return sum(vals) / len(vals) if vals else float("nan")

    by_cat = defaultdict(list)
    for r in ok:
        by_cat[r["category"]].append(r)

    print(f"\n{'='*56}\n  EVAL — {mode.upper()} zone   ({len(ok)}/{len(rows)} answered, {len(errs)} errors)\n{'='*56}")
    print(f"  refusal_correct : {frac('refusal_correct'):.2f}")
    print(f"  citation_hit    : {frac('citation_hit'):.2f}   (retrieval recall)")
    print(f"  fact_match      : {frac('fact_match'):.2f}")
    g = [r['groundedness'] for r in ok if r.get('groundedness') is not None]
    if g:
        print(f"  groundedness    : {statistics.mean(g):.2f}   (LLM-judged, n={len(g)})")
    if lat:
        p50 = statistics.median(lat)
        p95 = sorted(lat)[max(0, int(len(lat)*0.95)-1)]
        print(f"  latency p50/p95 : {p50:.2f}s / {p95:.2f}s")
    print("  --- by category ---")
    for cat in ("structured_outage", "freetext_umm", "cross_zonal", "news", "refusal"):
        cr = by_cat.get(cat, [])
        if not cr:
            continue
        ch = sum(r["citation_hit"] for r in cr) / len(cr)
        fm = sum(r["fact_match"] for r in cr) / len(cr)
        rf = sum(r["refusal_correct"] for r in cr) / len(cr)
        print(f"  {cat:18s} n={len(cr):2d}  cite={ch:.2f} fact={fm:.2f} refuse_ok={rf:.2f}")
    if errs:
        print("  --- errors ---")
        for r in errs:
            print(f"  {r['id']}: {r['error'][:70]}")
    return {"rows": rows, "mode": mode}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--gold", default="data/eval/gold.jsonl")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--mode", choices=["explicit", "inferred", "both"], default="both")
    args = ap.parse_args()

    gold = load_gold(args.gold)
    print(f"Loaded {len(gold)} gold questions from {args.gold}")
    print(f"Endpoint: {args.url}   judge={'on' if args.judge else 'off'}")

    modes = ["explicit", "inferred"] if args.mode == "both" else [args.mode]
    results = {}
    for m in modes:
        results[m] = run(args.url, gold, m, args.judge)

    # persist raw rows for the write-up
    out = "data/eval/results.json"
    try:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({m: results[m]["rows"] for m in results}, fh, indent=2, default=str)
        print(f"\nRaw results -> {out}")
    except Exception as e:
        print(f"(could not write results.json: {e})")


if __name__ == "__main__":
    main()