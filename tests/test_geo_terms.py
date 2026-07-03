"""Offline tests for the zone geography registry (U2.2 / pan-European pivot).

config.GEO_TERMS is the single source of truth for zone vocabulary, read by both
news tagging (names only, safe for scanning article text) and retrieval zone
detection (names + short codes, safe for scanning a user query).
"""
import config


def test_zone_terms_excludes_codes_by_default():
    # default (for scanning article bodies) must NOT include ambiguous short codes
    terms = config.zone_terms("NO2")
    assert "norway" in terms
    assert "no2" not in terms          # 'no2' == nitrogen dioxide in prose


def test_zone_terms_includes_codes_when_requested():
    # for scanning a user query, short codes are safe and wanted
    terms = config.zone_terms("NO2", include_codes=True)
    assert "no2" in terms
    assert "norway" in terms


def test_zone_terms_includes_tso_names():
    assert "statnett" in config.zone_terms("NO2")
    assert "energinet" in config.zone_terms("DK1")
    assert "50hertz" in config.zone_terms("DE-LU")


def test_zone_terms_unknown_zone_falls_back_to_lowercased_label():
    assert config.zone_terms("XX9") == ["xx9"]


def test_every_in_scope_zone_has_terms():
    for zone in config.ZONES:
        assert config.zone_terms(zone), f"{zone} has no geography terms"


def test_geo_terms_structure_is_registry_shaped():
    # each entry must expose names/tso/codes so zones can be added without code changes
    for zone, meta in config.GEO_TERMS.items():
        assert "names" in meta and "codes" in meta
        assert isinstance(meta["names"], list)