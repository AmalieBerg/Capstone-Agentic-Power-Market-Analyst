"""Dry-run the tightened news relevance gate against the CURRENT corpus.

Reads news messages from the DB, runs the REAL gate functions from
src.ingestion.outages against each, and prints what would be KEPT vs DROPPED.
Changes nothing — safe to run while the corpus is frozen.

    python dryrun_gate.py            # summary + full keep/drop lists
    python dryrun_gate.py drop       # only the DROP list
    python dryrun_gate.py keep       # only the KEEP list
"""
from __future__ import annotations

import sys
from src.index import db
from src.ingestion.outages import _is_energy_relevant, _is_energy_headline

NEWS = ("gnews", "clew", "guardian")
# Guardian is full-text -> use the stricter headline gate; others use the summary gate.
STRICT = ("guardian",)


def _rows(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, zone, source, title, body FROM messages "
            "WHERE source = ANY(%s) ORDER BY source, zone", (list(NEWS),)
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _verdict(r) -> bool:
    gate = _is_energy_headline if r["source"] in STRICT else _is_energy_relevant
    return gate(r.get("title", ""), r.get("body", ""))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    conn = db.get_connection()
    try:
        rows = _rows(conn)
    finally:
        conn.close()

    keep = [r for r in rows if _verdict(r)]
    drop = [r for r in rows if not r in keep]

    print(f"news items: {len(rows)}  ->  KEEP {len(keep)}   DROP {len(drop)}\n")

    def show(label, items):
        print(f"===== {label} ({len(items)}) =====")
        for r in items:
            print(f"[{r['source']:8s} {r['zone']:6s}] {r.get('title','')[:95]}")
        print()

    if mode in ("all", "drop"):
        show("DROP", drop)
    if mode in ("all", "keep"):
        show("KEEP", keep)

    # per-source breakdown so you see if one source is over/under-filtered
    print("===== by source =====")
    for s in NEWS:
        k = sum(1 for r in keep if r["source"] == s)
        d = sum(1 for r in drop if r["source"] == s)
        print(f"  {s:8s} keep {k:3d}  drop {d:3d}")


if __name__ == "__main__":
    main()