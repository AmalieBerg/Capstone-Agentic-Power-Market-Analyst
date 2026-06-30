"""Structured event extraction (U2.1).

Turns one raw outage message (a row from the `messages` table, U1.2) into a
validated `OutageEvent`. The LLM does *only* the natural-language part — it
reads the message text and returns {asset, capacity_mw, fuel, start, end}.
Everything we already know structurally (zone, source URL, source id) is filled
deterministically from the row, never trusted to the model.

Contract notes:
  - OutageEvent is the contract between extraction, the structured store (U3.2)
    and the agent. `source_id` links each event back to its `messages` row so
    U4.1 can cite it precisely.
  - Failures (bad JSON / failed validation) are collected and logged, never
    raised to the caller — one bad message must not stop a batch (AC: log failures).
  - One message -> one event (the dominant case for REMIT UMMs and the
    structured-outage fallback). Multi-unit messages are a known Sprint-2 refinement.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ValidationError, field_validator

logger = logging.getLogger(__name__)

# Fields the LLM is allowed to return. Anything else is ignored.
_LLM_FIELDS = ("asset", "capacity_mw", "fuel", "start", "end")


class OutageEvent(BaseModel):
    asset: str
    zone: str
    capacity_mw: float | None = None
    fuel: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    source_url: str
    source_id: str
    @field_validator("asset", mode="before")
    @classmethod
    def _default_asset(cls, v):
        return v or "unknown unit"

@dataclass
class ExtractionFailure:
    source_id: str
    source_url: str
    reason: str
    raw_response: str


def build_extraction_prompt(title: str, body: str, zone: str) -> str:
    """Build the extraction prompt for one message. Deterministic (no randomness)."""
    text = "\n".join(p for p in (title, body) if p).strip()
    return (
        "You extract a single power-plant outage from a market message.\n"
        f"The message concerns bidding zone {zone}.\n\n"
        "Return ONLY a JSON object, no prose, no markdown fences, with EXACTLY these keys:\n"
        '  "asset"        - the unit/plant name as a string (required, never null)\n'
        '  "capacity_mw"  - affected capacity in MW as a number, or null\n'
        '  "fuel"         - fuel/technology (e.g. Nuclear, Lignite, Gas, Wind), or null\n'
        '  "start"        - outage start as ISO-8601 (e.g. 2026-06-15T22:00:00+00:00), or null\n'
        '  "end"          - outage end as ISO-8601, or null\n\n'
        "If a value is not stated, use null. Do not invent values.\n\n"
        f"MESSAGE:\n{text}\n"
    )


def parse_extraction_response(text: str) -> dict:
    """Strip optional code fences, parse JSON, return only the allowed LLM fields.

    Raises ValueError on anything that isn't a JSON object.
    """
    s = text.strip()
    if s.startswith("```"):
        # drop ```json ... ``` (or plain ``` ... ```) fences
        s = s.split("```", 2)
        s = s[1] if len(s) >= 2 else text
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
        s = s.strip().rstrip("`").strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"expected a JSON object, got {type(obj).__name__}")
    return {k: obj.get(k) for k in _LLM_FIELDS}


def merge_event_fields(parsed: dict, row: dict) -> dict:
    """Combine LLM fields with the trusted row fields into OutageEvent kwargs.

    zone / source_url / source_id come from the row, not the model. Empty strings
    are normalised to None so optional datetime/float fields validate cleanly.
    """
    def clean(v):
        return None if isinstance(v, str) and v.strip() == "" else v

    return {
        "asset": (parsed.get("asset") or "").strip() or None,  # required -> None triggers validation error if missing
        "capacity_mw": clean(parsed.get("capacity_mw")),
        "fuel": clean(parsed.get("fuel")),
        "start": clean(parsed.get("start")),
        "end": clean(parsed.get("end")),
        "zone": row["zone"],
        "source_url": row.get("url") or row.get("source_url") or "",
        "source_id": row["id"],
    }


def extract_event(row: dict, complete) -> OutageEvent:
    """Extract one OutageEvent from a message row. May raise ValueError/ValidationError."""
    prompt = build_extraction_prompt(row.get("title", ""), row.get("body", ""), row["zone"])
    raw = complete(prompt)
    parsed = parse_extraction_response(raw)
    kwargs = merge_event_fields(parsed, row)
    return OutageEvent(**kwargs)


def extract_events(rows: list[dict], complete) -> tuple[list[OutageEvent], list[ExtractionFailure]]:
    """Extract events for a batch of message rows. Failures are logged, not raised."""
    events: list[OutageEvent] = []
    failures: list[ExtractionFailure] = []
    for row in rows:
        sid = str(row.get("id", "?"))
        surl = row.get("url") or row.get("source_url") or ""
        raw = ""
        try:
            prompt = build_extraction_prompt(row.get("title", ""), row.get("body", ""), row["zone"])
            raw = complete(prompt)
            parsed = parse_extraction_response(raw)
            kwargs = merge_event_fields(parsed, row)
            events.append(OutageEvent(**kwargs))
        except (ValueError, ValidationError) as exc:
            fail = ExtractionFailure(source_id=sid, source_url=surl, reason=str(exc), raw_response=raw)
            failures.append(fail)
            logger.warning("extraction failed for message %s: %s", sid, exc)
    logger.info("extracted %d events, %d failures from %d messages",
                len(events), len(failures), len(rows))
    return events, failures


# --------------------------------------------------------------------------- #
# Structured path (U3.2): ENTSO-E outages are ALREADY structured, so map them
# straight to events — no LLM call, no parse risk, exact source data.
# --------------------------------------------------------------------------- #
def _structured_event_fields(outage_id: str, zone: str, raw: dict) -> dict:
    """Build OutageEvent kwargs from one entsoe_outages row.

    source_id MUST mirror outages._outage_row_to_record's message id so the event
    joins back to its rendered `messages` row (citation + retrieval dedupe).
    """
    import hashlib

    mid = hashlib.sha1(f"entsoe_outage|{outage_id}".encode("utf-8")).hexdigest()
    cap = raw.get("nominal_power")
    try:
        cap = float(cap) if cap not in (None, "") else None
    except (TypeError, ValueError):
        cap = None
    return {
        "asset": raw.get("production_resource_name") or raw.get("production_resource_id") or "unknown",
        "zone": zone,
        "capacity_mw": cap,
        "fuel": raw.get("plant_type"),
        "start": raw.get("start"),
        "end": raw.get("end"),
        "source_url": "",
        "source_id": mid,
    }


def events_from_structured_outages(rows) -> list:
    """rows: iterable of (outage_id, zone, raw_dict) from db.read_entsoe_outages.
    Returns OutageEvents built directly — no LLM."""
    return [OutageEvent(**_structured_event_fields(oid, zone, raw)) for oid, zone, raw in rows]