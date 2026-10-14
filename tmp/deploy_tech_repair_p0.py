"""Deploy P0/P1 technical repair files and verify Neo Cab + legal + homepage SSR."""
from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/core/seo_landings.py",
    "app/core/site_tracking.py",
    "app/core/home_ssr.py",
    "app/main.py",
    "app/static/app.js",
    "app/static/index.html",
    "app/static/desktop-concept3.css",
    "app/core/seo_pages.py",
    "app/data/blog_posts.json",
    "scripts/audit_catalog_data.py",
    "tests/test_seo_landing_prices.py",
]


def main() -> int:
    client = _connect()
    sftp = client.open_sftp()
    try:
        for rel in FILES:
            lp = LOCAL / rel
            if not lp.is_file():
                print("MISSING", rel)
                continue
            remote = f"{REMOTE}/{rel}"
            # ensure remote dirs
            parts = remote.split("/")[:-1]
            for i in range(3, len(parts) + 1):
                d = "/".join(parts[:i])
                try:
                    sftp.stat(d)
                except OSError:
                    sftp.mkdir(d)
            sftp.put(str(lp), remote)
            print(f"OK {rel}")
    finally:
        sftp.close()

    cmd = r'''
systemctl restart kupujpl-games
sleep 2
systemctl is-active kupujpl-games
cd /opt/kupujpl-games && python3 <<'PY'
import sys
sys.path.insert(0, ".")
from app.core.database import SessionLocal
from app.models.models import Article
from app.core.seo_landings import SeoLanding, collect_landing_items
from app.core.game_offer_selection import best_offers_map
from app.models.models import Game, Offer
from app.schemas.schemas import GameListResponse

# Fix blog wording in DB
db = SessionLocal()
art = db.query(Article).filter(Article.slug == "jak-kupowac-gry-taniej").first()
old = "Klucze globalne działają w Polsce; unikaj wyłącznie regionalnych wersji bez PLN."
new = (
    "Klucze oznaczone jako Global zwykle można aktywować w Polsce, "
    "ale przed zakupem zawsze sprawdź ograniczenia regionu i aktywacji podane przez sprzedawcę."
)
if art and art.content and old in art.content:
    art.content = art.content.replace(old, new)
    db.commit()
    print("blog_fixed", True)
elif art:
    print("blog_fixed", False, "old_phrase_present", old[:40] in (art.content or ""))
else:
    print("blog_missing")

# Landing vs quality for Neo Cab
g = db.query(Game).filter(Game.slug == "neo-cab-794540").first()

def build_item(game, best, steam):
    return GameListResponse(
        id=game.id, title=game.title or "", slug=game.slug or "",
        cover_image=game.cover_image, steam_appid=game.steam_appid, platform="pc",
        best_price_pln=float(best.price_pln) if best else None,
        best_shop_name=best.shop_name if best else None,
        best_price_is_official=bool(best.is_official) if best else None,
        steam_price_pln=float(steam.price_pln) if steam and steam.price_pln else None,
    )

landing = SeoLanding("gry-pc-do-30-zl", "budget", "Gry PC do 30 zł", "cena", max_price=30)
items = collect_landing_items(db, landing, build_item=build_item, limit=60)
neo = next((i for i in items if i.slug == "neo-cab-794540"), None)
q = best_offers_map(db, [g.id], region="pl")[g.id]
print("neo_landing", None if not neo else neo.best_price_pln, neo.best_shop_name if neo else None)
print("neo_quality", q.price_pln, q.shop_name)
print("neo_match", bool(neo and abs(float(neo.best_price_pln) - float(q.price_pln)) < 0.01))
db.close()

import urllib.request, re, ssl
ctx = ssl.create_default_context()

def fetch(url, ua, mobile=None):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Cache-Control": "no-cache"})
    if mobile is not None:
        req.add_header("Sec-CH-UA-Mobile", mobile)
    with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
        return r.status, dict(r.headers.items()), r.read().decode("utf-8", "replace")

UA_SCRAPER = "Mozilla/5.0 (compatible; KupujPLAuditBot/1.0; +https://kupujpl.pl/)"
UA_GBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
UA_DESK = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

for path in ["regulamin", "polityka-prywatnosci"]:
    try:
        st, h, b = fetch(f"https://kupujpl.pl/games/{path}", UA_SCRAPER)
        print(f"legal_scraper {path}", st, "blocked" if b.strip()=="blocked" else "ok")
    except Exception as e:
        print(f"legal_scraper {path}", type(e).__name__, e)

st, h, b = fetch("https://kupujpl.pl/games/gry-pc-do-30-zl", UA_DESK, "?0")
print("budget_neo", re.findall(r"Neo\\s*Cab[^\\d]{0,80}(\\d+[.,]\\d{2})", b, re.I)[:5])
st, h, b = fetch("https://kupujpl.pl/games/?nocache=repair1", UA_DESK, "?0")
print("home_h1", re.findall(r"<h1[^>]*>(.*?)</h1>", b, re.I|re.S)[:2])
print("home_gra_links", len(re.findall(r'href=["\\'](?:\\./)?gra/', b)))
print("home_ssr_games", "ssr-home-games" in b)
print("home_news_item", "home-news-item" in b)
print("home_d3_title_not_dash", 'id="d3-hero-title">—' not in b)
print("app93", "app.js?v=93" in b)
print("css17", "desktop-concept3.css?v=17" in b)

st, h, b = fetch("https://kupujpl.pl/games/api/catalog/status", UA_DESK)
import json
d = json.loads(b)
print("stores_total", d.get("stores_total"), "stores_with_offers", d.get("stores_with_offers"), "games_total", d.get("games_total"))
PY
'''
    _, stdout, stderr = client.exec_command(cmd, timeout=120)
    print(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace").strip()
    if err:
        print("ERR", err[:800])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
