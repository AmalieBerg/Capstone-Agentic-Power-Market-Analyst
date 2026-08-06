from src.ingestion.entsoe_client import EntsoeClient
import pandas as pd
end = pd.Timestamp.now(tz="Europe/Brussels")
start = end - pd.Timedelta(hours=6)
rows = EntsoeClient().fetch_market_data("DE-LU", start, end)
print(len(rows), rows[:3])