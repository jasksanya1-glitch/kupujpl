"""Background scheduler: enrich Steam metadata for games still pending."""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.core.database import SessionLocal
from app.parsers.steam_catalog import enrich_pending_batch

logger = logging.getLogger("enrich_scheduler")

_STARTED = False
INTERVAL_SEC = int(os.environ.get("ENRICH_INTERVAL_SEC", "90"))
BATCH_SIZE = int(os.environ.get("ENRICH_BATCH_SIZE", "40"))


def run_enrich_batch(*, limit: int | None = None) -> dict[str, Any]:
    db = SessionLocal()
    try:
        return enrich_pending_batch(db, limit=limit or BATCH_SIZE)
    finally:
        db.close()


def _loop() -> None:
    logger.info("Enrich scheduler started (every %ss, batch=%s)", INTERVAL_SEC, BATCH_SIZE)
    while True:
        try:
            stats = run_enrich_batch()
            if stats.get("enriched"):
                logger.info(
                    "Enrich batch: +%s enriched, %s skipped, %s remaining",
                    stats["enriched"],
                    stats["skipped"],
                    stats["remaining"],
                )
        except Exception as exc:
            logger.error("Enrich batch failed: %s", exc)
        time.sleep(INTERVAL_SEC)


def start_enrich_scheduler() -> None:
    global _STARTED
    if os.environ.get("ENRICH_SCHEDULER_ENABLED", "1").lower() in ("0", "false", "no"):
        logger.info("Enrich scheduler disabled via ENRICH_SCHEDULER_ENABLED")
        return
    if _STARTED:
        return
    _STARTED = True
    threading.Thread(target=_loop, name="enrich-scheduler", daemon=True).start()
