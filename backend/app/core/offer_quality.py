"""Filters for which offers may drive catalog 'best price' and savings badges."""
from __future__ import annotations

from app.models.models import Offer

# Title-match score threshold for marketplace/keyshop offers (see keyshop_common.title_match_score).
BEST_PRICE_MIN_CONFIDENCE = 0.55

# Offers below this vs Steam are almost always wrong product / currency bugs.
STEAM_PRICE_RATIO_FLOOR = 0.12

# Absolute floor for marketplace listings when Steam price is high (EUR-as-PLN etc.).
MARKETPLACE_ABSURD_MAX_PLN = 3.0
STEAM_HIGH_PRICE_PLN = 25.0


def offer_eligible_for_best_price(
    offer: Offer,
    *,
    steam_price_pln: float | None = None,
) -> bool:
    """Return True if this offer may be shown as the catalog best price."""
    if not offer.in_stock:
        return False
    price = offer.price_pln
    if price is None or price <= 0:
        return False

    # Official stores (Steam/GOG/Epic/…) — linked by app id, trust the listing.
    if offer.is_official:
        return _passes_steam_sanity(offer.shop_name, price, steam_price_pln)

    # Marketplace / reseller — require match confidence.
    conf = offer.match_confidence
    if conf is None or conf < BEST_PRICE_MIN_CONFIDENCE:
        return False

    if not _passes_steam_sanity(offer.shop_name, price, steam_price_pln):
        return False

    # Very cheap marketplace listing vs expensive Steam → likely wrong match.
    if (
        steam_price_pln is not None
        and steam_price_pln >= STEAM_HIGH_PRICE_PLN
        and price <= MARKETPLACE_ABSURD_MAX_PLN
    ):
        return False

    return True


def _passes_steam_sanity(
    shop_name: str,
    price: float,
    steam_price_pln: float | None,
) -> bool:
    if steam_price_pln is None or steam_price_pln < 5:
        return True
    if shop_name == "Steam":
        return True
    ratio = price / steam_price_pln
    if ratio < STEAM_PRICE_RATIO_FLOOR:
        return False
    return True
