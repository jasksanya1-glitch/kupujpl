"""Catalog visibility rules: reviews, metacritic, F2P, type, offers, etc."""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Query, Session

from app.core.steam_reviews import (
    MIN_REVIEWS_FOR_NEW_RELEASES,
    MIN_REVIEWS_TO_SHOW,
    apply_review_summary_to_game,
    ensure_reviews_for_appids,
    fetch_review_summary,
    is_poorly_rated_game,
    is_too_obscure_game,
    min_reviews_for_list_slug,
)
from app.models.models import Game, Offer

logger = logging.getLogger("game_catalog_filter")

MIN_METACRITIC_TO_SHOW = int(os.environ.get("MIN_METACRITIC_TO_SHOW", "60"))
MIN_STEAM_RECOMMENDATIONS = int(os.environ.get("MIN_STEAM_RECOMMENDATIONS", "1000"))
FETCH_METADATA_ON_REQUEST = os.environ.get("CATALOG_METADATA_FETCH_ON_REQUEST", "0").lower() in (
    "1",
    "true",
    "yes",
)
CATALOG_FILTER_SCAN_BATCH = int(os.environ.get("CATALOG_FILTER_SCAN_BATCH", "32"))
CATALOG_FILTER_MAX_SCAN = int(os.environ.get("CATALOG_FILTER_MAX_SCAN", "96"))
VISIBLE_COUNT_CACHE = Path(__file__).resolve().parents[2] / "tmp" / "visible_games_count.json"
VISIBLE_COUNT_TTL_SEC = int(os.environ.get("VISIBLE_GAMES_COUNT_TTL_SEC", "1800"))

BLOCKED_STEAM_APP_TYPES = frozenset(
    t.strip().lower()
    for t in os.environ.get(
        "BLOCKED_STEAM_APP_TYPES",
        "dlc,demo,music,mod,video,series,episode,hardware,advertising,config",
    ).split(",")
    if t.strip()
)

NEW_RELEASE_JUNK_TITLE = (
    " soundtrack",
    " original soundtrack",
    " demo",
    " supporter pack",
    " supporter's",
    " premium upgrade",
    " - adult skin",
    " skin",
    " dlc",
    " ost",
    " playtest",
)


def apply_appdetails_metadata(game: Game, data: dict) -> None:
    game.steam_app_type = (data.get("type") or "").lower() or None
    game.is_free = bool(data.get("is_free"))
    release = data.get("release_date") or {}
    game.is_coming_soon = bool(release.get("coming_soon"))
    if release.get("date"):
        game.release_date = release.get("date")
    recommendations = data.get("recommendations") or {}
    if recommendations.get("total") is not None:
        game.steam_recommendations = int(recommendations["total"])
    metacritic = data.get("metacritic") or {}
    if metacritic.get("score") is not None:
        game.rating = float(metacritic["score"])


def is_blocked_app_type(game: Game | None) -> bool:
    if game is None:
        return False
    app_type = (game.steam_app_type or "").lower()
    return bool(app_type and app_type in BLOCKED_STEAM_APP_TYPES)


def _junk_new_release_title(title: str | None) -> bool:
    t = (title or "").lower()
    if not t:
        return True
    return any(p in t for p in NEW_RELEASE_JUNK_TITLE)


def is_hidden_from_steam_list(
    game: Game | None,
    *,
    list_slug: str | None = None,
    item: dict | None = None,
    min_reviews: int | None = None,
    in_stock_offers: int | None = None,
) -> bool:
    """Visibility rules for Steam-backed category lists (lighter for new releases)."""
    slug = (list_slug or "").strip().lower()
    if slug == "nowe-gry":
        if item and _junk_new_release_title(item.get("title")):
            return True
        if game is None:
            return False
        if is_blocked_app_type(game):
            return True
        if game.is_free:
            return True
        if game.is_coming_soon:
            return True
        if is_poorly_rated_game(game):
            return True
        return False

    return is_hidden_from_catalog(
        game,
        min_reviews=min_reviews,
        in_stock_offers=in_stock_offers,
    )


def is_hidden_from_catalog(
    game: Game | None,
    *,
    min_reviews: int | None = None,
    in_stock_offers: int | None = None,
) -> bool:
    if game is None:
        return False

    if is_blocked_app_type(game):
        return True
    if game.is_free:
        return True
    if game.is_coming_soon:
        return True

    if game.rating is not None and game.rating < MIN_METACRITIC_TO_SHOW:
        return True

    if game.steam_recommendations is not None and game.steam_recommendations < MIN_STEAM_RECOMMENDATIONS:
        return True

    if is_poorly_rated_game(game):
        return True
    if is_too_obscure_game(game, min_reviews=min_reviews):
        return True

    if in_stock_offers is not None and in_stock_offers == 0:
        return True

    return False


def exclude_hidden_games_query(query: Query) -> Query:
    """SQL filters mirroring is_hidden_from_catalog for DB search/browse."""
    bad_rating = and_(
        Game.steam_review_count.isnot(None),
        Game.steam_review_count > int(os.environ.get("MIN_STEAM_REVIEWS_TO_HIDE", "5000")),
        Game.steam_review_positive_pct.isnot(None),
        Game.steam_review_positive_pct
        < float(os.environ.get("MAX_STEAM_POSITIVE_PCT_TO_HIDE", "20")),
    )
    too_small = and_(
        Game.steam_review_count.isnot(None),
        Game.steam_review_count < MIN_REVIEWS_TO_SHOW,
    )
    blocked_type = and_(
        Game.steam_app_type.isnot(None),
        Game.steam_app_type.in_(list(BLOCKED_STEAM_APP_TYPES)),
    )
    no_offers = ~exists(
        select(Offer.id).where(
            Offer.game_id == Game.id,
            Offer.in_stock == True,
        )
    )
    eligible = or_(
        Game.steam_enriched == True,
        Game.steam_review_count >= MIN_REVIEWS_TO_SHOW,
    )
    visible = and_(
        Game.is_free.isnot(True),
        Game.is_coming_soon.isnot(True),
        ~blocked_type,
        or_(Game.rating.is_(None), Game.rating >= MIN_METACRITIC_TO_SHOW),
        or_(
            Game.steam_recommendations.is_(None),
            Game.steam_recommendations >= MIN_STEAM_RECOMMENDATIONS,
        ),
        ~bad_rating,
        ~too_small,
        ~no_offers,
    )
    return query.filter(eligible).filter(visible)


exclude_poorly_rated_query = exclude_hidden_games_query


def count_visible_games(db: Session) -> int:
    return exclude_hidden_games_query(db.query(Game)).count()


def get_visible_games_count(db: Session, *, force_refresh: bool = False) -> int:
    """Cached count of catalog-visible games (after all hide rules)."""
    if not force_refresh and VISIBLE_COUNT_CACHE.is_file():
        try:
            age = time.time() - VISIBLE_COUNT_CACHE.stat().st_mtime
            if age < VISIBLE_COUNT_TTL_SEC:
                data = json.loads(VISIBLE_COUNT_CACHE.read_text(encoding="utf-8"))
                if "count" in data:
                    return int(data["count"])
        except Exception as exc:
            logger.debug("Visible count cache read failed: %s", exc)

    count = count_visible_games(db)
    try:
        VISIBLE_COUNT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        VISIBLE_COUNT_CACHE.write_text(
            json.dumps(
                {
                    "count": count,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("Visible count cache write failed: %s", exc)
    return count


def refresh_visible_games_count_cache(db: Session) -> int:
    return get_visible_games_count(db, force_refresh=True)


def _fetch_appdetails(appid: int) -> dict | None:
    from app.parsers.steam_catalog import fetch_appdetails

    return fetch_appdetails(appid)


def ensure_catalog_metadata_for_appids(
    db: Session,
    appids: list[int],
    *,
    workers: int = 4,
) -> None:
    if not appids:
        return
    unique = list(dict.fromkeys(a for a in appids if a))
    games = db.query(Game).filter(Game.steam_appid.in_(unique)).all()
    missing = [g for g in games if g.steam_appid and not g.steam_app_type]
    if not missing:
        return

    def _fetch(game: Game) -> tuple[Game, dict | None]:
        time.sleep(0.15)
        return game, _fetch_appdetails(game.steam_appid)

    updated = False
    with ThreadPoolExecutor(max_workers=min(workers, len(missing))) as pool:
        futures = [pool.submit(_fetch, game) for game in missing]
        for future in as_completed(futures):
            try:
                game, data = future.result()
            except Exception as exc:
                logger.debug("Appdetails batch error: %s", exc)
                continue
            if not data:
                continue
            apply_appdetails_metadata(game, data)
            if game.steam_review_count is None and game.steam_appid:
                summary = fetch_review_summary(game.steam_appid)
                apply_review_summary_to_game(game, summary)
            updated = True

    if updated:
        db.commit()


def in_stock_offer_counts(db: Session, game_ids: list[int]) -> dict[int, int]:
    if not game_ids:
        return {}
    rows = (
        db.query(Offer.game_id, func.count(Offer.id))
        .filter(Offer.game_id.in_(game_ids), Offer.in_stock == True)
        .group_by(Offer.game_id)
        .all()
    )
    return {gid: count for gid, count in rows}


def filter_steam_list_items(
    db: Session,
    items: list[dict],
    *,
    min_reviews: int | None = None,
    fetch_metadata: bool | None = None,
    list_slug: str | None = None,
) -> list[dict]:
    if not items:
        return []

    appids = [item.get("appid") for item in items if item.get("appid")]
    if fetch_metadata if fetch_metadata is not None else FETCH_METADATA_ON_REQUEST:
        ensure_catalog_metadata_for_appids(db, appids)
        ensure_reviews_for_appids(db, appids)

    games = {
        g.steam_appid: g
        for g in db.query(Game).filter(Game.steam_appid.in_(appids)).all()
    }

    kept: list[dict] = []
    for item in items:
        appid = item.get("appid")
        game = games.get(appid) if appid else None
        if is_hidden_from_steam_list(
            game,
            list_slug=list_slug,
            item=item,
            min_reviews=min_reviews,
        ):
            continue
        kept.append(item)
    return kept


def fetch_steam_list_page_items(
    db: Session,
    items: list[dict],
    *,
    page: int,
    limit: int,
    scan_batch: int | None = None,
    min_reviews: int | None = None,
    fetch_metadata: bool | None = None,
    list_slug: str | None = None,
) -> tuple[list[dict], int]:
    if page < 1 or limit < 1 or not items:
        return [], 0

    batch = scan_batch or CATALOG_FILTER_SCAN_BATCH
    needed = page * limit
    max_scan = max(needed + limit, min(CATALOG_FILTER_MAX_SCAN, len(items)))
    if (list_slug or "").strip().lower() == "nowe-gry":
        max_scan = len(items)

    good: list[dict] = []
    idx = 0
    while idx < len(items) and len(good) < needed and idx < max_scan:
        chunk = items[idx : idx + batch]
        idx += batch
        good.extend(
            filter_steam_list_items(
                db,
                chunk,
                min_reviews=min_reviews,
                fetch_metadata=fetch_metadata,
                list_slug=list_slug,
            )
        )

    start = (page - 1) * limit
    page_items = good[start : start + limit]

    if idx >= len(items):
        total = len(good)
    elif len(page_items) >= limit:
        total = max(len(good), page * limit + limit)
    else:
        total = len(good)

    return page_items, total


__all__ = [
    "MIN_METACRITIC_TO_SHOW",
    "MIN_STEAM_RECOMMENDATIONS",
    "apply_appdetails_metadata",
    "is_blocked_app_type",
    "is_hidden_from_catalog",
    "is_hidden_from_steam_list",
    "exclude_hidden_games_query",
    "exclude_poorly_rated_query",
    "count_visible_games",
    "get_visible_games_count",
    "refresh_visible_games_count_cache",
    "ensure_catalog_metadata_for_appids",
    "filter_steam_list_items",
    "fetch_steam_list_page_items",
    "min_reviews_for_list_slug",
]
