"""Diagnostic: German IIP/REMIT Atom feed for DE-LU.

Run from repo root in .venv:
    python diag_german_feed.py

Answers three questions:
  1. Is the feed reachable and returning entries?
  2. Is the content actually German, or pan-European noise?
  3. Does the DE-LU bidding-zone EIC appear (i.e. would our content-zone
     filter keep anything)?
"""
from __future__ import annotations

import re
from collections import Counter

import requests

DE_LU_EIC = "10Y1001A1001A82H"
EIC_RE = re.compile(r"10Y[A-Z0-9\-]{13}")

# --- resolve feed URL from config, with a known fallback ---
FEED_URL = None
try:
    import config  # noqa: E402
    for attr in ("IIP_ATOM_URL", "DE_FEED_URL", "GERMAN_FEED_URL", "IIP_FEED_URL"):
        if hasattr(config, attr):
            FEED_URL = getattr(config, attr)
            print(f"config.{attr} = {FEED_URL}")
            break
    if hasattr(config, "OUTAGE_FEEDS"):
        print(f"config.OUTAGE_FEEDS = {config.OUTAGE_FEEDS}")
except Exception as e:  # noqa: BLE001
    print(f"(config import note: {e})")

if FEED_URL is None:
    FEED_URL = "https://platform.inside-information.de/electricity/electricity/atom"
    print(f"(using fallback URL)")
print(f"FEED_URL: {FEED_URL}\n")

# --- fetch ---
r = requests.get(
    FEED_URL,
    timeout=(5, 30),
    headers={"User-Agent": "capstone-diag/1.0"},
)
print(f"HTTP {r.status_code} | {len(r.content)} bytes")
text = r.text

# --- global EIC tally (whole payload) ---
tally = Counter(EIC_RE.findall(text))
print(f"\nDistinct 10Y EIC codes in payload: {len(tally)}")
print("Top 15 by frequency:")
for code, n in tally.most_common(15):
    mark = "   <-- DE-LU" if code == DE_LU_EIC else ""
    print(f"  {code}  x{n}{mark}")

print(f"\nDE-LU EIC ({DE_LU_EIC}) present in payload: "
      f"{DE_LU_EIC in tally}  (count {tally.get(DE_LU_EIC, 0)})")

# --- per-entry view (mirrors the content-zone filter) ---
try:
    import feedparser
    fp = feedparser.parse(text)
    n_entries = len(fp.entries)
    de_entries = sum(1 for e in fp.entries if DE_LU_EIC in str(e))
    print(f"\nAtom entries (feedparser): {n_entries}")
    print(f"Entries containing DE-LU EIC: {de_entries} / {n_entries}")
    if fp.entries:
        e = fp.entries[0]
        print("\nSample entry:")
        print(f"  title:   {e.get('title', '')[:120]}")
        print(f"  updated: {e.get('updated', '')}")
        ent_eics = sorted(set(EIC_RE.findall(str(e))))
        print(f"  EICs in entry: {ent_eics or 'none (feedparser may not capture inline REMIT body)'}")
except Exception as e:  # noqa: BLE001
    print(f"\n(feedparser step skipped: {e})")