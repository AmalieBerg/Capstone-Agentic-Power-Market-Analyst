from src.index import db
from src.extraction.events import extract_events
from src import llm

conn = db.get_connection()
rows = db.read_messages(conn, limit=10)
events, failures = extract_events(rows, llm.complete)

print(len(events), "events,", len(failures), "failures")
for e in events[:3]:
    print(e)