from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/schemas/schemas.py",
    "app/main.py",
    "app/core/seo_pages.py",
    "app/core/polish_counts.py",
    "app/static/app.js",
    "app/static/game_page.js",
    "app/static/panel.js",
    "app/static/i18n.js",
    "app/static/style.css",
    "scripts/validate_sitemaps.py",
    "tests/test_store_classification_consistency.py",
    "tests/test_polish_counts.py",
]


def main() -> int:
    client = _connect()
    sftp = client.open_sftp()
    for rel in FILES:
        remote = f"{REMOTE}/{rel}"
        client.exec_command(f"mkdir -p {remote.rsplit('/', 1)[0]}")
        sftp.put(str(LOCAL / rel), remote)
        print("OK", rel)
    sftp.close()

    cmd = r'''
systemctl restart kupujpl-games
sleep 2
systemctl is-active kupujpl-games
cd /opt/kupujpl-games && python3 - <<'PY'
# unit-ish imports without pytest
from app.core.store_classification import StoreClass, classify_store
from app.core.shops_trust import shop_trust_badge
from app.schemas.schemas import OfferResponse
from datetime import datetime
assert classify_store("Instant Gaming") is StoreClass.AUTHORIZED_RESELLER
assert classify_store("Fanatical") is StoreClass.AUTHORIZED_RESELLER
b = shop_trust_badge("Instant Gaming", is_official=False)
assert b["store_class"] == "AUTHORIZED_RESELLER" and b["label"] == "Autoryzowany"
OfferResponse(id=1, game_id=1, shop_name="Instant Gaming", price_pln=1.0, affiliate_url="https://x", is_official=False, in_stock=True, updated_at=datetime.utcnow(), store_class="AUTHORIZED_RESELLER")
print("local_asserts_ok")
PY
cd /opt/kupujpl-games && python3 -m scripts.validate_sitemaps --sample 20 --workers 2 2>&1 | tail -n 40
cd /opt/kupujpl-games && python3 <<'PY'
import re, urllib.request, ssl, json, random
from app.core.database import SessionLocal
from app.models.models import Game
from app.core.canonical_price import get_current_min_price
ctx=ssl.create_default_context()
UA='Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
CH='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'

def get(u, ua=UA):
    req=urllib.request.Request(u, headers={'User-Agent':ua,'Cache-Control':'no-cache'})
    with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
        return r.status, r.read().decode('utf-8','replace'), dict(r.headers)

# robots chrome
st,b,h=get('https://kupujpl.pl/robots.txt', CH)
print('robots', st, h.get('Content-Type'), 'Allow /games/' in b)

# homepage
st,html,_=get('https://kupujpl.pl/games/')
h2=html.find('id="games-heading"'); card=html.find('ssr-game-card')
print('home', st, 'h1', len(re.findall(r'<h1', html, re.I)), 'ssr', html.count('ssr-game-card'), 'h2_before', h2!=-1 and card!=-1 and h2<card)

# privacy
st,priv,_=get('https://kupujpl.pl/games/polityka-prywatnosci')
print('privacy', st, 'hash', 'hashu' in priv or 'skrótu' in priv, 'encrypt', 'zaszyfrowanej' in priv)

# API store_class
for slug in ['frostpunk-2','elden-ring']:
    st,body,_=get(f'https://kupujpl.pl/games/api/games/{slug}', CH)
    d=json.loads(body)
    for o in d.get('offers') or []:
        if o.get('shop_name') in ('Instant Gaming','Fanatical','Steam','G2A'):
            print('API', slug, o['shop_name'], 'label', o.get('trust_label'), 'class', o.get('store_class'))

# indexability sample
for path in ['/games/','/games/promocje','/games/regulamin','/games/polityka-prywatnosci','/games/blog','/games/gra/frostpunk-2']:
    st,body,h=get('https://kupujpl.pl'+path)
    robots=re.search(r'name=["\']robots["\'][^>]*content=["\']([^"\']+)', body, re.I)
    print('idx', path, st, robots.group(1) if robots else '-', 'xrobots', h.get('X-Robots-Tag'))

# prices
promo=get('https://kupujpl.pl/games/promocje')[1]
db=SessionLocal()
named=['frostpunk-2','black-myth-wukong-2358720','elden-ring','12-is-better-than-6-410110','crazy-machines-3-351920']
okn=0
for slug in named:
    g=db.query(Game).filter(Game.slug==slug).first()
    p,_=get_current_min_price(db,g)
    low=re.findall(r'"lowPrice"\s*:\s*"?([0-9.]+)', get(f'https://kupujpl.pl/games/gra/{slug}')[1])
    schema=float(low[0]) if low else None
    listed=None
    if slug in promo:
        m=re.search(re.escape(slug)+r'[\s\S]{0,900}?(\d+[.,]\d{2})\s*z', promo, re.I)
        if m: listed=float(m.group(1).replace(',','.'))
    match = p is not None and schema is not None and abs(p-schema)<0.05 and (listed is None or abs(listed-p)<0.05)
    print('PRICE', slug, p, schema, listed, match)
    if match: okn+=1
links=list(dict.fromkeys(re.findall(r'gra/([a-z0-9-]+)', promo)))
random.seed(19)
sample=links if len(links)<=20 else random.sample(links,20)
mism=0; checked=0
for slug in sample:
    g=db.query(Game).filter(Game.slug==slug).first()
    if not g: continue
    p,_=get_current_min_price(db,g)
    if p is None: continue
    m=re.search(re.escape(slug)+r'[\s\S]{0,900}?(\d+[.,]\d{2})\s*z', promo, re.I)
    if not m: continue
    listed=float(m.group(1).replace(',','.'))
    checked+=1
    if abs(listed-p)>0.05:
        mism+=1
        print('MISMATCH', slug, listed, p)
print('named_ok', okn, '/', len(named), 'random', checked, 'mismatches', mism)
db.close()
print('DONE')
PY
'''
    _i, stdout, stderr = client.exec_command(cmd, timeout=360)
    sys.stdout.buffer.write(stdout.read())
    err = stderr.read()
    if err.strip():
        sys.stdout.buffer.write(b"\nSTDERR\n")
        sys.stdout.buffer.write(err[:4000])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
