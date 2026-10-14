"""Production verification for remaining-gaps plan — read-mostly; no price pipeline changes."""
from __future__ import annotations

import json
import random
import re
import ssl
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

CTX = ssl.create_default_context()
UA_GB = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
UA_CH = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
UA_MOB = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def main() -> int:
    client = _connect()
    cmd = r'''
cd /opt/kupujpl-games && python3 <<'PY'
import json, re, random, urllib.request, ssl, subprocess
from app.core.database import SessionLocal
from app.models.models import Game
from app.core.canonical_price import get_current_min_price
from app.core.store_classification import StoreClass, classify_store
from app.core.shops_trust import shop_trust_badge
from app.core.security import get_password_hash, verify_password
from app.core.polish_counts import format_store_count, format_in_stores

ctx = ssl.create_default_context()
UA_GB = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
UA_CH = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
UA_MOB = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
UA_CURL = "curl/8.0.0"

def get(u, ua=UA_GB):
    req = urllib.request.Request(u, headers={"User-Agent": ua, "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
            return int(r.status), r.read().decode("utf-8", "replace"), dict(r.headers)
    except Exception as e:
        code = getattr(e, "code", 0) or 0
        body = ""
        try:
            body = e.read().decode("utf-8", "replace") if hasattr(e, "read") else str(e)
        except Exception:
            body = str(e)
        return int(code), body, {}

out = {"baseline": {}, "hardcodes": {}, "seo": {}, "prices": {}, "taxonomy": {}}

# --- baseline DOM / privacy / catalog ---
st, html, _ = get("https://kupujpl.pl/games/")
h2 = html.find('id="games-heading"')
card = html.find("ssr-game-card")
out["baseline"]["home"] = {
    "status": st,
    "h1": re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S),
    "ssr_cards": html.count("ssr-game-card"),
    "h2_before_cards": h2 != -1 and card != -1 and h2 < card,
    "placeholders_left": ("__STORE_COUNT__" in html) or ("__IN_STORES__" in html) or ("__GAME_COUNT__" in html),
}
st, mob, _ = get("https://kupujpl.pl/games/", UA_MOB)
m = re.search(r'id="m-deal-meta">([^<]+)', mob)
out["baseline"]["deal_meta"] = m.group(1) if m else None
st, priv, _ = get("https://kupujpl.pl/games/polityka-prywatnosci")
out["baseline"]["privacy"] = {
    "status": st,
    "hash_wording": ("hashu" in priv) or ("skrótu" in priv) or ("skrotu" in priv),
    "zaszyfrowanej": "zaszyfrowanej" in priv,
}
# bcrypt smoke
h = get_password_hash("verify-only-temp")
out["baseline"]["bcrypt_ok"] = bool(h.startswith("$2") and verify_password("verify-only-temp", h))
st, body, _ = get("https://kupujpl.pl/games/api/catalog/status", UA_CH)
cat = json.loads(body)
out["baseline"]["catalog"] = {
    "stores_total": cat.get("stores_total"),
    "games_total": cat.get("games_total"),
    "format_store_count": format_store_count(int(cat.get("stores_total") or 0)),
    "format_in_stores": format_in_stores(int(cat.get("stores_total") or 0)),
}

# taxonomy API + HTML
for slug in ["frostpunk-2", "elden-ring", "black-myth-wukong-2358720"]:
    st, api, _ = get(f"https://kupujpl.pl/games/api/games/{slug}", UA_CH)
    d = json.loads(api)
    labels = {}
    for o in d.get("offers") or []:
        if o.get("shop_name") in ("Instant Gaming", "Fanatical", "Steam", "G2A"):
            labels[o["shop_name"]] = {
                "trust_label": o.get("trust_label"),
                "store_class": o.get("store_class"),
            }
    st, ghtml, _ = get(f"https://kupujpl.pl/games/gra/{slug}")
    html_labels = {}
    for shop in ("Instant Gaming", "Fanatical", "Steam", "G2A"):
        m = re.search(re.escape(shop) + r"[\s\S]{0,200}?class=\"badge\"[^>]*>([^<]+)", ghtml)
        if m:
            html_labels[shop] = m.group(1)
    out["taxonomy"][slug] = {"api": labels, "html_badges": html_labels}

# classify module
out["taxonomy"]["module"] = {
    s: {"class": classify_store(s).value, "label": shop_trust_badge(s)["label"]}
    for s in ["Steam", "GOG", "Epic Games", "Fanatical", "Green Man Gaming", "Humble",
              "Instant Gaming", "Gamivo", "Kinguin", "G2A", "Eneba", "CDKeys"]
}

# --- hardcode grep on live app path ---
import pathlib
root = pathlib.Path("/opt/kupujpl-games/app")
hits = []
for p in root.rglob("*"):
    if not p.is_file():
        continue
    if p.suffix.lower() not in {".py", ".js", ".html", ".json", ".css"}:
        continue
    if "design-samples" in str(p) or "layout-samples" in str(p):
        continue
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    for pat in ("10 sklepów", "10 sklepach", "10 sklep", "5000+", "5000 gier"):
        if pat in text:
            hits.append({"file": str(p.relative_to(root.parent)), "pattern": pat})
out["hardcodes"]["live_app_hits"] = hits[:40]
legacy = pathlib.Path("/opt/kupujpl-games/static/index.html")
out["hardcodes"]["legacy_static_on_server"] = legacy.is_file()
out["hardcodes"]["legacy_static_marked"] = (
    legacy.is_file() and "UNUSED LEGACY" in legacy.read_text(encoding="utf-8", errors="ignore")
)
# also note local unused copy exists in repo (not deployed)
out["hardcodes"]["non_live_left_unchanged"] = [
    "backend/static/index.html (UNUSED LEGACY; not on server)",
    "app/static/design-samples/*",
    "discord-bot / audit sandbox (out of live app/)",
]

# --- robots / sitemaps ---
st, rb, rh = get("https://kupujpl.pl/robots.txt", UA_CH)
out["seo"]["robots_chrome"] = {
    "status": st,
    "ct": rh.get("Content-Type"),
    "has_allow_games": "Allow: /games/" in rb,
    "snippet": rb[:300],
}
stc, rbc, _ = get("https://kupujpl.pl/robots.txt", UA_CURL)
out["seo"]["robots_curl"] = {"status": stc, "body": rbc[:80]}
vs = subprocess.run(
    ["python3", "-m", "scripts.validate_sitemaps", "--sample", "20", "--workers", "2"],
    cwd="/opt/kupujpl-games",
    capture_output=True,
    text=True,
    timeout=180,
)
out["seo"]["validate_sitemaps"] = (vs.stdout or "")[-1500:]

# indexability — homepage, Promocje, 5 games, 5 categories, blog, 2 articles, legal
paths = [
    "/games/",
    "/games/promocje",
    "/games/regulamin",
    "/games/polityka-prywatnosci",
    "/games/blog",
    "/games/blog/jak-kupowac-gry-taniej",
    "/games/blog/czy-klucze-steam-sa-bezpieczne",
    "/games/gra/frostpunk-2",
    "/games/gra/elden-ring",
    "/games/gra/black-myth-wukong-2358720",
    "/games/gra/12-is-better-than-6-410110",
    "/games/gra/crazy-machines-3-351920",
    "/games/kategoria/akcja",
    "/games/kategoria/rpg",
    "/games/kategoria/strategia",
    "/games/kategoria/przygodowe",
    "/games/kategoria/symulacje",
]
idx = {}
for path in paths:
    st, body, h = get("https://kupujpl.pl" + path)
    robots = re.search(r'name=["\']robots["\'][^>]*content=["\']([^"\']+)', body, re.I)
    canon = re.search(r'rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', body, re.I)
    if not canon:
        canon = re.search(r'href=["\']([^"\']+)["\'][^>]*rel=["\']canonical', body, re.I)
    low = re.findall(r'"lowPrice"\s*:\s*"?([0-9.]+)', body)
    idx[path] = {
        "status": st,
        "robots": robots.group(1) if robots else None,
        "canonical": canon.group(1) if canon else None,
        "xrobots": h.get("X-Robots-Tag"),
        "lowPrice": low[:1],
        "noindex": "noindex" in ((robots.group(1) if robots else "") + " " + (h.get("X-Robots-Tag") or "")).lower(),
    }
out["seo"]["indexability"] = idx

# --- prices ---
promo = get("https://kupujpl.pl/games/promocje")[1]
db = SessionLocal()
named = [
    "frostpunk-2",
    "black-myth-wukong-2358720",
    "elden-ring",
    "12-is-better-than-6-410110",
    "crazy-machines-3-351920",
]
named_rows = []
okn = 0
for slug in named:
    g = db.query(Game).filter(Game.slug == slug).first()
    p, o = get_current_min_price(db, g) if g else (None, None)
    ghtml = get(f"https://kupujpl.pl/games/gra/{slug}")[1]
    low = re.findall(r'"lowPrice"\s*:\s*"?([0-9.]+)', ghtml)
    schema = float(low[0]) if low else None
    listed = None
    if slug in promo:
        m = re.search(re.escape(slug) + r"[\s\S]{0,900}?(\d+[.,]\d{2})\s*z", promo, re.I)
        if m:
            listed = float(m.group(1).replace(",", "."))
    match = (
        p is not None
        and schema is not None
        and abs(p - schema) < 0.05
        and (listed is None or abs(listed - p) < 0.05)
    )
    if match:
        okn += 1
    named_rows.append(
        {
            "slug": slug,
            "canonical": p,
            "shop": o.shop_name if o else None,
            "schema": schema,
            "promo": listed,
            "ok": match,
        }
    )
links = list(dict.fromkeys(re.findall(r"gra/([a-z0-9-]+)", promo)))
random.seed(23)
sample = links if len(links) <= 20 else random.sample(links, 20)
mism = []
checked = 0
for slug in sample:
    g = db.query(Game).filter(Game.slug == slug).first()
    if not g:
        continue
    p, _ = get_current_min_price(db, g)
    if p is None:
        continue
    m = re.search(re.escape(slug) + r"[\s\S]{0,900}?(\d+[.,]\d{2})\s*z", promo, re.I)
    if not m:
        continue
    listed = float(m.group(1).replace(",", "."))
    checked += 1
    if abs(listed - p) > 0.05:
        mism.append({"slug": slug, "listed": listed, "canonical": p})
db.close()
out["prices"] = {
    "named": named_rows,
    "named_ok": okn,
    "random_checked": checked,
    "random_mismatches": mism,
}

# app.js modal uses store_class?
app = pathlib.Path("/opt/kupujpl-games/app/static/app.js").read_text(encoding="utf-8", errors="ignore")
panel = pathlib.Path("/opt/kupujpl-games/app/static/panel.js").read_text(encoding="utf-8", errors="ignore")
gp = pathlib.Path("/opt/kupujpl-games/app/static/game_page.js").read_text(encoding="utf-8", errors="ignore")
out["taxonomy"]["modal_uses_store_class"] = "store_class" in app and "AUTHORIZED_RESELLER" in app
out["taxonomy"]["panel_uses_trust"] = ("trust_label" in panel) or ("store_class" in panel)
out["taxonomy"]["game_page_uses_trust"] = ("trust_label" in gp) or ("store_class" in gp)

# consistency asserts (pytest may be unavailable)
from app.core.store_classification import classify_store as cs, StoreClass as SC
assert cs("Instant Gaming") == SC.AUTHORIZED_RESELLER
assert cs("Fanatical") == SC.AUTHORIZED_RESELLER
assert shop_trust_badge("Instant Gaming")["label"] == "Autoryzowany"
assert shop_trust_badge("Fanatical")["label"] == "Autoryzowany"
out["taxonomy"]["consistency_asserts_ok"] = True

# desktop / mobile smoke (no redesign — structural signals only)
st_d, desk, _ = get("https://kupujpl.pl/games/", UA_CH)
st_m, mob2, _ = get("https://kupujpl.pl/games/", UA_MOB)
dm = re.search(r'id="m-deal-meta">([^<]+)', mob2)
out["smoke"] = {
    "desktop": {
        "status": st_d,
        "h1_count": len(re.findall(r"<h1[^>]*>", desk, re.I)),
        "h2_before_cards": desk.find('id="games-heading"') < desk.find("ssr-game-card") and "ssr-game-card" in desk,
        "ssr_cards": desk.count("ssr-game-card"),
        "has_d3": "d3-" in desk,
    },
    "mobile": {
        "status": st_m,
        "h1_count": len(re.findall(r"<h1[^>]*>", mob2, re.I)),
        "h2_before_cards": mob2.find('id="games-heading"') < mob2.find("ssr-game-card") and "ssr-game-card" in mob2,
        "ssr_cards": mob2.count("ssr-game-card"),
        "deal_meta": dm.group(1) if dm else None,
        "no_5000_plus": "5000+" not in mob2,
    },
}

print(json.dumps(out, ensure_ascii=False, indent=2))
PY
'''
    _i, stdout, stderr = client.exec_command(cmd, timeout=360)
    data = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    client.close()
    Path(r"F:\Cursor\Projects\kupujpl-games\tmp\verify_remaining_gaps.json").write_text(
        data, encoding="utf-8"
    )
    print(data)
    if err.strip():
        print("STDERR", err[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
