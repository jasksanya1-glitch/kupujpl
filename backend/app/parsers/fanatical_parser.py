"""Fanatical Global key shop offers (Awin product feed)."""
from __future__ import annotations

import logging

logger = logging.getLogger("fanatical_parser")

SHOP_NAME = "Fanatical"


def search_fanatical_price(query: str, game_slug: str) -> tuple[str | None, float | None, float | None]:
    from app.parsers.affiliate_feeds import affiliate_feed_lookup

    feed = affiliate_feed_lookup("Fanatical", query, game_slug)
    if feed:
        return feed.url, feed.price_pln, feed.confidence
    return None, None, None
