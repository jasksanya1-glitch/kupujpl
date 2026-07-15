#!/usr/bin/env python3
"""Run price alert notifications after offer scans."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal
from app.core.price_alerts import process_price_alerts
from app.core.price_history import prune_old_snapshots

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("price_alert_worker")


def main() -> int:
    db = SessionLocal()
    try:
        pruned = prune_old_snapshots(db)
        db.commit()
        if pruned:
            logger.info("Pruned %d old price snapshots", pruned)
        stats = process_price_alerts(db)
        logger.info("Alerts: checked=%d email=%d telegram=%d", stats["checked"], stats["email"], stats["telegram"])
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
