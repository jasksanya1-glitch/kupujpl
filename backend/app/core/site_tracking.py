"""Public page visit tracking for games admin panel3."""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
from datetime import datetime, timedelta
from typing import Any

import requests
from fastapi import Request
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.database import SessionLocal
from app.core.site_sessions import touch_site_session
from app.models.models import IpGeoCache, SiteVisit, User

_log = logging.getLogger("site_tracking")

VISIT_DEDUP_SECONDS = 45
RETENTION_DAYS = 7
GEO_CACHE_DAYS = 30

_SKIP_PREFIXES = (
    "/static/",
    "/api/",
    "/panel3",
    "/health",
    "/favicon",
    "/robots.txt",
)

_TRACK_EXACT = frozenset({
    "/login",
    "/register",
    "/forgot-password",
    "/reset-password",
    "/panel",
    "/regulamin",
    "/polityka-prywatnosci",
    "/kontakt",
    "/wsparcie",
    "/designs",
    "/layouts",
})

_BOT_RE = re.compile(r"bot|crawler|spider|slurp|curl/|wget|python-requests", re.I)
_KNOWN_CLIENT_AGENTS = frozenset({"cursor"})


def detect_client_agent(request: Request, declared: str | None = None) -> str | None:
    """Identify non-human clients (e.g. Cursor IDE browser) for live dashboard labels."""
    raw = (declared or "").strip().lower()
    if raw in _KNOWN_CLIENT_AGENTS:
        return raw
    hdr = (request.headers.get("x-kupujpl-agent") or request.headers.get("X-Kupujpl-Agent") or "").strip().lower()
    if hdr in _KNOWN_CLIENT_AGENTS:
        return hdr
    ua = request.headers.get("user-agent") or ""
    if re.search(r"\bCursor\b", ua):
        return "cursor"
    return None


def _client_ip(request: Request) -> str:
    cf = (request.headers.get("cf-connecting-ip") or request.headers.get("CF-Connecting-IP") or "").strip()
    if cf:
        return cf
    xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    xri = (request.headers.get("x-real-ip") or request.headers.get("X-Real-IP") or "").strip()
    if xri:
        return xri
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _visitor_key(request: Request) -> str:
    ip = _client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:120]
    return hashlib.sha256(f"{ip}|{ua}".encode()).hexdigest()[:24]


def _ip_hash(ip: str) -> str:
    return hashlib.sha256(ip.strip().encode()).hexdigest()[:24]


def _is_public_ip(ip: str) -> bool:
    if not ip or ip == "unknown":
        return False
    try:
        addr = ipaddress.ip_address(ip)
        return not (addr.is_private or addr.is_loopback or addr.is_reserved)
    except ValueError:
        return False


def _geo_from_headers(request: Request) -> tuple[str | None, str | None, str | None]:
    """Prefer Cloudflare geo headers (more accurate than IP-API for PL)."""
    city = (request.headers.get("cf-ipcity") or request.headers.get("CF-IPCity") or "").strip()
    cc = (request.headers.get("cf-ipcountry") or request.headers.get("CF-IPCountry") or "").strip().upper()
    if not city and not cc:
        return None, None, None
    country_names = {"PL": "Polska", "UA": "Ukraina", "DE": "Niemcy", "CZ": "Czechy", "SK": "Słowacja"}
    country_name = country_names.get(cc, cc) if cc else None
    return city or None, country_name, cc or None


def resolve_geo(db: Session, ip: str, request: Request | None = None) -> tuple[str | None, str | None, str | None]:
    if request is not None:
        from_headers = _geo_from_headers(request)
        if from_headers[0] or from_headers[2]:
            if _is_public_ip(ip):
                ip_h = _ip_hash(ip)
                try:
                    row = db.query(IpGeoCache).filter(IpGeoCache.ip_hash == ip_h).first()
                    now = datetime.utcnow()
                    city, country_name, country_code = from_headers
                    if row:
                        row.city = city
                        row.country_code = country_code
                        row.country_name = country_name
                        row.fetched_at = now
                    else:
                        db.add(
                            IpGeoCache(
                                ip_hash=ip_h,
                                city=city,
                                country_code=country_code,
                                country_name=country_name,
                                fetched_at=now,
                            )
                        )
                    db.commit()
                except Exception:
                    db.rollback()
            return from_headers

    if not _is_public_ip(ip):
        return None, None, None
    ip_h = _ip_hash(ip)
    cutoff = datetime.utcnow() - timedelta(days=GEO_CACHE_DAYS)
    cached = db.query(IpGeoCache).filter(IpGeoCache.ip_hash == ip_h).first()
    if cached and cached.fetched_at >= cutoff:
        return cached.city, cached.country_name, cached.country_code

    city = country_name = country_code = None
    try:
        r = requests.get(
            f"http://ip-api.com/json/{ip}",
            params={"fields": "status,country,countryCode,city", "lang": "pl"},
            timeout=3,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success":
                city = (data.get("city") or "").strip() or None
                country_name = (data.get("country") or "").strip() or None
                country_code = (data.get("countryCode") or "").strip().upper() or None
    except Exception as exc:
        _log.debug("geo lookup failed: %s", exc)

    try:
        row = db.query(IpGeoCache).filter(IpGeoCache.ip_hash == ip_h).first()
        now = datetime.utcnow()
        if row:
            row.city = city
            row.country_code = country_code
            row.country_name = country_name
            row.fetched_at = now
        else:
            db.add(
                IpGeoCache(
                    ip_hash=ip_h,
                    city=city,
                    country_code=country_code,
                    country_name=country_name,
                    fetched_at=now,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
    return city, country_name, country_code


_CLIENT_TRACKED_PATHS = frozenset({"/panel"})


def _normalize_track_path(path: str) -> str:
    p = (path or "/").strip().split("?")[0]
    if p.startswith("/games"):
        p = p[6:] or "/"
    if not p.startswith("/"):
        p = f"/{p}"
    return p[:480]


def should_track_visit(request: Request) -> bool:
    if request.method != "GET":
        return False
    path = _normalize_track_path(request.url.path or "")
    if not path:
        return False
    if path in _CLIENT_TRACKED_PATHS:
        return False
    for skip in _SKIP_PREFIXES:
        if path == skip or path.startswith(skip):
            return False
    ua = request.headers.get("user-agent") or ""
    if _BOT_RE.search(ua):
        return False
    return path in _TRACK_EXACT


def record_site_visit(
    request: Request,
    user_id: int | None = None,
    *,
    path: str | None = None,
    force: bool = False,
    utm_source: str | None = None,
    utm_medium: str | None = None,
    utm_campaign: str | None = None,
    client_agent: str | None = None,
) -> None:
    if not force and path is None and not should_track_visit(request):
        return
    visit_path = _normalize_track_path(path or request.url.path or "/")
    vkey = _visitor_key(request)
    ip = _client_ip(request)
    now = datetime.utcnow()
    agent = detect_client_agent(request, client_agent)
    db = SessionLocal()
    try:
        if user_id:
            guest_hit = (
                db.query(SiteVisit)
                .filter(
                    SiteVisit.visitor_key == vkey,
                    SiteVisit.user_id.is_(None),
                    SiteVisit.visited_at >= now - timedelta(seconds=VISIT_DEDUP_SECONDS),
                )
                .order_by(SiteVisit.visited_at.desc())
                .first()
            )
            if guest_hit:
                guest_hit.user_id = user_id
                if force and visit_path and guest_hit.path != visit_path:
                    guest_hit.path = visit_path
                touch_site_session(
                    db, request, user_id, path=visit_path, count_page_view=False, client_agent=agent
                )
                db.commit()
                return

        recent = (
            db.query(SiteVisit.id)
            .filter(
                SiteVisit.visitor_key == vkey,
                SiteVisit.path == visit_path,
                SiteVisit.visited_at >= now - timedelta(seconds=VISIT_DEDUP_SECONDS),
            )
            .first()
        )
        if recent:
            touch_site_session(
                db, request, user_id, path=visit_path, count_page_view=False, client_agent=agent
            )
            db.commit()
            return
        geo_city, geo_country, geo_cc = resolve_geo(db, ip, request)
        db.add(
            SiteVisit(
                visited_at=now,
                path=visit_path,
                visitor_key=vkey,
                user_id=user_id,
                utm_source=(utm_source or "")[:64] or None,
                utm_medium=(utm_medium or "")[:64] or None,
                utm_campaign=(utm_campaign or "")[:128] or None,
                geo_city=geo_city,
                geo_country=geo_country,
                geo_country_code=geo_cc,
                client_agent=agent,
            )
        )
        touch_site_session(
            db, request, user_id, path=visit_path, count_page_view=True, client_agent=agent
        )
        db.commit()
        if now.hour == 0 and now.minute < 5:
            cutoff = now - timedelta(days=RETENTION_DAYS)
            db.query(SiteVisit).filter(SiteVisit.visited_at < cutoff).delete(
                synchronize_session=False
            )
            db.commit()
    except Exception as exc:
        db.rollback()
        _log.debug("record_site_visit failed: %s", exc)
    finally:
        db.close()


def record_session_heartbeat(
    request: Request,
    user_id: int | None = None,
    *,
    path: str | None = None,
    client_agent: str | None = None,
) -> None:
    visit_path = _normalize_track_path(path or "/")
    agent = detect_client_agent(request, client_agent)
    db = SessionLocal()
    try:
        touch_site_session(
            db, request, user_id, path=visit_path, count_page_view=False, client_agent=agent
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        _log.debug("record_session_heartbeat failed: %s", exc)
    finally:
        db.close()


def touch_user_last_seen(user_id: int) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return
        now = datetime.utcnow()
        if user.last_seen_at and (now - user.last_seen_at).total_seconds() < 120:
            return
        user.last_seen_at = now
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def collect_traffic_stats(db: Session) -> dict[str, Any]:
    now = datetime.utcnow()
    since_15m = now - timedelta(minutes=15)
    since_1h = now - timedelta(hours=1)
    since_24h = now - timedelta(hours=24)

    def _counts(since: datetime) -> tuple[int, int]:
        views = db.query(SiteVisit).filter(SiteVisit.visited_at >= since).count()
        unique = (
            db.query(func.count(func.distinct(SiteVisit.visitor_key)))
            .filter(SiteVisit.visited_at >= since)
            .scalar()
            or 0
        )
        return int(views), int(unique)

    v15, u15 = _counts(since_15m)
    v1h, u1h = _counts(since_1h)
    v24, u24 = _counts(since_24h)
    views_all = db.query(SiteVisit).count()
    unique_all = db.query(func.count(func.distinct(SiteVisit.visitor_key))).scalar() or 0

    def _auth_views(since: datetime) -> tuple[int, int]:
        q = db.query(SiteVisit).filter(SiteVisit.visited_at >= since)
        registered = q.filter(SiteVisit.user_id.isnot(None)).count()
        guest = q.filter(SiteVisit.user_id.is_(None)).count()
        return int(registered), int(guest)

    reg_15m, guest_15m = _auth_views(since_15m)
    reg_24h, guest_24h = _auth_views(since_24h)

    recent_rows = (
        db.query(SiteVisit)
        .options(joinedload(SiteVisit.user))
        .order_by(SiteVisit.visited_at.desc())
        .limit(10)
        .all()
    )
    recent = []
    for v in recent_rows:
        geo = ", ".join(x for x in [v.geo_city, v.geo_country] if x)
        recent.append(
            {
                "at": v.visited_at.isoformat() + "Z",
                "path": v.path,
                "geo": geo or None,
                "user": v.user.email if v.user else None,
                "guest": v.user_id is None,
                "agent": (v.client_agent or "").lower() or None,
            }
        )

    top_paths = (
        db.query(SiteVisit.path, func.count(SiteVisit.id))
        .filter(SiteVisit.visited_at >= since_24h)
        .group_by(SiteVisit.path)
        .order_by(func.count(SiteVisit.id).desc())
        .limit(8)
        .all()
    )

    utm_rows = (
        db.query(SiteVisit.utm_source, func.count(SiteVisit.id))
        .filter(SiteVisit.visited_at >= since_24h, SiteVisit.utm_source.isnot(None))
        .group_by(SiteVisit.utm_source)
        .order_by(func.count(SiteVisit.id).desc())
        .limit(10)
        .all()
    )

    return {
        "views_15m": v15,
        "unique_15m": u15,
        "views_1h": v1h,
        "unique_1h": u1h,
        "views_24h": v24,
        "unique_24h": u24,
        "views_all": int(views_all),
        "unique_all": int(unique_all),
        "registered_views_15m": reg_15m,
        "guest_views_15m": guest_15m,
        "registered_views_24h": reg_24h,
        "guest_views_24h": guest_24h,
        "recent": recent,
        "top_paths": [{"path": p, "count": int(c)} for p, c in top_paths],
        "utm_sources_24h": [{"source": s or "direct", "count": int(c)} for s, c in utm_rows],
    }
