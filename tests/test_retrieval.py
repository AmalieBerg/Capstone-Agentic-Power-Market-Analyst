"""Offline tests for U3.3 pure helpers: detect_zones + merge_and_dedupe."""
from src.index.retrieval import detect_zones, merge_and_dedupe

KNOWN = ["DE-LU", "NO2", "DK1"]


def test_detect_explicit_code():
    assert detect_zones("what's down in DE-LU right now?", KNOWN) == ["DE-LU"]


def test_detect_country_word():
    assert detect_zones("any big outages in Germany?", KNOWN) == ["DE-LU"]
    assert detect_zones("show me Norway", KNOWN) == ["NO2"]


def test_detect_multiple():
    assert set(detect_zones("compare Germany and Denmark", KNOWN)) == {"DE-LU", "DK1"}


def test_detect_none_when_unspecified():
    assert detect_zones("what is the biggest outage anywhere?", KNOWN) == []


def test_detect_no_false_match_on_substring():
    assert detect_zones("nothing notable in demand today", KNOWN) == []


def _chunk(mid, score, content="c"):
    return {"message_id": mid, "zone": "DE-LU", "content": content,
            "url": "u", "title": "t", "score": score}


def _ev(mid, asset, mw=100.0):
    return {"source_id": mid, "asset": asset, "zone": "DE-LU", "capacity_mw": mw,
            "fuel": "Lignite", "start_ts": None, "end_ts": None, "source_url": "u"}


def test_collapses_repeated_windows_to_one_row_per_unit():
    # 5 messages, all asset "Neurath", different scores
    hits = [_chunk(f"m{i}", 0.5 - i * 0.01) for i in range(5)]
    events = {f"m{i}": _ev(f"m{i}", "Neurath") for i in range(5)}
    out = merge_and_dedupe(hits, events, limit=8)
    assert len(out) == 1                      # collapsed to one Neurath
    assert out[0]["message_id"] == "m0"       # the highest-scoring window kept
    assert out[0]["event"]["asset"] == "Neurath"


def test_event_attached_to_its_chunk():
    hits = [_chunk("m1", 0.9)]
    out = merge_and_dedupe(hits, {"m1": _ev("m1", "Boxberg")}, limit=8)
    assert out[0]["event"]["asset"] == "Boxberg" and out[0]["score"] == 0.9


def test_distinct_assets_all_kept_in_score_order():
    hits = [_chunk("m1", 0.9), _chunk("m2", 0.8), _chunk("m3", 0.7)]
    events = {"m1": _ev("m1", "A"), "m2": _ev("m2", "B"), "m3": _ev("m3", "C")}
    out = merge_and_dedupe(hits, events, limit=8)
    assert [o["event"]["asset"] for o in out] == ["A", "B", "C"]


def test_chunk_without_event_is_kept():
    hits = [_chunk("m9", 0.4, content="news text")]
    out = merge_and_dedupe(hits, {}, limit=8)
    assert len(out) == 1 and out[0]["event"] is None


def test_limit_respected():
    hits = [_chunk(f"m{i}", 0.9 - i * 0.01) for i in range(20)]
    events = {f"m{i}": _ev(f"m{i}", f"asset{i}") for i in range(20)}
    out = merge_and_dedupe(hits, events, limit=5)
    assert len(out) == 5