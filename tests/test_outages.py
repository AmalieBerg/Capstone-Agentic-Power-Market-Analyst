"""Offline unit tests for outage-message normalisation (U1.2 / U9.3).

Pure helpers only — no network, no feedparser, no DB — so they run in CI.
"""
import time

from src.ingestion import outages as ou


def test_parse_published_from_struct_time():
    st = time.strptime("2024-06-01T10:00:00", "%Y-%m-%dT%H:%M:%S")
    dt = ou._parse_published({"published_parsed": st})
    assert dt is not None and dt.tzinfo is not None
    assert dt.year == 2024 and dt.month == 6


def test_parse_published_from_rfc822_string():
    dt = ou._parse_published({"published": "Tue, 01 Jun 2024 10:00:00 +0000"})
    assert dt is not None and dt.year == 2024
    assert dt.tzinfo is not None


def test_parse_published_missing():
    assert ou._parse_published({}) is None


def test_entry_to_record_shape_and_stable_id():
    entry = {
        "title": "Unplanned outage — Unit X",
        "summary": "500 MW offline due to fault.",
        "link": "https://example.org/umm/123",
        "published": "Tue, 01 Jun 2024 10:00:00 +0000",
    }
    r1 = ou._entry_to_record("DE-LU", "nordpool_umm", entry)
    r2 = ou._entry_to_record("DE-LU", "nordpool_umm", entry)
    assert r1["zone"] == "DE-LU" and r1["source"] == "nordpool_umm"
    assert r1["title"].startswith("Unplanned outage")
    assert r1["body"] == "500 MW offline due to fault."
    assert r1["url"] == "https://example.org/umm/123"
    assert r1["published_at"] is not None
    assert r1["id"] == r2["id"]  # deterministic / idempotent


def test_outage_row_to_record_builds_body():
    raw = {"asset": "Unit Y", "capacity_mw": "800", "fuel": "Nuclear", "start": ""}
    r = ou._outage_row_to_record("abc123", "DK-1", raw)
    assert r["source"] == "entsoe_outage" and r["zone"] == "DK-1"
    assert "Unit Y" in r["body"] and "800" in r["body"]
    assert "start:" not in r["body"]  # empty fields dropped


# --- content-zone feed helpers (inside-information.de style) ---
import config  # noqa: E402


def test_strip_html():
    assert ou._strip_html("<p>500 MW <b>offline</b></p>") == "500 MW offline"
    assert ou._strip_html("A &amp; B") == "A & B"
    assert ou._strip_html(None) == ""


def test_zone_from_text_matches_configured_eic():
    idx = ou._eic_index()
    de_eic = config.ZONES["DE-LU"]["eic"]
    assert ou._zone_from_text(f"Bidding Zone: {de_eic} Affected Asset ...", idx) == "DE-LU"


def test_zone_from_text_skips_out_of_scope():
    idx = ou._eic_index()
    # Cyprus bidding zone from the live sample — not one of our zones
    assert ou._zone_from_text("Bidding Zone: 10YCY-1001A0003J", idx) is None
    assert ou._zone_from_text("", idx) is None