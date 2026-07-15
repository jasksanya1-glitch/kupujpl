"""Steam user review summary + quality filter for catalog lists."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from sqlalchemy.orm import Session

from app.models.models import Game

logger = logging.getLogger("steam_reviews")

APPREVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

MIN_REVIEWS_TO_HIDE = int(os.environ.get("MIN_STEAM_REVIEWS_TO_HIDE", "5000"))
MAX_POSITIVE_PCT_TO_HIDE = float(os.environ.get("MAX_STEAM_POSITIVE_PCT_TO_HIDE", "20"))
MIN_REVIEWS_TO_SHOW = int(os.environ.get("MIN_STEAM_REVIEWS_TO_SHOW", "1000"))
MIN_REVIEWS_FOR_NEW_RELEASES = int(os.environ.get("MIN_STEAM_REVIEWS_FOR_NEW", "0"))


def min_reviews_for_list_slug(slug: str | None) -> int:
    if (slug or "").strip().lower() == "nowe-gry":
        return MIN_REVIEWS_FOR_NEW_RELEASES
    return MIN_REVIEWS_TO_SHOW


def fetch_review_summary(appid: int) -> dict | None:
    if not appid:
        return None
    try:
        response = requests.get(
            APPREVIEWS_URL.format(appid=appid),
            params={
                "json": 1,
                "language": "all",
                "purchase_type": "all",
                "num_per_page": 0,
            },
            timeout=20,
            headers=HEADERS,
        )
        if response.status_code != 200:
            return None
        summary = (response.json() or {}).get("query_summary") or {}
        total = int(summary.get("total_reviews") or 0)
        if total <= 0:
            return None
        positive = int(summary.get("total_positive") or 0)
        score = summary.get("review_score")
        return {
            "review_score": int(score) if score is not None else None,
            "review_count": total,
            "positive_pct": round(positive / total * 100.0, 2),
        }
    except Exception as exc:
        logger.debug("Review fetch failed for %s: %s", appid, exc)
        return None


def apply_review_summary_to_game(game: Game, summary: dict | None) -> None:
    if not summary:
        return
    game.steam_review_score = summary.get("review_score")
    game.steam_review_count = summary.get("review_count")
    game.steam_review_positive_pct = summary.get("positive_pct")


def is_poorly_rated_game(game: Game | None) -> bool:
    if game is None:
        return False
    count = game.steam_review_count
    pct = game.steam_review_positive_pct
    if count is None or pct is None:
        return False
    return count > MIN_REVIEWS_TO_HIDE and pct < MAX_POSITIVE_PCT_TO_HIDE


def is_too_obscure_game(game: Game | None, *, min_reviews: int | None = None) -> bool:
    if game is None:
        return False
    count = game.steam_review_count
    if count is None:
        return False
    threshold = MIN_REVIEWS_TO_SHOW if min_reviews is None else min_reviews
    return count < threshold


def ensure_reviews_for_appids(db: Session, appids: list[int], *, workers: int = 6) -> None:
    if not appids:
        return
    unique = list(dict.fromkeys(a for a in appids if a))
    games = db.query(Game).filter(Game.steam_appid.in_(unique)).all()
    missing = [g for g in games if g.steam_appid and g.steam_review_count is None]
    if not missing:
        return

    def _fetch(game: Game) -> tuple[Game, dict | None]:
        return game, fetch_review_summary(game.steam_appid)

    updated = False
    with ThreadPoolExecutor(max_workers=min(workers, len(missing))) as pool:
        futures = [pool.submit(_fetch, game) for game in missing]
        for future in as_completed(futures):
            try:
                game, summary = future.result()
            except Exception as exc:
                logger.debug("Review batch error: %s", exc)
                continue
            if summary:
                apply_review_summary_to_game(game, summary)
                updated = True

    if updated:
        db.commit()
