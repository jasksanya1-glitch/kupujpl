"""Live session duration tracking (heartbeat + page views)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import distinct
from sqlalchemy.orm import Session, joinedload

from app.models.models import SiteSession, SiteVisit

SESSION_IDLE_SEC = 300
SESSION_ACTIVE_SEC = 120
SESSION_RETENTION_DAYS = 7


def format_duration(sec: int | None) -> str:
    if sec is None or sec < 0:
        return "—"
    sec = int(sec)
    if sec < 60:
        return f"{sec}с"
    if sec < 3600:
        m, s = divmod(sec, 60)
        return f"{m}хв {s}с" if s else f"{m}хв"
    h, rem = divmod(sec, 3600)
    m = rem // 60
    return f"{h}г {m}хв" if m else f"{h}г"


def display_session_who(
    *,
    user_id: int | None,
    user_email: str | None = None,
    client_agent: str | None = None,
) -> str:
    if user_id and user_email:
        return user_email
    if user_id:
        return "Користувач"
    if (client_agent or "").lower() == "cursor":
        return "Cursor"
    return "Гість"


def touch_site_session(
    db: Session,
    request: Request,
    user_id: int | None = None,
    *,
    path: str | None = None,
    count_page_view: bool = False,
    client_agent: str | None = None,
) -> SiteSession | None:
    from app.core.site_tracking import _client_ip, _normalize_track_path, _visitor_key, resolve_geo

    visit_path = _normalize_track_path(path or request.url.path or "/")
    vkey = _visitor_key(request)
    ip = _client_ip(request)
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=SESSION_IDLE_SEC)
    agent = (client_agent or "").strip().lower() or None

    session = (
        db.query(SiteSession)
        .filter(
            SiteSession.visitor_key == vkey,
            SiteSession.last_active_at >= cutoff,
        )
        .order_by(SiteSession.last_active_at.desc())
        .first()
    )

    if session:
        session.last_active_at = now
        session.last_path = visit_path
        if user_id and not session.user_id:
            session.user_id = user_id
        if agent and not session.client_agent:
            session.client_agent = agent
        if count_page_view:
            session.page_views = int(session.page_views or 0) + 1
    else:
        geo_city, geo_country, _ = resolve_geo(db, ip, request)
        session = SiteSession(
            visitor_key=vkey,
            user_id=user_id,
            started_at=now,
            last_active_at=now,
            last_path=visit_path,
            page_views=1 if count_page_view else 0,
            geo_city=geo_city,
            geo_country=geo_country,
            client_agent=agent,
        )
        db.add(session)

    if now.hour == 0 and now.minute < 5:
        prune_old = now - timedelta(days=SESSION_RETENTION_DAYS)
        db.query(SiteSession).filter(SiteSession.started_at < prune_old).delete(
            synchronize_session=False
        )

    return session


def session_duration_at(db: Session, visitor_key: str, at: datetime) -> int | None:
    if not visitor_key or not at:
        return None
    cutoff = at - timedelta(seconds=SESSION_IDLE_SEC)
    session = (
        db.query(SiteSession)
        .filter(
            SiteSession.visitor_key == visitor_key,
            SiteSession.started_at <= at,
            SiteSession.last_active_at >= cutoff,
        )
        .order_by(SiteSession.started_at.desc())
        .first()
    )
    if not session:
        return None
    return max(0, int((at - session.started_at).total_seconds()))


def collect_active_sessions(db: Session, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.utcnow()
    active_cutoff = now - timedelta(seconds=SESSION_ACTIVE_SEC)
    bot_keys = {
        key
        for (key,) in (
            db.query(distinct(SiteVisit.visitor_key))
            .filter(
                SiteVisit.visited_at >= active_cutoff,
                SiteVisit.is_suspected_bot.is_(True),
            )
            .all()
        )
        if key
    }
    rows = (
        db.query(SiteSession)
        .options(joinedload(SiteSession.user))
        .filter(SiteSession.last_active_at >= active_cutoff)
        .order_by(SiteSession.last_active_at.desc())
        .limit(12)
        .all()
    )
    out: list[dict[str, Any]] = []
    for s in rows:
        if s.visitor_key in bot_keys and (s.client_agent or "").lower() != "cursor":
            continue
        duration = max(0, int((now - s.started_at).total_seconds()))
        geo = ", ".join(x for x in [s.geo_city, s.geo_country] if x)
        who = display_session_who(
            user_id=s.user_id,
            user_email=s.user.email if s.user else None,
            client_agent=s.client_agent,
        )
        out.append(
            {
                "id": f"s{s.id}",
                "visitor_key": s.visitor_key,
                "who": who,
                "guest": s.user_id is None,
                "agent": (s.client_agent or "").lower() or None,
                "geo": geo or None,
                "path": s.last_path,
                "started_at": s.started_at.isoformat() + "Z",
                "last_active_at": s.last_active_at.isoformat() + "Z",
                "duration_sec": duration,
                "duration_label": format_duration(duration),
                "page_views": int(s.page_views or 0),
            }
        )
    return out
