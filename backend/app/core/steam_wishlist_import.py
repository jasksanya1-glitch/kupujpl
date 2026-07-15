"""Import Steam wishlist into favorites + Tier A scan queue."""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.db_retry import commit_with_retry
from app.models.models import Favorite, Game
from app.parsers.steam_catalog import ALLOWED_TYPES, enrich_game, fetch_appdetails, upsert_game_stub
from app.parsers.steam_wishlist import SteamWishlistError, fetch_wishlist_appids, resolve_steam_id64
from app.parsers.tier_a_scan_state import get_tier_a_scan_schedule_public
from app.parsers.tier_a_top5000 import append_games_to_tier_a_cache, is_tier_a_appid

logger = logging.getLogger("steam_wishlist_import")

WISHLIST_IMPORT_MAX = max(1, int(os.environ.get("WISHLIST_IMPORT_MAX", "100")))
WISHLIST_IMPORT_DELAY = float(os.environ.get("WISHLIST_IMPORT_DELAY_SEC", "0.35"))


def _scan_notice_pl() -> str:
    sched = get_tier_a_scan_schedule_public()
    tz = sched.get("timezone", "Europe/Warsaw")
    return (
        f"Gry nie było w naszej liście skanów — dodaliśmy ją. Ceny powinny pojawić się po "
        f"najbliższym cyklu Tier A (VPS ok. {sched.get('vps_local')}, "
        f"PC ok. {sched.get('pc_local')}, laptop ok. {sched.get('laptop_local')}, "
        f"strefa {tz})."
    )


def import_steam_wishlist(db: Session, *, user_id: int, profile_input: str) -> dict[str, Any]:
    steam_id64 = resolve_steam_id64(profile_input)
    appids = fetch_wishlist_appids(steam_id64)

    if not appids:
        return {
            "ok": True,
            "steam_id64": str(steam_id64),
            "wishlist_total": 0,
            "processed": 0,
            "truncated": False,
            "scan_notice_pl": _scan_notice_pl(),
            "schedule": get_tier_a_scan_schedule_public(),
            "tracked": [],
            "already_tracked": [],
            "added_to_catalog": [],
            "queued_for_scan": [],
            "skipped": [],
            "message": "Wishlista Steam jest pusta (lub brak gier do importu).",
        }

    truncated = len(appids) > WISHLIST_IMPORT_MAX
    work_appids = appids[:WISHLIST_IMPORT_MAX]

    tracked: list[dict[str, Any]] = []
    already_tracked: list[dict[str, Any]] = []
    added_to_catalog: list[dict[str, Any]] = []
    queued_for_scan: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    tier_a_candidates: list[Game] = []
    scan_notice = _scan_notice_pl()

    for appid in work_appids:
        game = db.query(Game).filter(Game.steam_appid == appid).first()
        was_new_catalog = False
        was_in_tier_a = is_tier_a_appid(appid)

        if not game:
            details = fetch_appdetails(appid)
            time.sleep(WISHLIST_IMPORT_DELAY)
            if not details:
                skipped.append(
                    {
                        "steam_appid": appid,
                        "reason": "steam_unavailable",
                        "message": "Steam nie zwrócił danych o grze.",
                    }
                )
                continue

            app_type = (details.get("type") or "").strip().lower()
            if app_type and app_type not in ALLOWED_TYPES:
                skipped.append(
                    {
                        "steam_appid": appid,
                        "title": details.get("name"),
                        "reason": "unsupported_type",
                        "message": f"Typ „{app_type}” nie jest obsługiwany w katalogu.",
                    }
                )
                continue

            game = upsert_game_stub(
                db,
                appid,
                details.get("name") or f"Steam {appid}",
                details.get("header_image"),
            )
            db.flush()
            try:
                enrich_game(db, game)
            except Exception as exc:
                logger.warning("Wishlist enrich failed for %s: %s", appid, exc)
            commit_with_retry(db)
            db.refresh(game)
            was_new_catalog = True
            added_to_catalog.append(
                {
                    "game_id": game.id,
                    "slug": game.slug,
                    "title": game.title,
                    "steam_appid": appid,
                    "message": scan_notice if not was_in_tier_a else "Dodano do katalogu.",
                }
            )

        fav = (
            db.query(Favorite)
            .filter(Favorite.user_id == user_id, Favorite.game_id == game.id)
            .first()
        )
        item = {
            "game_id": game.id,
            "slug": game.slug,
            "title": game.title,
            "steam_appid": appid,
            "best_price_pln": None,
        }

        if fav:
            already_tracked.append(item)
        else:
            db.add(Favorite(user_id=user_id, game_id=game.id))
            tracked.append(item)

        if not was_in_tier_a:
            tier_a_candidates.append(game)
            if not was_new_catalog:
                queued_for_scan.append(
                    {
                        **item,
                        "message": scan_notice,
                    }
                )

    newly_queued = append_games_to_tier_a_cache(db, tier_a_candidates, source="steam_wishlist")
    commit_with_retry(db)

    for row in added_to_catalog:
        if row["steam_appid"] in newly_queued:
            row["queued_for_scan"] = True

    return {
        "ok": True,
        "steam_id64": str(steam_id64),
        "wishlist_total": len(appids),
        "processed": len(work_appids),
        "truncated": truncated,
        "scan_notice_pl": scan_notice,
        "schedule": get_tier_a_scan_schedule_public(),
        "tracked": tracked,
        "already_tracked": already_tracked,
        "added_to_catalog": added_to_catalog,
        "queued_for_scan": queued_for_scan,
        "skipped": skipped,
        "tier_a_appended": len(newly_queued),
        "message": (
            f"Zaimportowano {len(tracked)} nowych śledzonych gier"
            f"{f' (z {len(appids)}, limit {WISHLIST_IMPORT_MAX})' if truncated else ''}."
        ),
    }


def wishlist_error_to_http(exc: SteamWishlistError) -> tuple[int, dict[str, Any]]:
    status = 400
    if exc.code in ("wishlist_private", "profile_not_found"):
        status = 403
    elif exc.code == "network_error":
        status = 502
    body: dict[str, Any] = {
        "ok": False,
        "code": exc.code,
        "detail": exc.message,
    }
    if exc.hint:
        body["hint"] = exc.hint
    return status, body
