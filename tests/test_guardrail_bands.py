"""Offline tests for the banded refusal guardrail (U4.2 / U8 calibration).

generate() uses three bands on the top retrieval score:
  score < RELEVANCE_LOW           -> refuse without any LLM call
  RELEVANCE_LOW <= score < HIGH   -> LLM relevance gate decides
  score >= RELEVANCE_HIGH         -> answer

A fake `complete` stands in for the LLM so the whole flow runs deterministically
in CI with no network / no quota.
"""
from src.generation import answer as A


def _item(score, mid="m1", content="Neurath lignite unit 1058 MW offline"):
    return {"message_id": mid, "zone": "DE-LU", "content": content,
            "title": "outage", "source_url": "u", "event": None, "score": score}


def _answering_complete(prompt):
    # gate prompt asks YES/NO; answer prompt asks for prose. Route by content.
    if "YES/NO" in prompt or "YES" in prompt.split()[-3:]:
        return "YES"
    return "Unit is offline [1]."


def _gate_says(verdict):
    def complete(prompt):
        if "in scope" in prompt.lower() or "YES/NO" in prompt:
            return verdict
        return "Answer text [1]."
    return complete


# --- Band 1: below LOW -> refuse, and the LLM is never called ---
def test_below_low_refuses_without_llm():
    calls = []
    def spy(prompt):
        calls.append(prompt)
        return "should not be called"
    out = A.generate("off-topic q", [_item(A.RELEVANCE_LOW - 0.05)], complete=spy)
    assert out["refused"] is True
    assert calls == []                       # no LLM spend on clear refusals


def test_empty_items_refuses():
    out = A.generate("q", [], complete=_answering_complete)
    assert out["refused"] is True


# --- Band 3: at/above HIGH -> answer, gate skipped ---
def test_above_high_answers():
    out = A.generate("Neurath?", [_item(A.RELEVANCE_HIGH + 0.05)], complete=_answering_complete)
    assert out["refused"] is False
    assert out["answer"]


# --- Band 2: ambiguous -> gate decides ---
def test_ambiguous_gate_no_refuses():
    score = (A.RELEVANCE_LOW + A.RELEVANCE_HIGH) / 2
    out = A.generate("borderline q", [_item(score)], complete=_gate_says("NO"))
    assert out["refused"] is True


def test_ambiguous_gate_yes_answers():
    score = (A.RELEVANCE_LOW + A.RELEVANCE_HIGH) / 2
    out = A.generate("borderline q", [_item(score)], complete=_gate_says("YES"))
    assert out["refused"] is False


# --- graceful degradation: LLM failure -> clean message, not a crash ---
def test_llm_failure_degrades_gracefully():
    def boom(prompt):
        raise RuntimeError("both providers rate-limited")
    out = A.generate("Neurath?", [_item(A.RELEVANCE_HIGH + 0.1)], complete=boom)
    assert out["refused"] is False
    assert out.get("error") == "llm_unavailable"
    assert "unavailable" in out["answer"].lower()


# --- citation extraction ties [n] markers back to sources ---
def test_answer_extracts_citations():
    out = A.generate("Neurath?", [_item(A.RELEVANCE_HIGH + 0.1)], complete=_answering_complete)
    assert out["citations"]                   # [1] in the answer resolved to a source
    assert out["citations"][0]["message_id"] == "m1"