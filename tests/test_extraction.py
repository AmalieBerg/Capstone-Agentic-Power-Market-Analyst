"""Offline tests for U2.1 extraction (no network, no real LLM).

A fake `complete` returns canned JSON so the full parse -> merge -> validate ->
log-failures flow is exercised deterministically.
"""
from src.extraction import events as ev


def _row(**kw):
    base = {"id": "m1", "zone": "DE-LU", "title": "Unplanned outage — Unit X",
            "body": "500 MW offline, lignite, until 2026-06-20.", "url": "https://e.org/umm/1"}
    base.update(kw)
    return base


def test_prompt_includes_zone_and_text():
    p = ev.build_extraction_prompt("Title here", "Body here", "DE-LU")
    assert "DE-LU" in p and "Title here" in p and "Body here" in p
    assert "JSON" in p


def test_parse_plain_json():
    d = ev.parse_extraction_response('{"asset":"Unit X","capacity_mw":500,"fuel":"Lignite","start":null,"end":null}')
    assert d["asset"] == "Unit X" and d["capacity_mw"] == 500 and d["fuel"] == "Lignite"


def test_parse_strips_code_fences():
    d = ev.parse_extraction_response('```json\n{"asset":"Unit Y","capacity_mw":null,"fuel":null,"start":null,"end":null}\n```')
    assert d["asset"] == "Unit Y" and d["capacity_mw"] is None


def test_parse_keeps_only_allowed_fields():
    d = ev.parse_extraction_response('{"asset":"A","zone":"HACK","extra":1,"capacity_mw":1}')
    assert set(d.keys()) == set(ev._LLM_FIELDS)  # zone/extra dropped


def test_parse_rejects_non_object():
    for bad in ("not json", "[1,2,3]", "42"):
        try:
            ev.parse_extraction_response(bad)
            assert False, f"should have raised on {bad!r}"
        except ValueError:
            pass


def test_merge_takes_zone_and_ids_from_row_not_llm():
    parsed = {"asset": "Unit X", "capacity_mw": 500, "fuel": "Lignite", "start": "", "end": None}
    m = ev.merge_event_fields(parsed, _row(zone="DE-LU", id="m1", url="https://e.org/umm/1"))
    assert m["zone"] == "DE-LU"            # from row
    assert m["source_id"] == "m1"          # from row
    assert m["source_url"] == "https://e.org/umm/1"
    assert m["start"] is None              # "" normalised to None
    assert m["capacity_mw"] == 500


def test_extract_events_success_and_failure_are_separated():
    good = '{"asset":"Unit X","capacity_mw":500,"fuel":"Lignite","start":null,"end":null}'
    bad = "the model rambled instead of returning json"

    def fake_complete(prompt):
        # route by which message body is in the prompt
        return good if "good-msg" in prompt else bad

    rows = [_row(id="ok", body="good-msg 500MW"), _row(id="nope", body="bad-msg")]
    oks, fails = ev.extract_events(rows, fake_complete)
    assert len(oks) == 1 and oks[0].asset == "Unit X" and oks[0].source_id == "ok"
    assert len(fails) == 1 and fails[0].source_id == "nope"
    assert "json" in fails[0].reason.lower()


def test_extract_events_coerces_missing_asset_to_placeholder():
    # asset is required but blank -> validator fills "unknown unit" -> event succeeds, no failure
    def fake_complete(prompt):
        return '{"asset":"","capacity_mw":null,"fuel":null,"start":null,"end":null}'
    oks, fails = ev.extract_events([_row(id="x")], fake_complete)
    assert len(oks) == 1 and len(fails) == 0
    assert oks[0].asset == "unknown unit"
    assert oks[0].source_id == "x"