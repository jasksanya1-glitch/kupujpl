"""Deploy technical repair batch + verify production."""
from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/parsers/shop_scan_config.py",
    "app/core/price_history.py",
    "app/core/home_ssr.py",
    "app/core/store_classification.py",
    "app/core/seo_landings.py",
    "app/core/site_tracking.py",
    "app/main.py",
    "app/static/i18n.js",
    "app/static/app.js",
    "app/static/index.html",
    "app/data/blog_posts.json",
    "scripts/audit_catalog_data.py",
    "tests/test_seo_landing_prices.py",
    "tests/test_price_history_rollups.py",
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
sleep 3
systemctl is-active kupujpl-games
cd /opt/kupujpl-games && python3 -m pytest tests/test_seo_landing_prices.py tests/test_price_history_rollups.py -q --tb=line 2>&1 | tail -40
cd /opt/kupujpl-games && python3 -m scripts.audit_catalog_data --repair-rollups --no-budget-landing 2>&1 | tail -30
cd /opt/kupujpl-games && python3 <<'PY'
import urllib.request, re, ssl, json
ctx = ssl.create_default_context()

def fetch(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return r.status, dict(r.headers.items()), r.read().decode("utf-8", "replace")

UA_DESK = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
UA_MOB = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
UA_GBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
UA_GBOT_M = "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/W.X.Y.Z Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
UA_SCRAPER = "Mozilla/5.0 (compatible; KupujPLAuditBot/1.0; +https://kupujpl.pl/)"
UA_CURL = "curl/8.0.0"

# catalog status
st, h, b = fetch("https://kupujpl.pl/games/api/catalog/status", UA_DESK)
d = json.loads(b)
print("stores_total", d.get("stores_total"), "games_total", d.get("games_total"), "display", d.get("display_shops"))

# Neo Cab game page vs landing prices
from app.core.database import SessionLocal
from app.models.models import Game
from app.core.game_offer_selection import best_offers_map
from app.core.price_history import _eligible_offer_prices, update_game_price_rollups
from app.core.seo_landings import SeoLanding, collect_landing_items
from app.schemas.schemas import GameListResponse
db=SessionLocal()
g=db.query(Game).filter(Game.slug=="neo-cab-794540").first()
q=best_offers_map(db,[g.id],region="pl")[g.id]
print("neo_quality", q.price_pln, q.shop_name)
print("neo_hist_eligible", _eligible_offer_prices(db,g.id,region="pl"))
update_game_price_rollups(db,g.id)
db.commit()
db.refresh(g)
print("neo_lowest_after", g.lowest_ever_pln, "avg30", g.avg_best_price_30d)

def build_item(game, best, steam):
    return GameListResponse(id=game.id,title=game.title or "",slug=game.slug or "",cover_image=None,steam_appid=game.steam_appid,platform="pc",
        best_price_pln=float(best.price_pln) if best else None, best_shop_name=best.shop_name if best else None,
        best_price_is_official=bool(best.is_official) if best else None)
landing=SeoLanding("gry-pc-do-30-zl","budget","x","cena",max_price=30)
items=collect_landing_items(db,landing,build_item=build_item,limit=60)
print("budget30_count", len(items), "any_037", any(abs((i.best_price_pln or 0)-0.37)<0.01 for i in items))
print("budget_prices_ok", all((i.best_price_pln or 0)>0 for i in items))
db.close()

# UA matrix homepage
for name, ua in [("desk",UA_DESK),("mob",UA_MOB),("gbot",UA_GBOT),("gbotm",UA_GBOT_M),("curl",UA_CURL)]:
    st,h,b=fetch("https://kupujpl.pl/games/", ua)
    h1s=re.findall(r"<h1[^>]*>([\s\S]*?)</h1>", b, re.I)
    h1_txt=[re.sub(r"<[^>]+>","",x).strip() for x in h1s]
    print(name, "status", st, "h1_count", len(h1s), "h1", h1_txt[:2],
          "ssr_games", "ssr-home-games" in b, "ssr_news", "home-news-item" in b,
          "legacy_tpl", "tpl-mobile-home-legacy" in b, "5000+", "5000+" in b,
          "10_sklep", "10 sklep" in b.lower())

# legal
for path in ["regulamin","polityka-prywatnosci","o-nas","kontakt","legal","blog","promocje"]:
    for name,ua in [("gbot",UA_GBOT),("scraper",UA_SCRAPER)]:
        try:
            st,_,b=fetch(f"https://kupujpl.pl/games/{path}", ua)
            print("page", path, name, st, "blocked" if b.strip()=="blocked" else "ok")
        except Exception as e:
            print("page", path, name, type(e).__name__, str(e)[:80])

# robots + sitemaps
for path in ["https://kupujpl.pl/robots.txt","https://kupujpl.pl/games/sitemap.xml","https://kupujpl.pl/games/sitemap-games.xml","https://kupujpl.pl/games/sitemap-categories.xml","https://kupujpl.pl/games/sitemap-deals.xml","https://kupujpl.pl/games/sitemap-blog.xml"]:
    try:
        st,h,b=fetch(path, UA_GBOT)
        ct=h.get("Content-Type") or h.get("content-type")
        print("seo", path.split("/")[-1], st, ct, "xml" if b.lstrip().startswith("<?xml") or b.lstrip().startswith("<urlset") or b.lstrip().startswith("<sitemapindex") or "User-agent" in b[:200] else b[:40].replace("\n"," "))
    except Exception as e:
        print("seo", path, type(e).__name__, str(e)[:80])

# budget landing Neo Cab absent + no 0.37
st,_,b=fetch("https://kupujpl.pl/games/gry-pc-do-30-zl", UA_GBOT)
print("landing30 neo", "neo-cab" in b.lower(), "has_037", "0.37" in b or "0,37" in b)
print("landing30 game_links", len(re.findall(r"href=[\"']/games/gra/|href=[\"']gra/", b)))
PY
'''
    stdin, stdout, stderr = client.exec_command(cmd, timeout=600)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    print(out)
    if err.strip():
        print("STDERR", err[:2000])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
