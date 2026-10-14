"""Production verification for final report — run via SSH helper."""
from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect  # noqa: E402

CTX = ssl.create_default_context()
UAS = {
    "chrome": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "googlebot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "googlebot_mobile": "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/W.X.Y.Z Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "curl": "curl/8.0.0",
}


def fetch(url: str, ua: str) -> tuple[int, str, dict]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": ua, "Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    try:
        with urllib.request.urlopen(req, timeout=40, context=CTX) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body, dict(resp.headers)
    except Exception as e:  # noqa: BLE001
        code = getattr(getattr(e, "code", None), "__int__", lambda: None)()
        if hasattr(e, "code"):
            return int(e.code), str(getattr(e, "read", lambda: b"")()[:500]), {}
        return 0, str(e), {}


def price_from_game_html(html: str) -> str | None:
    m = re.search(r'class="[^"]*price[^"]*"[^>]*>\s*([0-9]+[.,][0-9]{2})\s*zł', html, re.I)
    if m:
        return m.group(1).replace(",", ".")
    m = re.search(r'"price"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?', html)
    if m:
        return m.group(1)
    m = re.search(r"([0-9]+\.[0-9]{2})\s*zł", html)
    return m.group(1) if m else None


def main() -> int:
    out: dict = {"pages": {}, "promocje": {}, "home": {}, "api": {}, "robots": {}}

    # robots
    st, body, hdrs = fetch("https://kupujpl.pl/robots.txt", UAS["curl"])
    out["robots"] = {
        "status": st,
        "ct": hdrs.get("Content-Type") or hdrs.get("content-type"),
        "has_games": "/games" in body,
        "snippet": body[:400],
    }

    # legal + public pages under Googlebot
    for path in [
        "/games/regulamin",
        "/games/polityka-prywatnosci",
        "/games/o-nas",
        "/games/kontakt",
        "/games/legal",
        "/games/blog",
        "/games/promocje",
    ]:
        row = {}
        for name, ua in UAS.items():
            st, b, h = fetch(f"https://kupujpl.pl{path}", ua)
            row[name] = st
        out["pages"][path] = row

    # homepage SSR
    st, html, _ = fetch("https://kupujpl.pl/games/", UAS["googlebot"])
    out["home"] = {
        "status": st,
        "h1": re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S),
        "ssr_games": html.count("ssr-game-card"),
        "ssr_news": html.count("home-news-item"),
        "placeholder_left": ("__STORE_COUNT__" in html) or ("__GAME_COUNT__" in html),
        "d3_hero_title": bool(re.search(r'id="d3-hero-title"[^>]*>[^<]+', html)),
        "d3_side": html.count("d3-side-row"),
        "sort_pills": html.count("sort-pill"),
        "search_inputs": len(re.findall(r'type="search"|id="[^"]*search', html, re.I)),
    }

    # promocje vs game pages
    st, promo, _ = fetch("https://kupujpl.pl/games/promocje", UAS["googlebot"])
    samples = [
        ("frostpunk-2", "Frostpunk 2"),
        ("last-epoch", "Last Epoch"),
        ("black-myth-wukong-2358720", "Black Myth"),
        ("elden-ring", "Elden Ring"),
    ]
    for slug, label in samples:
        stg, ghtml, _ = fetch(f"https://kupujpl.pl/games/gra/{slug}", UAS["googlebot"])
        # extract price near slug on promocje
        block = ""
        idx = promo.lower().find(slug.lower())
        if idx >= 0:
            block = promo[max(0, idx - 200) : idx + 400]
        prices_promo = re.findall(r"([0-9]+\.[0-9]{2})\s*zł", block)
        gp = price_from_game_html(ghtml)
        out["promocje"][slug] = {
            "label": label,
            "on_promocje": slug in promo,
            "promo_prices_near": prices_promo[:3],
            "game_status": stg,
            "game_price": gp,
            "legacy_bad": {
                "frostpunk-2": "28.49",
                "last-epoch": "34.99",
                "black-myth-wukong-2358720": "145.39",
                "elden-ring": "186.89",
            }.get(slug)
            in promo,
        }

    # API catalog status
    st, body, _ = fetch("https://kupujpl.pl/games/api/catalog/status", UAS["chrome"])
    try:
        out["api"]["catalog_status"] = json.loads(body)
    except Exception:  # noqa: BLE001
        out["api"]["catalog_status"] = {"status": st, "raw": body[:300]}

    # remote audit sample
    client = _connect()
    cmd = r"""
cd /opt/kupujpl-games && python3 -m scripts.audit_catalog_data --limit 200 2>&1 | tail -n 80
"""
    _i, stdout, stderr = client.exec_command(cmd, timeout=300)
    out["audit_tail"] = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        out["audit_err"] = err[:2000]
    client.close()

    Path(r"F:\Cursor\Projects\kupujpl-games\tmp\prod_final_verify.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
