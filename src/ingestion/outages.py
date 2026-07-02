"""Outage disclosure ingestion (U1.2): REMIT/ACER Urgent Market Messages (UMM).

Pulls outage *messages* (text) into the Neon `messages` table — the primary
retrieval corpus (chunked + embedded in U3.1) and the input to extraction
(U2.1). Text is loaded at runtime and stored in Neon, NOT committed to the
repo (D4).

Two feed shapes are supported in config.OUTAGE_FEEDS:
  1. Fixed-zone   {"zone": "NO2", "source": "...", "url": "..."}
       zone is tagged from the feed (e.g. Nord Pool per-area RSS).
  2. Content-zone {"zone_from": "content", "source": "...", "url": "..."}
       zone is read from each message by matching configured bidding-zone EICs
       (e.g. the German IIP electricity Atom feed); messages outside
       config.ZONES are skipped.

Fallback: if no feeds are configured, render the ENTSO-E structured outages
already stored by U1.1 as text messages, so the pipeline is runnable today.

Run a manual ingest:
    python -m src.ingestion.outages
"""
from __future__ import annotations

import calendar
import hashlib
import html
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import config
from src.index import db

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested offline — no network, no feedparser)
# --------------------------------------------------------------------------- #
def _strip_html(text: str | None) -> str:
    """Remove tags and unescape entities, collapsing whitespace."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()

ENERGY_TERMS = ("energy", "electric", "power", "grid", "renewable",
                "wind", "solar", "nuclear", "gas", "coal", "hydro",
                "MW", "GW", "price", "outage", "capacity", "emission")

# Power-system terms: at least one must appear (whole-word). These are
# specific to electricity/power markets, excluding leaky macro terms
# like "oil", "gas", "price", "energy" that pull in geopolitics/economics.
POWER_TERMS = ("electricity", "electrical", "power plant", "power station",
               "grid", "generation", "generator", "megawatt", "gigawatt",
               "mw", "gw", "outage", "blackout", "renewable", "renewables",
               "wind power", "wind farm", "solar", "photovoltaic", "nuclear",
               "hydropower", "turbine", "transmission", "interconnector",
               "power market", "day-ahead", "capacity market", "tso",
               "power price", "electricity price", "power supply", "power grid")

_POWER_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in POWER_TERMS) + r")\b", re.IGNORECASE
)


def _is_energy_relevant(title: str, body: str) -> bool:
    """News gate (short-summary sources: gnews, clew). Requires a whole-word
    power-system term in title+summary. Rejects macro/geopolitics that merely
    mention 'oil'/'gas'/'energy costs'."""
    return bool(_POWER_RE.search(f"{title} {body}"))

def _is_energy_headline(title: str, body: str) -> bool:
    """Stricter gate for full-text sources (Guardian): the power-system term
    must appear in the title or lead (~first 400 chars), not deep in the body."""
    lead = f"{title or ''} {(body or '')[:400]}"
    return bool(_POWER_RE.search(lead))

def _eic_index() -> dict[str, str]:
    """Map every in-scope bidding-zone / control-area EIC -> zone label."""
    index: dict[str, str] = {}
    for zone, meta in config.ZONES.items():
        for code in [meta.get("eic"), *meta.get("match_eics", [])]:
            if code:
                index[code] = zone
    return index

def _zone_from_text(text: str | None, index: dict[str, str] | None = None) -> str | None:
    """Return our zone label if the text contains one of our bidding-zone EICs."""
    if not text:
        return None
    index = index if index is not None else _eic_index()
    for eic, zone in index.items():
        if eic in text:
            return zone
    return None


def _parse_published(entry) -> datetime | None:
    """Best-effort publish time -> tz-aware UTC datetime, or None."""
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st is not None:
            try:
                return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                pass
    for key in ("published", "updated", "date"):
        raw = entry.get(key)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (TypeError, ValueError):
                pass
    return None


def _entry_to_record(zone: str | None, source: str, entry) -> dict:
    """Normalise one feed entry (Mapping) into a messages-table record."""
    title = _strip_html(entry.get("title"))
    body = _strip_html(entry.get("summary") or entry.get("description"))
    url = entry.get("link") or entry.get("id") or ""
    published = _parse_published(entry)
    raw_id = (
        entry.get("id")
        or entry.get("guid")
        or url
        or f"{title}|{published.isoformat() if published else ''}"
    )
    mid = hashlib.sha1(f"{source}|{raw_id}".encode("utf-8")).hexdigest()
    return {
        "id": mid, "zone": zone, "source": source, "url": url,
        "title": title, "body": body, "published_at": published,
    }


def _outage_row_to_record(outage_id: str, zone: str, raw: dict) -> dict:
    """Render one stored ENTSO-E structured outage (raw dict) as a text message."""
    lines = [f"{k}: {v}" for k, v in raw.items() if v not in (None, "", "nan")]
    body = "Structured generation-unit outage (ENTSO-E).\n" + "\n".join(lines)
    published = None
    for k in ("start", "Start", "created_doc_time"):
        if raw.get(k):
            try:
                published = parsedate_to_datetime(str(raw[k]))
                break
            except (TypeError, ValueError):
                published = None
    mid = hashlib.sha1(f"entsoe_outage|{outage_id}".encode("utf-8")).hexdigest()
    return {
        "id": mid, "zone": zone, "source": "entsoe_outage", "url": "",
        "title": f"Generation outage — {zone}", "body": body,
        "published_at": published,
    }


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #
def fetch_feed(feed: dict) -> list[dict]:
    """Fetch + normalise one feed (fixed-zone or content-zone).

    The bytes are fetched with an explicit timeout (with retries for flaky hosts)
    and handed to feedparser as content — feedparser.parse(url) does its own fetch
    with NO timeout and can hang indefinitely. A failed feed is skipped, not fatal.
    """
    import feedparser  # lazy
    import requests

    url = feed["url"]
    source = feed.get("source", "umm")
    derive = feed.get("zone_from") == "content"
    fixed_zone = feed.get("zone")
    index = _eic_index()

    resp = None
    for attempt in (1, 2, 3):
        try:
            resp = requests.get(url, timeout=(5, 30))
            resp.raise_for_status()
            break
        except requests.RequestException as exc:
            log.warning("feed %s attempt %d/3 failed: %s", source, attempt, exc)
            resp = None
    if resp is None:
        log.warning("feed %s unreachable after retries, skipping", source)
        return []
    
    if feed.get("format") == "remit_xml":
        parsed_feed = feedparser.parse(resp.content)
        records, skipped = _remit_entries_to_records(parsed_feed.entries, source, index)
        log.info("feed %s: %d kept, %d skipped (out-of-scope zone)", source, len(records), skipped)
        return records

    parsed = feedparser.parse(resp.content)
    records, skipped = [], 0
    for e in parsed.entries:
        if derive:
            blob = " ".join(
                v for v in (e.get("title"), e.get("summary"), e.get("description")) if v
            )
            zone = _zone_from_text(blob, index)
            if zone is None:
                skipped += 1
                continue
        else:
            zone = fixed_zone
        rec = _entry_to_record(zone, source, e)
        if source in ("gnews", "clew") and not _is_energy_relevant(
            rec.get("title", ""), rec.get("body", "")
        ):
            skipped += 1
            continue
        records.append(rec)
    log.info("feed %s: %d kept, %d skipped (out-of-scope zone)", source, len(records), skipped)
    return records


def render_entsoe_outages_as_messages(conn, zones=None) -> list[dict]:
    """Fallback corpus: stored structured outages -> text messages."""
    rows = db.read_entsoe_outages(conn, zones)
    return [_outage_row_to_record(oid, zone, raw) for (oid, zone, raw) in rows]

def _remit_record(parsed: dict, source: str, zone: str) -> dict:
    """Turn one parsed REMIT UMM (remit.parse_remit_umm) into a messages record.
 
    Body is human-readable text — the narrative `reason` is the value ENTSO-E
    lacks — so it chunks/embeds well; structured fields stay available for events.
    """
    asset = parsed.get("asset") or "unknown unit"
    cap = parsed.get("unavailable_mw")
    parts = [
        f"{parsed.get('event_type') or 'Unavailability'} — {asset}.",
        f"Unavailable capacity: {cap} MW." if cap else "",
        f"Fuel: {parsed['fuel']}." if parsed.get("fuel") else "",
        f"Type: {parsed.get('unavailability_type')}." if parsed.get("unavailability_type") else "",
        f"Reason: {parsed['reason']}." if parsed.get("reason") else "",
        f"Window: {parsed.get('start')} to {parsed.get('end')}." if parsed.get("start") else "",
        f"Participant: {parsed['participant']}." if parsed.get("participant") else "",
    ]
    body = " ".join(p for p in parts if p)
    mid = hashlib.sha1(f"{source}|{parsed.get('message_id')}".encode("utf-8")).hexdigest()
    published = None
    if parsed.get("start"):
        try:
            published = datetime.fromisoformat(parsed["start"])
        except (TypeError, ValueError):
            published = None
    return {
        "id": mid, "zone": zone, "source": source, "url": "",
        "title": f"REMIT outage — {asset} ({zone})", "body": body,
        "published_at": published,
    }
 
 
def _remit_entries_to_records(entries, source: str, index: dict) -> tuple[list[dict], int]:
    """Parse REMIT-XML Atom entries -> records, keeping only in-scope bidding zones."""
    from src.ingestion import remit
 
    records, skipped = [], 0
    for e in entries:
        xml = e.get("summary") or e.get("description") or ""
        try:
            parsed_list = remit.parse_remit_umm(xml)
        except Exception as exc:  # malformed XML: skip this entry, keep going
            log.warning("REMIT parse failed for one entry in %s: %s", source, exc)
            continue
        for parsed in parsed_list:
            zone = index.get(parsed.get("bidding_zone"))
            if zone is None:
                skipped += 1
                continue
            records.append(_remit_record(parsed, source, zone))
    return records, skipped

# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def ingest(zones: list[str] | None = None, conn=None) -> int:
    """Ingest outage messages into Neon. Returns number of records upserted.

    Union of two sources, not either/or:
      - structured ENTSO-E outages rendered as messages (the only source for
        zones with no UMM feed, e.g. DE-LU)
      - any configured UMM feeds (real disclosure text, e.g. Nord Pool NO2/DK1)
    """
    if config.CORPUS_FROZEN:
        raise RuntimeError("Corpus is frozen (U1.4). Set CORPUS_FROZEN=False to rebuild.")
    own = conn is None
    conn = conn or db.get_connection()
    try:
        db.init_messages_schema(conn)
        total = 0

        # 1) always render structured outages -> messages (covers DE-LU)
        total += db.upsert_messages(conn, render_entsoe_outages_as_messages(conn, zones))

        # 2) plus any configured feeds (real UMM text)
        feeds = []
        for f in config.OUTAGE_FEEDS:
            if f.get("zone_from") == "content":
                feeds.append(f)                       # self-filters by message content
            elif (not zones) or f.get("zone") in zones:
                feeds.append(f)
        for f in feeds:
            total += db.upsert_messages(conn, fetch_feed(f))

        if not feeds:
            log.info("No matching UMM feeds; corpus is structured outages only.")
        return total
    finally:
        if own:
            conn.close()

def fetch_guardian(feed: dict) -> list[dict]:
    """Guardian Content API -> message records (full bodyText, open licence)."""
    import requests
    key = config.GUARDIAN_API_KEY
    if not key:
        log.warning("guardian: no API key, skipping")
        return []
    params = {
        "q": f"({feed['query']}) AND NOT (review OR theatre OR music OR concert OR diary OR playlist)",
        "from-date": config.SNAPSHOT_START,
        "to-date": config.SNAPSHOT_END,
        "show-fields": "bodyText,trailText",
        "page-size": 50,
        "api-key": key,
    }
    try:
        resp = requests.get("https://content.guardianapis.com/search",
                            params=params, timeout=(5, 30))
        resp.raise_for_status()
        results = resp.json()["response"]["results"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        log.warning("guardian feed failed: %s", exc)
        return []

    records = []
    for a in results:
        fields = a.get("fields", {})
        body = _strip_html(fields.get("bodyText") or fields.get("trailText"))
        if not _is_energy_headline(a.get("webTitle", ""), body):   # <-- stricter gate for full-text
            continue
        published = None
        if a.get("webPublicationDate"):
            try:
                published = datetime.fromisoformat(a["webPublicationDate"].replace("Z", "+00:00"))
            except ValueError:
                published = None
        mid = hashlib.sha1(f"guardian|{a['id']}".encode("utf-8")).hexdigest()
        records.append({
            "id": mid, "zone": feed["zone"], "source": "guardian",
            "url": a.get("webUrl", ""), "title": _strip_html(a.get("webTitle")),
            "body": body, "published_at": published,
        })
    log.info("feed guardian (%s): %d kept", feed["query"], len(records))
    return records


def ingest_news(zones: list[str] | None = None, conn=None) -> int:
    """Ingest query-scoped news into the messages corpus (source != outage)."""
    if config.CORPUS_FROZEN:
        raise RuntimeError("Corpus is frozen (U1.4). Set CORPUS_FROZEN=False to rebuild.")
    own = conn is None
    conn = conn or db.get_connection()
    try:
        db.init_messages_schema(conn)
        total = 0
        for f in config.NEWS_FEEDS:
            if zones and f.get("zone") not in zones:
                continue
            recs = fetch_guardian(f) if f.get("format") == "guardian" else fetch_feed(f)
            total += db.upsert_messages(conn, recs)
        return total
    finally:
        if own:
            conn.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    n = ingest()
    print(f"Ingested {n} outage messages into the corpus.")