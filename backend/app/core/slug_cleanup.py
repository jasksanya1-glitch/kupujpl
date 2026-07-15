"""Remove duplicate games created when title numbers were parsed as Steam appids."""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session, joinedload

from app.core.slug_lookup import _likely_mistaken_stub, _trailing_digits
from app.models.models import Favorite, Game, Offer

logger = logging.getLogger("slug_cleanup")

_ORPHAN_STUB_RE = re.compile(r"^gra-(\d+)-\1$")


def _is_orphan_gra_stub(slug: str) -> bool:
    return bool(_ORPHAN_STUB_RE.match(slug or ""))


def cleanup_mistaken_stub_games(db: Session) -> dict[str, int]:
    """Delete stub rows like forza-horizon-6 (appid 6) when forza-horizon-6-2483190 exists."""
    removed = 0
    favorites_moved = 0
    offers_dropped = 0

    rows = db.query(Game.id, Game.slug).all()
    candidate_ids = [
        gid
        for gid, slug in rows
        if (_trailing_digits(slug) and _trailing_digits(slug)[1] <= 2)
        or _is_orphan_gra_stub(slug)
    ]

    for game_id in candidate_ids:
        game = (
            db.query(Game)
            .options(joinedload(Game.offers))
            .filter(Game.id == game_id)
            .first()
        )
        if not game:
            continue

        is_mistaken = _likely_mistaken_stub(game, game.slug)
        is_orphan = _is_orphan_gra_stub(game.slug)
        if not is_mistaken and not is_orphan:
            continue

        canonical_list = (
            db.query(Game)
            .filter(Game.slug.like(f"{game.slug}-%"))
            .all()
        )
        if canonical_list:
            canonical = max(
                canonical_list,
                key=lambda g: (
                    bool(g.steam_enriched),
                    len(g.offers),
                    g.steam_appid or 0,
                    g.id,
                ),
            )
            if canonical.id == game.id:
                continue
        elif is_orphan:
            canonical = None
        else:
            continue

        for fav in db.query(Favorite).filter(Favorite.game_id == game.id).all():
            if canonical is None:
                db.delete(fav)
                continue
            dup = (
                db.query(Favorite)
                .filter(Favorite.user_id == fav.user_id, Favorite.game_id == canonical.id)
                .first()
            )
            if dup:
                db.delete(fav)
            else:
                fav.game_id = canonical.id
                favorites_moved += 1

        offers_dropped += db.query(Offer).filter(Offer.game_id == game.id).delete()
        db.delete(game)
        removed += 1
        if canonical:
            logger.info("Removed mistaken stub %s -> %s", game.slug, canonical.slug)
        else:
            logger.info("Removed orphan stub %s", game.slug)

    if removed:
        db.commit()

    return {
        "removed": removed,
        "favorites_moved": favorites_moved,
        "offers_dropped": offers_dropped,
    }
