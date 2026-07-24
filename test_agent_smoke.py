from src.index import db
from src.agent import run_agent

conn = db.get_connection()
try:
    r1 = run_agent("What's the current day-ahead price in DE-LU?", conn, zone="DE-LU")
    r2 = run_agent("What outages affected DE-LU in June?", conn, zone="DE-LU")
    r3 = run_agent("What's the electricity market like in Texas?", conn)
finally:
    conn.close()

for label, result in [("LIVE PRICE", r1), ("JUNE OUTAGES", r2), ("TEXAS (should refuse)", r3)]:
    print(f"\n--- {label} ---")
    print("ANSWER:", result["answer"])
    print("USED TOOL:", result.get("used_tool"))
    print("CITATIONS:", result["citations"])
    print("REFUSED:", result["refused"])