"""Background scheduler: slowly fill Steam catalog filter fields (type, reviews)."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from sqlalchemy import and_, or_

from app.core.database import SessionLocal
from app.core.game_catalog_filter import (
    ensure_catalog_metadata_for_appids,
    refresh_visible_games_count_cache,
)
from app.core.steam_reviews import ensure_reviews_for_appids
from app.models.models import Game

logger = logging.getLogger("catalog_filter_scheduler")

_STARTED = False
INTERVAL_SEC = int(os.environ.get("CATALOG_FILTER_INTERVAL_SEC", "300"))
BATCH_SIZE = int(os.environ.get("CATALOG_FILTER_BATCH_SIZE", "12"))
WORKERS = int(os.environ.get("CATALOG_FILTER_WORKERS", "2"))


def run_catalog_filter_batch(*, limit: int | None = None) -> dict[str, Any]:
    """Fetch missing app_type / review_count for a small batch of enriched games."""
    batch_limit = limit or BATCH_SIZE
    db = SessionLocal()
    try:
        games = (
            db.query(Game)
            .filter(
                Game.steam_enriched == True,
                Game.steam_appid.isnot(None),
                or_(
                    Game.steam_app_type.is_(None),
                    Game.steam_review_count.is_(None),
                ),
            )
            .order_by(Game.id.desc())
            .limit(batch_limit)
            .all()
        )
        appids = [g.steam_appid for g in games if g.steam_appid]
        if not appids:
            return {"updated": 0, "remaining": 0}

        before = len(appids)
        ensure_catalog_metadata_for_appids(db, appids, workers=WORKERS)
        ensure_reviews_for_appids(db, appids, workers=WORKERS)

        remaining = (
            db.query(Game)
            .filter(
                Game.steam_enriched == True,
                Game.steam_appid.isnot(None),
                or_(
                    Game.steam_app_type.is_(None),
                    Game.steam_review_count.is_(None),
                ),
            )
            .count()
        )
        refresh_count = remaining % (BATCH_SIZE * 5) < BATCH_SIZE
        if refresh_count:
            try:
                refresh_visible_games_count_cache(db)
            except Exception as exc:
                logger.debug("Visible count refresh skipped: %s", exc)
        return {"updated": before, "remaining": remaining}
    finally:
        db.close()


def _loop() -> None:
    logger.info(
        "Catalog filter scheduler started (every %ss, batch=%s, workers=%s)",
        INTERVAL_SEC,
        BATCH_SIZE,
        WORKERS,
    )
    while True:
        try:
            stats = run_catalog_filter_batch()
            if stats.get("updated"):
                logger.info(
                    "Catalog filter batch: touched %s games, ~%s remaining",
                    stats["updated"],
                    stats["remaining"],
                )
        except Exception as exc:
            logger.error("Catalog filter batch failed: %s", exc)
        time.sleep(INTERVAL_SEC)


def start_catalog_filter_scheduler() -> None:
    global _STARTED
    if os.environ.get("CATALOG_FILTER_SCHEDULER_ENABLED", "1").lower() in ("0", "false", "no"):
        logger.info("Catalog filter scheduler disabled via CATALOG_FILTER_SCHEDULER_ENABLED")
        return
    if _STARTED:
        return
    _STARTED = True
    threading.Thread(target=_loop, name="catalog-filter-scheduler", daemon=True).start()
