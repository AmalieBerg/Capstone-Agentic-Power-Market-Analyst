"""Browse the frozen corpus while authoring the U8 gold set.

Prints candidate passages grouped by the gold-set categories, each with its
message id, so you can copy real ids into gold.jsonl and write questions that
are actually grounded in the frozen corpus.

Usage:
    python browse_corpus.py                # summary counts + samples per category
    python browse_corpus.py freetext 20    # 20 free-text UMM passages
    python browse_corpus.py news 20        # 20 news passages
    python browse_corpus.py structured 15  # 15 structured outage messages
    python browse_corpus.py crosszonal 20  # messages tagged to >1 zone
    python browse_corpus.py search Skagerrak   # full-text search the corpus
"""
from __future__ import annotations

import sys
from src.index import db

NEWS = ("gnews", "clew", "guardian")
FREETEXT = ("nordpool_umm", "iip_de")


def _rows(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _show(rows, n):
    for r in rows[:n]:
        body = (r.get("body") or "").replace("\n", " ")
        print(f"\n[{r['id']}]  zone={r.get('zone')}  source={r.get('source')}")
        print(f"  TITLE: {r.get('title','')[:100]}")
        print(f"  BODY : {body[:240]}")


def main():
    conn = db.get_connection()
    try:
        arg = sys.argv[1] if len(sys.argv) > 1 else "summary"
        n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 12

        if arg == "summary":
            print("=== corpus by source ===")
            for r in _rows(conn, "SELECT source, count(*) c FROM messages GROUP BY source ORDER BY c DESC"):
                print(f"  {r['source']:16s} {r['c']}")
            print("\n=== free-text sample ===")
            _show(_rows(conn, "SELECT id,zone,source,title,body FROM messages WHERE source = ANY(%s) ORDER BY random()", (list(FREETEXT),)), 3)
            print("\n=== news sample ===")
            _show(_rows(conn, "SELECT id,zone,source,title,body FROM messages WHERE source = ANY(%s) ORDER BY random()", (list(NEWS),)), 3)
            print("\n(use: python browse_corpus.py [freetext|news|structured|crosszonal|search <term>] [N])")

        elif arg == "freetext":
            _show(_rows(conn, "SELECT id,zone,source,title,body FROM messages WHERE source = ANY(%s) ORDER BY zone", (list(FREETEXT),)), n)
        elif arg == "news":
            _show(_rows(conn, "SELECT id,zone,source,title,body FROM messages WHERE source = ANY(%s) ORDER BY zone", (list(NEWS),)), n)
        elif arg == "structured":
            _show(_rows(conn, "SELECT id,zone,source,title,body FROM messages WHERE source='entsoe_outage' ORDER BY zone", ()), n)
        elif arg == "crosszonal":
            rows = _rows(conn,
                "SELECT m.id,m.zone,m.source,m.title,m.body, count(*) OVER (PARTITION BY t.message_id) z "
                "FROM messages m JOIN news_zone_tags t ON t.message_id=m.id", ())
            multi = [r for r in rows if r.get("z", 1) > 1]
            print(f"{len(multi)} rows tagged to >1 zone")
            _show(multi, n)
        elif arg == "search":
            term = sys.argv[2] if len(sys.argv) > 2 else ""
            _show(_rows(conn, "SELECT id,zone,source,title,body FROM messages WHERE body ILIKE %s OR title ILIKE %s", (f"%{term}%", f"%{term}%")), 25)
    finally:
        conn.close()


if __name__ == "__main__":
    main()