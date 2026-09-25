"""PlayStation Store PL prices (chihiro search + product page price)."""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote

from app.parsers.keyshop_common import (
    MIN_MATCH_SCORE,
    fetch_url,
    slugify,
    title_match_score,
)

logger = logging.getLogger("playstation_store_parser")

SHOP_NAME = "PlayStation Store"
CHIHIRO_SEARCH = (
    "https://store.playstation.com/store/api/chihiro/00_09_000/tumbler/"
    "PL/pl/999/{query}?suggested_size=20&mode=game"
)
PRODUCT_PAGE = "https://store.playstation.com/pl-pl/product/{product_id}"


def _parse_price_cents(html: str) -> float | None:
    """Extract PLN price from PS product HTML (values are in grosze)."""
    # Prefer discounted (current) price.
    for pat in (
        r'"discountedValue"\s*:\s*(\d+)',
        r'"basePriceValue"\s*:\s*(\d+)',
        r'"discountedPrice"\s*:\s*"(\d+)"',
        r'"basePrice"\s*:\s*"(\d+)"',
    ):
        match = re.search(pat, html)
        if not match:
            continue
        raw = int(match.group(1))
        # discountedValue is in cents; discountedPrice string can be whole zloty
        if "Value" in pat or raw >= 100:
            price = raw / 100.0 if raw >= 100 else float(raw)
        else:
            price = float(raw)
        if price >= 0.5:
            return round(price, 2)
    return None


def _product_price_pln(product_id: str) -> float | None:
    url = PRODUCT_PAGE.format(product_id=product_id)
    response = fetch_url(url, prefer_cffi=True)
    if response is None or response.status_code != 200:
        logger.warning("PS Store product page failed for %s", product_id)
        return None
    return _parse_price_cents(response.text)


def _score_link(title: str, name: str) -> float:
    if not name:
        return -1.0
    score = title_match_score(title, name)
    if score < MIN_MATCH_SCORE:
        return -1.0
    # Prefer titles that keep distinctive tokens from the query.
    q_tokens = {t for t in slugify(title).split("-") if len(t) > 2}
    n_tokens = {t for t in slugify(name).split("-") if len(t) > 2}
    if q_tokens and not (q_tokens & n_tokens):
        return -1.0
    return score


def _chihiro_query(title: str) -> str:
    """Chihiro returns 0 hits when the query contains ':' — strip punctuation."""
    cleaned = re.sub(r"[:™®©|/\\\\]+", " ", title or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def search_playstation_store_price(
    title: str,
    game_slug: str = "",
) -> tuple[str | None, float | None, float | None]:
    """Return (store_url, price_pln, match_confidence) for a PS Store title."""
    query = (title or "").strip()
    if not query:
        return None, None, None

    search_query = _chihiro_query(query)
    search_url = CHIHIRO_SEARCH.format(query=quote(search_query, safe=""))
    response = fetch_url(search_url, prefer_cffi=True)
    if response is None or response.status_code != 200:
        logger.warning("PS Store search failed for %s", search_query)
        return None, None, None

    try:
        data = response.json()
    except Exception:
        logger.warning("PS Store search JSON parse failed for %s", search_query)
        return None, None, None

    best: tuple[float, str, str] | None = None  # score, product_id, name
    for link in data.get("links") or []:
        if not isinstance(link, dict):
            continue
        name = str(link.get("name") or link.get("short_name") or "")
        product_id = str(link.get("id") or "")
        if not product_id or not name:
            continue
        # Skip bundles / add-ons when looking for the base game.
        lower = name.lower()
        if any(x in lower for x in ("bundle", " dodatek", "dlc", "upgrade", " season pass")):
            if not any(x in query.lower() for x in ("bundle", "dlc", "upgrade", "season")):
                continue
        score = _score_link(query, name)
        if game_slug:
            score = max(score, _score_link(game_slug.replace("-", " "), name))
        if score < MIN_MATCH_SCORE:
            continue
        if best is None or score > best[0]:
            best = (score, product_id, name)

    if best is None:
        return None, None, None

    score, product_id, _name = best
    price = _product_price_pln(product_id)
    if price is None:
        # Listed but not priced yet (coming soon) — still no offer row.
        logger.info("PS Store match without price for %s (%s)", query, product_id)
        return None, None, None

    url = PRODUCT_PAGE.format(product_id=product_id)
    return url, price, score
