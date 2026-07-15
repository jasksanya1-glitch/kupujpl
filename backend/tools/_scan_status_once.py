import json
import sqlite3

from app.parsers.offer_scheduler import get_scheduler_status

c = sqlite3.connect("database.db")
c.row_factory = sqlite3.Row
games = c.execute(
    """
    SELECT g.title, g.slug, COUNT(DISTINCT o.shop_name) AS shops, MAX(o.updated_at) AS last_up
    FROM offers o JOIN games g ON g.id = o.game_id
    WHERE o.updated_at >= datetime('now', '-15 minutes')
    GROUP BY g.id ORDER BY last_up DESC LIMIT 8
    """
).fetchall()
print("=== games with fresh offers (last 15 min) ===")
for g in games:
    print(g["last_up"], f"{g['shops']} shops |", g["title"][:55])

s = get_scheduler_status()
print()
print("=== background scheduler ===")
print("active_cycle:", s.get("running"))
lc = s.get("last_cycle") or {}
print("last_finished:", lc.get("finished_at"))
print("last_batch:", lc.get("games_refreshed"), "games /", round(lc.get("duration_sec", 0), 1), "s")
print("shops_hit:", json.dumps(lc.get("offers_by_shop") or {}))
print("interval:", s.get("interval_sec"), "s | cooldown:", s.get("cooldown_hours"), "h")
