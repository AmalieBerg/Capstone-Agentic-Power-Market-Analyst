"""Offline unit tests for the ENTSO-E tidy transforms (U1.1 / U9.3).

These exercise the pure DataFrame->rows logic only — no API token, no network —
so they run in CI. The entsoe-py client itself is integration-tested manually.
"""
import pandas as pd

from src.ingestion import entsoe_client as ec


def test_series_to_rows_drops_nan_and_normalises_tz():
    idx = pd.date_range("2024-01-01", periods=3, freq="h", tz="Europe/Brussels")
    s = pd.Series([10.0, float("nan"), 12.0], index=idx)
    rows = ec._series_to_rows("DE-LU", ec.SERIES_PRICE, s)
    assert len(rows) == 2  # NaN dropped
    zone, series, ts, value = rows[0]
    assert zone == "DE-LU"
    assert series == ec.SERIES_PRICE
    assert value == 10.0
    assert ts.tzinfo is not None  # tz-aware (UTC)


def test_frame_to_rows_one_series_per_column():
    idx = pd.date_range("2024-01-01", periods=2, freq="h", tz="Europe/Brussels")
    df = pd.DataFrame({"Wind Onshore": [5.0, 6.0], "Solar": [1.0, 2.0]}, index=idx)
    rows = ec._frame_to_rows("DK-1", ec.SERIES_WIND_SOLAR_FC, df)
    series_names = {r[1] for r in rows}
    assert series_names == {
        "wind_solar_forecast.wind_onshore",
        "wind_solar_forecast.solar",
    }
    assert len(rows) == 4


def test_empty_frame_is_safe():
    assert ec._frame_to_rows("NO-2", ec.SERIES_GENERATION, None) == []
    assert ec._frame_to_rows("NO-2", ec.SERIES_GENERATION, pd.DataFrame()) == []
