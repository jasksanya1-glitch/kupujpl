"""Homepage deal feeds: new drops, historical lows, freebies."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.models import Game, Offer, PriceSnapshot
from app.parsers.shop_scan_config import get_display_shops

PRICE_EPSILON = 0.05

# Short in-process cache so game + DLC page loads don't re-hit Steam appdetails.
_APPDETAILS_CACHE: dict[int, tuple[float, dict | None]] = {}
_APPDETAILS_TTL_SEC = 3600.0


def _display_shops() -> list[str]:
    return list(get_display_shops())


def games_at_historical_low(db: Session, *, limit: int = 16) -> list[Game]:
    """Games whose current best price matches all-time low."""
    display = _display_shops()
    best_subq = (
        db.query(
            Offer.game_id.label("gid"),
            func.min(Offer.price_pln).label("best"),
        )
        .filter(
            Offer.in_stock.is_(True),
            Offer.price_pln > 0,
            Offer.shop_name.in_(display),
        )
        .group_by(Offer.game_id)
        .subquery()
    )
    rows = (
        db.query(Game)
        .join(best_subq, best_subq.c.gid == Game.id)
        .filter(
            Game.lowest_ever_pln.isnot(None),
            Game.is_free.is_(False),
            best_subq.c.best <= Game.lowest_ever_pln + PRICE_EPSILON,
            best_subq.c.best > 0,
        )
        .order_by(Game.steam_review_count.desc(), best_subq.c.best.asc())
        .limit(limit)
        .all()
    )
    return rows


def games_new_deals(db: Session, *, limit: int = 16, hours: int = 48) -> list[tuple[Game, datetime]]:
    """Recent price drops (newer snapshot cheaper than previous for same shop)."""
    display = _display_shops()
    since = datetime.utcnow() - timedelta(hours=hours)
    latest = (
        db.query(
            PriceSnapshot.game_id.label("gid"),
            func.max(PriceSnapshot.recorded_at).label("last_at"),
            func.min(PriceSnapshot.price_pln).label("drop_price"),
        )
        .filter(
            PriceSnapshot.recorded_at >= since,
            PriceSnapshot.in_stock.is_(True),
            PriceSnapshot.shop_name.in_(display),
            PriceSnapshot.price_pln > 0,
        )
        .group_by(PriceSnapshot.game_id)
        .subquery()
    )
    best_subq = (
        db.query(
            Offer.game_id.label("gid"),
            func.min(Offer.price_pln).label("best"),
        )
        .filter(
            Offer.in_stock.is_(True),
            Offer.price_pln > 0,
            Offer.shop_name.in_(display),
        )
        .group_by(Offer.game_id)
        .subquery()
    )
    rows = (
        db.query(Game, latest.c.last_at)
        .join(latest, latest.c.gid == Game.id)
        .join(best_subq, best_subq.c.gid == Game.id)
        .filter(
            Game.is_free.is_(False),
            best_subq.c.best > 0,
        )
        .order_by(latest.c.last_at.desc())
        .limit(limit)
        .all()
    )
    return [(game, last_at) for game, last_at in rows]


def games_freebies(db: Session, *, limit: int = 12) -> list[Game]:
    """Prefer limited giveaways (Epic/Steam), then popular always-free titles."""
    from app.parsers.free_giveaways import get_free_giveaways

    selected: list[Game] = []
    seen: set[int] = set()

    try:
        payload = get_free_giveaways(db)
        for item in payload.get("current") or []:
            game = None
            slug = item.get("slug")
            appid = item.get("steam_appid")
            if slug:
                game = db.query(Game).filter(Game.slug == slug).first()
            if not game and appid:
                game = db.query(Game).filter(Game.steam_appid == int(appid)).first()
            if game and game.id not in seen:
                seen.add(game.id)
                selected.append(game)
            if len(selected) >= limit:
                return selected
    except Exception:
        pass

    official = ("Steam", "GOG", "Epic Games")
    free_offer_gids = (
        db.query(Offer.game_id)
        .filter(
            Offer.in_stock.is_(True),
            Offer.price_pln <= 0.01,
            or_(Offer.is_official.is_(True), Offer.shop_name.in_(official)),
        )
        .distinct()
    )
    rows = (
        db.query(Game)
        .filter(
            or_(
                Game.is_free.is_(True),
                Game.id.in_(free_offer_gids),
            ),
            ~Game.id.in_(list(seen) or [-1]),
        )
        .order_by(Game.steam_review_count.desc())
        .limit(max(limit - len(selected), 0) + 8)
        .all()
    )
    for game in rows:
        if game.id in seen:
            continue
        seen.add(game.id)
        selected.append(game)
        if len(selected) >= limit:
            break
    return selected[:limit]


def _title_prefix(title: str) -> str:
    title = (title or "").strip()
    if len(title) < 3:
        return ""
    prefix = title.split(":")[0].strip()
    if len(prefix) < 3:
        prefix = title[: min(24, len(title))]
    return prefix


def _steam_appdetails(appid: int | None) -> dict | None:
    if not appid:
        return None
    aid = int(appid)
    now = datetime.utcnow().timestamp()
    cached = _APPDETAILS_CACHE.get(aid)
    if cached and now - cached[0] < _APPDETAILS_TTL_SEC:
        return cached[1]
    data = None
    try:
        from app.parsers.steam_catalog import fetch_appdetails

        data = fetch_appdetails(aid)
    except Exception:
        data = None
    _APPDETAILS_CACHE[aid] = (now, data)
    if len(_APPDETAILS_CACHE) > 512:
        for key in sorted(_APPDETAILS_CACHE, key=lambda k: _APPDETAILS_CACHE[k][0])[:256]:
            _APPDETAILS_CACHE.pop(key, None)
    return data


def _steam_dlc_appids(appid: int | None) -> list[int]:
    data = _steam_appdetails(appid)
    if not data:
        return []
    raw = data.get("dlc") or []
    return [int(x) for x in raw if str(x).isdigit()][:40]


def parent_game_for_dlc(db: Session, game: Game) -> Game | None:
    """Resolve base game for a DLC row via Steam fullgame or title heuristic."""
    if (game.steam_app_type or "").lower() != "dlc":
        return None

    data = _steam_appdetails(game.steam_appid)
    if data:
        fullgame = data.get("fullgame") or {}
        parent_id = fullgame.get("appid")
        if parent_id is not None and str(parent_id).isdigit():
            parent = (
                db.query(Game)
                .filter(Game.steam_appid == int(parent_id))
                .first()
            )
            if parent:
                return parent

    title = (game.title or "").strip()
    prefix = _title_prefix(title)
    if len(prefix) < 4:
        return None
    candidates = (
        db.query(Game)
        .filter(
            Game.id != game.id,
            or_(Game.steam_app_type == "game", Game.steam_app_type.is_(None)),
            Game.title.ilike(f"{prefix}%"),
        )
        .order_by(func.length(Game.title).asc(), Game.steam_review_count.desc())
        .limit(12)
        .all()
    )
    title_l = title.lower()
    best: Game | None = None
    for cand in candidates:
        cand_title = (cand.title or "").strip()
        if not cand_title:
            continue
        if title_l.startswith(cand_title.lower()) and cand.id != game.id:
            if best is None or len(cand_title) > len(best.title or ""):
                best = cand
    return best


def related_dlc_games(db: Session, game: Game, *, limit: int = 8) -> list[Game]:
    """DLC in our DB linked by Steam appdetails dlc[] and/or steam_app_type + title."""
    if (game.steam_app_type or "").lower() == "dlc":
        parent = parent_game_for_dlc(db, game)
        base = parent or game
        siblings = _related_dlc_for_base(db, base, limit=limit + 1, exclude_ids={game.id})
        return [g for g in siblings if g.id != game.id][:limit]

    return _related_dlc_for_base(db, game, limit=limit, exclude_ids={game.id})


def _related_dlc_for_base(
    db: Session,
    game: Game,
    *,
    limit: int,
    exclude_ids: set[int] | None = None,
) -> list[Game]:
    exclude_ids = set(exclude_ids or ())
    exclude_ids.add(game.id)
    found: list[Game] = []
    seen = set(exclude_ids)

    dlc_ids = _steam_dlc_appids(game.steam_appid)
    if dlc_ids:
        rows = (
            db.query(Game)
            .filter(Game.steam_appid.in_(dlc_ids), Game.id.notin_(list(seen) or [0]))
            .order_by(Game.steam_review_count.desc())
            .limit(limit)
            .all()
        )
        for row in rows:
            if row.id in seen:
                continue
            found.append(row)
            seen.add(row.id)

    if len(found) < limit:
        extra = _related_by_title_dlc_only(
            db, game, limit=limit - len(found), exclude_ids=seen
        )
        found.extend(extra)
    return found[:limit]


def _related_by_title_dlc_only(
    db: Session,
    game: Game,
    *,
    limit: int,
    exclude_ids: set[int] | None = None,
) -> list[Game]:
    """Fallback: only steam_app_type=dlc with shared title prefix (no sequels)."""
    exclude_ids = exclude_ids or {game.id}
    prefix = _title_prefix(game.title or "")
    if len(prefix) < 3 or limit <= 0:
        return []
    return (
        db.query(Game)
        .filter(
            Game.id.notin_(list(exclude_ids) or [0]),
            Game.steam_app_type == "dlc",
            or_(
                Game.title.ilike(f"{prefix}%"),
                Game.title.ilike(f"%{prefix}%"),
            ),
        )
        .order_by(Game.steam_review_count.desc())
        .limit(limit)
        .all()
    )


def deal_age_label(when: datetime | None) -> str | None:
    if not when:
        return None
    delta = datetime.utcnow() - when
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        return "przed chwilą"
    if mins < 60:
        return f"{mins} min temu"
    hours = mins // 60
    if hours < 48:
        return f"{hours} godz. temu"
    days = hours // 24
    return f"{days} dni temu"
