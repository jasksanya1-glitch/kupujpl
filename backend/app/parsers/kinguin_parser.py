"""Kinguin PL key shop offers."""
from __future__ import annotations

import logging
import re
import threading
from urllib.parse import quote_plus, urljoin

from sqlalchemy.orm import Session

from app.parsers.keyshop_common import (
    MIN_MATCH_SCORE,
    extract_best_price,
    fetch_url,
    import_keyshop_offers,
    is_restricted_region_listing,
    title_match_score,
)

logger = logging.getLogger("kinguin_parser")

BASE = "https://www.kinguin.net"
SEARCH_URL = "https://www.kinguin.net/pl/catalogsearch/result/?q={query}"
_KINGUIN_TLS = threading.local()

_PS_MARKERS = ("ps4", "ps5", "playstation", "psn")
_XBOX_MARKERS = ("xbox",)
_CONSOLE_SKIP = ("altergift", "account", "nintendo", "subscription")


def peek_kinguin_fetch_error() -> str | None:
    return getattr(_KINGUIN_TLS, "error", None)


def _kinguin_set_error(msg: str | None) -> None:
    _KINGUIN_TLS.error = msg


def _platform_ok(lower: str, platform: str) -> bool:
    platform = (platform or "pc").lower()
    if any(x in lower for x in _CONSOLE_SKIP):
        return False
    if platform == "ps":
        return any(m in lower for m in _PS_MARKERS) and not any(m in lower for m in _XBOX_MARKERS)
    if platform == "xbox":
        return any(m in lower for m in _XBOX_MARKERS) and not any(m in lower for m in _PS_MARKERS)
    # PC: skip console listings
    if any(x in lower for x in ("ps4", "ps5", "xbox", "nintendo", "playstation")):
        return False
    return True


def _search_query(query: str, platform: str) -> str:
    platform = (platform or "pc").lower()
    if platform == "ps":
        return f"{query} PS5"
    if platform == "xbox":
        return f"{query} Xbox"
    return query


def _slug_keywords(game_slug: str, platform: str) -> list[str]:
    skip = {"ps", "xbox", "ps4", "ps5", "playstation"}
    return [k for k in game_slug.split("-") if len(k) > 2 and k not in skip][:4]


def search_kinguin_price(
    query: str,
    game_slug: str,
    *,
    platform: str = "pc",
) -> tuple[str | None, float | None, float | None]:
    from app.parsers.affiliate_feeds import affiliate_feed_lookup

    if (platform or "pc").lower() == "pc":
        feed = affiliate_feed_lookup("Kinguin", query, game_slug)
        if feed:
            return feed.url, feed.price_pln, feed.confidence

    _kinguin_set_error(None)
    search_url = SEARCH_URL.format(query=quote_plus(_search_query(query, platform)))
    response = fetch_url(search_url)
    if response is None:
        _kinguin_set_error("fetch failed")
        logger.warning("Kinguin search failed for %s", query)
        return None, None, None
    if response.status_code != 200:
        _kinguin_set_error(f"HTTP {response.status_code}")
        logger.warning("Kinguin search failed for %s", query)
        return None, None, None

    scored_links: list[tuple[float, str]] = []
    keywords = _slug_keywords(game_slug, platform)
    for href in re.findall(r'href="(https://www\.kinguin\.net/[^"]+|/[^"]+)"', response.text):
        lower = href.lower()
        if "/category/" not in lower or "catalogsearch" in lower:
            continue
        if not _platform_ok(lower, platform):
            continue
        if is_restricted_region_listing(lower):
            continue
        if keywords and not all(k in lower for k in keywords):
            continue
        path = href.split("kinguin.net", 1)[-1]
        title_part = path.rsplit("/", 1)[-1].replace("-", " ")
        score = title_match_score(query, title_part)
        if score < MIN_MATCH_SCORE:
            score = title_match_score(game_slug.replace("-", " "), title_part)
        if score < MIN_MATCH_SCORE:
            continue
        full = href if href.startswith("http") else urljoin(BASE, href)
        pl_url = re.sub(r"kinguin\.net/[a-z]{2}/", "kinguin.net/pl/", full)
        scored_links.append((score, pl_url))

    scored_links.sort(key=lambda item: item[0], reverse=True)
    seen: set[str] = set()
    for score, category_url in scored_links:
        if category_url in seen:
            continue
        seen.add(category_url)
        listing = fetch_url(category_url)
        if listing is None or listing.status_code != 200:
            continue
        price_pln = extract_best_price(listing.text, kinguin_listing=True)
        if price_pln is not None:
            return category_url, price_pln, score

    return None, None, None


def import_kinguin_offers(db: Session, limit: int = 150) -> dict:
    return import_keyshop_offers(
        db,
        shop_name="Kinguin",
        search_fn=search_kinguin_price,
        limit=limit,
        delay_sec=1.2,
    )
