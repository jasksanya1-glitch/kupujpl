"""Probe Steam search params for new releases."""
import sys
sys.path.insert(0, r"D:\CursorProjects\kupujpl-games\backend")
from app.parsers.steam_lists import fetch_steam_search_page

cases = [
    {"filter_name": "newreleases", "sort_by": None},
    {"filter_name": "newreleases", "sort_by": "Released_DESC"},
    {"filter_name": "newreleases", "sort_by": "Released_ASC"},
    {"filter_name": "recent", "sort_by": None},
    {"filter_name": "recent", "sort_by": "Released_DESC"},
]

for spec in cases:
    items, total = fetch_steam_search_page(count=20, **spec)
    print("\n=== filter=%r sort=%r total=%s ===" % (spec["filter_name"], spec.get("sort_by"), total))
    for i, it in enumerate(items[:15], 1):
        t = it.get("title", "?")
        flag = " *GTA*" if "grand theft" in t.lower() else ""
        flag += " *CS2*" if it.get("appid") == 730 else ""
        print(f"  {i:2}. [{it.get('appid')}] {t}{flag}")
