"""Filters for which offers may drive catalog 'best price' and savings badges."""
from __future__ import annotations

from datetime import datetime
from statistics import median

from app.core.offer_freshness import offer_may_confirm_best_price
from app.models.models import Offer
from app.parsers.keyshop_common import classify_keyshop_product, product_title_from_url

# Title-match score threshold for marketplace/keyshop offers (see keyshop_common.title_match_score).
BEST_PRICE_MIN_CONFIDENCE = 0.55

# Offers below this vs Steam are almost always wrong product / currency bugs.
STEAM_PRICE_RATIO_FLOOR = 0.12
# Keyshop listing far above Steam / peers — wrong SKU or currency (e.g. Love Is All Around 2401 zł).
STEAM_PRICE_RATIO_CEILING = 3.5

# Absolute floor for marketplace listings when Steam price is high (EUR-as-PLN etc.).
MARKETPLACE_ABSURD_MAX_PLN = 3.0
STEAM_HIGH_PRICE_PLN = 25.0

# Peer-cluster outlier: one shop at 15 zł while others cluster around 200 zł.
PEER_OUTLIER_MIN_OTHERS = 1
PEER_OUTLIER_MIN_MEDIAN_PLN = 25.0
PEER_OUTLIER_RATIO = 0.40
PEER_OUTLIER_ABS_GAP_PLN = 20.0

# Marketplace confirmed / hero: reject implausible deep undercut vs Steam (wrong SKU cluster).
KEYSHOP_CONFIRMED_STEAM_RATIO = 0.22

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


def is_expensive_vs_steam_reference(
    price: float,
    *,
    steam_price_pln: float | None,
    shop_name: str,
) -> bool:
    if price is None or price <= 0:
        return False
    if shop_name in _STEAM_SHOPS or shop_name in _CONSOLE_OFFICIAL_SHOPS:
        return False
    if steam_price_pln is None or steam_price_pln < 5:
        return False
    return price > float(steam_price_pln) * STEAM_PRICE_RATIO_CEILING


def _outlier_reference_median(
    price: float,
    peer_prices: list[float] | None,
    *,
    steam_price_pln: float | None = None,
) -> float | None:
    """Median of peer prices (excluding this offer), anchored up to Steam when Steam is high."""
    others = _other_peer_prices(price, peer_prices)
    if steam_price_pln is not None and steam_price_pln > 0:
        others = others + [float(steam_price_pln)]
    if len(others) < PEER_OUTLIER_MIN_OTHERS:
        return None
    med = float(median(others))
    if steam_price_pln is not None and steam_price_pln >= STEAM_HIGH_PRICE_PLN:
        med = max(med, float(steam_price_pln))
    return med


def is_keyshop_too_cheap_vs_steam(
    price: float,
    *,
    steam_price_pln: float | None,
    shop_name: str,
    is_official: bool,
) -> bool:
    if is_official or shop_name in _STEAM_SHOPS or shop_name in _CONSOLE_OFFICIAL_SHOPS:
        return False
    if steam_price_pln is None or steam_price_pln < STEAM_HIGH_PRICE_PLN:
        return False
    if price is None or price <= 0:
        return False
    return (float(price) / float(steam_price_pln)) < KEYSHOP_CONFIRMED_STEAM_RATIO


def is_peer_price_outlier(
    price: float,
    other_prices: list[float] | None,
    *,
    steam_price_pln: float | None = None,
) -> bool:
    """True when price is absurdly below the peer cluster (wrong SKU / currency bug)."""
    if price is None or price <= 0:
        return False
    med = _outlier_reference_median(price, other_prices, steam_price_pln=steam_price_pln)
    if med is None or med < PEER_OUTLIER_MIN_MEDIAN_PLN:
        return False
    if price <= med * PEER_OUTLIER_RATIO and (med - price) >= PEER_OUTLIER_ABS_GAP_PLN:
        return True
    return False


def offer_edition_verified(
    offer: Offer,
    *,
    game_title: str | None = None,
) -> bool:
    """Reject marketplace rows whose URL/title points at another edition/SKU."""
    shop = offer.shop_name or ""
    if shop in _STEAM_SHOPS or shop in _CONSOLE_OFFICIAL_SHOPS:
        return True
    if not game_title:
        return True
    # Official digital stores (GOG/Epic/Fanatical) still need edition checks when
    # the affiliate URL embeds a product title (kp_title / path slug).
    candidate = product_title_from_url(offer.affiliate_url or "")
    if not candidate and offer.is_official:
        return True
    verdict = classify_keyshop_product(
        game_title,
        candidate,
        offer.affiliate_url or "",
        min_score=0.35,
    )
    return bool(verdict.get("valid"))


def offer_eligible_for_best_price(
    offer: Offer,
    *,
    steam_price_pln: float | None = None,
    peer_prices: list[float] | None = None,
    game_title: str | None = None,
    now: datetime | None = None,
    require_fresh: bool = True,
    allow_zero_price: bool = False,
) -> bool:
    """Return True if this offer may be shown as the catalog best price."""
    if not offer.in_stock:
        return False
    price = offer.price_pln
    if price is None:
        return False
    if price < 0:
        return False
    if price == 0 and not allow_zero_price:
        return False

    shop = offer.shop_name or ""

    if require_fresh and not offer_may_confirm_best_price(
        offer.updated_at, shop_name=shop, now=now
    ):
        return False

    if not offer_edition_verified(offer, game_title=game_title):
        return False

    # Steam / console storefronts are trusted official references.
    if shop in _STEAM_SHOPS or shop in _CONSOLE_OFFICIAL_SHOPS:
        return True

    if price > 0 and not _passes_steam_sanity(shop, price, steam_price_pln):
        return False

    if price > 0 and is_expensive_vs_steam_reference(
        price, steam_price_pln=steam_price_pln, shop_name=shop
    ):
        return False

    if offer.is_official:
        return True

    # Wrong GOG/Epic match (e.g. Sword of the Samurai @15 zł vs Onimusha @200 zł).
    if price > 0 and is_peer_price_outlier(
        price, peer_prices, steam_price_pln=steam_price_pln
    ):
        return False
    if is_keyshop_too_cheap_vs_steam(
        price, steam_price_pln=steam_price_pln, shop_name=shop, is_official=bool(offer.is_official)
    ):
        return False

    # Marketplace / reseller — require match confidence.
    conf = offer.match_confidence
    if conf is None or conf < BEST_PRICE_MIN_CONFIDENCE:
        return False

    # Very cheap marketplace listing vs expensive Steam → likely wrong match.
    if (
        price > 0
        and steam_price_pln is not None
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
    game_title: str | None = None,
) -> bool:
    """Offer that should not be shown / highlighted (wrong SKU, broken cheap link)."""
    price = offer.price_pln
    if price is None or price < 0:
        return True
    if price == 0:
        return False

    shop = offer.shop_name or ""
    if not offer_edition_verified(offer, game_title=game_title):
        return True
    if shop in _STEAM_SHOPS or shop in _CONSOLE_OFFICIAL_SHOPS:
        return False

    if offer.is_official:
        return False

    if not _passes_steam_sanity(shop, price, steam_price_pln):
        return True

    if is_expensive_vs_steam_reference(price, steam_price_pln=steam_price_pln, shop_name=shop):
        return True

    if is_peer_price_outlier(price, peer_prices, steam_price_pln=steam_price_pln):
        return True

    if is_keyshop_too_cheap_vs_steam(
        price, steam_price_pln=steam_price_pln, shop_name=shop, is_official=bool(offer.is_official)
    ):
        return True

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
