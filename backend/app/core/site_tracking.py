"""Public page visit tracking for games admin panel3."""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlparse

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
_HEADLESS_UA_RE = re.compile(r"headless|puppeteer|playwright|selenium", re.I)
_BOT_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("meta-externalagent", "meta_externalagent"),
    ("facebookexternalhit", "facebookexternalhit"),
    ("semrush", "semrush"),
    ("bytespider", "bytespider"),
    ("ahrefsbot", "ahrefsbot"),
    ("mj12bot", "mj12bot"),
    ("dotbot", "dotbot"),
    ("petalbot", "petalbot"),
    ("bingbot", "bingbot"),
    ("googlebot", "googlebot"),
)


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


def _clean(value: str | None, limit: int) -> str | None:
    val = (value or "").strip()
    if not val:
        return None
    return val[:limit]


def _query_overrides_from_path(raw_path: str | None) -> dict[str, str]:
    if not raw_path or "?" not in raw_path:
        return {}
    query = raw_path.split("?", 1)[1]
    try:
        return {
            k: v
            for k, v in parse_qsl(query, keep_blank_values=False)
            if k and v
        }
    except Exception:
        return {}


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def _request_marketing_values(
    request: Request,
    raw_path: str | None,
    *,
    utm_source: str | None,
    utm_medium: str | None,
    utm_campaign: str | None,
    utm_term: str | None,
    utm_content: str | None,
    gclid: str | None,
    wbraid: str | None,
    gbraid: str | None,
    referrer_url: str | None,
) -> dict[str, str | None]:
    from_path = _query_overrides_from_path(raw_path)
    req_qs = request.query_params
    ref_url = _first_non_empty(
        referrer_url,
        request.headers.get("x-original-referer"),
        request.headers.get("referer"),
    )
    ref_host = None
    if ref_url:
        try:
            ref_host = (urlparse(ref_url).hostname or "").strip().lower() or None
        except Exception:
            ref_host = None
    return {
        "utm_source": _clean(
            _first_non_empty(utm_source, from_path.get("utm_source"), req_qs.get("utm_source")),
            64,
        ),
        "utm_medium": _clean(
            _first_non_empty(utm_medium, from_path.get("utm_medium"), req_qs.get("utm_medium")),
            64,
        ),
        "utm_campaign": _clean(
            _first_non_empty(
                utm_campaign,
                from_path.get("utm_campaign"),
                req_qs.get("utm_campaign"),
            ),
            128,
        ),
        "utm_term": _clean(
            _first_non_empty(utm_term, from_path.get("utm_term"), req_qs.get("utm_term")),
            128,
        ),
        "utm_content": _clean(
            _first_non_empty(
                utm_content,
                from_path.get("utm_content"),
                req_qs.get("utm_content"),
            ),
            128,
        ),
        "gclid": _clean(_first_non_empty(gclid, from_path.get("gclid"), req_qs.get("gclid")), 128),
        "wbraid": _clean(
            _first_non_empty(wbraid, from_path.get("wbraid"), req_qs.get("wbraid")),
            128,
        ),
        "gbraid": _clean(
            _first_non_empty(gbraid, from_path.get("gbraid"), req_qs.get("gbraid")),
            128,
        ),
        "referrer_url": _clean(ref_url, 700),
        "referrer_host": _clean(ref_host, 120),
    }


def _detect_bot_visit(
    request: Request,
    *,
    path: str,
    user_agent: str,
    client_agent: str | None,
) -> tuple[bool, str | None]:
    if client_agent in _KNOWN_CLIENT_AGENTS:
        return False, None
    lower_ua = (user_agent or "").lower()
    if not lower_ua:
        return True, "missing_user_agent"
    for token, reason in _BOT_SIGNATURES:
        if token in lower_ua:
            return True, reason
    if _HEADLESS_UA_RE.search(lower_ua):
        return True, "headless_ua"
    if _BOT_RE.search(lower_ua):
        return True, "generic_bot_ua"
    if request.method == "GET":
        accept = (request.headers.get("accept") or "").lower()
        if not accept:
            return True, "missing_accept"
        if "text/html" not in accept and "*/*" not in accept:
            return True, "non_html_accept"
        accept_lang = (request.headers.get("accept-language") or "").strip()
        if not accept_lang and path not in _TRACK_EXACT and not path.startswith("/gra/"):
            return True, "missing_accept_language"
    return False, None


def visitor_geo_hint(request: Request) -> dict[str, str | None]:
    """Lightweight geo for region UX (prefer CDN headers, else IP cache)."""
    city_h, country_h, cc_h = _geo_from_headers(request)
    if cc_h:
        return {
            "country_code": cc_h,
            "country": country_h,
            "city": city_h,
            "source": "cdn",
        }
    ip = _client_ip(request)
    db = SessionLocal()
    try:
        city, country, cc = resolve_geo(db, ip, request)
    finally:
        db.close()
    return {
        "country_code": (cc or "").upper() or None,
        "country": country,
        "city": city,
        "source": "ip",
    }


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
    if path in _TRACK_EXACT:
        return True
    # Full game pages + catalog root (SPA also pings /view/home via JS)
    if path == "/" or path.startswith("/gra/"):
        return True
    if path.startswith("/promocje") or path.startswith("/kategoria/"):
        return True
    return False


def record_site_visit(
    request: Request,
    user_id: int | None = None,
    *,
    path: str | None = None,
    force: bool = False,
    utm_source: str | None = None,
    utm_medium: str | None = None,
    utm_campaign: str | None = None,
    utm_term: str | None = None,
    utm_content: str | None = None,
    gclid: str | None = None,
    wbraid: str | None = None,
    gbraid: str | None = None,
    referrer_url: str | None = None,
    client_agent: str | None = None,
) -> None:
    if not force and path is None and not should_track_visit(request):
        return
    raw_path = path or request.url.path or "/"
    visit_path = _normalize_track_path(raw_path)
    vkey = _visitor_key(request)
    ip = _client_ip(request)
    now = datetime.utcnow()
    agent = detect_client_agent(request, client_agent)
    user_agent = _clean(request.headers.get("user-agent"), 480)
    marketing = _request_marketing_values(
        request,
        raw_path,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        utm_term=utm_term,
        utm_content=utm_content,
        gclid=gclid,
        wbraid=wbraid,
        gbraid=gbraid,
        referrer_url=referrer_url,
    )
    is_bot, bot_reason = _detect_bot_visit(
        request,
        path=visit_path,
        user_agent=user_agent or "",
        client_agent=agent,
    )
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
                utm_source=marketing["utm_source"],
                utm_medium=marketing["utm_medium"],
                utm_campaign=marketing["utm_campaign"],
                utm_term=marketing["utm_term"],
                utm_content=marketing["utm_content"],
                gclid=marketing["gclid"],
                wbraid=marketing["wbraid"],
                gbraid=marketing["gbraid"],
                referrer_host=marketing["referrer_host"],
                referrer_url=marketing["referrer_url"],
                geo_city=geo_city,
                geo_country=geo_country,
                geo_country_code=geo_cc,
                client_agent=agent,
                user_agent=user_agent,
                is_suspected_bot=is_bot,
                bot_reason=bot_reason,
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

    human_filter = (
        SiteVisit.is_suspected_bot.is_(False) | SiteVisit.is_suspected_bot.is_(None)
    )
    bot_filter = SiteVisit.is_suspected_bot.is_(True)

    def _counts(since: datetime, *, bots: bool = False) -> tuple[int, int]:
        base = db.query(SiteVisit).filter(SiteVisit.visited_at >= since)
        if bots:
            base = base.filter(bot_filter)
        else:
            base = base.filter(human_filter)
        views = base.count()
        unique = (
            db.query(func.count(func.distinct(SiteVisit.visitor_key)))
            .filter(SiteVisit.visited_at >= since)
            .filter(bot_filter if bots else human_filter)
            .scalar()
            or 0
        )
        return int(views), int(unique)

    v15, u15 = _counts(since_15m)
    v1h, u1h = _counts(since_1h)
    v24, u24 = _counts(since_24h)
    cv15, cu15 = _counts(since_15m, bots=True)
    cv1h, cu1h = _counts(since_1h, bots=True)
    cv24, cu24 = _counts(since_24h, bots=True)
    views_all = db.query(SiteVisit).filter(human_filter).count()
    unique_all = (
        db.query(func.count(func.distinct(SiteVisit.visitor_key)))
        .filter(human_filter)
        .scalar()
        or 0
    )
    crawler_views_all = db.query(SiteVisit).filter(bot_filter).count()
    crawler_unique_all = (
        db.query(func.count(func.distinct(SiteVisit.visitor_key)))
        .filter(bot_filter)
        .scalar()
        or 0
    )

    def _auth_views(since: datetime) -> tuple[int, int]:
        q = db.query(SiteVisit).filter(SiteVisit.visited_at >= since, human_filter)
        registered = q.filter(SiteVisit.user_id.isnot(None)).count()
        guest = q.filter(SiteVisit.user_id.is_(None)).count()
        return int(registered), int(guest)

    reg_15m, guest_15m = _auth_views(since_15m)
    reg_24h, guest_24h = _auth_views(since_24h)

    recent_rows = (
        db.query(SiteVisit)
        .options(joinedload(SiteVisit.user))
        .filter(human_filter)
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
        .filter(SiteVisit.visited_at >= since_24h, human_filter)
        .group_by(SiteVisit.path)
        .order_by(func.count(SiteVisit.id).desc())
        .limit(8)
        .all()
    )

    utm_rows = (
        db.query(SiteVisit.utm_source, func.count(SiteVisit.id))
        .filter(
            SiteVisit.visited_at >= since_24h,
            SiteVisit.utm_source.isnot(None),
            human_filter,
        )
        .group_by(SiteVisit.utm_source)
        .order_by(func.count(SiteVisit.id).desc())
        .limit(10)
        .all()
    )

    bot_reason_rows = (
        db.query(SiteVisit.bot_reason, func.count(SiteVisit.id))
        .filter(SiteVisit.visited_at >= since_24h, bot_filter)
        .group_by(SiteVisit.bot_reason)
        .order_by(func.count(SiteVisit.id).desc())
        .limit(8)
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
        "crawler_views_15m": cv15,
        "crawler_unique_15m": cu15,
        "crawler_views_1h": cv1h,
        "crawler_unique_1h": cu1h,
        "crawler_views_24h": cv24,
        "crawler_unique_24h": cu24,
        "crawler_views_all": int(crawler_views_all),
        "crawler_unique_all": int(crawler_unique_all),
        "registered_views_15m": reg_15m,
        "guest_views_15m": guest_15m,
        "registered_views_24h": reg_24h,
        "guest_views_24h": guest_24h,
        "recent": recent,
        "top_paths": [{"path": p, "count": int(c)} for p, c in top_paths],
        "utm_sources_24h": [{"source": s or "direct", "count": int(c)} for s, c in utm_rows],
        "crawler_reasons_24h": [
            {"reason": reason or "unknown", "count": int(count)}
            for reason, count in bot_reason_rows
        ],
    }
