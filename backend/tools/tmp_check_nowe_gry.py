"""Compare Steam newreleases vs site nowe-gry category."""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"D:\CursorProjects\kupujpl-games\backend")
from app.parsers.steam_lists import fetch_steam_search_page, get_steam_list_items, refresh_steam_list
from app.core.game_catalog_filter import filter_steam_list_items, fetch_steam_list_page_items
from app.core.database import SessionLocal

# Fresh from Steam
items, total = fetch_steam_search_page(filter_name="newreleases", count=50)
print("=== Steam newreleases (first 50) ===")
print("total_count:", total)
for i, it in enumerate(items[:30], 1):
    title = it.get("title", "?")
    appid = it.get("appid")
    flag = " *** GTA ***" if "grand theft" in title.lower() or appid in (271590, 3240220) else ""
    print(f"{i:2}. [{appid}] {title}{flag}")

# Cached list
cached_path = Path(r"D:\CursorProjects\kupujpl-games\backend\tmp\steam_lists\nowe-gry.json")
if cached_path.is_file():
    data = json.loads(cached_path.read_text(encoding="utf-8"))
    cached = data.get("items") or []
    print("\n=== Cached nowe-gry.json (first 30) ===")
    for i, it in enumerate(cached[:30], 1):
        title = it.get("title", "?")
        appid = it.get("appid")
        flag = " *** GTA ***" if "grand theft" in title.lower() or appid in (271590, 3240220) else ""
        print(f"{i:2}. [{appid}] {title}{flag}")

# What site API would return after filters
db = SessionLocal()
try:
    refresh_steam_list("nowe-gry", db)
    items2, _ = get_steam_list_items("nowe-gry", db, force_refresh=True)
    page_items, total_f = fetch_steam_list_page_items(
        db, items2, page=1, limit=48, min_reviews=100, fetch_metadata=True
    )
    print("\n=== Site page 1 after catalog filters ===")
    print("total estimate:", total_f, "shown:", len(page_items))
    games = {g.steam_appid: g for g in db.query(__import__('app.models.models', fromlist=['Game']).Game).filter(
        __import__('app.models.models', fromlist=['Game']).Game.steam_appid.in_([x.get('appid') for x in page_items])
    ).all()}
    for i, it in enumerate(page_items[:30], 1):
        g = games.get(it.get("appid"))
        title = (g.title if g else None) or it.get("title")
        print(f"{i:2}. [{it.get('appid')}] {title}")
finally:
    db.close()
