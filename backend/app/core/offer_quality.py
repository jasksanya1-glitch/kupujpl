"""Filters for which offers may drive catalog 'best price' and savings badges."""
from __future__ import annotations

from statistics import median

from app.models.models import Offer

# Title-match score threshold for marketplace/keyshop offers (see keyshop_common.title_match_score).
BEST_PRICE_MIN_CONFIDENCE = 0.55

# Offers below this vs Steam are almost always wrong product / currency bugs.
STEAM_PRICE_RATIO_FLOOR = 0.12

# Absolute floor for marketplace listings when Steam price is high (EUR-as-PLN etc.).
MARKETPLACE_ABSURD_MAX_PLN = 3.0
STEAM_HIGH_PRICE_PLN = 25.0

# Peer-cluster outlier: one shop at 15 zł while others cluster around 200 zł.
PEER_OUTLIER_MIN_OTHERS = 1
PEER_OUTLIER_MIN_MEDIAN_PLN = 25.0
PEER_OUTLIER_RATIO = 0.40
PEER_OUTLIER_ABS_GAP_PLN = 20.0

# Steam is the price reference — never treat it as a peer outlier.
_STEAM_SHOPS = frozenset({"Steam", "Steam US"})
# Console storefronts are priced independently from Steam PC.
_CONSOLE_OFFICIAL_SHOPS = frozenset({"PlayStation Store", "Xbox Store"})


def _other_peer_prices(price: float, peer_prices: list[float] | None) -> list[float]:
    """Peer prices excluding one copy of this offer's price."""
    others = [float(p) for p in (peer_prices or []) if p is not None and float(p) > 0]
    try:
        others.remove(float(price))
    except ValueError:
        pass
    return others


def is_peer_price_outlier(price: float, other_prices: list[float] | None) -> bool:
    """True when price is absurdly below the peer cluster (wrong SKU / currency bug)."""
    if price is None or price <= 0 or not other_prices:
        return False
    peers = [float(p) for p in other_prices if p is not None and float(p) > 0]
    if len(peers) < PEER_OUTLIER_MIN_OTHERS:
        return False
    med = float(median(peers))
    if med < PEER_OUTLIER_MIN_MEDIAN_PLN:
        return False
    if price <= med * PEER_OUTLIER_RATIO and (med - price) >= PEER_OUTLIER_ABS_GAP_PLN:
        return True
    return False


def offer_eligible_for_best_price(
    offer: Offer,
    *,
    steam_price_pln: float | None = None,
    peer_prices: list[float] | None = None,
) -> bool:
    """Return True if this offer may be shown as the catalog best price."""
    if not offer.in_stock:
        return False
    price = offer.price_pln
    if price is None or price <= 0:
        return False

    shop = offer.shop_name or ""

    # Steam / console storefronts are trusted official references.
    if shop in _STEAM_SHOPS or shop in _CONSOLE_OFFICIAL_SHOPS:
        return True

    if not _passes_steam_sanity(shop, price, steam_price_pln):
        return False

    # Wrong GOG/Epic match (e.g. Sword of the Samurai @15 zł vs Onimusha @200 zł).
    if is_peer_price_outlier(price, _other_peer_prices(price, peer_prices)):
        return False

    if offer.is_official:
        return True

    # Marketplace / reseller — require match confidence.
    conf = offer.match_confidence
    if conf is None or conf < BEST_PRICE_MIN_CONFIDENCE:
        return False

    # Very cheap marketplace listing vs expensive Steam → likely wrong match.
    if (
        steam_price_pln is not None
        and steam_price_pln >= STEAM_HIGH_PRICE_PLN
        and price <= MARKETPLACE_ABSURD_MAX_PLN
    ):
        return False

    return True


def offer_is_suspicious_outlier(
    offer: Offer,
    *,
    steam_price_pln: float | None = None,
    peer_prices: list[float] | None = None,
) -> bool:
    """Offer that should not be shown / highlighted (wrong SKU, broken cheap link)."""
    price = offer.price_pln
    if price is None or price <= 0:
        return True

    shop = offer.shop_name or ""
    if shop in _STEAM_SHOPS or shop in _CONSOLE_OFFICIAL_SHOPS:
        return False

    if not _passes_steam_sanity(shop, price, steam_price_pln):
        return True

    if is_peer_price_outlier(price, _other_peer_prices(price, peer_prices)):
        return True

    if offer.is_official:
        return False

    conf = offer.match_confidence
    if conf is None or conf < BEST_PRICE_MIN_CONFIDENCE:
        return True

    if (
        steam_price_pln is not None
        and steam_price_pln >= STEAM_HIGH_PRICE_PLN
        and price <= MARKETPLACE_ABSURD_MAX_PLN
    ):
        return True

    return False


def _passes_steam_sanity(
    shop_name: str,
    price: float,
    steam_price_pln: float | None,
) -> bool:
    if steam_price_pln is None or steam_price_pln < 5:
        return True
    if shop_name in _STEAM_SHOPS or shop_name in _CONSOLE_OFFICIAL_SHOPS:
        return True
    ratio = price / steam_price_pln
    if ratio < STEAM_PRICE_RATIO_FLOOR:
        return False
    return True
