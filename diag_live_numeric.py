from src.index import db
from src.agent import run_agent

conn = db.get_connection()
try:
    tests = [
        ("What's the current day-ahead price in DE-LU?", "DE-LU"),
        ("What's the current generation mix in DK1?", "DK1"),
    ]
    for q, z in tests:
        r = run_agent(q, conn, zone=z)
        print("---", q)
        print("used_tool:", r["used_tool"], "refused:", r["refused"])
        print("answer:", r["answer"][:300])
finally:
    conn.close()