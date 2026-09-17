#!/usr/bin/env python3
"""Apply audit fixes on VPS. Run locally: python tools/apply_audit_fixes.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "cursor-server-mcp"))
import ssh_exec  # noqa: E402

REMOTE = "/opt/kupujpl-games/app"
ASSET_VER = "86"


def patch(path: str, old: str, new: str, *, required: bool = True) -> None:
    full = f"{REMOTE}/{path}" if not path.startswith("/") else path
    r = ssh_exec.read_file(full)
    content = r.get("content", "")
    if old not in content:
        if required:
            raise SystemExit(f"MISS {full}: anchor not found")
        print(f"SKIP {full}")
        return
    ssh_exec.write_file(full, content.replace(old, new, 1))
    print(f"OK {full}")


def patch_all(path: str, old: str, new: str) -> None:
    full = f"{REMOTE}/{path}"
    content = ssh_exec.read_file(full).get("content", "")
    if old not in content:
        raise SystemExit(f"MISS {full}")
    ssh_exec.write_file(full, content.replace(old, new))
    print(f"OK ALL {full}")


def main() -> None:
    # --- Steam US cc/shop_name ---
    patch(
        "parsers/steam_catalog.py",
        'def fetch_appdetails(appid: int) -> dict | None:\n    for attempt in range(1, 4):\n        try:\n            r = requests.get(\n                APPDETAILS_URL,\n                params={"appids": appid, "cc": "pl", "l": "polish"},',
        'def fetch_appdetails(appid: int, *, cc: str = "pl", lang: str | None = None) -> dict | None:\n    lang = lang or ("polish" if cc == "pl" else "english")\n    for attempt in range(1, 4):\n        try:\n            r = requests.get(\n                APPDETAILS_URL,\n                params={"appids": appid, "cc": cc, "l": lang},',
    )
    patch(
        "parsers/steam_catalog.py",
        "def _upsert_steam_offer(db: Session, game: Game, appid: int, data: dict) -> None:",
        "def _upsert_steam_offer(\n    db: Session, game: Game, appid: int, data: dict, *, shop_name: str = \"Steam\"\n) -> None:",
    )
    patch_all(
        "parsers/steam_catalog.py",
        'Offer.shop_name == "Steam"',
        'Offer.shop_name == shop_name',
    )
    patch_all(
        "parsers/steam_catalog.py",
        'shop_name="Steam",',
        'shop_name=shop_name,',
    )
    patch(
        "parsers/steam_catalog.py",
        'def refresh_steam_offer_for_game(db: Session, game: Game) -> bool:\n    """Update Steam store price from appdetails (PL region)."""\n    if not game.steam_appid:\n        return False\n    data = fetch_appdetails(game.steam_appid)\n    if not data:\n        return False\n    _upsert_steam_offer(db, game, game.steam_appid, data)\n    return True',
        'def refresh_steam_offer_for_game(\n    db: Session,\n    game: Game,\n    *,\n    cc: str = "pl",\n    shop_name: str = "Steam",\n    lang: str | None = None,\n) -> bool:\n    """Update Steam store price from appdetails (PL or US region)."""\n    if not game.steam_appid:\n        return False\n    data = fetch_appdetails(game.steam_appid, cc=cc, lang=lang)\n    if not data:\n        return False\n    _upsert_steam_offer(db, game, game.steam_appid, data, shop_name=shop_name)\n    return True',
    )

    # --- Telegram deals HTML (do not escape URLs in href) ---
    patch(
        "core/deals_channel.py",
        '        url = f"{SITE_ORIGIN}/gra/{item.slug}?utm_source=telegram&utm_medium=channel&utm_campaign=daily_deals"\n        shop = html_lib.escape(best.shop_name or "")\n        price = f"{item.best_price_pln:.2f} zł" if item.best_price_pln else "—"\n        line = f\'{i}. <a href="{html_lib.escape(url)}"><b>{title}</b></a>\\n💰 {price} ({shop})\'',
        '        url = f"{SITE_ORIGIN}/gra/{item.slug}?utm_source=telegram&utm_medium=channel&utm_campaign=daily_deals"\n        shop = html_lib.escape(best.shop_name or "")\n        price = f"{item.best_price_pln:.2f} zł" if item.best_price_pln else "—"\n        line = f\'{i}. <a href="{url}"><b>{title}</b></a>\\n💰 {price} ({shop})\'',
    )
    # --- Telegram error detail + deals backoff ---
    patch(
        "core/telegram_bot.py",
        '    except Exception as exc:\n        logger.warning("sendMessage failed: %s", exc)\n        return False',
        '    except Exception as exc:\n        detail = ""\n        if hasattr(exc, "response") and exc.response is not None:\n            try:\n                detail = exc.response.text[:300]\n            except Exception:\n                pass\n        logger.warning("sendMessage failed: %s %s", exc, detail)\n        return False',
    )
    patch(
        "core/deals_channel.py",
        '_STATE_PATH = BASE_DIR / "tmp" / "deals_channel_state.json"\n_LOCK = threading.Lock()\n_STARTED = False',
        '_STATE_PATH = BASE_DIR / "tmp" / "deals_channel_state.json"\n_LOCK = threading.Lock()\n_STARTED = False\n_FAIL_BACKOFF_SEC = int(os.environ.get("DEALS_CHANNEL_FAIL_BACKOFF_SEC", "86400"))',
    )
    patch(
        "core/deals_channel.py",
        '    if ok:\n        with _LOCK:\n            state = _load_state()\n            state["last_posted_date"] = today_iso\n            state["last_posted_at"] = datetime.utcnow().isoformat()\n            state["last_count"] = len(deals)\n            _save_state(state)\n        logger.info("Posted %s deals to Telegram channel %s", len(deals), chat_id)\n    return {"posted": ok, "count": len(deals), "chat_id": chat_id}',
        '    if ok:\n        with _LOCK:\n            state = _load_state()\n            state["last_posted_date"] = today_iso\n            state["last_posted_at"] = datetime.utcnow().isoformat()\n            state["last_count"] = len(deals)\n            state.pop("fail_until", None)\n            _save_state(state)\n        logger.info("Posted %s deals to Telegram channel %s", len(deals), chat_id)\n    else:\n        with _LOCK:\n            state = _load_state()\n            state["fail_until"] = (datetime.utcnow().timestamp() + _FAIL_BACKOFF_SEC)\n            state["last_fail_at"] = datetime.utcnow().isoformat()\n            _save_state(state)\n    return {"posted": ok, "count": len(deals), "chat_id": chat_id}',
    )
    patch(
        "core/deals_channel.py",
        '    today_iso = date.today().isoformat()\n    if not force:\n        with _LOCK:\n            if _load_state().get("last_posted_date") == today_iso:\n                return {"posted": False, "reason": "already_posted_today"}',
        '    today_iso = date.today().isoformat()\n    if not force:\n        with _LOCK:\n            st = _load_state()\n            fail_until = float(st.get("fail_until") or 0)\n            if fail_until and datetime.utcnow().timestamp() < fail_until:\n                return {"posted": False, "reason": "backoff_after_fail"}\n            if st.get("last_posted_date") == today_iso:\n                return {"posted": False, "reason": "already_posted_today"}',
    )

    # --- OG preview crawlers whitelist ---
    patch(
        "core/site_tracking.py",
        '_BLOCKED_PROBE_PATHS = (',
        '_OG_PREVIEW_RE = re.compile(\n    r"facebookexternalhit|twitterbot|telegrambot|slackbot|discordbot|linkedinbot|whatsapp",\n    re.I,\n)\n_BLOCKED_PROBE_PATHS = (',
    )
    patch(
        "core/site_tracking.py",
        '    if re.search(r"googlebot|bingbot|duckduckbot|yandexbot|applebot", ua, re.I):\n        return False\n    if _is_public_seo_path(path):',
        '    if re.search(r"googlebot|bingbot|duckduckbot|yandexbot|applebot", ua, re.I):\n        return False\n    if _OG_PREVIEW_RE.search(ua) and (\n        path.startswith("/gra/") or _is_public_seo_path(path)\n    ):\n        return False\n    if _is_public_seo_path(path):',
    )

    # --- Click filter: allow gra-page browse without JS verify ---
    patch(
        "core/click_tracking.py",
        'def _visitor_has_verified_human(db: Session, visitor_key: str, *, before: datetime) -> bool:\n    if not visitor_key:\n        return False\n    since = before - _HUMAN_LOOKBACK\n    return (\n        db.query(SiteVisit.id)\n        .filter(\n            SiteVisit.visitor_key == visitor_key,\n            SiteVisit.visited_at >= since,\n            SiteVisit.visited_at <= before,\n            SiteVisit.is_verified_human.is_(True),\n            SiteVisit.is_suspected_bot.is_(False),\n        )\n        .first()\n        is not None\n    )',
        'def _visitor_has_verified_human(db: Session, visitor_key: str, *, before: datetime) -> bool:\n    if not visitor_key:\n        return False\n    since = before - _HUMAN_LOOKBACK\n    base = (\n        db.query(SiteVisit.id)\n        .filter(\n            SiteVisit.visitor_key == visitor_key,\n            SiteVisit.visited_at >= since,\n            SiteVisit.visited_at <= before,\n            SiteVisit.is_suspected_bot.is_(False),\n        )\n    )\n    if base.filter(SiteVisit.is_verified_human.is_(True)).first():\n        return True\n    # Game-page browse without JS verify still counts as human intent.\n    gra = (\n        base.filter(SiteVisit.path.like("/gra/%"))\n        .limit(1)\n        .first()\n    )\n    return gra is not None',
    )
    patch(
        "core/click_tracking.py",
        '    is_bot, reason = _detect_bot_visit(\n        request,\n        path="/api/go",\n        user_agent=user_agent,\n        client_agent=None,\n    )\n    if is_bot:\n        return True, reason or "bot_ua"\n    if not _visitor_has_verified_human(db, visitor_key, before=now):',
        '    is_bot, reason = _detect_bot_visit(\n        request,\n        path="/api/go",\n        user_agent=user_agent,\n        client_agent=None,\n    )\n    if is_bot and reason not in ("missing_accept_language", "missing_accept"):\n        return True, reason or "bot_ua"\n    if not _visitor_has_verified_human(db, visitor_key, before=now):',
    )

    # --- app.js: skip home load on search URL ---
    patch(
        "static/app.js",
        "    loadCategories();\n    loadCatalogStats();\n    setInterval(loadCatalogStats, 5 * 60 * 1000);\n    loadHomeSections();",
        "    loadCategories();\n    loadCatalogStats();\n    setInterval(loadCatalogStats, 5 * 60 * 1000);",
    )
    patch(
        "static/app.js",
        '    const urlQuery = new URLSearchParams(location.search).get(\'q\');\n    if (urlQuery && urlQuery.trim()) {\n        searchInput.value = urlQuery.trim();\n        runSearch(urlQuery.trim());\n    } else if (deepLinkGra) {\n        location.replace(`gra/${encodeURIComponent(deepLinkGra)}`);\n    }',
        '    const urlQuery = new URLSearchParams(location.search).get(\'q\');\n    if (urlQuery && urlQuery.trim()) {\n        searchInput.value = urlQuery.trim();\n        runSearch(urlQuery.trim());\n    } else if (deepLinkGra) {\n        location.replace(`gra/${encodeURIComponent(deepLinkGra)}`);\n    } else {\n        loadHomeSections();\n    }',
    )

    # --- main.py: /health root, CORS, debug gate ---
    patch(
        "main.py",
        'app.add_middleware(\n    CORSMiddleware,\n    allow_origins=["*"],\n    allow_credentials=True,',
        'app.add_middleware(\n    CORSMiddleware,\n    allow_origins=[\n        o.strip()\n        for o in os.environ.get(\n            "CORS_ORIGINS", "https://kupujpl.pl,https://www.kupujpl.pl"\n        ).split(",")\n        if o.strip()\n    ],\n    allow_credentials=True,',
    )
    patch(
        "main.py",
        '@app.get("/api/health")\ndef api_health():\n    return {"ok": True, "service": "kupujpl-games"}',
        '@app.get("/health")\n@app.get("/api/health")\ndef api_health():\n    return {"ok": True, "service": "kupujpl-games"}',
    )
    patch(
        "main.py",
        '@app.post("/api/debug/price-log", include_in_schema=False)\nasync def debug_price_log(request: Request):\n    """Temporary price-debug sink for this debug session."""\n    try:',
        '@app.post("/api/debug/price-log", include_in_schema=False)\nasync def debug_price_log(request: Request):\n    if os.environ.get("ENABLE_PRICE_DEBUG", "").lower() not in ("1", "true", "yes"):\n        raise HTTPException(status_code=404, detail="Not found")\n    try:',
    )
    patch(
        "main.py",
        '            if refresh_steam_offer_for_game(db, game, cc="us", shop_name="Steam US"):',
        '            if refresh_steam_offer_for_game(\n                db, game, cc="us", shop_name="Steam US", lang="english"\n            ):',
    )

    # --- CDKeys: extra fetch URLs ---
    patch(
        "parsers/cdkeys_parser.py",
        '_FETCH_URLS = (\n    f"{BASE}/",\n    "https://www.loaded.com/",\n    f"{BASE}/pl/",\n)',
        '_FETCH_URLS = (\n    f"{BASE}/",\n    f"{BASE}/pl/",\n    "https://www.loaded.com/",\n    "https://www.loaded.com/pl/",\n    "https://www.cdkeys.com/media/wysiwyg/",\n)',
    )

    # --- Asset cache bust v86 ---
    static_dir = f"{REMOTE}/static"
    for name in ssh_exec.run_command(f"ls {static_dir}/*.html").get("stdout", "").split():
        if not name.endswith(".html"):
            continue
        base = Path(name).name
        if base.startswith("google"):
            continue
        content = ssh_exec.read_file(name).get("content", "")
        import re

        new_content = re.sub(r"style\.css\?v=\d+", f"style.css?v={ASSET_VER}", content)
        new_content = re.sub(r"i18n\.js\?v=\d+", f"i18n.js?v={ASSET_VER}", new_content)
        new_content = re.sub(r"app\.js\?v=\d+", f"app.js?v={ASSET_VER}", new_content)
        new_content = re.sub(r"auth\.js\?v=\d+", f"auth.js?v={ASSET_VER}", new_content)
        if new_content != content:
            ssh_exec.write_file(name, new_content)
            print(f"OK assets {base}")

    print("DONE — restart service manually")


if __name__ == "__main__":
    main()
