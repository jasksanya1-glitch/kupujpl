"""Remove absurd outlier prices from price_snapshots and rebuild game rollups."""
from __future__ import annotations

import logging
from collections import defaultdict
from statistics import median

from app.core.database import SessionLocal, init_db
from app.core.db_retry import commit_with_retry
from app.core.offer_quality import (
    PEER_OUTLIER_ABS_GAP_PLN,
    PEER_OUTLIER_MIN_MEDIAN_PLN,
    PEER_OUTLIER_MIN_OTHERS,
    PEER_OUTLIER_RATIO,
    STEAM_PRICE_RATIO_FLOOR,
    is_peer_price_outlier,
)
from app.core.price_history import update_game_price_rollups
from app.models.models import Game, Offer, PriceSnapshot
from app.parsers.shop_scan_config import get_display_shops

logger = logging.getLogger("clean_price_stats")


def _is_bad_price(price: float, peers: list[float], steam: float | None) -> bool:
    """Stricter than live CTA filters — historical mins must not be lone absurd lows."""
    if price <= 0:
        return True
    # Live floor is 0.12; history cleanup uses 0.35 so stale wrong SKUs / stuck sales drop.
    if steam is not None and steam >= 25 and price / steam < 0.35:
        return True
    others = list(peers)
    try:
        others.remove(price)
    except ValueError:
        pass
    if is_peer_price_outlier(price, others):
        return True
    if len(peers) >= PEER_OUTLIER_MIN_OTHERS + 1:
        med = float(median(peers))
        # 0.50 vs live 0.40 — catches Cyberpunk-style 59 zł vs ~120–200 cluster.
        hist_ratio = max(PEER_OUTLIER_RATIO, 0.50)
        if (
            med >= PEER_OUTLIER_MIN_MEDIAN_PLN
            and price <= med * hist_ratio
            and (med - price) >= PEER_OUTLIER_ABS_GAP_PLN
        ):
            return True
    return False


def clean_all(*, batch_size: int = 500) -> dict[str, int]:
    init_db()
    db = SessionLocal()
    display = list(get_display_shops())
    stats = {
        "games_total": 0,
        "snapshots_deactivated": 0,
        "rollups_rebuilt": 0,
        "suspect_lowest_before": 0,
        "suspect_lowest_after": 0,
    }
    try:
        game_ids = [gid for (gid,) in db.query(Game.id).order_by(Game.id).all()]
        stats["games_total"] = len(game_ids)

        # Preload current stock peers + steam
        offer_rows = (
            db.query(Offer.game_id, Offer.shop_name, Offer.price_pln)
            .filter(
                Offer.in_stock.is_(True),
                Offer.price_pln > 0,
                Offer.shop_name.in_(display),
            )
            .all()
        )
        peers_now: dict[int, list[float]] = defaultdict(list)
        steam_map: dict[int, float] = {}
        for gid, shop, price in offer_rows:
            price_f = float(price)
            peers_now[gid].append(price_f)
            if shop == "Steam":
                prev = steam_map.get(gid)
                if prev is None or price_f < prev:
                    steam_map[gid] = price_f

        snap_rows = (
            db.query(PriceSnapshot.game_id, PriceSnapshot.price_pln)
            .filter(
                PriceSnapshot.in_stock.is_(True),
                PriceSnapshot.price_pln > 0,
                PriceSnapshot.shop_name.in_(display),
            )
            .all()
        )
        peers_snap: dict[int, list[float]] = defaultdict(list)
        for gid, price in snap_rows:
            peers_snap[gid].append(float(price))

        # Count suspect lowest_ever before
        for game in db.query(Game).filter(Game.lowest_ever_pln.isnot(None)).yield_per(500):
            peers = peers_now.get(game.id) or peers_snap.get(game.id) or []
            if len(peers) >= PEER_OUTLIER_MIN_OTHERS and _is_bad_price(
                float(game.lowest_ever_pln), peers, steam_map.get(game.id)
            ):
                stats["suspect_lowest_before"] += 1

        # Deactivate bad snapshots in batches
        for i in range(0, len(game_ids), batch_size):
            chunk = game_ids[i : i + batch_size]
            snaps = (
                db.query(PriceSnapshot)
                .filter(
                    PriceSnapshot.game_id.in_(chunk),
                    PriceSnapshot.in_stock.is_(True),
                    PriceSnapshot.shop_name.in_(display),
                    PriceSnapshot.price_pln > 0,
                )
                .all()
            )
            for snap in snaps:
                price = float(snap.price_pln)
                peers = peers_now.get(snap.game_id) or peers_snap.get(snap.game_id) or []
                if not _is_bad_price(price, peers, steam_map.get(snap.game_id)):
                    continue
                snap.in_stock = False
                stats["snapshots_deactivated"] += 1
            commit_with_retry(db)
            print(
                f"deactivate batch {i // batch_size + 1}/{(len(game_ids) + batch_size - 1) // batch_size}: "
                f"total_off={stats['snapshots_deactivated']}"
            )

        # Rebuild rollups for every game that has stats or snapshots
        rebuild_ids = [
            gid
            for (gid,) in db.query(Game.id)
            .filter(
                (Game.lowest_ever_pln.isnot(None))
                | (Game.avg_best_price_30d.isnot(None))
            )
            .all()
        ]
        snap_game_ids = [
            gid
            for (gid,) in db.query(PriceSnapshot.game_id).distinct().all()
        ]
        rebuild_ids = sorted(set(rebuild_ids) | set(snap_game_ids))

        for i in range(0, len(rebuild_ids), batch_size):
            chunk = rebuild_ids[i : i + batch_size]
            for gid in chunk:
                update_game_price_rollups(db, gid)
                stats["rollups_rebuilt"] += 1
            commit_with_retry(db)
            print(
                f"rollup batch {i // batch_size + 1}/{(len(rebuild_ids) + batch_size - 1) // batch_size}: "
                f"rebuilt={stats['rollups_rebuilt']}"
            )

        # Refresh peers after rollup and recount suspect lowest
        peers_now = defaultdict(list)
        for gid, shop, price in (
            db.query(Offer.game_id, Offer.shop_name, Offer.price_pln)
            .filter(
                Offer.in_stock.is_(True),
                Offer.price_pln > 0,
                Offer.shop_name.in_(display),
            )
            .all()
        ):
            peers_now[gid].append(float(price))

        for game in db.query(Game).filter(Game.lowest_ever_pln.isnot(None)).yield_per(500):
            peers = peers_now.get(game.id) or []
            if len(peers) >= PEER_OUTLIER_MIN_OTHERS and _is_bad_price(
                float(game.lowest_ever_pln), peers, steam_map.get(game.id)
            ):
                # Robust cluster: drop lone cheap outliers, then take min of remaining.
                med = float(median(peers))
                robust = [p for p in peers if p >= med * PEER_OUTLIER_RATIO]
                if not robust:
                    robust = peers
                game.lowest_ever_pln = round(min(robust), 2) if robust else None
                game.lowest_ever_at = None
                if robust:
                    game.avg_best_price_30d = round(float(median(robust)), 2)
                stats["suspect_lowest_after"] += 1
        commit_with_retry(db)
        return stats
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stats = clean_all()
    print("DONE", stats)


if __name__ == "__main__":
    main()
