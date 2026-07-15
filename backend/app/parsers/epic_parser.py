"""Epic Games Store offers (official, PL region)."""
from __future__ import annotations

import logging
import re
import time

import requests
from sqlalchemy.orm import Session

from app.core.affiliate import make_affiliate_link
from app.core.db_retry import commit_with_retry
from app.models.models import Game, Offer
from app.parsers.keyshop_common import MIN_MATCH_SCORE, should_skip_product_title, title_match_score, slugify

logger = logging.getLogger("epic_parser")

GRAPHQL_URL = "https://store.epicgames.com/graphql"
STORE_BASE = "https://store.epicgames.com/pl/p"
COUNTRY = "PL"
LOCALE = "pl"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept-Language": "pl-PL,pl;q=0.9",
}

_SEARCH_QUERY = """
query searchStoreQuery($country: String!, $locale: String!, $keywords: String!, $count: Int) {
  Catalog {
    searchStore(country: $country, locale: $locale, keywords: $keywords, count: $count) {
      elements {
        title
        productSlug
        urlSlug
        price(country: $country) {
          totalPrice {
            discountPrice
            originalPrice
            currencyCode
          }
        }
      }
    }
  }
}
"""

_SKIP_TITLE = (
    "soundtrack",
    " artbook",
    "redkit",
    " expansion",
    " dlc",
    " add-on",
    " addon",
    " season pass",
    " coin ",
    " credits",
    " currency",
)


def _search_queries(title: str) -> list[str]:
    cleaned = re.sub(r"[:™®]", " ", title or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    queries = [cleaned]
    short = " ".join(cleaned.split()[:4])
    if short and short not in queries:
        queries.append(short)
    for suffix in (
        " game of the year edition",
        " goty edition",
        " complete edition",
        " definitive edition",
        " ultimate edition",
        " deluxe edition",
        " - edition",
    ):
        if suffix in cleaned.lower():
            base = re.sub(suffix, "", cleaned, flags=re.IGNORECASE).strip()
            if base and base not in queries:
                queries.append(base)
    return list(dict.fromkeys(q for q in queries if q))


def _search_catalog(title: str, *, limit: int = 8) -> list[dict]:
    elements: list[dict] = []
    seen: set[str] = set()
    for query in _search_queries(title):
        try:
            response = requests.post(
                GRAPHQL_URL,
                json={
                    "query": _SEARCH_QUERY,
                    "variables": {
                        "country": COUNTRY,
                        "locale": LOCALE,
                        "keywords": query,
                        "count": limit,
                    },
                },
                headers=HEADERS,
                timeout=15,
            )
            if response.status_code != 200:
                continue
            payload = response.json()
            if payload.get("errors"):
                logger.debug("Epic GraphQL errors for %s: %s", query, payload["errors"])
                continue
            batch = (
                payload.get("data", {})
                .get("Catalog", {})
                .get("searchStore", {})
                .get("elements")
                or []
            )
            for item in batch:
                slug = item.get("urlSlug") or item.get("productSlug") or ""
                if slug and slug not in seen:
                    seen.add(slug)
                    elements.append(item)
        except Exception as exc:
            logger.debug("Epic search failed for '%s': %s", query, exc)
    return elements


def _pick_best_product(title: str, products: list[dict]) -> dict | None:
    best: dict | None = None
    best_score = 0.0
    title_slug = slugify(title)
    title_tokens = {t for t in title_slug.split("-") if len(t) > 2}

    for product in products:
        candidate = product.get("title") or ""
        lower = candidate.lower()
        if should_skip_product_title(candidate):
            continue
        price_block = (product.get("price") or {}).get("totalPrice") or {}
        if price_block.get("currencyCode") != "PLN":
            continue

        score = title_match_score(title, candidate)
        product_slug = slugify(product.get("urlSlug") or product.get("productSlug") or "")
        slug_tokens = {t for t in product_slug.split("-") if len(t) > 2}
        overlap = len(title_tokens & slug_tokens) / max(len(title_tokens), 1)
        score += overlap * 0.35

        if score > best_score:
            best_score = score
            best = product
    if best is None or best_score < MIN_MATCH_SCORE:
        return None
    best["_match_score"] = best_score
    return best


def _price_pln_from_product(product: dict) -> float | None:
    total = (product.get("price") or {}).get("totalPrice") or {}
    if total.get("currencyCode") != "PLN":
        return None
    amount = total.get("discountPrice")
    if amount is None:
        return None
    return round(int(amount) / 100.0, 2)


def _product_url(product: dict) -> str | None:
    slug = product.get("urlSlug") or product.get("productSlug")
    if not slug:
        return None
    return f"{STORE_BASE}/{slug}"


def search_epic_price(title: str) -> tuple[str | None, float | None, float | None]:
    """Return (product_url, price_pln, match_confidence) for the best Epic match."""
    products = _search_catalog(title)
    product = _pick_best_product(title, products)
    if not product:
        return None, None, None
    price_pln = _price_pln_from_product(product)
    product_url = _product_url(product)
    if not product_url or price_pln is None:
        return None, None, None
    confidence = float(product.get("_match_score") or MIN_MATCH_SCORE)
    return product_url, price_pln, confidence


def update_epic_offer_for_game(db: Session, game: Game) -> bool:
    product_url, price_pln, confidence = search_epic_price(game.title)
    if not product_url or price_pln is None:
        return False

    affiliate_url = make_affiliate_link(product_url, "Epic Games")
    existing = (
        db.query(Offer)
        .filter(Offer.game_id == game.id, Offer.shop_name == "Epic Games")
        .first()
    )
    if existing:
        existing.price_pln = price_pln
        existing.affiliate_url = affiliate_url
        existing.in_stock = True
        if confidence is not None:
            existing.match_confidence = confidence
    else:
        db.add(
            Offer(
                game_id=game.id,
                shop_name="Epic Games",
                price_pln=price_pln,
                original_price_pln=None,
                affiliate_url=affiliate_url,
                is_official=True,
                in_stock=True,
                match_confidence=confidence,
            )
        )
    return True


def import_epic_offers(db: Session, limit: int = 150) -> dict:
    games = (
        db.query(Game)
        .filter(Game.steam_enriched == True)
        .order_by(Game.id.desc())
        .limit(limit)
        .all()
    )
    added = updated = skipped = 0
    logger.info("Starting Epic Games updates for %s games...", len(games))

    for game in games:
        had = (
            db.query(Offer)
            .filter(Offer.game_id == game.id, Offer.shop_name == "Epic Games")
            .first()
        )
        if update_epic_offer_for_game(db, game):
            commit_with_retry(db)
            if had:
                updated += 1
            else:
                added += 1
        else:
            skipped += 1
        time.sleep(0.5)

    logger.info("Epic import done: added=%s updated=%s skipped=%s", added, updated, skipped)
    return {"shop": "Epic Games", "added": added, "updated": updated, "skipped": skipped}
