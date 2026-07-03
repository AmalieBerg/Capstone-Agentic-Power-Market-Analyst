"""Offline tests for news relevance filtering (U1.3) and zone tagging (U2.2).

The energy-relevance gates are pure string predicates. These lock in the
regression cases found during Sprint 2 (sport / politics / macro articles that
must be rejected) so the corpus can't silently re-contaminate.
"""
from src.ingestion.outages import _is_energy_relevant, _is_energy_headline


# --- relevance gate: KEEP genuine power news ---
def test_keeps_power_outage_news():
    assert _is_energy_relevant("France suffers major power outage", "grid strain in heatwave")


def test_keeps_hydropower_news():
    assert _is_energy_relevant("Statkraft plans Mar hydropower upgrade", "Norwegian plant")


def test_keeps_grid_and_nuclear_terms():
    assert _is_energy_relevant("Europe's electricity grid buckles", "nuclear cuts")


# --- relevance gate: DROP junk that only incidentally matches ---
def test_drops_sport_high_energy():
    # "high-energy start" — sport, no power-system term
    assert not _is_energy_relevant("Tuchel brings the surge to England", "a high-energy start in Dallas")


def test_drops_politics_without_power_terms():
    assert not _is_energy_relevant("Burnham prepares for power", "leadership contest briefing war")


def test_drops_generic_non_energy():
    assert not _is_energy_relevant("Best foods to eat before a workout", "sports day season is here")


# --- headline gate (Guardian full-text): signal must be in title/lead ---
def test_headline_gate_accepts_lead_signal():
    body = "The manufacturing lobby warned that high electricity prices are killing industry. " + ("x " * 300)
    assert _is_energy_headline("Electricity prices and industry", body)


def test_headline_gate_rejects_buried_signal():
    # a long non-energy article that only mentions 'power' far past the lead window
    body = ("A film review about romance and wit. " * 40) + " star power in the final act"
    assert not _is_energy_headline("A review of the summer's romcom", body)


def test_headline_gate_reads_title_even_if_body_empty():
    assert _is_energy_headline("Nuclear plant shut down in heatwave", "")