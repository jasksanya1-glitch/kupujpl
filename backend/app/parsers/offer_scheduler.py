"""Background scheduler: keep shop offers fresh in SQLite."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.database import BASE_DIR, SessionLocal
from app.models.models import Game, Offer
from app.parsers.game_offers import MIN_SHOPS_TARGET, REFRESH_COOLDOWN, refresh_offers_for_game
from app.parsers.featured_offer_prefetch import collect_featured_appids
from app.parsers.tier_a_top5000 import load_tier_a_appid_set
from app.parsers.shop_scan_config import filter_active_shops, VPS_SCAN_SHOPS
from app.parsers.epic_parser import import_epic_offers
from app.parsers.gog_parser import import_gog_offers

logger = logging.getLogger("offer_scheduler")

_STATE_PATH = BASE_DIR / "tmp" / "offer_scheduler_state.json"
_LOCK = threading.Lock()
_STARTED = False

INTERVAL_SEC = int(os.environ.get("OFFER_REFRESH_INTERVAL_SEC", "3600"))  # 1 h
BATCH_SIZE = int(os.environ.get("OFFER_REFRESH_BATCH_SIZE", "80"))
GAME_DELAY_SEC = float(os.environ.get("OFFER_REFRESH_GAME_DELAY_SEC", "0.8"))
PARALLEL_WORKERS = max(1, int(os.environ.get("OFFER_REFRESH_PARALLEL", "3")))
SHOP_BATCH_LIMIT = int(os.environ.get("OFFER_SHOP_BATCH_LIMIT", "120"))
SHOP_BATCH_EVERY_CYCLES = int(os.environ.get("OFFER_SHOP_BATCH_EVERY_CYCLES", "2"))
MIN_CYCLE_PAUSE_SEC = int(os.environ.get("OFFER_MIN_CYCLE_PAUSE_SEC", "30"))
FAST_REFRESH = os.environ.get("OFFER_FAST_REFRESH", "0").lower() not in ("0", "false", "no")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _load_state() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_scheduler_status() -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
    return {
        "running": _STARTED,
        "interval_sec": INTERVAL_SEC,
        "batch_size": BATCH_SIZE,
        "parallel_workers": PARALLEL_WORKERS,
        "game_delay_sec": GAME_DELAY_SEC,
        "fast_refresh": FAST_REFRESH,
        "games_per_day_estimate": int(BATCH_SIZE * max(1, 86400 // max(INTERVAL_SEC, 1))),
        "cooldown_hours": REFRESH_COOLDOWN.total_seconds() / 3600,
        **state,
    }


def select_games_for_refresh(db: Session, *, limit: int) -> list[Game]:
    """Pick enriched games with missing or stale offers (featured first, exclude tier A)."""
    cutoff = _utcnow() - REFRESH_COOLDOWN
    featured_appids = set(collect_featured_appids())
    tier_a_appids = load_tier_a_appid_set()

    agg = (
        db.query(
            Offer.game_id.label("game_id"),
            func.max(Offer.updated_at).label("last_update"),
            func.count(Offer.id).label("offer_count"),
        )
        .group_by(Offer.game_id)
        .subquery()
    )

    rows = (
        db.query(Game)
        .options(joinedload(Game.offers))
        .outerjoin(agg, Game.id == agg.c.game_id)
        .filter(Game.steam_enriched == True, Game.steam_appid.isnot(None))
        .order_by(
            agg.c.offer_count.asc().nulls_first(),
            Game.steam_review_count.desc().nulls_last(),
            Game.steam_recommendations.desc().nulls_last(),
            Game.rating.desc().nulls_last(),
        )
        .limit(limit * 4)
        .all()
    )

    def _needs(game: Game) -> bool:
        present = len({o.shop_name for o in game.offers if o.in_stock}) if game.offers else 0
        if present < MIN_SHOPS_TARGET:
            return True
        if not game.offers:
            return True
        latest = max((o.updated_at or datetime.min for o in game.offers), default=datetime.min)
        return latest < cutoff

    featured: list[Game] = []
    regular: list[Game] = []
    for game in rows:
        if not _needs(game):
            continue
        if game.steam_appid and int(game.steam_appid) in tier_a_appids:
            continue
        if game.steam_appid in featured_appids:
            featured.append(game)
        else:
            regular.append(game)

    selected: list[Game] = []
    for bucket in (featured, regular):
        for game in bucket:
            if len(selected) >= limit:
                break
            selected.append(game)
        if len(selected) >= limit:
            break
    return selected


def _count_offers_by_shop(db: Session) -> dict[str, int]:
    rows = db.query(Offer.shop_name, func.count(Offer.id)).group_by(Offer.shop_name).all()
    return {name: count for name, count in rows}


def _refresh_one(game_id: int, *, force: bool) -> tuple[int, bool]:
    try:
        refresh_offers_for_game(game_id, force=force, fast=False, fill_missing=True)
        return game_id, True
    except Exception as exc:
        logger.warning("Offer refresh failed for game %s: %s", game_id, exc)
        return game_id, False


def run_offer_refresh_cycle(*, force: bool = False) -> dict[str, Any]:
    """Refresh a batch of games (all configured shops)."""
    started = _utcnow()
    stats: dict[str, Any] = {
        "started_at": started.isoformat(),
        "games_processed": 0,
        "games_refreshed": 0,
        "errors": 0,
        "parallel_workers": PARALLEL_WORKERS,
    }

    db = SessionLocal()
    try:
        games = select_games_for_refresh(db, limit=BATCH_SIZE)
        stats["games_selected"] = len(games)
        game_ids = [g.id for g in games]
    finally:
        db.close()

    if not game_ids:
        stats["finished_at"] = _utcnow().isoformat()
        stats["duration_sec"] = 0
        return stats

    if PARALLEL_WORKERS <= 1:
        for game_id in game_ids:
            stats["games_processed"] += 1
            _gid, ok = _refresh_one(game_id, force=force)
            if ok:
                stats["games_refreshed"] += 1
            else:
                stats["errors"] += 1
            time.sleep(GAME_DELAY_SEC)
    else:
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
            futures = [pool.submit(_refresh_one, gid, force=force) for gid in game_ids]
            for idx, future in enumerate(as_completed(futures)):
                stats["games_processed"] += 1
                _gid, ok = future.result()
                if ok:
                    stats["games_refreshed"] += 1
                else:
                    stats["errors"] += 1
                if (idx + 1) % PARALLEL_WORKERS == 0:
                    time.sleep(GAME_DELAY_SEC)

    db = SessionLocal()
    try:
        stats["offers_by_shop"] = _count_offers_by_shop(db)
    finally:
        db.close()

    stats["finished_at"] = _utcnow().isoformat()
    stats["duration_sec"] = round(
        (_utcnow() - started).total_seconds(),
        1,
    )
    return stats


def run_shop_import_batch() -> dict[str, Any]:
    """Rotate through VPS official shop importers only (no keyshops / disabled)."""
    started = _utcnow()
    state = _load_state()
    rotation = int(state.get("shop_rotation", 0))
    vps_names = set(filter_active_shops(VPS_SCAN_SHOPS)) - {"Steam"}
    all_shops = [
        ("GOG", import_gog_offers),
        ("Epic Games", import_epic_offers),
    ]
    shops = [(n, fn) for n, fn in all_shops if n in vps_names]
    if not shops:
        return {"shop_batch_at": started.isoformat(), "shop_batch_shop": None, "skipped": True}
    shop_name, import_fn = shops[rotation % len(shops)]

    db = SessionLocal()
    try:
        result = import_fn(db, limit=SHOP_BATCH_LIMIT)
    finally:
        db.close()

    rotation += 1
    finished = _utcnow()
    batch_stats = {
        "shop_batch_at": finished.isoformat(),
        "shop_batch_shop": shop_name,
        "shop_batch_result": result,
        "shop_rotation": rotation,
    }
    with _LOCK:
        merged = _load_state()
        merged.update(batch_stats)
        _save_state(merged)
    logger.info("Shop import batch: %s %s", shop_name, result)
    return batch_stats


def _scheduler_loop() -> None:
    logger.info(
        "Offer scheduler started (every %ss, batch=%s, parallel=%s, fast=%s, cooldown=%sh)",
        INTERVAL_SEC,
        BATCH_SIZE,
        PARALLEL_WORKERS,
        FAST_REFRESH,
        REFRESH_COOLDOWN.total_seconds() / 3600,
    )
    cycle = 0
    while True:
        cycle += 1
        try:
            stats = run_offer_refresh_cycle()
            with _LOCK:
                state = _load_state()
                state.update(
                    {
                        "last_cycle_at": stats.get("finished_at"),
                        "last_cycle": stats,
                        "cycles_total": int(state.get("cycles_total", 0)) + 1,
                    }
                )
                _save_state(state)
            logger.info(
                "Offer cycle #%s done: refreshed %s/%s games",
                cycle,
                stats.get("games_refreshed"),
                stats.get("games_selected"),
            )

            if cycle % SHOP_BATCH_EVERY_CYCLES == 0:
                run_shop_import_batch()
        except Exception as exc:
            logger.error("Offer scheduler cycle failed: %s", exc)
            with _LOCK:
                state = _load_state()
                state["last_error"] = str(exc)
                state["last_error_at"] = _utcnow().isoformat()
                _save_state(state)
            stats = {"duration_sec": 0}

        pause = max(MIN_CYCLE_PAUSE_SEC, INTERVAL_SEC - float(stats.get("duration_sec") or 0))
        time.sleep(pause)


def start_offer_scheduler() -> None:
    global _STARTED
    if os.environ.get("OFFER_SCHEDULER_ENABLED", "1").lower() in ("0", "false", "no"):
        logger.info("Offer scheduler disabled via OFFER_SCHEDULER_ENABLED")
        return
    if _STARTED:
        return
    _STARTED = True
    thread = threading.Thread(target=_scheduler_loop, name="offer-scheduler", daemon=True)
    thread.start()
