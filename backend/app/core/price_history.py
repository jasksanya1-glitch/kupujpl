"""Price snapshots and rollups for history + alerts."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.models import Game, Offer, PriceSnapshot
from app.parsers.shop_scan_config import get_display_shops

logger = logging.getLogger("price_history")

RETENTION_DAYS = 90
PRICE_EPSILON = 0.009
# Marketplace/keyshop offers below this confidence are excluded from history rollups.
HISTORY_MIN_CONFIDENCE = 0.55


def _best_price_for_game(db: Session, game_id: int) -> float | None:
    display = list(get_display_shops())
    row = (
        db.query(func.min(Offer.price_pln))
        .filter(
            Offer.game_id == game_id,
            Offer.in_stock.is_(True),
            Offer.price_pln.isnot(None),
            Offer.price_pln > 0,
            Offer.shop_name.in_(display),
            or_(
                Offer.is_official.is_(True),
                Offer.match_confidence.is_(None),
                Offer.match_confidence >= HISTORY_MIN_CONFIDENCE,
            ),
        )
        .scalar()
    )
    return float(row) if row is not None else None


def record_offer_price_change(
    db: Session,
    *,
    game_id: int,
    shop_name: str,
    price_pln: float,
    in_stock: bool = True,
    previous_price: float | None = None,
) -> None:
    """Write snapshot when price changes (or on first offer)."""
    if not in_stock or price_pln is None or price_pln <= 0:
        return
    if previous_price is not None and abs(previous_price - price_pln) < PRICE_EPSILON:
        return
    db.add(
        PriceSnapshot(
            game_id=game_id,
            shop_name=shop_name,
            price_pln=price_pln,
            in_stock=True,
            recorded_at=datetime.utcnow(),
        )
    )
    db.flush()
    update_game_price_rollups(db, game_id)


def update_game_price_rollups(db: Session, game_id: int) -> None:
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        return
    now = datetime.utcnow()
    since_30 = now - timedelta(days=30)
    display = list(get_display_shops())

    best_daily = (
        db.query(
            func.date(PriceSnapshot.recorded_at).label("day"),
            func.min(PriceSnapshot.price_pln).label("min_price"),
        )
        .filter(
            PriceSnapshot.game_id == game_id,
            PriceSnapshot.in_stock.is_(True),
            PriceSnapshot.recorded_at >= since_30,
            PriceSnapshot.shop_name.in_(display),
        )
        .group_by(func.date(PriceSnapshot.recorded_at))
        .all()
    )
    if best_daily:
        game.avg_best_price_30d = round(
            sum(float(r.min_price) for r in best_daily) / len(best_daily),
            2,
        )
    else:
        game.avg_best_price_30d = None

    lowest_row = (
        db.query(func.min(PriceSnapshot.price_pln))
        .filter(
            PriceSnapshot.game_id == game_id,
            PriceSnapshot.in_stock.is_(True),
            PriceSnapshot.shop_name.in_(display),
        )
        .scalar()
    )
    current_best = _best_price_for_game(db, game_id)
    candidates = [x for x in [lowest_row, current_best] if x is not None]
    if candidates:
        game.lowest_ever_pln = round(min(float(c) for c in candidates), 2)
        lowest_at = (
            db.query(func.min(PriceSnapshot.recorded_at))
            .filter(
                PriceSnapshot.game_id == game_id,
                PriceSnapshot.in_stock.is_(True),
                PriceSnapshot.shop_name.in_(display),
                PriceSnapshot.price_pln <= game.lowest_ever_pln + PRICE_EPSILON,
            )
            .scalar()
        )
        game.lowest_ever_at = lowest_at or now
    else:
        game.lowest_ever_pln = None
        game.lowest_ever_at = None


def prune_old_snapshots(db: Session, *, days: int = RETENTION_DAYS) -> int:
    cutoff = datetime.utcnow() - timedelta(days=days)
    deleted = (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.recorded_at < cutoff)
        .delete(synchronize_session=False)
    )
    return int(deleted or 0)


def get_price_history(
    db: Session,
    game_id: int,
    *,
    days: int = 90,
) -> list[dict]:
    """Daily best price across shops."""
    since = datetime.utcnow() - timedelta(days=days)
    display = list(get_display_shops())
    rows = (
        db.query(
            func.date(PriceSnapshot.recorded_at).label("day"),
            func.min(PriceSnapshot.price_pln).label("min_price"),
        )
        .filter(
            PriceSnapshot.game_id == game_id,
            PriceSnapshot.in_stock.is_(True),
            PriceSnapshot.recorded_at >= since,
            PriceSnapshot.shop_name.in_(display),
        )
        .group_by(func.date(PriceSnapshot.recorded_at))
        .order_by(func.date(PriceSnapshot.recorded_at))
        .all()
    )
    return [{"date": str(r.day), "best_price_pln": round(float(r.min_price), 2)} for r in rows]


def lowest_ever_label_pl(game: Game, current_best: float | None) -> str | None:
    if game.lowest_ever_pln is None or current_best is None:
        return None
    if abs(game.lowest_ever_pln - current_best) > 0.05:
        return None
    if not game.lowest_ever_at:
        return "najniższa cena w historii"
    days = (datetime.utcnow() - game.lowest_ever_at).days
    if days >= 60:
        months = max(1, days // 30)
        return f"najniżej od {months} mies."
    if days >= 14:
        weeks = max(1, days // 7)
        return f"najniżej od {weeks} tyg."
    if days >= 1:
        return f"najniżej od {days} dni"
    return "najniższa cena dziś"
