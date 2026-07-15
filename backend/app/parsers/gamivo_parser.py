"""Gamivo PL key shop offers (search page HTML tiles)."""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.core.affiliate import make_affiliate_link
from app.parsers.currency_pln import money_to_pln
from app.parsers.keyshop_common import (
    MIN_MATCH_SCORE,
    import_keyshop_offers,
    title_match_score,
)

logger = logging.getLogger("gamivo_parser")

BASE = "https://www.gamivo.com"
SEARCH_URL = f"{BASE}/pl/search/{{query}}"
SHOP_NAME = "Gamivo"

_HEADERS = {
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": f"{BASE}/pl/",
}

_SKIP_MARKERS = (
    "xbox",
    "playstation",
    "ps4",
    "ps5",
    "nintendo",
    "switch",
    "apple",
    "google-play",
    "ubisoft connect",
)

_PREFER_MARKERS = (
    "pc-steam",
    "-steam-",
    "pc-gog",
    "-gog-",
    "epic",
    "ea-app",
    "ea app",
    "origin",
)

_DLC_MARKERS = (
    "dlc",
    "expansion pass",
    "blood and wine",
    "hearts of stone",
    "phantom liberty",
    "season pass",
)

try:
    from curl_cffi import requests as _cffi_requests

    _HAS_CFFI = True
except ImportError:
    _cffi_requests = None
    _HAS_CFFI = False

_GAMIVO_LOCK = threading.Lock()
_GAMIVO_LAST_REQUEST = 0.0
_GAMIVO_TLS = threading.local()

_REQUEST_DELAY = float(os.environ.get("GAMIVO_REQUEST_DELAY_SEC", "3.0"))
_429_COOLDOWN = float(os.environ.get("GAMIVO_429_COOLDOWN_SEC", "45"))
_429_RETRIES = max(0, int(os.environ.get("GAMIVO_429_RETRIES", "3")))
_429_STREAK = 0


def peek_gamivo_fetch_error() -> str | None:
    return getattr(_GAMIVO_TLS, "error", None)


def peek_gamivo_status() -> dict:
    return {
        "delay_sec": _REQUEST_DELAY,
        "429_retries": _429_RETRIES,
    }


def _gamivo_set_error(msg: str | None) -> None:
    _GAMIVO_TLS.error = msg


def _gamivo_throttle() -> None:
    global _GAMIVO_LAST_REQUEST
    with _GAMIVO_LOCK:
        now = time.monotonic()
        wait = _REQUEST_DELAY - (now - _GAMIVO_LAST_REQUEST)
        if wait > 0:
            time.sleep(wait)
        _GAMIVO_LAST_REQUEST = time.monotonic()


def _fetch_search_html(query: str) -> str | None:
    global _429_STREAK
    url = SEARCH_URL.format(query=quote_plus(query))
    timeout = int(os.environ.get("HTTP_FETCH_TIMEOUT", "20"))
    impersonate = os.environ.get("GAMIVO_CFFI_IMPERSONATE", "safari17_0")
    _gamivo_set_error(None)
    for attempt in range(_429_RETRIES + 1):
        _gamivo_throttle()
        try:
            if _HAS_CFFI and _cffi_requests is not None:
                response = _cffi_requests.get(
                    url,
                    headers=_HEADERS,
                    timeout=timeout,
                    impersonate=impersonate,
                )
            else:
                from app.parsers.keyshop_common import fetch_url

                response = fetch_url(url, prefer_cffi=True)
            if response is None:
                _gamivo_set_error("fetch failed")
                return None
            if response.status_code == 429:
                _429_STREAK += 1
                if attempt < _429_RETRIES:
                    backoff = _429_COOLDOWN * (attempt + 1) + min(90.0, _429_STREAK * 10.0)
                    logger.warning(
                        "Gamivo rate limited (429) for %s — retry in %.0fs",
                        query,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue
                _gamivo_set_error("HTTP 429 rate limit")
                logger.warning("Gamivo search HTTP 429 for %s", query)
                return None
            _429_STREAK = max(0, _429_STREAK - 1)
            if response.status_code != 200:
                _gamivo_set_error(f"HTTP {response.status_code}")
                logger.warning(
                    "Gamivo search HTTP %s for %s",
                    response.status_code,
                    query,
                )
                return None
            return response.text
        except Exception as exc:
            _gamivo_set_error(str(exc)[:120])
            logger.warning("Gamivo search failed for %s: %s", query, exc)
            return None
    return None


def _tile_title(tile_el, slug: str, text: str) -> str:
    title_el = tile_el.select_one(
        '[data-testid*="product-tile__title"], .product-tile__title, h3, h2'
    )
    if title_el:
        title = title_el.get_text(" ", strip=True)
        if title and title.lower() != slug.replace("-", " "):
            return title
    match = re.search(r"%\s+(.+?)\s+(?:Global|EU|ROW|od)\s", text)
    if match:
        return match.group(1).strip()
    return slug.replace("-", " ")


def _parse_tiles(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for tile in soup.select('[data-testid^="search-results__product-tile--"]'):
        testid = tile.get("data-testid", "")
        slug = testid.rsplit("--", 1)[-1] if "--" in testid else ""
        anchor = tile.select_one('a[href*="/product/"]')
        href = anchor.get("href") if anchor else f"/product/{slug}"
        text = tile.get_text(" ", strip=True)
        title = _tile_title(tile, slug, text)

        price_pln: float | None = None
        pln_match = re.search(r"(\d+[\.,]\d+)\s*(?:zł|PLN)", text, re.I)
        if pln_match:
            price_pln = float(pln_match.group(1).replace(",", "."))
        else:
            eur_match = re.search(r"(\d+[\.,]\d+)\s*(?:€|EUR)", text, re.I)
            if eur_match:
                price_pln = money_to_pln(
                    float(eur_match.group(1).replace(",", ".")), "EUR", minor_units=False
                )

        if price_pln is None or price_pln < 0.5:
            continue

        out.append(
            {
                "slug": slug,
                "href": urljoin(BASE, href),
                "title": title,
                "price_pln": round(price_pln, 2),
                "text": text,
            }
        )
    return out


def _product_url(url: str) -> str:
    return make_affiliate_link(url, SHOP_NAME)


def _platform_score(slug: str, text: str) -> float:
    blob = f"{slug} {text}".lower()
    if any(skip in blob for skip in _SKIP_MARKERS):
        return -1.0
    for idx, prefer in enumerate(_PREFER_MARKERS):
        if prefer in blob:
            return 1.0 - idx * 0.05
    if "pc" in blob:
        return 0.55
    return 0.4


def _score_tile(tile: dict, query: str, game_slug: str) -> float:
    slug = tile.get("slug") or ""
    text = tile.get("text") or ""
    title = tile.get("title") or ""
    lower = f"{slug} {text} {title}".lower()

    if any(marker in lower for marker in _DLC_MARKERS):
        if not any(marker in (query or "").lower() for marker in _DLC_MARKERS):
            return -1.0

    platform_bonus = _platform_score(slug, text)
    if platform_bonus < 0:
        return -1.0

    score = title_match_score(query, title)
    if score < MIN_MATCH_SCORE:
        score = title_match_score(game_slug.replace("-", " "), title)
    if score < MIN_MATCH_SCORE:
        score = title_match_score(query, slug.replace("-", " "))
    if score < MIN_MATCH_SCORE:
        return -1.0

    if any(x in slug for x in ("complete", "goty", "ultimate")):
        if not any(
            x in (query or "").lower()
            for x in ("complete", "goty", "ultimate", "edition")
        ):
            score -= 0.1

    return score + platform_bonus * 0.15


def search_gamivo_price(query: str, game_slug: str) -> tuple[str | None, float | None, float | None]:
    from app.parsers.affiliate_feeds import affiliate_feed_lookup

    feed = affiliate_feed_lookup("Gamivo", query, game_slug)
    if feed:
        return feed.url, feed.price_pln, feed.confidence

    html = _fetch_search_html(query)
    if not html:
        return None, None, None

    best: tuple[float, str, float] | None = None
    for tile in _parse_tiles(html):
        score = _score_tile(tile, query, game_slug)
        if score < MIN_MATCH_SCORE:
            continue
        url = _product_url(tile["href"])
        price_pln = tile["price_pln"]
        if best is None or score > best[0]:
            best = (score, url, price_pln)

    if best is None:
        return None, None, None
    return best[1], best[2], best[0]


def import_gamivo_offers(db: Session, limit: int = 150) -> dict:
    return import_keyshop_offers(
        db,
        shop_name=SHOP_NAME,
        search_fn=search_gamivo_price,
        limit=limit,
        delay_sec=1.5,
    )
