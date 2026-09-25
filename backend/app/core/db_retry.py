"""SQLite commit helper with busy-timeout retries."""
from __future__ import annotations

import logging
import time

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.catalog_cache import bump_catalog_generation

logger = logging.getLogger("db_retry")


def commit_with_retry(db: Session, *, attempts: int = 6, base_delay: float = 1.0) -> None:
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            db.commit()
            bump_catalog_generation()
            return
        except OperationalError as exc:
            last_exc = exc
            if "locked" not in str(exc).lower():
                raise
            db.rollback()
            delay = base_delay * (attempt + 1)
            logger.warning("DB locked, retry %s/%s in %.1fs", attempt + 1, attempts, delay)
            time.sleep(delay)
    if last_exc:
        raise last_exc
