"""Answer generation (U4.1) + guardrails (U4.2).

Retrieve context -> answer ONLY from it -> cited, length-capped answer.
Guardrails (U4.2):
  - refuse outside-corpus questions (empty retrieval, or top relevance below a
    threshold) WITHOUT calling the LLM
  - always cite (prompt + extract_citations)
  - cap output length (prompt instruction + a hard truncation backstop)
"""
from __future__ import annotations

import re

from src.index import retrieval
from src import llm

_CITE = re.compile(r"\[(\d+)\]")


# Guardrail bands, calibrated against the U8 gold set (refusals ≤0.575,
# answerable ≥0.613). A single cosine cutoff can't separate them (gap too
# narrow), so the ambiguous band gets a semantic relevance check.
RELEVANCE_LOW = 0.45    # below: refuse without LLM (clearly off-corpus)
RELEVANCE_HIGH = 0.60   # above: answer without gate (clearly in-corpus)
MAX_ANSWER_CHARS = 1500  # hard backstop on output length

REFUSAL = (
    "I don't have information about that in my power-market corpus. I can answer "
    "questions about generation and transmission outages (asset, capacity, fuel, "
    "timing) for the DE-LU, DK1, and NO2 bidding zones."
)


def _fmt_dt(v) -> str:
    return "" if v is None else str(v)[:16]


def _describe_event(ev: dict) -> str:
    if not ev:
        return ""
    bits = [ev.get("asset") or "unknown unit"]
    if ev.get("capacity_mw") is not None:
        bits.append(f"{ev['capacity_mw']:.0f} MW")
    if ev.get("fuel"):
        bits.append(str(ev["fuel"]))
    window = " to ".join(p for p in (_fmt_dt(ev.get("start_ts")), _fmt_dt(ev.get("end_ts"))) if p)
    desc = ", ".join(bits)
    return f"{desc}; {window}" if window else desc

def _passes_relevance_gate(question: str, items: list[dict], complete) -> bool:
    """Ambiguous-band gate: refuse only if the question is clearly OUTSIDE scope
    (different region/commodity/time), not merely because the snippets are a
    partial answer. Scope = generation/transmission outages & power news for
    DE-LU, DK1, NO2."""
    ctx = "\n".join(
        f"[{i+1}] {(it.get('content') or it.get('title') or '')[:300]}"
        for i, it in enumerate(items[:5])
    )
    prompt = (
        "You filter questions for a power-market assistant covering the DE-LU, DK1, "
        "and NO2 bidding zones (Germany/Luxembourg, West Denmark, South Norway) and "
        "the mid-2026 period. Answer NO only if the question is clearly OUT OF SCOPE: "
        "a different region (e.g. Texas, Japan, Poland), a different commodity "
        "(e.g. crypto, oil futures), or a different time period (e.g. 2023). "
        "If the question is about power/outages/energy in the covered zones and the "
        "sources are at all related, answer YES even if they only partially answer it. "
        "Reply with ONLY 'YES' or 'NO'.\n\n"
        f"SOURCES:\n{ctx}\n\nQUESTION: {question}\n\nIn scope (YES/NO):"
    )
    try:
        return not (complete(prompt) or "").strip().upper().startswith("NO")
    except Exception:
        return True


def format_context(items: list[dict], max_chars: int = 400) -> tuple[str, list[dict]]:
    """Numbered context block + parallel sources list (1-indexed, with snippets)."""
    lines: list[str] = []
    sources: list[dict] = []
    for i, item in enumerate(items, start=1):
        ev = item.get("event")
        zone = item.get("zone") or "?"
        head = _describe_event(ev) if ev else (item.get("title") or "source")
        body = (item.get("content") or "").strip().replace("\n", " ")
        snippet = body[:max_chars] + ("…" if len(body) > max_chars else "")
        lines.append(f"[{i}] ({zone}) {head}. {snippet}".rstrip())
        sources.append({
            "index": i,
            "message_id": item.get("message_id"),
            "source_url": item.get("source_url") or "",
            "label": (ev.get("asset") if ev else item.get("title")) or "source",
            "zone": item.get("zone"),
            "snippet": snippet,
        })
    return "\n".join(lines), sources


def build_answer_prompt(question: str, context_text: str) -> str:
    return (
        "You are a power-market analyst assistant. Answer the question using ONLY "
        "the numbered sources below. Cite every claim inline with its source number "
        "like [1] or [2]. Answer concisely, in at most ~150 words. If the sources do "
        "not contain enough information to answer, say so plainly instead of guessing.\n\n"
        f"Sources:\n{context_text}\n\n"
        f"Question: {question}\n\n"
        "Answer (cite sources as [n]):"
    )


def extract_citations(answer_text: str, sources: list[dict]) -> list[dict]:
    by_index = {s["index"]: s for s in sources}
    seen: list[int] = []
    for m in _CITE.finditer(answer_text or ""):
        n = int(m.group(1))
        if n in by_index and n not in seen:
            seen.append(n)
    return [by_index[n] for n in seen]


def _top_score(items: list[dict]) -> float:
    scores = [i["score"] for i in items if i.get("score") is not None]
    return max(scores) if scores else 0.0


def generate(question: str, items: list[dict], complete=llm.complete) -> dict:
    """Format -> banded guardrail -> prompt -> LLM -> cited, capped answer."""
    top = _top_score(items)
    # Band 1: clearly off-corpus -> refuse, no LLM
    if not items or top < RELEVANCE_LOW:
        return {"answer": REFUSAL, "sources": [], "citations": [], "refused": True}
    # Band 2 (ambiguous): semantic gate decides
    if top < RELEVANCE_HIGH and not _passes_relevance_gate(question, items, complete):
        return {"answer": REFUSAL, "sources": [], "citations": [], "refused": True}
    # Band 3 (or gate passed): answer
    context_text, sources = format_context(items)
    prompt = build_answer_prompt(question, context_text)
    try:
        answer = complete(prompt)
    except Exception:
        return {"answer": "The analysis service is temporarily unavailable (LLM rate limit). Please try again shortly.", "sources": [], "citations": [], "refused": False, "error": "llm_unavailable"}
    if len(answer) > MAX_ANSWER_CHARS:
        answer = answer[:MAX_ANSWER_CHARS].rstrip() + "…"
    return {"answer": answer, "sources": sources,
            "citations": extract_citations(answer, sources), "refused": False}


def answer_question(conn, question: str, k: int = 6, complete=llm.complete, zone: str | None = None) -> dict:
    """End-to-end: retrieve then generate a cited, guarded answer."""
    items = retrieval.retrieve(conn, question, k=k, zone=zone)
    return generate(question, items, complete=complete)