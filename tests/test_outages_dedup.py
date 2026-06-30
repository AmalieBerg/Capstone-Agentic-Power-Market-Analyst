"""Offline tests for the U1.1 outage dedup/filter logic (_build_outage_rows)."""
from src.index import db


def _rec(**kw):
    base = {"production_resource_id": "11WD2ZOLL0002880",
            "start": "2026-01-01 00:00:00+01:00", "end": "2027-01-01 00:00:00+01:00",
            "docstatus": None, "revision": "1"}
    base.update(kw)
    return base


def test_cancelled_and_withdrawn_dropped():
    recs = [_rec(docstatus="Cancelled"), _rec(docstatus="Withdrawn"),
            _rec(docstatus=None), _rec(docstatus="Active")]
    rows = db._build_outage_rows("DE-LU", recs)
    assert len(rows) == 2  # only the live ones


def test_revisions_of_same_outage_share_one_id():
    recs = [_rec(revision="1"), _rec(revision="3")]  # same unit/start/end
    rows = db._build_outage_rows("DE-LU", recs)
    assert rows[0][0] == rows[1][0]            # same id
    assert {r[2] for r in rows} == {1, 3}      # revision captured for conflict resolution


def test_different_window_is_a_different_outage():
    a = db._build_outage_rows("DE-LU", [_rec(start="2026-01-01 00:00:00+01:00")])
    b = db._build_outage_rows("DE-LU", [_rec(start="2026-03-01 00:00:00+01:00")])
    assert a[0][0] != b[0][0]


def test_zone_separates_ids():
    a = db._build_outage_rows("DE-LU", [_rec()])
    b = db._build_outage_rows("NO2", [_rec()])
    assert a[0][0] != b[0][0]


def test_revision_non_numeric_defaults_zero():
    rows = db._build_outage_rows("DE-LU", [_rec(revision=None)])
    assert rows[0][2] == 0