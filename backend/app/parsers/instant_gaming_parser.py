"""Instant Gaming PL key shop offers (searchResults JSON embedded in HTML)."""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote_plus

from sqlalchemy.orm import Session

from app.core.affiliate import make_affiliate_link
from app.parsers.currency_pln import to_pln
from app.parsers.keyshop_common import (
    MIN_MATCH_SCORE,
    fetch_url,
    import_keyshop_offers,
    slugify,
    title_match_score,
    title_mismatch,
)

logger = logging.getLogger("instant_gaming_parser")

BASE = "https://www.instant-gaming.com"
SEARCH_URL = f"{BASE}/pl/szukaj/?q={{query}}"
SHOP_NAME = "Instant Gaming"

_SKIP_TYPES = (
    "playstation",
    "xbox",
    "nintendo",
    "switch",
    "apple",
    "google play",
    "ubisoft connect",
)

_CONSOLE_MARKERS = (
    "xbox",
    "ps4",
    "ps5",
    "playstation",
    "nintendo",
    "switch",
)

_PREFER_TYPES = (
    "steam",
    "gog.com",
    "epic games",
    "ea app",
    "origin",
    "battle.net",
    "rockstar",
)

_TOKEN_STOP = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "for",
    "pc",
    "mac",
    "game",
    "steam",
    "gog",
    "com",
    "epic",
    "games",
    "edition",
    "global",
    "key",
    "europe",
}


def _strict_tokens(*parts: str) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        for token in slugify(part).split("-"):
            if not token or token in _TOKEN_STOP:
                continue
            if len(token) > 1 or token.isdigit() or token in {"i", "v", "x"}:
                tokens.add(token)
    return tokens


def _parse_search_results(html: str) -> list[dict]:
    match = re.search(r"window\.searchResults\s*=\s*(\{.+?\});\s*\n", html, re.S)
    if not match:
        match = re.search(r"window\.searchResults\s*=\s*(\{.+?\});", html, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    hits = data.get("hits")
    return hits if isinstance(hits, list) else []


def _platform_score(platform_type: str) -> float:
    lower = (platform_type or "").lower()
    if any(skip in lower for skip in _SKIP_TYPES):
        return -1.0
    for idx, prefer in enumerate(_PREFER_TYPES):
        if prefer in lower:
            return 1.0 - idx * 0.05
    if "microsoft" in lower:
        return 0.35
    return 0.5


def _product_base_url(prod_id: int, seo_name: str) -> str:
    path = f"/pl/{prod_id}-{seo_name}/"
    return f"{BASE}{path}"


def _product_url(prod_id: int, seo_name: str) -> str:
    return make_affiliate_link(_product_base_url(prod_id, seo_name), SHOP_NAME)


def _product_page_price_pln(url: str) -> float | None:
    """Read the visible product page price in selected PLN currency."""
    sep = "&" if "?" in url else "?"
    response = fetch_url(f"{url}{sep}currency=PLN", prefer_cffi=True)
    if response is None or response.status_code != 200:
        return None
    html = response.text

    # Instant Gaming renders the current currency price in schema/meta tags.
    match = re.search(
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([0-9]+(?:[.,][0-9]+)?)["\']',
        html,
        re.I,
    )
    if not match:
        match = re.search(
            r'"currencyCode"\s*:\s*"PLN".{0,300}?"price"\s*:\s*"([0-9]+(?:[.,][0-9]+)?)"',
            html,
            re.I | re.S,
        )
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None

    currency_match = re.search(
        r'<meta[^>]+itemprop=["\']priceCurrency["\'][^>]+content=["\']([A-Z]{3})["\']',
        html,
        re.I,
    )
    currency = currency_match.group(1).upper() if currency_match else "PLN"
    if currency != "PLN":
        converted = to_pln(value, currency)
        return converted if converted is not None and converted >= 0.5 else None
    return round(value, 2) if value >= 0.5 else None


def _price_pln(hit: dict) -> float | None:
    """IG search embeds EUR amounts in every currency slot — convert EUR to PLN."""
    prices = hit.get("currency_prices") or {}
    eur_raw = prices.get("EUR")
    if eur_raw is not None:
        try:
            eur = float(eur_raw)
        except (TypeError, ValueError):
            eur = -1.0
        if eur >= 0.5:
            converted = to_pln(eur, "EUR")
            if converted is not None:
                return converted

    pln_raw = prices.get("PLN")
    if pln_raw is None:
        pln_raw = hit.get("price")
    if pln_raw is None:
        return None
    try:
        value = float(pln_raw)
    except (TypeError, ValueError):
        return None
    return round(value, 2) if value >= 0.5 else None


def _score_hit(hit: dict, query: str, game_slug: str) -> float:
    if hit.get("is_dlc") or hit.get("is_subscription") or hit.get("is_draft"):
        return -1.0
    if not hit.get("has_stock", 1):
        return -1.0

    blob = " ".join(
        str(hit.get(key) or "")
        for key in ("type", "platform", "seo_name", "fullname", "name")
    ).lower()
    if any(marker in blob for marker in _CONSOLE_MARKERS):
        return -1.0

    platform = str(hit.get("type") or hit.get("platform") or "")
    platform_bonus = _platform_score(platform)
    if platform_bonus < 0:
        return -1.0

    name = str(hit.get("name") or hit.get("en_name") or hit.get("fullname") or "")
    seo = str(hit.get("seo_name") or "")
    if title_mismatch(query, name) or title_mismatch(query, seo.replace("-", " ")):
        return -1.0

    q_tokens = _strict_tokens(query, game_slug.replace("-", " "))
    c_tokens = _strict_tokens(name, seo.replace("-", " "))
    if q_tokens and len(q_tokens) <= 2:
        # Short/common titles ("The Forest", "Dungeons 2", "Reigns") are prone to
        # false positives in IG search. Require a tight title, not just one token.
        allowed_extra = {"remastered", "remaster", "remake", "complete", "goty"}
        extra = c_tokens - q_tokens - allowed_extra
        if extra:
            return -1.0

    score = title_match_score(query, name)
    if score < MIN_MATCH_SCORE:
        score = title_match_score(game_slug.replace("-", " "), name)
    if score <= 0:
        return -1.0

    edition = str(hit.get("edition") or "").lower()
    if edition and edition not in (query or "").lower():
        if any(x in edition for x in ("ultimate", "deluxe", "goty", "complete", "gold")):
            if not any(x in (query or "").lower() for x in ("ultimate", "deluxe", "goty", "complete", "gold", "edition")):
                score -= 0.12

    return score + platform_bonus * 0.15


def search_instant_gaming_price(query: str, game_slug: str) -> tuple[str | None, float | None, float | None]:
    search_url = SEARCH_URL.format(query=quote_plus(query))
    response = fetch_url(search_url, prefer_cffi=True)
    if response is None:
        logger.warning("Instant Gaming search failed for %s", query)
        return None, None, None
    if response.status_code != 200:
        logger.warning("Instant Gaming search HTTP %s for %s", response.status_code, query)
        return None, None, None

    best: tuple[float, str, float] | None = None
    for hit in _parse_search_results(response.text):
        prod_id = hit.get("prod_id")
        seo_name = hit.get("seo_name")
        if not prod_id or not seo_name:
            continue
        score = _score_hit(hit, query, game_slug)
        if score < MIN_MATCH_SCORE:
            continue
        product_base_url = _product_base_url(int(prod_id), str(seo_name))
        price_pln = _product_page_price_pln(product_base_url) or _price_pln(hit)
        if price_pln is None:
            continue
        url = make_affiliate_link(product_base_url, SHOP_NAME)
        if best is None or score > best[0]:
            best = (score, url, price_pln)

    if best is None:
        return None, None, None
    return best[1], best[2], best[0]


def import_instant_gaming_offers(db: Session, limit: int = 150) -> dict:
    return import_keyshop_offers(
        db,
        shop_name=SHOP_NAME,
        search_fn=search_instant_gaming_price,
        limit=limit,
        delay_sec=1.2,
    )
