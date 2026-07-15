import requests
from urllib.parse import urlencode

HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/131", "Accept-Language": "pl-PL,pl;q=0.9"}
BASE = "https://store.steampowered.com/search/results/"

def show(**params):
    p = {"json": 1, "cc": "pl", "l": "polish", "start": 0, "count": 20, "filter": "newreleases", **params}
    r = requests.get(f"{BASE}?{urlencode(p)}", headers=HEADERS, timeout=20)
    items = (r.json().get("items") or []) if r.status_code == 200 else []
    print("\n", params)
    for i, it in enumerate(items[:15], 1):
        name = (it.get("name") or "")[:55]
        print(f"  {i:2}. {name}")

show(sort_by="Released_DESC")
show(sort_by="Released_DESC", category1=998)
show(sort_by="Released_DESC", hidef2p=1)
show(sort_by="Released_DESC", category1=998, hidef2p=1)
