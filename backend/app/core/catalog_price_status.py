"""Catalog card price_status values for Cozy Orange list cards."""
from __future__ import annotations

from app.models.models import Game, Offer


def catalog_price_status(game: Game, best: Offer | None) -> str:
    """Mutually exclusive catalog card state.

    Returns: confirmed | no_confirmed | no_offers | free
    """
    if bool(getattr(game, "is_free", False)):
        return "free"
    if best is not None and best.price_pln is not None:
        return "confirmed"
    has_priced = any(
        o.in_stock and o.price_pln is not None and o.price_pln > 0
        for o in (game.offers or [])
    )
    if has_priced:
        return "no_confirmed"
    return "no_offers"
