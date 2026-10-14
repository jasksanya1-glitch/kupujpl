from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/core/polish_counts.py",
    "app/core/home_ssr.py",
    "app/core/store_classification.py",
    "app/core/shops_trust.py",
    "app/core/game_page_html.py",
    "app/core/seo_pages.py",
    "app/static/index.html",
    "app/static/polityka-prywatnosci.html",
    "app/static/i18n.js",
    "app/static/app.js",
    "app/static/game_page.js",
    "scripts/__init__.py",
    "scripts/audit_catalog_data.py",
    "scripts/audit_price_anomalies.py",
    "scripts/validate_sitemaps.py",
    "tests/test_polish_counts.py",
]


def main() -> int:
    client = _connect()
    sftp = client.open_sftp()
    for rel in FILES:
        local = LOCAL / rel
        remote = f"{REMOTE}/{rel}"
        # ensure remote dir
        parts = remote.rsplit("/", 1)[0]
        client.exec_command(f"mkdir -p {parts}")
        sftp.put(str(local), remote)
        print("OK", rel)
    sftp.close()

    cmd = r'''
systemctl restart kupujpl-games
sleep 2
systemctl is-active kupujpl-games
cd /opt/kupujpl-games && python3 -m pytest tests/test_polish_counts.py tests/test_promocje_price_consistency.py -q --tb=line 2>&1 | tail -n 40
cd /opt/kupujpl-games && python3 -m scripts.audit_price_anomalies --sample 400 --limit 15 2>&1 | tail -n 40
cd /opt/kupujpl-games && python3 <<'PY'
import re, urllib.request, ssl, json, random
from app.core.database import SessionLocal
from app.models.models import Game
from app.core.canonical_price import get_current_min_price
from app.core.store_classification import audit_store_classification

ctx=ssl.create_default_context()
UA='Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
CH='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'

def fetch(u, ua=UA):
    req=urllib.request.Request(u, headers={'User-Agent':ua,'Cache-Control':'no-cache'})
    with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
        return r.status, r.read().decode('utf-8','replace'), dict(r.headers)

# robots
st,b,h=fetch('https://kupujpl.pl/robots.txt', CH)
print('robots', st, h.get('Content-Type'), 'Allow /games/' in b)

# homepage DOM order
st,html,_=fetch('https://kupujpl.pl/games/')
h2=html.find('Wszystkie gry')
card=html.find('ssr-game-card')
print('home_status', st, 'h1', len(re.findall(r'<h1', html, re.I)),
      'ssr_cards', html.count('ssr-game-card'),
      'h2_before_cards', h2!=-1 and card!=-1 and h2 < card,
      'placeholder_left', '__STORE_COUNT__' in html or '__IN_STORES__' in html,
      'hardcoded_10_sklep', bool(re.search(r'(?<![0-9])10 sklep', html)),
      'in_stores_meta', 'w 10 sklepach' in html or 'w 11 sklepach' in html or re.search(r'w \d+ sklep', html) is not None)

# privacy wording
st,priv,_=fetch('https://kupujpl.pl/games/polityka-prywatnosci')
print('privacy', st, 'hashu' in priv, 'zaszyfrowanej' in priv)

# sitemaps sample
import subprocess
print(subprocess.check_output(['python3','-m','scripts.validate_sitemaps','--sample','15','--workers','2'], cwd='/opt/kupujpl-games', text=True)[-1200:])

# price regression
promo=fetch('https://kupujpl.pl/games/promocje')[1]
db=SessionLocal()
named=['frostpunk-2','last-epoch-899770','black-myth-wukong-2358720','elden-ring','12-is-better-than-6-410110','crazy-machines-3-351920']
ok=0
for slug in named:
    g=db.query(Game).filter(Game.slug==slug).first()
    p,_=get_current_min_price(db,g) if g else (None,None)
    ghtml=fetch(f'https://kupujpl.pl/games/gra/{slug}')[1]
    low=re.findall(r'"lowPrice"\s*:\s*"?([0-9.]+)', ghtml)
    schema=float(low[0]) if low else None
    match = p is not None and schema is not None and abs(p-schema)<0.05
    on=slug in promo
    listed=None
    if on:
        m=re.search(re.escape(slug)+r'[\s\S]{0,900}?(\d+[.,]\d{2})\s*z', promo, re.I)
        if m: listed=float(m.group(1).replace(',','.'))
    promo_ok = (not on) or (listed is not None and abs(listed-p)<0.05)
    print('price', slug, p, 'schema', schema, 'promo', listed, 'ok', match and promo_ok)
    if match and promo_ok: ok+=1
# 20 random from promocje
links=list(dict.fromkeys(re.findall(r'gra/([a-z0-9-]+)', promo)))
random.seed(11)
sample=links if len(links)<=20 else random.sample(links,20)
mism=0
checked=0
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
print('random_promo', checked, 'mismatches', mism, 'named_ok', ok, '/', len(named))
print('taxonomy')
for row in audit_store_classification():
    if row['shop'] in {'Steam','GOG','Epic Games','Fanatical','Green Man Gaming','Humble','Instant Gaming','Gamivo','Kinguin','G2A','Eneba','CDKeys'}:
        print(' ', row['shop'], row['class'], row['label_pl'])
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
