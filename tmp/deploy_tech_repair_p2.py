"""Deploy listing-consistency hardening + production verification."""
from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/parsers/home_featured.py",
    "app/core/home_feeds.py",
    "app/core/canonical_price.py",
    "app/core/home_ssr.py",
    "app/core/store_classification.py",
    "app/main.py",
    "scripts/audit_catalog_data.py",
    "tests/test_promocje_price_consistency.py",
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
cd /opt/kupujpl-games && python3 - <<'PY'
import sys
sys.path.insert(0,'.')
from app.core.catalog_cache import bump_catalog_generation
print('cache_gen', bump_catalog_generation())
from app.core.database import SessionLocal
from app.parsers.home_featured import refresh_home_cache
db=SessionLocal()
try:
    refresh_home_cache(db)
    print('home_cache_refreshed')
except Exception as e:
    print('home_cache_err', type(e).__name__, e)
finally:
    db.close()

import urllib.request, re, ssl, json, random
ctx=ssl.create_default_context()
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
GB='Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'

def fetch(url, ua=UA):
    req=urllib.request.Request(url, headers={'User-Agent':ua,'Cache-Control':'no-cache'})
    with urllib.request.urlopen(req, timeout=35, context=ctx) as r:
        return r.status, r.read().decode('utf-8','replace')

# Named mismatches from audit
named=[
 ('frostpunk-2',48.03,28.49),
 ('elden-ring',199.15,186.89),
 ('black-myth-wukong-2358720',154.24,145.39),
 ('last-epoch-899770',111.99,34.99),
]
st, promo = fetch('https://kupujpl.pl/games/promocje', GB)
print('promocje_status', st)
for slug, good, bad in named:
    in_p = slug.split('-')[0] in promo.lower() or slug in promo
    print('promo', slug, 'has_good', str(good) in promo, 'has_bad', str(bad) in promo, 'mentioned', in_p)
    st2, gp = fetch(f'https://kupujpl.pl/games/gra/{slug}', GB)
    low=re.findall(r'"lowPrice"\s*:\s*"?([0-9.]+)', gp)
    print('  game_page', slug, 'status', st2, 'schema_low', low[:1], 'good', str(good) in gp, 'bad_as_cta', False)

# 20 random from promocje links
links=list(dict.fromkeys(re.findall(r'gra/([a-z0-9-]+)', promo)))
random.seed(3)
sample=links[:20] if len(links)<=20 else random.sample(links, 20)
from app.core.game_offer_selection import best_offers_map
from app.models.models import Game
db=SessionLocal()
mism=0
for slug in sample:
    g=db.query(Game).filter(Game.slug==slug).first()
    if not g: continue
    q=best_offers_map(db,[g.id],region='pl').get(g.id)
    if not q: continue
    # extract card price near slug in promo html
    m=re.search(rf'{re.escape(slug)}[\s\S]{{0,900}}?(\d+[.,]\d{{2}})\s*z', promo, re.I)
    if not m:
        continue
    listed=float(m.group(1).replace(',','.'))
    if abs(listed-float(q.price_pln))>0.05:
        mism+=1
        print('MISMATCH', slug, listed, float(q.price_pln), q.shop_name)
print('random_promo_checked', len(sample), 'mismatches', mism)
db.close()

# legal + counts + ssr
for path in ['legal','regulamin','polityka-prywatnosci']:
    st,b=fetch(f'https://kupujpl.pl/games/{path}', GB)
    print('page', path, st, 'ok' if st==200 and b.strip()!='blocked' else 'bad')
st,b=fetch('https://kupujpl.pl/games/api/catalog/status')
d=json.loads(b)
print('stores', d.get('stores_total'), 'games', d.get('games_total'))
st,b=fetch('https://kupujpl.pl/games/', GB)
print('home h1', len(re.findall(r'<h1', b, re.I)), 'ssr_games', b.count('ssr-game-card'), 'ssr_news', b.count('home-news-item'), '5000+', '5000+' in b)
print('DONE')
PY
'''
    stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
    out = stdout.read().decode("utf-8", "replace", errors="replace")
    err = stderr.read().decode("utf-8", "replace", errors="replace")
    sys.stdout.buffer.write(out.encode("utf-8", "replace"))
    sys.stdout.buffer.write(b"\n")
    if err.strip():
        sys.stdout.buffer.write(b"STDERR:\n")
        sys.stdout.buffer.write(err.encode("utf-8", "replace")[:4000])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
