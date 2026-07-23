"""Compact live stats for /panel3/live — visits, Kup clicks, signups."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.site_sessions import (
    collect_active_sessions,
    display_session_who,
    format_duration,
    session_duration_at,
)
from app.models.models import AffiliateClick, Game, SiteVisit, User


def _iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.isoformat() + "Z"


def _game_slug_from_path(path: str | None) -> str | None:
    raw = (path or "").split("?", 1)[0].strip()
    if raw.startswith("/gra/"):
        slug = raw[5:].strip("/")
        return slug or None
    return None


def _game_titles_for_slugs(db: Session, slugs: set[str]) -> dict[str, str]:
    if not slugs:
        return {}
    rows = db.query(Game.slug, Game.title).filter(Game.slug.in_(slugs)).all()
    return {slug: title for slug, title in rows if slug and title}


def _visit_item(
    v: SiteVisit,
    game_titles: dict[str, str] | None = None,
    *,
    db: Session | None = None,
) -> dict[str, Any]:
    geo = ", ".join(x for x in [v.geo_city, v.geo_country] if x)
    is_guest = v.user_id is None
    slug = _game_slug_from_path(v.path)
    duration_sec = None
    if db and v.visitor_key and v.visited_at:
        duration_sec = session_duration_at(db, v.visitor_key, v.visited_at)
    duration_label = format_duration(duration_sec) if duration_sec is not None else None
    who = display_session_who(
        user_id=v.user_id,
        user_email=v.user.email if v.user else None,
        client_agent=v.client_agent,
    )
    if slug:
        title = (game_titles or {}).get(slug) or slug.replace("-", " ")
        detail = " · ".join(x for x in [who, title, geo] if x)
        return {
            "kind": "game",
            "id": f"v{v.id}",
            "at": _iso(v.visited_at),
            "path": v.path,
            "geo": geo or None,
            "user": v.user.email if v.user else None,
            "guest": is_guest,
            "agent": (v.client_agent or "").lower() or None,
            "game_slug": slug,
            "game_title": title,
            "session_duration_sec": duration_sec,
            "session_duration_label": duration_label,
            "label": "Вибрав гру",
            "detail": detail or title,
        }
    detail_parts = [who]
    if geo:
        detail_parts.append(geo)
    if v.path:
        detail_parts.append(v.path)
    return {
        "kind": "visit",
        "id": f"v{v.id}",
        "at": _iso(v.visited_at),
        "path": v.path,
        "geo": geo or None,
        "user": v.user.email if v.user else None,
        "guest": is_guest,
        "agent": (v.client_agent or "").lower() or None,
        "session_duration_sec": duration_sec,
        "session_duration_label": duration_label,
        "label": who,
        "detail": " · ".join(detail_parts) or (v.path or "/"),
    }


def _click_item(c: AffiliateClick, *, db: Session | None = None) -> dict[str, Any]:
    price = f"{c.price_pln:.0f} zł" if c.price_pln is not None else ""
    detail = " · ".join(x for x in [c.shop_name, c.game_title, price] if x)
    duration_sec = None
    if db and c.visitor_key and c.clicked_at:
        duration_sec = session_duration_at(db, c.visitor_key, c.clicked_at)
    duration_label = format_duration(duration_sec) if duration_sec is not None else None
    return {
        "kind": "click",
        "id": f"c{c.id}",
        "at": _iso(c.clicked_at),
        "shop": c.shop_name,
        "game_title": c.game_title,
        "game_slug": c.game_slug,
        "price_pln": c.price_pln,
        "has_tracking": bool(c.has_tracking),
        "session_duration_sec": duration_sec,
        "session_duration_label": duration_label,
        "label": "Перейшов",
        "detail": detail or c.shop_name or "—",
    }


def _user_item(u: User) -> dict[str, Any]:
    return {
        "kind": "signup",
        "id": f"u{u.id}",
        "at": _iso(u.created_at),
        "email": u.email,
        "label": "Реєстрація",
        "detail": u.email or "—",
    }


def collect_live_dashboard(db: Session) -> dict[str, Any]:
    now = datetime.utcnow()
    since_5m = now - timedelta(minutes=5)
    since_15m = now - timedelta(minutes=15)
    since_1h = now - timedelta(hours=1)
    since_24h = now - timedelta(hours=24)
    since_7d = now - timedelta(days=7)
    human_filter = SiteVisit.is_suspected_bot.is_(False)
    bot_filter = SiteVisit.is_suspected_bot.is_(True)

    def visit_counts(since: datetime, *, bots: bool = False) -> tuple[int, int]:
        views = (
            db.query(func.count(SiteVisit.id))
            .filter(SiteVisit.visited_at >= since)
            .filter(bot_filter if bots else human_filter)
            .scalar()
            or 0
        )
        unique = (
            db.query(func.count(func.distinct(SiteVisit.visitor_key)))
            .filter(SiteVisit.visited_at >= since)
            .filter(bot_filter if bots else human_filter)
            .scalar()
            or 0
        )
        return int(views), int(unique)

    v5, u5 = visit_counts(since_5m)
    v15, u15 = visit_counts(since_15m)
    v1h, u1h = visit_counts(since_1h)
    v24, u24 = visit_counts(since_24h)
    cv5, cu5 = visit_counts(since_5m, bots=True)
    cv15, cu15 = visit_counts(since_15m, bots=True)
    cv1h, cu1h = visit_counts(since_1h, bots=True)
    cv24, cu24 = visit_counts(since_24h, bots=True)

    clicks_5m = (
        db.query(func.count(AffiliateClick.id))
        .filter(AffiliateClick.clicked_at >= since_5m)
        .scalar()
        or 0
    )
    clicks_15m = (
        db.query(func.count(AffiliateClick.id))
        .filter(AffiliateClick.clicked_at >= since_15m)
        .scalar()
        or 0
    )
    clicks_24h = (
        db.query(func.count(AffiliateClick.id))
        .filter(AffiliateClick.clicked_at >= since_24h)
        .scalar()
        or 0
    )
    tracked_24h = (
        db.query(func.count(AffiliateClick.id))
        .filter(
            AffiliateClick.clicked_at >= since_24h,
            AffiliateClick.has_tracking.is_(True),
        )
        .scalar()
        or 0
    )

    users_total = db.query(func.count(User.id)).scalar() or 0
    signups_7d = (
        db.query(func.count(User.id)).filter(User.created_at >= since_7d).scalar() or 0
    )
    signups_24h = (
        db.query(func.count(User.id)).filter(User.created_at >= since_24h).scalar() or 0
    )
    users_online = (
        db.query(func.count(User.id)).filter(User.last_seen_at >= since_15m).scalar() or 0
    )

    visit_rows = (
        db.query(SiteVisit)
        .options(joinedload(SiteVisit.user))
        .filter(human_filter)
        .order_by(SiteVisit.id.desc())
        .limit(20)
        .all()
    )
    game_slugs = {
        slug
        for v in visit_rows
        if (slug := _game_slug_from_path(v.path))
    }
    game_titles = _game_titles_for_slugs(db, game_slugs)
    active_sessions = collect_active_sessions(db, now)
    click_rows = (
        db.query(AffiliateClick)
        .order_by(AffiliateClick.id.desc())
        .limit(20)
        .all()
    )
    user_rows = db.query(User).order_by(User.id.desc()).limit(12).all()

    feed: list[dict[str, Any]] = []
    for v in visit_rows:
        feed.append(_visit_item(v, game_titles, db=db))
    for c in click_rows:
        feed.append(_click_item(c, db=db))
    for u in user_rows:
        feed.append(_user_item(u))

    feed.sort(key=lambda x: x.get("at") or "", reverse=True)
    feed = feed[:12]

    active_now = v5 > 0 or clicks_5m > 0 or users_online > 0

    return {
        "server_time": _iso(now),
        "active_now": active_now,
        "kpis": {
            "visits_5m": v5,
            "unique_5m": u5,
            "visits_15m": v15,
            "unique_15m": u15,
            "visits_1h": v1h,
            "unique_1h": u1h,
            "visits_24h": v24,
            "unique_24h": u24,
            "crawler_visits_5m": cv5,
            "crawler_unique_5m": cu5,
            "crawler_visits_15m": cv15,
            "crawler_unique_15m": cu15,
            "crawler_visits_1h": cv1h,
            "crawler_unique_1h": cu1h,
            "crawler_visits_24h": cv24,
            "crawler_unique_24h": cu24,
            "clicks_5m": int(clicks_5m),
            "clicks_15m": int(clicks_15m),
            "clicks_24h": int(clicks_24h),
            "tracked_clicks_24h": int(tracked_24h),
            "users_online_15m": int(users_online),
            "users_total": int(users_total),
            "signups_24h": int(signups_24h),
            "signups_7d": int(signups_7d),
            "sessions_active": len(active_sessions),
        },
        "active_sessions": active_sessions,
        "feed": feed,
    }
