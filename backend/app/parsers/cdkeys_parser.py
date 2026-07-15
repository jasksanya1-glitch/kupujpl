"""CDKeys PL key shop offers via Algolia (works when cdkeys.com blocks datacenter IPs)."""
from __future__ import annotations

import base64
import logging
import os
import re
import time
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.parsers.keyshop_common import (
    fetch_url,
    import_keyshop_offers,
    is_restricted_region_listing,
    slugify,
    title_match_score,
    title_mismatch,
)

logger = logging.getLogger("cdkeys_parser")

BASE = "https://www.cdkeys.com"
ALGOLIA_APP_ID = os.environ.get("CDKEYS_ALGOLIA_APP_ID", "MUVYIB7TEY").strip()
ALGOLIA_INDEX = os.environ.get("CDKEYS_ALGOLIA_INDEX", "magento2_default_products").strip()
ALGOLIA_URL = (
    f"https://{ALGOLIA_APP_ID.lower()}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"
)

# Secured search-only key from cdkeys.com frontend (refreshed from cdkeys.com/).
_DEFAULT_ALGOLIA_KEY = (
    "NGE2MWY4Y2Y4NmY4NGNmYWVjY2Q2NjllZmQ0NzQzNmEzMDc0MjEwN2U0ZWUyOTE2ZDBlN2JiMzZkNTRk"
    "OTU4YnRhZ0ZpbHRlcnM9JnZhbGlkVW50aWw9MTc4MDg3NzAyNA=="
)

_FETCH_URLS = (
    f"{BASE}/",
    "https://www.loaded.com/",
    f"{BASE}/pl/",
)

_cached_api_key: str | None = None
_cached_api_key_at: float = 0.0
_KEY_CACHE_TTL_SEC = 6 * 3600
# When no usable key can be obtained (default expired + live refresh blocked by
# Cloudflare on datacenter IPs), back off so a long catalog scan does not re-hit
# the blocked frontends / dead Algolia endpoint for every single game.
_NO_KEY_BACKOFF_SEC = 3600
_no_key_until: float = 0.0

_CONSOLE_MARKERS = (
    "xbox",
    "ps4",
    "ps5",
    "playstation",
    "nintendo",
    "switch",
    " ps3",
)

_SKIP_IN_NAME = (
    "dlc",
    "add-on",
    "addon",
    "season pass",
    "soundtrack",
    "artbook",
    "wallet",
    "gift card",
    " points",
    " coin ",
    "currency",
    "expansion pass",
    "blood and wine",
    "hearts of stone",
    "phantom liberty",
    "nightreign",
    "comic",
    " ebook",
)

_SKIP_UNLESS_IN_TITLE = (
    "dlc",
    "expansion pass",
    "blood and wine",
    "hearts of stone",
    "remake",
    "remaster",
)


def _extract_api_key_from_html(html: str) -> str | None:
    for pattern in (
        r'"apiKey"\s*:\s*"([^"]+)"',
        r"'apiKey'\s*:\s*'([^']+)'",
    ):
        match = re.search(pattern, html)
        if match and len(match.group(1)) > 40:
            return match.group(1)
    return None


def _key_valid_until(key: str) -> float | None:
    """Return the embedded validUntil epoch of an Algolia secured key, if any."""
    try:
        decoded = base64.b64decode(key).decode("utf-8", "replace")
    except Exception:
        return None
    match = re.search(r"validUntil=(\d+)", decoded)
    return float(match.group(1)) if match else None


def _key_is_expired(key: str) -> bool:
    valid_until = _key_valid_until(key)
    if valid_until is None:
        return False  # Opaque / non-expiring key: assume usable.
    return valid_until <= time.time()


def _get_algolia_api_key() -> str | None:
    global _cached_api_key, _cached_api_key_at, _no_key_until

    env_key = os.environ.get("CDKEYS_ALGOLIA_API_KEY", "").strip()
    if env_key:
        return env_key

    now = time.time()
    if _cached_api_key and (now - _cached_api_key_at) < _KEY_CACHE_TTL_SEC:
        if not _key_is_expired(_cached_api_key):
            return _cached_api_key
        _cached_api_key = None
    if now < _no_key_until:
        return None

    for url in _FETCH_URLS:
        response = fetch_url(url, prefer_cffi=True)
        if response is None or response.status_code != 200:
            continue
        if len(response.text) < 5000:
            continue
        key = _extract_api_key_from_html(response.text)
        if key and not _key_is_expired(key):
            _cached_api_key = key
            _cached_api_key_at = now
            logger.info("CDKeys Algolia key refreshed from %s", url)
            return key

    if _DEFAULT_ALGOLIA_KEY and not _key_is_expired(_DEFAULT_ALGOLIA_KEY):
        _cached_api_key = _DEFAULT_ALGOLIA_KEY
        _cached_api_key_at = now
        return _DEFAULT_ALGOLIA_KEY

    _no_key_until = now + _NO_KEY_BACKOFF_SEC
    logger.warning(
        "CDKeys Algolia key unavailable (bundled key expired, live refresh blocked); "
        "skipping CDKeys until a fresh key is configured via CDKEYS_ALGOLIA_API_KEY"
    )
    return None


def _localized_field(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("default") or value.get("pl_pl") or "")
    return str(value or "")


def _pln_price(hit: dict) -> float | None:
    price = hit.get("price")
    if not isinstance(price, dict):
        return None
    pln = price.get("PLN")
    if not isinstance(pln, dict):
        return None
    amount = pln.get("default")
    if amount is None:
        return None
    try:
        return float(amount)
    except (TypeError, ValueError):
        return None


def _product_url(hit: dict) -> str | None:
    raw = _localized_field(hit.get("url"))
    if not raw:
        urls = hit.get("url")
        if isinstance(urls, dict):
            raw = urls.get("pl_pl") or urls.get("default") or ""
    if not raw:
        return None
    if raw.startswith("/"):
        raw = f"{BASE}{raw}"
    return (
        raw.replace("www.loaded.com/pl_pl/", "www.cdkeys.com/pl/")
        .replace("www.loaded.com/", "www.cdkeys.com/")
    )


def _in_stock(hit: dict) -> bool:
    stock = hit.get("in_stock")
    if isinstance(stock, dict):
        return bool(stock.get("default", True))
    if stock is None:
        return True
    return bool(stock)


def _search_queries(title: str) -> list[str]:
    cleaned = re.sub(r"[:™®]", " ", title or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    queries = [cleaned]
    short = " ".join(cleaned.split()[:4])
    if short and short not in queries:
        queries.append(short)
    if " pc" not in cleaned.lower():
        pc_q = f"{cleaned} pc"
        if pc_q not in queries:
            queries.append(pc_q)
    return list(dict.fromkeys(q for q in queries if q))


def _token_coverage(title: str, name: str) -> float:
    stop = {"the", "a", "an", "of", "and", "for", "game", "edition", "global", "pl", "key", "pc"}
    tokens = [t for t in slugify(title).split("-") if t and t not in stop and len(t) > 1]
    if not tokens:
        return 0.0
    cand = slugify(name)
    matched = sum(1 for token in tokens if token in cand)
    return matched / len(tokens)


def _is_pc_product(combined: str) -> bool:
    if any(marker in combined for marker in _CONSOLE_MARKERS):
        if not any(p in combined for p in (" pc", "pc ", "steam", "gog", "epic", "-pc", "/pc")):
            return False
    return any(
        p in combined
        for p in (" pc", "pc ", "steam", "gog", "epic", "cd-key", "cd key", "-pc", "/pc")
    )


def _sequel_mismatch(title: str, name: str) -> bool:
    title_l = f" {title.lower()} "
    name_l = f" {name.lower().replace('-', ' ')} "
    for marker in (" ii ", " iii ", " iv ", " 2 ", " 3 ", " 4 "):
        if marker in name_l and marker not in title_l:
            return True
    return False


def _should_skip(title: str, name: str, combined: str) -> bool:
    title_lower = title.lower()
    name_lower = name.lower()
    combined_lower = combined.lower()

    if _sequel_mismatch(title, name):
        return True

    if is_restricted_region_listing(combined):
        return True

    for marker in _SKIP_IN_NAME:
        if marker in name_lower and marker not in title_lower:
            return True

    for marker in _SKIP_UNLESS_IN_TITLE:
        if marker in name_lower and marker not in title_lower:
            return True

    if "digital code" in combined_lower and "pc" not in combined_lower:
        return True

    return False


def _score_hit(title: str, hit: dict) -> float:
    name = _localized_field(hit.get("name"))
    url = _product_url(hit) or ""
    combined = f"{name} {url}".lower()

    if _should_skip(title, name, combined):
        return -1.0
    if not _in_stock(hit):
        return -1.0
    if not _is_pc_product(combined):
        return -1.0

    coverage = _token_coverage(title, name)
    if coverage < 0.75:
        return -1.0

    if title_mismatch(title, name) or title_mismatch(title, url):
        return -1.0

    score = title_match_score(title, name)
    if score <= 0:
        return -1.0
    score += coverage * 0.35

    if "steam" in combined and "pc" in combined:
        score += 0.28
    elif re.search(r"\bpc\b", combined):
        score += 0.18
    elif "gog" in combined:
        score += 0.12

    if "cd-key" in combined or "cd key" in name.lower():
        score += 0.04

    return score


def _search_algolia(query: str, *, limit: int = 24) -> list[dict]:
    api_key = _get_algolia_api_key()
    if not api_key:
        logger.debug("CDKeys Algolia API key unavailable")
        return []

    headers = {
        "X-Algolia-Application-Id": ALGOLIA_APP_ID,
        "X-Algolia-API-Key": api_key,
        "Content-Type": "application/json",
    }
    payload = {"query": query, "hitsPerPage": limit}

    try:
        response = requests.post(ALGOLIA_URL, json=payload, headers=headers, timeout=15)
    except Exception as exc:
        logger.warning("CDKeys Algolia request failed for %s: %s", query, exc)
        return []

    if response.status_code == 403:
        logger.warning("CDKeys Algolia key rejected (403) for %s", query)
        return []
    if response.status_code != 200:
        logger.warning("CDKeys Algolia HTTP %s for %s", response.status_code, query)
        return []

    return list(response.json().get("hits") or [])


def search_cdkeys_price(query: str, game_slug: str) -> tuple[str | None, float | None]:
    from app.parsers.affiliate_feeds import affiliate_feed_lookup

    feed = affiliate_feed_lookup("CDKeys", query, game_slug, min_score=0.55)
    if feed:
        return feed.url, feed.price_pln

    del game_slug  # Algolia search uses title tokens instead of slug URLs.

    if not _get_algolia_api_key():
        return None, None  # No usable key; skip quietly (backoff logs once/hour).

    best_url: str | None = None
    best_price: float | None = None
    best_score = 0.0
    seen_urls: set[str] = set()

    for q in _search_queries(query):
        for hit in _search_algolia(q):
            score = _score_hit(query, hit)
            if score < 0.55:
                continue

            price = _pln_price(hit)
            url = _product_url(hit)
            if price is None or not url or url in seen_urls:
                continue
            seen_urls.add(url)

            if score > best_score or (
                score == best_score
                and best_url
                and is_restricted_region_listing(best_url)
                and not is_restricted_region_listing(url)
            ) or (
                score == best_score
                and (best_price is None or price < best_price)
                and not (
                    best_url
                    and not is_restricted_region_listing(best_url)
                    and is_restricted_region_listing(url)
                )
            ):
                best_score = score
                best_url = url
                best_price = price

    if best_url and best_price is not None:
        return best_url, best_price

    return None, None


def import_cdkeys_offers(db: Session, limit: int = 150) -> dict:
    return import_keyshop_offers(
        db,
        shop_name="CDKeys",
        search_fn=search_cdkeys_price,
        limit=limit,
        delay_sec=0.35,
    )
