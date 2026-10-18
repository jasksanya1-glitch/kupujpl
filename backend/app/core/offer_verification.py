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
    "unavailable",
    "rate_limited",
    "auth_failed",
    "blocked",
    "timeout",
    "error",
    "skipped",
]

VALID_STATUSES: frozenset[str] = frozenset(
    {
        "verified",
        "unavailable",
        "rate_limited",
        "auth_failed",
        "blocked",
        "timeout",
        "error",
        "skipped",
    }
)


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
    """Record a check attempt. Never sets last_verified_at on failure."""
    if status not in VALID_STATUSES:
        status = "error"
    ts = now or _utcnow()
    if hasattr(offer, "last_attempt_at"):
        offer.last_attempt_at = ts
    if hasattr(offer, "last_check_status"):
        offer.last_check_status = status
    if source and hasattr(offer, "price_source"):
        # Only stamp source on successful verify; attempts may pass hint.
        if status == "verified":
            offer.price_source = source[:64]


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


def shop_auth_blocker(shop: str) -> str | None:
    """Return auth_failed reason if shop cannot be scanned usefully right now."""
    if shop == "CDKeys":
        try:
            from app.parsers import cdkeys_parser as cd

            if not cd._get_algolia_api_key():
                return "CDKeys Algolia key missing/expired"
        except Exception as exc:
            return f"CDKeys auth check error: {exc}"[:120]
    # Kinguin has an HTML search fallback — do not pause the whole shop when
    # the Awin feed is in negative cache. Fanatical is feed-only today.
    if shop == "Fanatical":
        try:
            from app.parsers import affiliate_feeds as af

            if af._feed_fail_active(shop):
                return f"{shop} affiliate feed in negative cache"
            # Feed-only shop: without an on-disk CSV there is nothing to verify.
            cache = af._cache_path(shop)
            if not cache.is_file():
                return f"{shop} affiliate feed unavailable (no cache; Awin FID invalid)"
        except Exception as exc:
            return f"{shop} feed check error: {exc}"[:120]
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
