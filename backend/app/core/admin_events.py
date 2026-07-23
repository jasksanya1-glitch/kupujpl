"""Lightweight admin event poll for panel3 live notifications."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.models.models import SiteVisit, User


def collect_admin_events(
    db: Session,
    last_user_id: int = 0,
    last_visit_id: int = 0,
) -> dict[str, Any]:
    last_user_id = max(0, int(last_user_id or 0))
    last_visit_id = max(0, int(last_visit_id or 0))

    user_rows = (
        db.query(User)
        .filter(User.id > last_user_id)
        .order_by(User.id.asc())
        .limit(25)
        .all()
    )
    visit_rows = (
        db.query(SiteVisit)
        .options(joinedload(SiteVisit.user))
        .filter(
            SiteVisit.id > last_visit_id,
            SiteVisit.is_suspected_bot.is_(False),
        )
        .order_by(SiteVisit.id.asc())
        .limit(25)
        .all()
    )

    max_user_id = last_user_id
    if user_rows:
        max_user_id = user_rows[-1].id
    else:
        latest = db.query(User.id).order_by(User.id.desc()).limit(1).scalar()
        if latest is not None:
            max_user_id = int(latest)

    max_visit_id = last_visit_id
    if visit_rows:
        max_visit_id = visit_rows[-1].id
    else:
        latest_v = db.query(SiteVisit.id).order_by(SiteVisit.id.desc()).limit(1).scalar()
        if latest_v is not None:
            max_visit_id = int(latest_v)

    users = [
        {
            "id": u.id,
            "email": u.email,
            "created_at": (u.created_at.isoformat() + "Z") if u.created_at else None,
        }
        for u in user_rows
    ]
    visits = []
    for v in visit_rows:
        geo = ", ".join(x for x in [v.geo_city, v.geo_country] if x)
        visits.append(
            {
                "id": v.id,
                "at": v.visited_at.isoformat() + "Z",
                "path": v.path,
                "geo": geo or None,
                "user": v.user.email if v.user else None,
                "guest": v.user_id is None,
                "agent": (v.client_agent or "").lower() or None,
            }
        )

    return {
        "users": users,
        "visits": visits,
        "max_user_id": max_user_id,
        "max_visit_id": max_visit_id,
    }
