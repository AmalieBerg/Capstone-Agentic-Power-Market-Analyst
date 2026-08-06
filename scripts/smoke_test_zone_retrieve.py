"""Smoke-test the new explicit-zone retrieval param. Run: python test_zone_retrieve.py"""
from src.index import db, retrieval

conn = db.get_connection()
try:
    print("=== zone='NO2' ===")
    r = retrieval.retrieve(conn, "grid strain and outages", zone="NO2")
    print(len(r), "hits")
    for x in r:
        print(f"  [{x['zone']:<6}] {(x['title'] or '')[:70]}")

    print("\n=== zone=None (all Europe) ===")
    r2 = retrieval.retrieve(conn, "grid strain and outages")
    print(len(r2), "hits")
    for x in r2:
        print(f"  [{x['zone']:<6}] {(x['title'] or '')[:70]}")
finally:
    conn.close()