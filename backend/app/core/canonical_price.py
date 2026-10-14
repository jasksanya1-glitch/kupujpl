"""Canonical current-price service for all public surfaces.

DATA SOURCE → SERVICE → CACHE → PAGE/API
---------------------------------------
offers (DB)
  → offer_eligible_for_best_price + region filters  (game_offer_selection)
  → best_offers_map / get_current_min_price          (this module)
  → short TTL in-process caches (_HOME_RESP_CACHE, games list)
  → homepage / promocje / categories / search / Polecane / game page / API

Business rules live in offer_quality.offer_eligible_for_best_price and
game_offer_selection (region, display shops). Do not invent a second min-price
path with raw SQL MIN(price_pln) for displayed prices.
"""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.game_offer_selection import (
    best_offers_map,
    display_shops_for_game,
    normalize_shopping_region,
    offer_visible_for_shopping_region,
)
from app.core.offer_quality import offer_eligible_for_best_price
from app.models.models import Game, Offer


def get_valid_current_offers(
    db: Session,
    game: Game,
    *,
    region: str = "pl",
) -> list[Offer]:
    """Return in-stock offers eligible to drive the catalog best price."""
    region = normalize_shopping_region(region)
    allowed = display_shops_for_game(game, region=region)
    rows = (
        db.query(Offer)
        .filter(
            Offer.game_id == game.id,
            Offer.in_stock.is_(True),
            Offer.price_pln.isnot(None),
            Offer.price_pln > 0,
            Offer.shop_name.in_(list(allowed)),
        )
        .all()
    )
    visible = [o for o in rows if offer_visible_for_shopping_region(o, region)]
    steam = next((o for o in visible if o.shop_name == ("Steam US" if region == "us" else "Steam")), None)
    steam_price = float(steam.price_pln) if steam and steam.price_pln else None
    peers = [float(o.price_pln) for o in visible if o.price_pln]
    return [
        o
        for o in visible
        if offer_eligible_for_best_price(o, steam_price_pln=steam_price, peer_prices=peers)
    ]


def get_current_min_price(
    db: Session,
    game: Game,
    *,
    region: str = "pl",
) -> tuple[float | None, Offer | None]:
    """Canonical minimum: (price_pln, winning offer) or (None, None)."""
    best = best_offers_map(db, [game.id], region=region, games={game.id: game}).get(game.id)
    if not best or best.price_pln is None:
        return None, None
    return float(best.price_pln), best


def get_current_min_prices_map(
    db: Session,
    game_ids: Sequence[int],
    *,
    region: str = "pl",
    games: dict[int, Game] | None = None,
) -> dict[int, Offer]:
    """Batch canonical best offers — prefer this over per-game loops."""
    return best_offers_map(db, list(game_ids), region=region, games=games)
