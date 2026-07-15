"""Offer coverage metrics for admin panel."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import BASE_DIR
from app.models.models import Offer
from app.parsers.game_offers import EXPECTED_SHOPS, MIN_SHOPS_TARGET

_WORKER_STATE = Path(BASE_DIR) / "tmp" / "local_worker_state.json"


def _load_worker_state() -> dict[str, Any]:
    if not _WORKER_STATE.is_file():
        return {}
    try:
        return json.loads(_WORKER_STATE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def collect_offer_coverage_stats(db: Session) -> dict[str, Any]:
    offers_by_shop = dict(
        db.query(Offer.shop_name, func.count(Offer.id))
        .filter(Offer.in_stock == True)
        .group_by(Offer.shop_name)
        .order_by(func.count(Offer.id).desc())
        .all()
    )

    sub = (
        db.query(Offer.game_id, func.count(Offer.id).label("shop_count"))
        .filter(Offer.in_stock == True)
        .group_by(Offer.game_id)
        .subquery()
    )
    distribution: dict[int, int] = {}
    for shop_count, games in (
        db.query(sub.c.shop_count, func.count())
        .group_by(sub.c.shop_count)
        .order_by(sub.c.shop_count)
        .all()
    ):
        distribution[int(shop_count)] = int(games)

    games_with_offers = sum(distribution.values())

    # Games (with any offer) missing a given shop.
    games_missing_shop: dict[str, int] = {}
    game_ids_with_offers = {row[0] for row in db.query(sub.c.game_id).all()}
    if game_ids_with_offers:
        for shop_name in EXPECTED_SHOPS:
            have_shop = {
                row[0]
                for row in db.query(Offer.game_id)
                .filter(Offer.in_stock == True, Offer.shop_name == shop_name)
                .distinct()
                .all()
            }
            games_missing_shop[shop_name] = len(game_ids_with_offers - have_shop)
    else:
        games_missing_shop = {name: 0 for name in EXPECTED_SHOPS}

    steam_only = distribution.get(1, 0)
    multi_shop = sum(count for shops, count in distribution.items() if shops >= 2)
    full_coverage = sum(
        count for shops, count in distribution.items() if shops >= len(EXPECTED_SHOPS)
    )
    sparse = sum(
        count
        for shops, count in distribution.items()
        if 0 < shops < MIN_SHOPS_TARGET
    )

    return {
        "expected_shops": list(EXPECTED_SHOPS),
        "min_shops_target": MIN_SHOPS_TARGET,
        "offers_by_shop": offers_by_shop,
        "games_with_offers": games_with_offers,
        "shop_count_distribution": distribution,
        "steam_only_games": steam_only,
        "multi_shop_games": multi_shop,
        "sparse_games_lt_target": sparse,
        "full_coverage_games": full_coverage,
        "games_missing_shop": games_missing_shop,
        "local_worker": _load_worker_state(),
    }
