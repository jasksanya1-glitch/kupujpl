import logging
from sqlalchemy.orm import Session

from app.parsers.steam_catalog import enrich_pending_batch

logger = logging.getLogger("steam_parser")


def import_steam_games(db: Session, appids: list | None = None) -> None:
    """Scheduled: enrich pending Steam games (prices, genres)."""
    result = enrich_pending_batch(db, limit=150)
    logger.info("Steam enrich batch: %s", result)
