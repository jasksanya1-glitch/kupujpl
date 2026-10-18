"""Offer verification semantics (Scanner Reliability V2).

Separates attempt / verified / price-change timestamps and check status.
Controlled by SCAN_V2_VERIFICATION (default on when SCAN_V2=1).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Literal

from app.models.models import Offer

CheckStatus = Literal[
    "verified",
    "unavailable",  # product known / matched but explicitly out of stock
    "not_found",  # search completed; no matching product (≠ HTTP failure)
    "rate_limited",
    "auth_failed",
    "blocked",
    "timeout",
    "error",  # transport / parse failure — not proof of OOS
    "skipped",
]

VALID_STATUSES: frozenset[str] = frozenset(
    {
        "verified",
        "unavailable",
        "not_found",
        "rate_limited",
        "auth_failed",
        "blocked",
        "timeout",
        "error",
        "skipped",
    }
)

# Only explicit OOS evidence may flip in_stock=False on a previously verified offer.
# Search miss (not_found) is negative-cache only — never definitive unavailability.
OOS_LIKE_STATUSES: frozenset[str] = frozenset({"unavailable"})

# Transient / infra failures — must not invent product unavailability.
TRANSIENT_MISS_STATUSES: frozenset[str] = frozenset(
    {"error", "timeout", "rate_limited", "auth_failed", "blocked"}
)

# Search completed without a match — backoff only; do not OOS prior verified stock.
SEARCH_MISS_STATUSES: frozenset[str] = frozenset({"not_found"})


def scan_v2_enabled() -> bool:
    return os.environ.get("SCAN_V2", "1").strip().lower() not in {"0", "false", "no"}


def scan_v2_verification_enabled() -> bool:
    if not scan_v2_enabled():
        return False
    raw = os.environ.get("SCAN_V2_VERIFICATION", "1").strip().lower()
    return raw not in {"0", "false", "no"}


def scan_v2_display_dry_run() -> bool:
    """When true, compute display stale stats but do not hide offers."""
    if not scan_v2_enabled():
        return False
    raw = os.environ.get("SCAN_V2_DISPLAY_DRY_RUN", "1").strip().lower()
    return raw not in {"0", "false", "no"}


def scan_v2_independent_workers() -> bool:
    if not scan_v2_enabled():
        return False
    raw = os.environ.get("SCAN_V2_INDEPENDENT_WORKERS", "1").strip().lower()
    return raw not in {"0", "false", "no"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def verification_timestamp(offer: Offer | None) -> datetime | None:
    """Timestamp used for verified-freshness metrics.

    Prefer last_verified_at when V2 columns are populated; never treat a failed
    attempt's updated_at as verification.
    """
    if offer is None:
        return None
    if scan_v2_verification_enabled():
        verified = getattr(offer, "last_verified_at", None)
        if verified is not None:
            return verified
        # Legacy rows: only trust updated_at when status is verified or unset
        # (pre-migration). Do not invent historical verifications.
        status = getattr(offer, "last_check_status", None)
        if status in (None, "", "verified"):
            return offer.updated_at
        return None
    return offer.updated_at


def record_attempt(
    offer: Offer,
    *,
    status: CheckStatus,
    source: str | None = None,
    now: datetime | None = None,
) -> None:
    """Record a check attempt. Never sets last_verified_at on failure.

    Also freezes ``updated_at`` so SQLAlchemy ``onupdate`` cannot artificially
    extend freshness after a search miss / timeout / error.
    """
    if status not in VALID_STATUSES:
        status = "error"
    ts = now or _utcnow()
    # Capture before mutating other columns (ORM onupdate would otherwise bump it).
    prev_updated = getattr(offer, "updated_at", None)
    if hasattr(offer, "last_attempt_at"):
        offer.last_attempt_at = ts
    if hasattr(offer, "last_check_status"):
        offer.last_check_status = status
    if source and hasattr(offer, "price_source"):
        # Only stamp source on successful verify; attempts may pass hint.
        if status == "verified":
            offer.price_source = source[:64]
    if prev_updated is not None and hasattr(offer, "updated_at"):
        offer.updated_at = prev_updated


def record_verified_price(
    offer: Offer,
    *,
    price_pln: float,
    source: str,
    previous_price: float | None = None,
    now: datetime | None = None,
) -> bool:
    """Mark a successful price verification. Returns True if price changed.

    Refuses out-of-order writes: if ``now`` is older than the offer's current
    ``last_verified_at``, leave the row unchanged (no timestamp / price clobber).
    """
    ts = now or _utcnow()
    existing_verified = getattr(offer, "last_verified_at", None)
    if existing_verified is not None and ts < existing_verified:
        return False
    changed = previous_price is None or abs(float(previous_price) - float(price_pln)) > 1e-6
    offer.price_pln = price_pln
    offer.in_stock = True
    offer.updated_at = ts
    if hasattr(offer, "last_attempt_at"):
        offer.last_attempt_at = ts
    if hasattr(offer, "last_verified_at"):
        offer.last_verified_at = ts
    if hasattr(offer, "last_check_status"):
        offer.last_check_status = "verified"
    if hasattr(offer, "price_source"):
        offer.price_source = (source or "unknown")[:64]
    if changed and hasattr(offer, "last_price_changed_at"):
        offer.last_price_changed_at = ts
    return changed


def _affiliate_cache_usable(shop: str) -> bool:
    """True when an on-disk affiliate feed cache has at least one product row."""
    try:
        from app.parsers import affiliate_feeds as af

        cache = af._cache_path(shop)
        if not cache.is_file():
            return False
        return len(af._read_cache_rows(shop)) > 0
    except Exception:
        return False


def shop_data_source_status(shop: str) -> dict[str, Any]:
    """Per-source diagnostics for admin UI (never includes secrets)."""
    out: dict[str, Any] = {
        "shop": shop,
        "primary": None,
        "fallback": None,
        "block_scan": False,
        "block_reason": None,
        "owner_action": None,
    }
    try:
        from app.parsers import affiliate_feeds as af

        if shop == "Fanatical":
            out["primary"] = "awin_feed"
            out["fallback"] = None
            if af._feed_fail_active(shop):
                out["block_scan"] = True
                out["block_reason"] = "Fanatical affiliate feed in negative cache"
                out["owner_action"] = (
                    "Wait for backoff or refresh Awin Fanatical feed / FID"
                )
                return out
            if _affiliate_cache_usable(shop):
                return out
            _url, reason = af._resolve_download_url(shop)
            out["block_scan"] = True
            out["block_reason"] = f"Fanatical affiliate feed unavailable ({reason})"
            if not af._awin_api_key():
                out["owner_action"] = (
                    "Set AWIN_DATAFEED_API_KEY in backend .env, then join Fanatical "
                    "and set AWIN_FEED_FID_FANATICAL from Awin Product Feed List"
                )
            elif reason.startswith("not_joined"):
                out["owner_action"] = (
                    "Join Fanatical (MID 118821) in Awin → wait for approval → "
                    "set AWIN_FEED_FID_FANATICAL from Product Feed List"
                )
            elif "no_fid" in reason or reason.startswith("awin_mid"):
                out["owner_action"] = (
                    "From Awin Product Feed List, copy the Fanatical Feed ID into "
                    "AWIN_FEED_FID_FANATICAL (never invent FIDs)"
                )
            else:
                last = af._last_download_errors.get(shop) or ""
                try:
                    marker = af._fail_marker_path(shop)
                    if marker.is_file():
                        last = last or marker.read_text(encoding="utf-8")[:300]
                except OSError:
                    pass
                # FID is configured (awin_fid_*) but no usable cache → download failed.
                if (
                    "Feed not found" in last
                    or "404" in last
                    or str(reason).startswith("awin_fid_")
                ):
                    out["block_reason"] = (
                        "Fanatical Awin Feed ID invalid/expired (download 404 / no cache)"
                    )
                    out["owner_action"] = (
                        "In Awin → Tools → Product Feeds, open Fanatical, copy the "
                        "current Feed ID into AWIN_FEED_FID_FANATICAL; confirm the "
                        "DataFeed API key can list feeds (catalog must not return 401)"
                    )
                else:
                    out["owner_action"] = (
                        "Verify Awin Fanatical program join + valid Feed ID; "
                        "ensure DataFeed API key is authorized for feed list/download"
                    )
            return out

        if shop == "Kinguin":
            out["primary"] = "awin_feed"
            out["fallback"] = "html_search"
            # HTML fallback is authorized — never pause the whole shop on feed fail.
            feed_ok = _affiliate_cache_usable(shop) and not af._feed_fail_active(shop)
            out["feed_ok"] = feed_ok
            out["html_fallback"] = True
            if not feed_ok:
                out["degraded_reason"] = "Awin feed unavailable; HTML search active"
            return out

        if shop == "CDKeys":
            out["primary"] = "algolia"
            out["fallback"] = "awin_feed" if af._merchant_id(shop) or af._custom_feed_urls(shop) else None
            from app.parsers import cdkeys_parser as cd

            algolia_ok = bool(cd._get_algolia_api_key())
            feed_ok = _affiliate_cache_usable(shop)
            out["algolia_ok"] = algolia_ok
            out["feed_ok"] = feed_ok
            if algolia_ok or feed_ok:
                if not algolia_ok and feed_ok:
                    out["degraded_reason"] = "Algolia key missing; affiliate feed active"
                return out
            out["block_scan"] = True
            out["block_reason"] = "CDKeys Algolia key missing/expired (no feed cache)"
            out["owner_action"] = (
                "Set CDKEYS_ALGOLIA_API_KEY to a fresh search-only key from "
                "cdkeys.com/loaded.com frontend, or provide AWIN_FEED_FID_CDKEYS / "
                "AFFILIATE_FEED_URL_CDKEYS partner feed"
            )
            return out
    except Exception as exc:
        out["block_scan"] = True
        out["block_reason"] = f"{shop} data-source check error: {exc}"[:160]
    return out


def shop_auth_blocker(shop: str) -> str | None:
    """Return auth_failed reason if shop cannot be scanned usefully right now.

    Shops with an authorized fallback (e.g. Kinguin HTML) must return None even
    when an optional feed is down — admin UI uses shop_data_source_status for
    DEGRADED vs AUTH_REQUIRED.
    """
    status = shop_data_source_status(shop)
    if status.get("block_scan"):
        return str(status.get("block_reason") or f"{shop} auth required")[:200]
    return None


def display_freshness_dry_run_stats(db: Any, *, hours: float = 48.0) -> dict[str, Any]:
    """Report how many in-stock offers would be marked stale (no UI mutation)."""
    from datetime import timedelta

    from sqlalchemy import func

    cutoff = _utcnow() - timedelta(hours=hours)
    q = db.query(Offer).filter(Offer.in_stock.is_(True))
    total = q.count()
    # Prefer last_verified_at when present; else updated_at (legacy).
    if scan_v2_verification_enabled():
        from sqlalchemy import and_, or_

        stale = (
            db.query(func.count(Offer.id))
            .filter(
                Offer.in_stock.is_(True),
                or_(
                    and_(Offer.last_verified_at.isnot(None), Offer.last_verified_at < cutoff),
                    and_(
                        Offer.last_verified_at.is_(None),
                        or_(Offer.updated_at.is_(None), Offer.updated_at < cutoff),
                    ),
                ),
            )
            .scalar()
            or 0
        )
    else:
        stale = (
            db.query(func.count(Offer.id))
            .filter(
                Offer.in_stock.is_(True),
                (Offer.updated_at.is_(None)) | (Offer.updated_at < cutoff),
            )
            .scalar()
            or 0
        )
    return {
        "dry_run": True,
        "hide_enabled": False,
        "stale_hours": hours,
        "in_stock_total": total,
        "would_mark_stale": stale,
        "would_mark_stale_pct": round(100.0 * stale / total, 2) if total else 0.0,
        "note": "Report-only; public catalog unchanged",
    }
