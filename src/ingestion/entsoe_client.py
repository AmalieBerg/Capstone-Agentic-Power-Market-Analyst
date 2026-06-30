"""ENTSO-E ingestion (U1.1).

Fetches the market series the analyst is grounded on — day-ahead price, load
forecast, wind/solar forecast, generation — plus structured generation-unit
outages, per zone (config.ZONES), and stores them idempotently in Neon.

This is structured grounding + agent-tool data, NOT part of the searchable text
corpus (that is U1.2 outages text + U1.3 news).

Reuse note (U7.1): the Sprint-3 agent calls these same fetch methods / the
db.get_latest read path for live figures — do not duplicate this client.

Run a manual ingest:
    python -m src.ingestion.entsoe_client            # default: last 7 days, all zones
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta

import pandas as pd

import config
from src.index import db

log = logging.getLogger(__name__)

# Canonical series prefixes written to market_data.series
SERIES_PRICE = "day_ahead_price"
SERIES_LOAD_FC = "load_forecast"
SERIES_WIND_SOLAR_FC = "wind_solar_forecast"
SERIES_GENERATION = "generation"

_TZ = "Europe/Brussels"
_MIN_INTERVAL_S = 0.2  # throttle: well under ENTSO-E's 400 req/min
_last_call_ts = 0.0


# --------------------------------------------------------------------------- #
# Pure transforms (unit-tested offline — no network)
# --------------------------------------------------------------------------- #
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def _series_to_rows(zone: str, series_name: str, s: "pd.Series") -> list[tuple]:
    """pandas Series (tz-aware index) -> [(zone, series, ts_utc, value)], NaN dropped."""
    rows: list[tuple] = []
    if s is None or len(s) == 0:
        return rows
    for idx, val in s.items():
        if pd.isna(val):
            continue
        ts = pd.Timestamp(idx)
        ts = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
        rows.append((zone, series_name, ts.to_pydatetime(), float(val)))
    return rows


def _frame_to_rows(zone: str, prefix: str, df: "pd.DataFrame") -> list[tuple]:
    """DataFrame -> rows, one series per column: '<prefix>.<column-slug>'."""
    rows: list[tuple] = []
    if df is None or getattr(df, "empty", True):
        return rows
    for col in df.columns:
        label = ".".join(map(str, col)) if isinstance(col, tuple) else str(col)
        rows += _series_to_rows(zone, f"{prefix}.{_slug(label)}", df[col])
    return rows


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class EntsoeClient:
    """Thin, reusable wrapper around entsoe-py (lazy-imported)."""

    def __init__(self, token: str | None = None):
        from entsoe import EntsoePandasClient  # lazy: module imports without entsoe

        self._c = EntsoePandasClient(api_key=token or config.require("ENTSOE_API_TOKEN"))

    # -- throttled + retried API call ------------------------------------- #
    def _call(self, fn, area, start, end):
        from tenacity import retry, stop_after_attempt, wait_exponential

        @retry(wait=wait_exponential(multiplier=1, max=10),
               stop=stop_after_attempt(3), reraise=True)
        def go():
            global _last_call_ts
            wait = _MIN_INTERVAL_S - (time.monotonic() - _last_call_ts)
            if wait > 0:
                time.sleep(wait)
            _last_call_ts = time.monotonic()
            return fn(area, start=start, end=end)

        return go()

    def _try(self, label, fn, area, start, end):
        """Run one query; on no-data / transient failure, log and return None."""
        try:
            return self._call(fn, area, start, end)
        except Exception as exc:  # NoMatchingDataError and friends
            log.warning("%s unavailable for %s: %s", label, area, exc)
            return None

    # -- fetch ------------------------------------------------------------ #
    def fetch_market_data(self, zone: str, start, end) -> list[tuple]:
        area = config.ZONES[zone]["entsoe_area"]
        rows: list[tuple] = []
        rows += _series_to_rows(
            zone, SERIES_PRICE,
            self._try("day-ahead price", self._c.query_day_ahead_prices, area, start, end))
        rows += _frame_to_rows(
            zone, SERIES_LOAD_FC,
            self._try("load forecast", self._c.query_load_forecast, area, start, end))
        rows += _frame_to_rows(
            zone, SERIES_WIND_SOLAR_FC,
            self._try("wind/solar forecast", self._c.query_wind_and_solar_forecast, area, start, end))
        rows += _frame_to_rows(
            zone, SERIES_GENERATION,
            self._try("generation", self._c.query_generation, area, start, end))
        return rows

    def fetch_generation_unit_outages(self, zone: str, start, end):
        area = config.ZONES[zone]["entsoe_area"]
        return self._try(
            "outages", self._c.query_unavailability_of_generation_units, area, start, end)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _window(start, end):
    end = pd.Timestamp(end, tz=_TZ) if end is not None else pd.Timestamp.now(tz=_TZ) + timedelta(days=1)
    start = pd.Timestamp(start, tz=_TZ) if start is not None else end - timedelta(days=8)
    return start, end


def ingest(zones: list[str] | None = None, start=None, end=None) -> int:
    """Fetch all series for the given zones and upsert into Neon. Returns row count."""
    if config.CORPUS_FROZEN:
        raise RuntimeError("Corpus is frozen (U1.4). Set CORPUS_FROZEN=False to rebuild.")
    config.set_seeds()
    zones = zones or list(config.ZONES)
    start, end = _window(start, end)
    conn = db.get_connection()
    try:
        db.init_market_schema(conn)
        total = 0
        for zone in zones:
            rows = EntsoeClient().fetch_market_data(zone, start, end)
            total += db.upsert_market_data(conn, rows)
            odf = EntsoeClient().fetch_generation_unit_outages(zone, start, end)
            db.upsert_outages(conn, zone, odf)
            log.info("ingested %s: %d market rows", zone, len(rows))
        return total
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    n = ingest()
    print(f"Ingested {n} market-data rows across {len(config.ZONES)} zones.")
