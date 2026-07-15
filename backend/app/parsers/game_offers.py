"""On-demand offer refresh for a single game (background job)."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.core.db_retry import commit_with_retry
from app.models.models import Game, Offer
from app.parsers.steam_catalog import enrich_game, refresh_steam_offer_for_game
from app.parsers.gog_parser import search_gog_price
from app.parsers.epic_parser import search_epic_price
from app.parsers.eneba_parser import search_eneba_price
from app.parsers.kinguin_parser import search_kinguin_price
from app.parsers.cdkeys_parser import search_cdkeys_price
from app.parsers.g2a_parser import search_g2a_price
from app.parsers.gamivo_parser import search_gamivo_price
from app.parsers.fanatical_parser import search_fanatical_price
from app.parsers.instant_gaming_parser import search_instant_gaming_price
from app.parsers.keyshop_common import upsert_keyshop_offer, slugify

logger = logging.getLogger("game_offers")

REFRESH_COOLDOWN = timedelta(hours=int(os.environ.get("OFFER_REFRESH_COOLDOWN_HOURS", "24")))
MIN_SHOPS_TARGET = int(os.environ.get("MIN_OFFERS_SHOPS_TARGET", "4"))

from app.parsers.shop_scan_config import EXPECTED_SHOPS, get_active_scan_shops, is_shop_active

_OFFICIAL_FETCHERS: tuple[tuple[str, object], ...] = (
    ("GOG", search_gog_price),
    ("Epic Games", search_epic_price),
)

_KEYSHOPS: tuple[tuple[str, object], ...] = (
    ("Instant Gaming", search_instant_gaming_price),
    ("Eneba", search_eneba_price),
    ("Kinguin", search_kinguin_price),
    ("CDKeys", search_cdkeys_price),
    ("G2A", search_g2a_price),
    ("Gamivo", search_gamivo_price),
    ("Fanatical", search_fanatical_price),
)
_KEYSHOPS_FAST: tuple[tuple[str, object], ...] = (("Kinguin", search_kinguin_price),)


def _present_shops(game: Game) -> set[str]:
    return {o.shop_name for o in game.offers if o.in_stock}


def _shop_count(game: Game) -> int:
    return len(_present_shops(game))


def _missing_shops(game: Game) -> set[str]:
    return set(get_active_scan_shops()) - _present_shops(game)


def _filter_fetchers(
    fetchers: tuple[tuple[str, object], ...],
    *,
    allowed: frozenset[str] | None,
) -> tuple[tuple[str, object], ...]:
    active = set(get_active_scan_shops())
    out: list[tuple[str, object]] = []
    for name, fn in fetchers:
        if name not in active:
            continue
        if allowed is not None and name not in allowed:
            continue
        out.append((name, fn))
    return tuple(out)


def _needs_refresh(game: Game) -> bool:
    if _missing_shops(game):
        return True
    if not game.offers:
        return True
    latest = max((o.updated_at or datetime.min for o in game.offers), default=datetime.min)
    if latest.tzinfo:
        latest = latest.replace(tzinfo=None)
    return latest < datetime.utcnow() - REFRESH_COOLDOWN


def _unpack_price_result(
    result: tuple | None,
) -> tuple[str | None, float | None, float | None]:
    if not result:
        return None, None, None
    if len(result) >= 3:
        return result[0], result[1], result[2]
    return result[0], result[1], None


def _fetch_keyshops_parallel(
    title: str,
    shops: tuple[tuple[str, object], ...],
) -> list[tuple[str, str, float]]:
    if not shops:
        return []
    slug = slugify(title)
    found: list[tuple[str, str, float, float | None]] = []

    def _one(shop_name: str, search_fn) -> tuple[str, str | None, float | None, float | None]:
        url, price, confidence = _unpack_price_result(search_fn(title, slug))
        return shop_name, url, price, confidence

    with ThreadPoolExecutor(max_workers=len(shops)) as pool:
        futures = [pool.submit(_one, name, fn) for name, fn in shops]
        for future in as_completed(futures):
            try:
                shop_name, url, price, confidence = future.result()
                if url and price is not None:
                    found.append((shop_name, url, price, confidence))
            except Exception as exc:
                logger.debug("Keyshop fetch error: %s", exc)
    return found


def _shops_to_query(
    game: Game,
    *,
    fast: bool,
    fill_missing: bool,
    force: bool,
    shop_names: frozenset[str] | None = None,
) -> tuple[tuple[str, object], ...]:
    pool = _KEYSHOPS_FAST if fast else _KEYSHOPS
    pool = _filter_fetchers(pool, allowed=shop_names)
    if force:
        return pool

    missing = _missing_shops(game)
    keyshop_names = {name for name, _ in _KEYSHOPS}

    if fill_missing and missing:
        names = missing & keyshop_names
        return tuple((n, f) for n, f in pool if n in names)

    if fast:
        return _filter_fetchers(_KEYSHOPS_FAST, allowed=shop_names)

    return pool


def _fetch_official_prices(title: str, shops: tuple[tuple[str, object], ...]) -> list[tuple[str, str, float]]:
    if not shops:
        return []
    found: list[tuple[str, str, float, float | None]] = []

    def _one(shop_name: str, search_fn) -> tuple[str, str | None, float | None, float | None]:
        url, price, confidence = _unpack_price_result(search_fn(title))
        return shop_name, url, price, confidence

    with ThreadPoolExecutor(max_workers=len(shops)) as pool:
        futures = [pool.submit(_one, name, fn) for name, fn in shops]
        for future in as_completed(futures):
            try:
                shop_name, url, price, confidence = future.result()
                if url and price is not None:
                    found.append((shop_name, url, price, confidence))
            except Exception as exc:
                logger.debug("Official store fetch error: %s", exc)
    return found


def _official_shops_to_query(
    game: Game,
    *,
    fast: bool,
    fill_missing: bool,
    force: bool,
    shop_names: frozenset[str] | None = None,
) -> tuple[tuple[str, object], ...]:
    pool = _filter_fetchers(_OFFICIAL_FETCHERS, allowed=shop_names)
    if force:
        return pool

    missing = _missing_shops(game)
    official_names = {name for name, _ in _OFFICIAL_FETCHERS}

    if fill_missing and missing:
        names = missing & official_names
        return tuple((n, f) for n, f in pool if n in names)

    if fast:
        gog = _filter_fetchers((("GOG", search_gog_price),), allowed=shop_names)
        return gog

    return pool


def game_needs_offer_refresh(game: Game) -> bool:
    """True when offers are missing shops, sparse, or past cooldown."""
    if _shop_count(game) < MIN_SHOPS_TARGET:
        return True
    return _needs_refresh(game)


def _effective_refresh_flags(
    game: Game,
    *,
    force: bool,
    fast: bool,
    fill_missing: bool,
) -> tuple[bool, bool]:
    """Use full multi-shop scan when the game still has few shops."""
    if force or fill_missing or _shop_count(game) < MIN_SHOPS_TARGET:
        return True, False
    return fill_missing, fast


def _deactivate_shop_offer(db, game: Game, shop_name: str) -> None:
    existing = (
        db.query(Offer)
        .filter(Offer.game_id == game.id, Offer.shop_name == shop_name)
        .first()
    )
    if existing:
        existing.in_stock = False


def refresh_offers_for_game(
    game_id: int,
    *,
    force: bool = False,
    fast: bool = False,
    fill_missing: bool = False,
    shop_names: frozenset[str] | None = None,
) -> None:
    title: str | None = None
    official_shops: tuple[tuple[str, object], ...] = ()
    keyshops: tuple[tuple[str, object], ...] = ()
    missing_at_fetch: set[str] = set()

    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if not game:
            return

        fill_missing, fast = _effective_refresh_flags(
            game, force=force, fast=fast, fill_missing=fill_missing
        )

        missing_before = _missing_shops(game)
        if not force and not fill_missing and not _needs_refresh(game):
            logger.debug("Skip refresh for game %s (recent offers)", game_id)
            return

        if not fast and game.steam_appid and not game.steam_enriched:
            try:
                if enrich_game(db, game):
                    db.commit()
                    db.refresh(game)
            except Exception as exc:
                logger.warning("Steam enrich failed for %s: %s", game_id, exc)
                db.rollback()

        need_steam = game.steam_appid and (
            force or fill_missing or not fast or "Steam" in missing_before
        )
        steam_allowed = shop_names is None or "Steam" in shop_names
        if (
            steam_allowed
            and need_steam
            and (force or fill_missing or "Steam" in _missing_shops(game))
            and is_shop_active("Steam")
        ):
            try:
                refresh_steam_offer_for_game(db, game)
            except Exception as exc:
                logger.warning("Steam price refresh failed for %s: %s", game_id, exc)

        title = game.title
        missing_at_fetch = _missing_shops(game)
        official_shops = _official_shops_to_query(
            game, fast=fast, fill_missing=fill_missing, force=force, shop_names=shop_names
        )
        keyshops = _shops_to_query(
            game, fast=fast, fill_missing=fill_missing, force=force, shop_names=shop_names
        )
        commit_with_retry(db)
    except Exception as exc:
        logger.error("Offer refresh failed for game %s: %s", game_id, exc)
        db.rollback()
        return
    finally:
        db.close()

    if not title:
        return

    official_found: list[tuple[str, str, float, float | None]] = []
    if official_shops:
        official_found = _fetch_official_prices(title, official_shops)

    keyshop_found: list[tuple[str, str, float, float | None]] = []
    if keyshops:
        keyshop_found = _fetch_keyshops_parallel(title, keyshops)

    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if not game:
            return

        official_found_names: set[str] = set()
        if official_shops and official_found:
            for shop_name, url, price, confidence in official_found:
                if force or fill_missing or shop_name in missing_at_fetch or not fast:
                    upsert_keyshop_offer(
                        db,
                        game,
                        shop_name,
                        url,
                        price,
                        is_official=True,
                        match_confidence=confidence,
                    )
                    official_found_names.add(shop_name)

        keyshop_found_names: set[str] = set()
        if keyshops and keyshop_found:
            for shop_name, url, price, confidence in keyshop_found:
                upsert_keyshop_offer(
                    db, game, shop_name, url, price, match_confidence=confidence
                )
                keyshop_found_names.add(shop_name)

        queried = {name for name, _ in official_shops} | {name for name, _ in keyshops}
        found_all = official_found_names | keyshop_found_names
        for shop_name in queried:
            if shop_name not in found_all:
                _deactivate_shop_offer(db, game, shop_name)

        commit_with_retry(db)
        still_missing = _missing_shops(game)
        logger.info(
            "Refreshed offers for game %s (%s); missing: %s",
            game_id,
            game.title,
            sorted(still_missing) if still_missing else "none",
        )
    except Exception as exc:
        logger.error("Offer refresh failed for game %s: %s", game_id, exc)
        db.rollback()
    finally:
        db.close()
