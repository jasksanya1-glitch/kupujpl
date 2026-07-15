"""Humble Store offers (official, PL region — EUR converted to PLN)."""
from __future__ import annotations

import logging
import os
import re
import time
from urllib.parse import urlencode

import requests
from sqlalchemy.orm import Session

from app.core.affiliate import make_affiliate_link
from app.core.db_retry import commit_with_retry
from app.models.models import Game, Offer
from app.parsers.currency_pln import to_pln
from app.parsers.keyshop_common import title_match_score, slugify

logger = logging.getLogger("humble_parser")

SHOP_NAME = "Humble Store"
STORE_BASE = "https://www.humblebundle.com/store"
ALGOLIA_APP_ID = os.environ.get("HUMBLE_ALGOLIA_APP_ID", "AYSZEWDAZ2")
ALGOLIA_API_KEY = os.environ.get("HUMBLE_ALGOLIA_API_KEY", "5229f8b3dec4b8ad265ad17ead42cb7f")
ALGOLIA_INDEX = os.environ.get("HUMBLE_ALGOLIA_INDEX", "replica_product_query_site_search")
ALGOLIA_URL = (
    f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"
)

HEADERS = {
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
    "X-Algolia-API-Key": ALGOLIA_API_KEY,
    "Content-Type": "application/json",
    "Accept-Language": "pl-PL,pl;q=0.9",
}

_SKIP_TITLE = (
    "soundtrack",
    " artbook",
    " expansion",
    " dlc",
    " add-on",
    " addon",
    " season pass",
    " coin ",
    " credits",
    " currency",
    " volume ",
    " bundle",
    " comic",
    " book",
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


def _search_catalog(title: str, *, limit: int = 10) -> list[dict]:
    hits: list[dict] = []
    seen: set[str] = set()
    for query in _search_queries(title):
        params = urlencode(
            {
                "query": query,
                "hitsPerPage": limit,
                "filters": "type:storefront",
            }
        )
        try:
            response = requests.post(
                ALGOLIA_URL,
                headers=HEADERS,
                json={"params": params},
                timeout=15,
            )
            if response.status_code != 200:
                logger.debug("Humble Algolia HTTP %s for %s", response.status_code, query)
                continue
            for item in response.json().get("hits") or []:
                if item.get("type") != "storefront":
                    continue
                key = item.get("machine_name") or item.get("objectID") or ""
                if key and key not in seen:
                    seen.add(key)
                    hits.append(item)
        except Exception as exc:
            logger.debug("Humble search failed for '%s': %s", query, exc)
    return hits


def _score_product(title: str, product: dict) -> float:
    candidate = product.get("human_name") or ""
    score = title_match_score(title, candidate)
    if score <= 0:
        return -1.0

    title_slug = slugify(title)
    title_tokens = {t for t in title_slug.split("-") if len(t) > 2}
    link_slug = slugify((product.get("link") or "").strip("/"))
    candidate_tokens = set(link_slug.split("-"))

    for token in title_tokens:
        if token in candidate_tokens:
            continue
        if any(token in other and token != other for other in candidate_tokens):
            score -= 0.55

    if link_slug and (link_slug in title_slug or title_slug in link_slug):
        score += 0.4
    overlap = len(title_tokens & candidate_tokens) / max(len(title_tokens), 1)
    score += overlap * 0.35
    return score


def _pick_best_product(title: str, products: list[dict]) -> dict | None:
    best: dict | None = None
    best_score = 0.0
    title_tokens = {t for t in slugify(title).split("-") if len(t) > 2}
    title_lower = title.lower()

    for product in products:
        candidate = product.get("human_name") or ""
        lower = candidate.lower()
        if any(x in lower for x in _SKIP_TITLE):
            continue
        if "ultimate edition" in lower and "ultimate" not in title_lower:
            if title_tokens.isdisjoint({"ultimate", "goty", "complete", "definitive"}):
                continue
        if "phantom liberty" in lower and "phantom liberty" not in title_lower:
            continue

        machine = product.get("machine_name") or ""
        link = (product.get("link") or "").lower()
        if "switch" not in title_lower and (
            machine.endswith("_switch")
            or machine.endswith("_switch2")
            or "-switch" in link
            or link.endswith("-switch-2")
        ):
            continue

        score = _score_product(title, product)

        if "complete edition" in title_lower and "complete edition" in lower:
            score += 0.2
        if "wild hunt" in title_lower and "wild hunt" in lower:
            score += 0.15

        if score > best_score:
            best_score = score
            best = product

    if best is None or best_score < 0.35:
        return None
    return best


def _price_pln_from_product(product: dict) -> float | None:
    localized = product.get("localized_prices") or {}
    pln_block = localized.get("PLN")
    if isinstance(pln_block, dict):
        amount = pln_block.get("current_price")
        if amount is not None:
            return to_pln(float(amount), "PLN")

    eur_amount = product.get("price_eur")
    if eur_amount is None:
        eur_block = localized.get("EUR") or {}
        eur_amount = eur_block.get("current_price")
    if eur_amount is None:
        pricing = product.get("current_pricing") or {}
        euro = pricing.get("EUROPE_EURO")
        if isinstance(euro, (list, tuple)) and euro:
            eur_amount = euro[0]
    if eur_amount is None:
        return None
    return to_pln(float(eur_amount), "EUR")


def _product_url(product: dict) -> str | None:
    link = (product.get("link") or "").strip()
    if not link:
        return None
    if not link.startswith("/"):
        link = f"/{link}"
    return f"{STORE_BASE}{link}"


def search_humble_price(title: str) -> tuple[str | None, float | None]:
    """Return (product_url, price_pln) for the best Humble Store match."""
    products = _search_catalog(title)
    product = _pick_best_product(title, products)
    if not product:
        return None, None
    price_pln = _price_pln_from_product(product)
    product_url = _product_url(product)
    if not product_url or price_pln is None:
        return None, None
    return product_url, price_pln


def update_humble_offer_for_game(db: Session, game: Game) -> bool:
    product_url, price_pln = search_humble_price(game.title)
    if not product_url or price_pln is None:
        return False

    affiliate_url = make_affiliate_link(product_url, SHOP_NAME)
    existing = (
        db.query(Offer)
        .filter(Offer.game_id == game.id, Offer.shop_name == SHOP_NAME)
        .first()
    )
    if existing:
        existing.price_pln = price_pln
        existing.affiliate_url = affiliate_url
        existing.in_stock = True
    else:
        db.add(
            Offer(
                game_id=game.id,
                shop_name=SHOP_NAME,
                price_pln=price_pln,
                original_price_pln=None,
                affiliate_url=affiliate_url,
                is_official=True,
                in_stock=True,
            )
        )
    return True


def import_humble_offers(db: Session, limit: int = 150) -> dict:
    games = (
        db.query(Game)
        .filter(Game.steam_enriched == True)
        .order_by(Game.id.desc())
        .limit(limit)
        .all()
    )
    added = updated = skipped = 0
    logger.info("Starting Humble Store updates for %s games...", len(games))

    for game in games:
        had = (
            db.query(Offer)
            .filter(Offer.game_id == game.id, Offer.shop_name == SHOP_NAME)
            .first()
        )
        if update_humble_offer_for_game(db, game):
            commit_with_retry(db)
            if had:
                updated += 1
            else:
                added += 1
        else:
            skipped += 1
        time.sleep(0.35)

    logger.info("Humble import done: added=%s updated=%s skipped=%s", added, updated, skipped)
    return {"shop": SHOP_NAME, "added": added, "updated": updated, "skipped": skipped}
