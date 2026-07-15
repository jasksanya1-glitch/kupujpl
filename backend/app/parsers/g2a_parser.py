"""G2A PL key shop offers."""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from urllib.parse import quote_plus, urljoin

from sqlalchemy.orm import Session

from app.parsers.currency_pln import to_pln
from app.parsers.keyshop_common import (
    extract_best_price,
    fetch_url,
    import_keyshop_offers,
    title_match_score,
)

logger = logging.getLogger("g2a_parser")

BASE = "https://www.g2a.com"
SEARCH_URL = "https://www.g2a.com/pl/search?query={query}"

_G2A_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.g2a.com/pl/",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}

_G2A_LOCK = threading.Lock()
_G2A_LAST_REQUEST = 0.0
_G2A_CONSECUTIVE_403 = 0
_G2A_WARMED = False
_G2A_TLS = threading.local()

_REQUEST_DELAY = float(os.environ.get("G2A_REQUEST_DELAY_SEC", "8.0"))
_403_COOLDOWN = float(os.environ.get("G2A_403_COOLDOWN_SEC", "120"))
_MAX_PRODUCT_TRIES = max(1, int(os.environ.get("G2A_MAX_PRODUCT_TRIES", "2")))
_403_MAX_COOLDOWN = float(os.environ.get("G2A_403_MAX_COOLDOWN_SEC", "180"))


def peek_g2a_fetch_error() -> str | None:
    return getattr(_G2A_TLS, "error", None)


def peek_g2a_status() -> dict:
    with _G2A_LOCK:
        streak = _G2A_CONSECUTIVE_403
    return {
        "streak_403": streak,
        "delay_sec": _REQUEST_DELAY,
        "cooldown_sec": min(_403_COOLDOWN * max(streak, 1), _403_MAX_COOLDOWN) if streak else 0,
    }


def _g2a_set_error(msg: str | None) -> None:
    _G2A_TLS.error = msg


def _g2a_throttle() -> None:
    global _G2A_LAST_REQUEST
    with _G2A_LOCK:
        now = time.monotonic()
        wait = _REQUEST_DELAY - (now - _G2A_LAST_REQUEST)
        if wait > 0:
            time.sleep(wait)
        _G2A_LAST_REQUEST = time.monotonic()


def _g2a_note_success() -> None:
    global _G2A_CONSECUTIVE_403
    with _G2A_LOCK:
        _G2A_CONSECUTIVE_403 = 0


def _g2a_note_403() -> float:
    global _G2A_CONSECUTIVE_403
    with _G2A_LOCK:
        _G2A_CONSECUTIVE_403 += 1
        streak = _G2A_CONSECUTIVE_403
    cooldown = min(_403_COOLDOWN * streak, _403_MAX_COOLDOWN)
    logger.warning("G2A rate block — cooldown %.0fs (streak %s)", cooldown, streak)
    time.sleep(cooldown)
    return cooldown


def _g2a_warmup() -> None:
    global _G2A_WARMED
    if _G2A_WARMED:
        return
    with _G2A_LOCK:
        if _G2A_WARMED:
            return
        _g2a_throttle()
        response = _fetch_g2a_once(f"{BASE}/pl/")
        if response is not None and response.status_code == 200:
            _G2A_WARMED = True
            _g2a_note_success()


def _fetch_g2a_once(url: str):
    try:
        from curl_cffi import requests as cffi_requests

        from app.parsers.keyshop_common import HEADERS, SHOP_HTTP_PROXY

        headers = {**HEADERS, **_G2A_HEADERS}
        proxies = (
            {"http": SHOP_HTTP_PROXY, "https": SHOP_HTTP_PROXY}
            if SHOP_HTTP_PROXY
            else None
        )
        return cffi_requests.get(
            url,
            headers=headers,
            timeout=25,
            impersonate="chrome131",
            proxies=proxies,
        )
    except Exception:
        return fetch_url(url, prefer_cffi=True)


def _fetch_g2a(url: str):
    """G2A blocks aggressive scraping — warmup, throttle, single cooldown on 403."""
    _g2a_warmup()
    _g2a_throttle()
    response = _fetch_g2a_once(url)
    if response is None:
        return None
    if response.status_code == 403:
        _g2a_note_403()
        logger.warning("G2A HTTP 403 for %s", url[:80])
        return response
    if response.status_code == 200:
        _g2a_note_success()
    return response


_SKIP_PARTS = (
    "account",
    "random",
    "try-to-get",
    "xbox",
    "psn",
    "playstation",
    "nintendo",
    "switch",
    "subscription",
    "gift-card",
    "wallet",
    "points",
    "software",
    "pass",
    "cd-key-random",
)

_PREFER_PARTS = (
    "pc-steam-key-global",
    "steam-key-global",
    "steam-cd-key-global",
    "gogcom-key-global",
    "epic-games-key-global",
)


def _normalize_path(href: str) -> str:
    path = href.split("?", 1)[0]
    if not path.startswith("/"):
        path = "/" + path
    if not path.startswith("/pl/"):
        path = "/pl/" + path.lstrip("/")
    return path


def _is_bad_path(path: str) -> bool:
    lower = path.lower()
    return any(x in lower for x in _SKIP_PARTS)


def _score_path(path: str, game_slug: str) -> float:
    slug_part = path.split("-i", 1)[0].replace("/pl/", "").replace("-", " ")
    score = title_match_score(game_slug.replace("-", " "), slug_part)
    lower = path.lower()
    if any(part in lower for part in _PREFER_PARTS):
        score += 0.2
    if "ultimate-edition" in lower and "ultimate" not in game_slug:
        score -= 0.15
    if "phantom-liberty" in lower and "phantom" not in game_slug:
        score -= 0.2
    if "dlc" in lower and "dlc" not in game_slug:
        score -= 0.25
    return score


def _product_links(html: str, game_slug: str) -> list[str]:
    links: list[tuple[float, str]] = []
    for href in re.findall(r'href="([^"]*?-i\d+[^"]*)"', html):
        path = _normalize_path(href)
        if _is_bad_path(path):
            continue
        keywords = [k for k in game_slug.split("-") if len(k) > 2][:4]
        if keywords and not all(k in path.lower() for k in keywords):
            continue
        score = _score_path(path, game_slug)
        if score < 0.35:
            continue
        links.append((score, path))

    links.sort(key=lambda item: item[0], reverse=True)
    seen: set[str] = set()
    out: list[str] = []
    for _score, path in links:
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out[:_MAX_PRODUCT_TRIES]


def _extract_g2a_price(html: str) -> float | None:
    # Prefer basePrice + currency — "price" on G2A is often EUR without conversion.
    base = re.search(r'"basePrice"\s*:\s*"([\d.]+)"', html)
    if base:
        try:
            return to_pln(float(base.group(1)), "EUR")
        except ValueError:
            pass

    currency_match = re.search(
        r'"price"\s*:\s*"([\d.]+)"[^}]{0,120}"currency"\s*:\s*"([A-Z]{3})"',
        html,
    )
    if currency_match:
        try:
            amount = float(currency_match.group(1))
            currency = currency_match.group(2)
            return to_pln(amount, currency)
        except ValueError:
            pass

    match = re.search(r'"price"\s*:\s*"([\d.]+)"', html)
    if match:
        try:
            price = float(match.group(1))
            if price >= 1.0:
                # Bare "price" without currency — only trust if page is PL storefront.
                if "/pl/" in html or "PLN" in html[:8000]:
                    return round(price, 2)
        except ValueError:
            pass

    return extract_best_price(html)


def _g2a_feed_only() -> bool:
    return os.environ.get("G2A_FEED_ONLY", "").strip().lower() in ("1", "true", "yes")


def search_g2a_price(query: str, game_slug: str) -> tuple[str | None, float | None]:
    from app.parsers.affiliate_feeds import affiliate_feed_lookup

    feed = affiliate_feed_lookup("G2A", query, game_slug)
    if feed:
        return feed.url, feed.price_pln, feed.confidence

    if _g2a_feed_only():
        _g2a_set_error(None)
        return None, None

    _g2a_set_error(None)
    search_url = SEARCH_URL.format(query=quote_plus(query))
    response = _fetch_g2a(search_url)
    if response is None:
        _g2a_set_error("fetch failed")
        logger.warning("G2A search failed for %s", query)
        return None, None
    if response.status_code == 429:
        _g2a_set_error("HTTP 429 rate limit")
        logger.warning("G2A rate limited for %s", query)
        return None, None
    if response.status_code != 200:
        _g2a_set_error(f"HTTP {response.status_code}")
        logger.warning("G2A search HTTP %s for %s", response.status_code, query)
        return None, None

    for path in _product_links(response.text, game_slug):
        product_url = urljoin(BASE, path)
        listing = _fetch_g2a(product_url)
        if listing is None or listing.status_code != 200:
            continue
        price_pln = _extract_g2a_price(listing.text)
        if price_pln is not None:
            return product_url, price_pln

    return None, None


def import_g2a_offers(db: Session, limit: int = 150) -> dict:
    return import_keyshop_offers(
        db,
        shop_name="G2A",
        search_fn=search_g2a_price,
        limit=limit,
        delay_sec=max(_REQUEST_DELAY, 1.5),
    )
