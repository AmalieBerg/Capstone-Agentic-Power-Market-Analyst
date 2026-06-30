"""Offline tests for U3.1/U3.2 pure helpers (no DB, no network)."""
from datetime import datetime
from types import SimpleNamespace

from src.index.chunking import chunk_text
from src.index.embeddings import to_pgvector
from src.index import db


def test_chunk_short_text_is_single_chunk():
    assert chunk_text("a short outage message") == ["a short outage message"]


def test_chunk_empty_is_empty_list():
    assert chunk_text("") == [] and chunk_text(None) == []


def test_chunk_long_text_overlaps_and_covers():
    text = "".join(str(i % 10) for i in range(2500))
    pieces = chunk_text(text, size=1000, overlap=200)
    assert len(pieces) >= 3
    assert all(len(p) <= 1000 for p in pieces)
    assert "".join(pieces).find(text[:50]) == 0  # start preserved
    # overlap: end of chunk0 reappears at start of chunk1
    assert pieces[0][-200:] == pieces[1][:200]


def test_to_pgvector_format():
    assert to_pgvector([0.5, -1.0, 2]) == "[0.5,-1.0,2.0]"


def test_chunk_id_deterministic_and_index_sensitive():
    assert db._chunk_id("m1", 0) == db._chunk_id("m1", 0)
    assert db._chunk_id("m1", 0) != db._chunk_id("m1", 1)


def test_event_id_deterministic():
    assert db._event_id("s1", "Unit X") == db._event_id("s1", "Unit X")
    assert db._event_id("s1", "Unit X") != db._event_id("s1", "Unit Y")


def test_event_to_row_column_order():
    e = SimpleNamespace(
        asset="Vinje - G3", zone="NO2", capacity_mw=100.0, fuel="Hydro",
        start=datetime(2026, 6, 15, 7, 0), end=datetime(2026, 6, 15, 15, 0),
        source_url="https://umm/x", source_id="abc",
    )
    row = db._event_to_row(e)
    assert row[0] == db._event_id("abc", "Vinje - G3")  # id
    assert row[1] == "abc"            # source_id
    assert row[2] == "Vinje - G3"     # asset
    assert row[3] == "NO2"            # zone
    assert row[4] == 100.0            # capacity_mw
    assert row[5] == "Hydro"          # fuel
    assert row[8] == "https://umm/x"  # source_url