"""Offline tests for U4.1 generation + U4.2 guardrails + llm cache."""
from src.generation import answer as gen
from src import llm


def _item(mid, asset, score, content="gas unit offline", url="https://e/1"):
    ev = None if asset is None else {
        "asset": asset, "zone": "DE-LU", "capacity_mw": 383.0, "fuel": "Fossil Gas",
        "start_ts": "2026-06-15 07:00:00+00", "end_ts": "2026-06-20 18:00:00+00",
        "source_url": url}
    return {"message_id": mid, "zone": "DE-LU", "score": score, "content": content,
            "title": "t", "source_url": url, "event": ev}


def test_format_context_includes_snippet_in_sources():
    _, sources = gen.format_context([_item("m1", "Franken I", 0.5)])
    assert sources[0]["snippet"] and sources[0]["source_url"] == "https://e/1"


def test_generate_answers_when_relevant():
    items = [_item("m1", "Franken I", 0.45)]
    out = gen.generate("what's down in DE-LU?", items, complete=lambda p: "Franken I is offline [1].")
    assert out["refused"] is False
    assert out["citations"][0]["source_url"] == "https://e/1"


def test_guardrail_refuses_empty_retrieval():
    out = gen.generate("q", [], complete=lambda p: "should not run")
    assert out["refused"] is True and out["citations"] == []
    assert "don't have information" in out["answer"].lower()


def test_guardrail_refuses_low_relevance():
    # top score below threshold -> out-of-corpus -> refuse without calling LLM
    called = {"n": 0}
    def fake(p):
        called["n"] += 1
        return "x"
    items = [_item("m1", "Something", 0.18)]
    out = gen.generate("price of bitcoin?", items, complete=fake)
    assert out["refused"] is True and called["n"] == 0   # LLM never called


def test_guardrail_caps_output_length():
    items = [_item("m1", "Franken I", 0.5)]
    out = gen.generate("q", items, complete=lambda p: "y" * 5000)
    assert len(out["answer"]) <= gen.MAX_ANSWER_CHARS + 1   # +1 for the ellipsis


def test_llm_cache_avoids_second_call():
    llm.clear_cache()
    calls = {"n": 0}
    def fake_groq(prompt, *, temperature, max_tokens):
        calls["n"] += 1
        return "cached"
    llm._groq = fake_groq
    assert llm.complete("p") == llm.complete("p") == "cached"
    assert calls["n"] == 1
    llm.clear_cache()