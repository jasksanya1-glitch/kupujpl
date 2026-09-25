"""Shared best-offer selection for SSR indexable and sitemap membership."""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy.orm import Session

from app.core.offer_quality import offer_eligible_for_best_price
from app.models.models import Game, Offer
from app.parsers.shop_scan_config import get_display_shops

SITEMAP_SHOPPING_REGION = "pl"


def normalize_shopping_region(region: str | None) -> str:
    r = (region or "pl").strip().lower()
    return "us" if r == "us" else "pl"


def steam_shop_for_region(region: str) -> str:
    return "Steam US" if region == "us" else "Steam"


def display_shops_for_region(region: str) -> set[str]:
    active = set(get_display_shops())
    if region == "us":
        active.discard("Steam")
        active.add("Steam US")
    else:
        active.discard("Steam US")
    return active


def offer_activation_region(offer: Offer) -> str:
    raw = (getattr(offer, "activation_region", None) or "unknown").strip().lower()
    if raw in {"eu", "na", "global", "unknown"}:
        return raw
    return "unknown"


def offer_visible_for_shopping_region(offer: Offer, region: str) -> bool:
    """Filter keyshop rows by activation region for PL vs US shoppers."""
    region = normalize_shopping_region(region)
    act = offer_activation_region(offer)
    shop = (offer.shop_name or "").strip()
    if shop == "Steam US":
        return region == "us"
    if shop == "Steam":
        return region != "us"
    if act == "unknown":
        return True
    if region == "us":
        return act in {"na", "global"}
    return act in {"eu", "global"}


def display_shops_for_game(game: Game, *, region: str = "pl") -> set[str]:
    """Shops shown for a game; console titles include PlayStation/Xbox storefronts."""
    active = set(display_shops_for_region(region))
    platform = (getattr(game, "platform", None) or "pc").strip().lower()
    if platform == "ps":
        active |= {
            "PlayStation Store",
            "Instant Gaming",
            "Kinguin",
            "G2A",
            "Gamivo",
            "CDKeys",
            "Eneba",
        }
        # PC-only storefronts are noise on PS stubs.
        active -= {"Steam", "Steam US", "GOG", "Epic Games", "Fanatical"}
    elif platform == "xbox":
        active |= {"Xbox Store", "Instant Gaming", "Kinguin", "G2A", "Gamivo", "CDKeys", "Eneba"}
        active -= {"Steam", "Steam US", "GOG", "Epic Games", "Fanatical"}
    else:
        active -= {"PlayStation Store", "Xbox Store"}
    return active


def steam_offers_map(
    db: Session,
    game_ids: list[int],
    shop_name: str = "Steam",
    *,
    fallback_shop: str | None = None,
) -> dict[int, Offer]:
    if not game_ids:
        return {}
    names = [shop_name]
    if fallback_shop and fallback_shop != shop_name:
        names.append(fallback_shop)
    offers = (
        db.query(Offer)
        .filter(
            Offer.game_id.in_(game_ids),
            Offer.shop_name.in_(names),
            Offer.in_stock == True,  # noqa: E712
            Offer.price_pln.isnot(None),
            Offer.price_pln > 0,
        )
        .all()
    )
    primary: dict[int, Offer] = {}
    fallback: dict[int, Offer] = {}
    for offer in offers:
        target = primary if offer.shop_name == shop_name else fallback
        prev = target.get(offer.game_id)
        if prev is None or offer.price_pln < prev.price_pln:
            target[offer.game_id] = offer
    if not fallback_shop:
        return primary
    out = dict(primary)
    for gid, offer in fallback.items():
        if gid not in out:
            out[gid] = offer
    return out


def best_offers_map(
    db: Session,
    game_ids: Sequence[int],
    *,
    region: str = "pl",
    games: dict[int, Game] | None = None,
) -> dict[int, Offer]:
    ids = list(game_ids)
    if not ids:
        return {}
    region = normalize_shopping_region(region)
    steam_shop = steam_shop_for_region(region)
    steam_map = steam_offers_map(
        db,
        ids,
        shop_name=steam_shop,
        fallback_shop="Steam" if region == "us" else None,
    )
    if games is None:
        games = {
            g.id: g
            for g in db.query(Game).filter(Game.id.in_(ids)).all()
        }
    offers = (
        db.query(Offer)
        .filter(
            Offer.game_id.in_(ids),
            Offer.in_stock == True,  # noqa: E712
            Offer.price_pln.isnot(None),
            Offer.price_pln > 0,
        )
        .all()
    )
    by_game: dict[int, list[Offer]] = {}
    for offer in offers:
        if not offer_visible_for_shopping_region(offer, region):
            continue
        game = games.get(offer.game_id)
        if not game:
            continue
        allowed = display_shops_for_game(game, region=region)
        if offer.shop_name not in allowed:
            continue
        by_game.setdefault(offer.game_id, []).append(offer)

    best: dict[int, Offer] = {}
    for game_id, game_offers in by_game.items():
        steam = steam_map.get(game_id)
        steam_price = float(steam.price_pln) if steam and steam.price_pln else None
        peer_prices = [float(o.price_pln) for o in game_offers if o.price_pln]
        for offer in game_offers:
            if not offer_eligible_for_best_price(
                offer,
                steam_price_pln=steam_price,
                peer_prices=peer_prices,
            ):
                continue
            prev = best.get(game_id)
            if prev is None or offer.price_pln < prev.price_pln:
                best[game_id] = offer
    return best


def indexable_game_ids(
    db: Session,
    game_ids: Sequence[int],
    *,
    region: str = SITEMAP_SHOPPING_REGION,
    games: dict[int, Game] | None = None,
) -> set[int]:
    return set(best_offers_map(db, game_ids, region=region, games=games))


def iter_games_with_slugs(
    db: Session,
    *,
    batch_size: int,
    after_id: int = 0,
) -> Iterable[list[Game]]:
    last_id = after_id
    while True:
        rows = (
            db.query(Game)
            .filter(
                Game.id > last_id,
                Game.slug.isnot(None),
                Game.slug != "",
            )
            .order_by(Game.id)
            .limit(batch_size)
            .all()
        )
        if not rows:
            return
        yield rows
        last_id = rows[-1].id
