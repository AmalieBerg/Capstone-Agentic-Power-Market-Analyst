"""Find the Clean Energy Wire RSS feed URL. Run from repo root:  python diag_clew.py"""
import re
import requests

HEADERS = {"User-Agent": "capstone-diag/1.0"}

# 1) scrape the news page for any rss/feed/atom link
r = requests.get("https://www.cleanenergywire.org/news", timeout=30, headers=HEADERS)
print("news page HTTP", r.status_code)
hrefs = re.findall(r'href="([^"]*(?:rss|feed|atom)[^"]*)"', r.text, flags=re.I)
print("candidate feed links:", sorted(set(hrefs))[:10] or "none found in page")

# 2) also probe the common conventional paths directly
for path in ("/rss.xml", "/rss", "/feed", "/news/rss", "/en/rss.xml"):
    url = "https://www.cleanenergywire.org" + path
    try:
        resp = requests.get(url, timeout=20, headers=HEADERS)
        n_items = resp.text.count("<item") + resp.text.count("<entry")
        print(f"{url}  ->  HTTP {resp.status_code}, items/entries {n_items}")
    except requests.RequestException as e:
        print(f"{url}  ->  ERROR {e}")