from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect


def main() -> int:
    client = _connect()
    cmd = r'''
cd /opt/kupujpl-games && python3 - <<'PY'
import json, re, urllib.request, ssl
from app.core.database import SessionLocal
from app.models.models import Game
from app.core.canonical_price import get_current_min_price
from app.core.seo_landings import SeoLanding, collect_landing_items
from app.core.game_offer_selection import best_offers_map

ctx = ssl.create_default_context()
UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"

def fetch(u):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
        return r.read().decode("utf-8", errors="replace")

slugs = ["frostpunk-2","last-epoch","black-myth-wukong-2358720","elden-ring"]
promo = fetch("https://kupujpl.pl/games/promocje")
out = {"samples": {}, "promocje_match_sample20": None, "audit": None, "robots_chrome": None}

# robots with chrome
req = urllib.request.Request("https://kupujpl.pl/robots.txt", headers={"User-Agent":"Mozilla/5.0"})
try:
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        body = r.read().decode()
        out["robots_chrome"] = {"status": r.status, "ct": r.headers.get("Content-Type"), "len": len(body), "head": body[:300]}
except Exception as e:
    out["robots_chrome"] = {"error": str(e)}

db = SessionLocal()
try:
    for slug in slugs:
        g = db.query(Game).filter(Game.slug==slug).first()
        if not g:
            out["samples"][slug] = {"missing": True}
            continue
        price, offer = get_current_min_price(db, g, region="pl")
        # price near link on promocje
        m = re.search(rf'href="[^"]*{re.escape(slug)}[^"]*"[^>]*>[\s\S]{{0,800}}?([0-9]+\.[0-9]{{2}})\s*z', promo, re.I)
        # also card pattern
        if not m:
            idx = promo.find(slug)
            chunk = promo[idx:idx+800] if idx>=0 else ""
            prices = re.findall(r"([0-9]+\.[0-9]{2})\s*zł", chunk)
        else:
            prices = [m.group(1)]
        ghtml = fetch(f"https://kupujpl.pl/games/gra/{slug}")
        # JSON-LD price
        ld = re.findall(r'"price"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?', ghtml)
        out["samples"][slug] = {
            "canonical": price,
            "shop": offer.shop_name if offer else None,
            "on_promocje": slug in promo,
            "promo_prices": prices[:3],
            "game_ld_prices": ld[:5],
            "legacy_bad_in_promo": any(x in promo for x in {
                "frostpunk-2":["28.49"],
                "last-epoch":["34.99"],
                "black-myth-wukong-2358720":["145.39"],
                "elden-ring":["186.89"],
            }[slug]),
            "match_promo_canonical": (price is not None and any(abs(float(p)-float(price))<0.02 for p in prices)),
        }

    # 20 random promocje items vs canonical
    landing = SeoLanding("promocje", "promocje", "Promocje", "inne", min_savings_pct=5)
    items = collect_landing_items(db, landing, limit=20)
    mism = []
    ok = 0
    for it in items:
        g = db.query(Game).filter(Game.id==it.id).first()
        if not g:
            continue
        p, _ = get_current_min_price(db, g, region="pl")
        listed = float(it.best_price_pln) if it.best_price_pln is not None else None
        if p is None or listed is None:
            mism.append({"slug": g.slug, "listed": listed, "canonical": p, "reason": "null"})
            continue
        if abs(p - listed) > 0.009:
            mism.append({"slug": g.slug, "listed": listed, "canonical": p})
        else:
            ok += 1
    out["promocje_match_sample20"] = {"ok": ok, "mismatches": mism, "checked": ok+len(mism)}
finally:
    db.close()

# audit sample
import subprocess
r = subprocess.run(["python3","-m","scripts.audit_catalog_data","--sample","300","--json"], cwd="/opt/kupujpl-games", capture_output=True, text=True, timeout=240)
out["audit_stdout"] = r.stdout[-4000:]
out["audit_stderr"] = r.stderr[-1000:]
print(json.dumps(out, ensure_ascii=False, indent=2))
PY
'''
    _i, stdout, stderr = client.exec_command(cmd, timeout=300)
    data = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    client.close()
    Path(r"F:\Cursor\Projects\kupujpl-games\tmp\prod_price_audit.json").write_text(data, encoding="utf-8")
    print(data)
    if err.strip():
        print("STDERR", err[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
