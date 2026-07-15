import logging
import re
import time
from urllib.parse import quote_plus

import requests
from sqlalchemy.orm import Session

from app.core.affiliate import make_affiliate_link
from app.core.db_retry import commit_with_retry
from app.models.models import Game, Offer
from app.parsers.keyshop_common import MIN_MATCH_SCORE, should_skip_product_title, title_match_score, slugify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gog_parser")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9",
}


def _gog_search_queries(title: str) -> list[str]:
    cleaned = re.sub(r"[:™®]", " ", title or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    queries = [cleaned]
    if cleaned.lower() != title.lower():
        queries.append(title)
    short = " ".join(cleaned.split()[:4])
    if short and short not in queries:
        queries.append(short)
    for suffix in (
        " game of the year edition",
        " goty edition",
        " complete edition",
        " definitive edition",
        " deluxe edition",
    ):
        if suffix in cleaned.lower():
            queries.append(re.sub(suffix, "", cleaned, flags=re.IGNORECASE).strip())
    return list(dict.fromkeys(q for q in queries if q))


def search_gog_catalog(title: str, *, limit: int = 8) -> list[dict]:
    products: list[dict] = []
    seen: set[str] = set()
    for query in _gog_search_queries(title):
        url = f"https://catalog.gog.com/v1/catalog?limit={limit}&query={quote_plus(query)}"
        try:
            response = requests.get(url, headers=HEADERS, timeout=12)
            if response.status_code != 200:
                continue
            for product in response.json().get("products") or []:
                pid = str(product.get("id") or "")
                if pid and pid not in seen:
                    seen.add(pid)
                    products.append(product)
        except Exception as exc:
            logger.error("GOG catalog search failed for '%s': %s", query, exc)
    return products


_SKIP_TITLE = (
    "dlc",
    "expansion",
    "soundtrack",
    " artbook",
    "redkit",
    " add-on",
    " addon",
    " season pass",
    " phantom liberty",
    " soundtrack",
    " coin ",
    " credits",
)


def pick_best_gog_product(title: str, products: list[dict]) -> dict | None:
    best: dict | None = None
    best_score = 0.0
    title_slug = slugify(title)
    title_tokens = {t for t in title_slug.split("-") if len(t) > 2}
    title_lower = title.lower()

    for product in products:
        candidate = product.get("title") or ""
        lower = candidate.lower()
        if should_skip_product_title(candidate):
            continue
        if "phantom liberty" in lower and "phantom liberty" not in title_lower:
            continue
        if "ultimate edition" in lower and "ultimate" not in title_lower and "edition" not in title_lower:
            if title_tokens.isdisjoint({"ultimate", "goty", "complete", "definitive"}):
                continue

        score = title_match_score(title, candidate)
        if score <= 0:
            continue
        product_slug = slugify(product.get("slug") or "")
        slug_tokens = {t for t in product_slug.split("-") if len(t) > 2}
        overlap = len(title_tokens & slug_tokens) / max(len(title_tokens), 1)
        score += overlap * 0.35

        if "complete edition" in title_lower and "complete edition" in lower:
            score += 0.2
        if "wild hunt" in title_lower and "wild hunt" in lower:
            score += 0.15

        if score > best_score:
            best_score = score
            best = product
    if best is None or best_score < MIN_MATCH_SCORE:
        return None
    best["_match_score"] = best_score
    return best


def fetch_gog_price_pln(gog_id: str) -> tuple[float | None, float | None]:
    url = f"https://api.gog.com/products/prices?ids={gog_id}&countryCode=PL"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            items = response.json().get("_embedded", {}).get("items", [])
            if items:
                prices = items[0].get("_embedded", {}).get("prices", [])
                for price in prices:
                    if price.get("currency", {}).get("code") == "PLN":
                        base_str = price.get("basePrice", "0 PLN").split()[0]
                        final_str = price.get("finalPrice", "0 PLN").split()[0]
                        return int(final_str) / 100.0, int(base_str) / 100.0
    except Exception as exc:
        logger.error("GOG price fetch failed for ID %s: %s", gog_id, exc)
    return None, None


def search_gog_price(title: str) -> tuple[str | None, float | None, float | None]:
    """Return (product_url, price_pln, match_confidence) for the best GOG match."""
    products = search_gog_catalog(title)
    product = pick_best_gog_product(title, products)
    if not product:
        return None, None, None

    gog_id = product.get("id")
    slug = product.get("slug")
    if not gog_id or not slug:
        return None, None, None

    price_pln, _original = fetch_gog_price_pln(gog_id)
    if price_pln is None:
        return None, None, None

    confidence = float(product.get("_match_score") or MIN_MATCH_SCORE)
    return f"https://www.gog.com/pl/game/{slug}", price_pln, confidence


def find_gog_game(title: str) -> dict:
    products = search_gog_catalog(title, limit=5)
    return pick_best_gog_product(title, products) or {}


def update_gog_offer_for_game(db: Session, game: Game) -> bool:
    product_url, price_pln, confidence = search_gog_price(game.title)
    if not product_url or price_pln is None:
        return False

    affiliate_url = make_affiliate_link(product_url, "GOG")
    existing_offer = (
        db.query(Offer)
        .filter(Offer.game_id == game.id, Offer.shop_name == "GOG")
        .first()
    )
    if existing_offer:
        existing_offer.price_pln = price_pln
        existing_offer.affiliate_url = affiliate_url
        existing_offer.in_stock = True
        if confidence is not None:
            existing_offer.match_confidence = confidence
    else:
        db.add(
            Offer(
                game_id=game.id,
                shop_name="GOG",
                price_pln=price_pln,
                original_price_pln=None,
                affiliate_url=affiliate_url,
                is_official=True,
                in_stock=True,
                match_confidence=confidence,
            )
        )
    return True


def import_gog_offers(db: Session, limit: int = 150) -> dict:
    games = (
        db.query(Game)
        .filter(Game.steam_enriched == True)
        .order_by(Game.id.desc())
        .limit(limit)
        .all()
    )
    added = updated = skipped = 0
    logger.info("Starting GOG price updates for %s games...", len(games))

    for game in games:
        had = (
            db.query(Offer)
            .filter(Offer.game_id == game.id, Offer.shop_name == "GOG")
            .first()
        )
        if update_gog_offer_for_game(db, game):
            commit_with_retry(db)
            if had:
                updated += 1
            else:
                added += 1
        else:
            skipped += 1
        time.sleep(0.6)

    logger.info("GOG import done: added=%s updated=%s skipped=%s", added, updated, skipped)
    return {"shop": "GOG", "added": added, "updated": updated, "skipped": skipped}
