"""Price snapshots and rollups for history + alerts."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.offer_quality import (
    STEAM_PRICE_RATIO_FLOOR,
    is_peer_price_outlier,
)
from app.models.models import Game, Offer, PriceSnapshot
from app.parsers.shop_scan_config import get_display_shops

logger = logging.getLogger("price_history")

RETENTION_DAYS = 90
PRICE_EPSILON = 0.009
# Marketplace/keyshop offers below this confidence are excluded from history rollups.
HISTORY_MIN_CONFIDENCE = 0.55


def _steam_price_for_game(db: Session, game_id: int) -> float | None:
    row = (
        db.query(func.min(Offer.price_pln))
        .filter(
            Offer.game_id == game_id,
            Offer.shop_name == "Steam",
            Offer.in_stock.is_(True),
            Offer.price_pln > 0,
        )
        .scalar()
    )
    return float(row) if row is not None else None


def _eligible_offer_prices(db: Session, game_id: int) -> list[float]:
    """Current in-stock prices eligible for history / best (official or confident)."""
    display = list(get_display_shops())
    rows = (
        db.query(Offer.price_pln, Offer.is_official, Offer.match_confidence, Offer.shop_name)
        .filter(
            Offer.game_id == game_id,
            Offer.in_stock.is_(True),
            Offer.price_pln.isnot(None),
            Offer.price_pln > 0,
            Offer.shop_name.in_(display),
        )
        .all()
    )
    steam = _steam_price_for_game(db, game_id)
    raw = [float(r.price_pln) for r in rows]
    out: list[float] = []
    for price, is_official, conf, shop_name in rows:
        price_f = float(price)
        if not is_official and (conf is None or float(conf) < HISTORY_MIN_CONFIDENCE):
            continue
        if steam is not None and steam >= 5 and shop_name != "Steam":
            if price_f / steam < STEAM_PRICE_RATIO_FLOOR:
                continue
        others = list(raw)
        try:
            others.remove(price_f)
        except ValueError:
            pass
        if not is_official and is_peer_price_outlier(price_f, others):
            continue
        out.append(price_f)
    return out


def _best_price_for_game(db: Session, game_id: int) -> float | None:
    prices = _eligible_offer_prices(db, game_id)
    if not prices:
        return None
    return min(prices)


def _snapshot_price_ok(
    price: float,
    *,
    peer_prices: list[float],
    steam_price: float | None,
) -> bool:
    if price <= 0:
        return False
    if steam_price is not None and steam_price >= 5 and price / steam_price < STEAM_PRICE_RATIO_FLOOR:
        return False
    others = list(peer_prices)
    try:
        others.remove(price)
    except ValueError:
        pass
    if is_peer_price_outlier(price, others):
        return False
    return True


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
    peers = _eligible_offer_prices(db, game_id)
    steam = _steam_price_for_game(db, game_id)
    if not _snapshot_price_ok(
        float(price_pln),
        peer_prices=peers or [float(price_pln)],
        steam_price=steam,
    ):
        logger.debug(
            "Skip outlier snapshot game=%s shop=%s price=%s",
            game_id,
            shop_name,
            price_pln,
        )
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
    steam = _steam_price_for_game(db, game_id)
    peer_now = _eligible_offer_prices(db, game_id)

    snaps = (
        db.query(PriceSnapshot)
        .filter(
            PriceSnapshot.game_id == game_id,
            PriceSnapshot.in_stock.is_(True),
            PriceSnapshot.shop_name.in_(display),
            PriceSnapshot.price_pln > 0,
        )
        .all()
    )
    peer_base = peer_now or [float(s.price_pln) for s in snaps]
    if peer_base and len(peer_base) >= 3:
        med = float(median(peer_base))
        filtered = [p for p in peer_base if p >= med * 0.35]
        if filtered:
            peer_base = filtered

    valid_snaps = [
        s
        for s in snaps
        if _snapshot_price_ok(float(s.price_pln), peer_prices=peer_base, steam_price=steam)
    ]

    best_by_day: dict[str, float] = {}
    for snap in valid_snaps:
        if snap.recorded_at is None or snap.recorded_at < since_30:
            continue
        day = snap.recorded_at.date().isoformat()
        price = float(snap.price_pln)
        prev = best_by_day.get(day)
        if prev is None or price < prev:
            best_by_day[day] = price

    if best_by_day:
        game.avg_best_price_30d = round(sum(best_by_day.values()) / len(best_by_day), 2)
    else:
        game.avg_best_price_30d = None

    snap_lowest = min((float(s.price_pln) for s in valid_snaps), default=None)
    current_best = min(peer_now) if peer_now else None
    candidates = [x for x in [snap_lowest, current_best] if x is not None]
    if candidates:
        game.lowest_ever_pln = round(min(candidates), 2)
        lowest_at = None
        for snap in valid_snaps:
            if float(snap.price_pln) <= game.lowest_ever_pln + PRICE_EPSILON:
                if lowest_at is None or (snap.recorded_at and snap.recorded_at < lowest_at):
                    lowest_at = snap.recorded_at
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


def ensure_today_best_snapshot(
    db: Session,
    *,
    game_id: int,
    price_pln: float,
    shop_name: str | None = None,
) -> None:
    """Make sure live best price appears in history (chart "teraz" = live min)."""
    if price_pln is None or price_pln <= 0:
        return
    price = round(float(price_pln), 2)
    peers = _eligible_offer_prices(db, game_id)
    steam = _steam_price_for_game(db, game_id)
    if not _snapshot_price_ok(price, peer_prices=peers or [price], steam_price=steam):
        return
    shop = (shop_name or "Best").strip() or "Best"
    today = datetime.utcnow().date()
    day_start = datetime.combine(today, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    existing = (
        db.query(PriceSnapshot)
        .filter(
            PriceSnapshot.game_id == game_id,
            PriceSnapshot.in_stock.is_(True),
            PriceSnapshot.recorded_at >= day_start,
            PriceSnapshot.recorded_at < day_end,
            PriceSnapshot.price_pln <= price + PRICE_EPSILON,
        )
        .first()
    )
    if existing:
        return
    db.add(
        PriceSnapshot(
            game_id=game_id,
            shop_name=shop,
            price_pln=price,
            in_stock=True,
            recorded_at=datetime.utcnow(),
        )
    )
    db.flush()
    update_game_price_rollups(db, game_id)


def get_price_history(
    db: Session,
    game_id: int,
    *,
    days: int = 90,
    current_best_pln: float | None = None,
) -> list[dict]:
    """Daily best price across shops; fold in live best so chart matches offers."""
    since = datetime.utcnow() - timedelta(days=days)
    display = list(get_display_shops())
    steam = _steam_price_for_game(db, game_id)
    peer_now = _eligible_offer_prices(db, game_id)
    snaps = (
        db.query(PriceSnapshot)
        .filter(
            PriceSnapshot.game_id == game_id,
            PriceSnapshot.in_stock.is_(True),
            PriceSnapshot.recorded_at >= since,
            PriceSnapshot.shop_name.in_(display),
            PriceSnapshot.price_pln > 0,
        )
        .all()
    )
    peer_base = peer_now or [float(s.price_pln) for s in snaps]
    best_by_day: dict[str, float] = {}
    for snap in snaps:
        price = float(snap.price_pln)
        if not _snapshot_price_ok(price, peer_prices=peer_base, steam_price=steam):
            continue
        day = str(snap.recorded_at.date()) if snap.recorded_at else None
        if not day:
            continue
        prev = best_by_day.get(day)
        if prev is None or price < prev:
            best_by_day[day] = price
    points = [
        {"date": day, "best_price_pln": round(price, 2)}
        for day, price in sorted(best_by_day.items())
    ]
    if current_best_pln is not None and current_best_pln > 0:
        today = str(datetime.utcnow().date())
        cur = round(float(current_best_pln), 2)
        if _snapshot_price_ok(cur, peer_prices=peer_base or [cur], steam_price=steam):
            if points and points[-1]["date"] == today:
                points[-1]["best_price_pln"] = min(points[-1]["best_price_pln"], cur)
            else:
                points.append({"date": today, "best_price_pln": cur})
    return points


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
