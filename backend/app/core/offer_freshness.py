"""Centralized offer freshness policy for best-price / KUP TERAZ / savings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

FreshnessStatus = Literal["fresh", "stale_warning", "too_old", "unknown"]

# Default windows (hours). Per-shop overrides via env:
#   OFFER_FRESH_HOURS_<SHOP>=24
#   OFFER_STALE_HOURS_<SHOP>=48
# Shop key: uppercased, spaces -> underscores (e.g. INSTANT_GAMING, STEAM_US).
DEFAULT_FRESH_HOURS = float(os.environ.get("OFFER_FRESH_HOURS_DEFAULT", "24"))
DEFAULT_STALE_HOURS = float(os.environ.get("OFFER_STALE_HOURS_DEFAULT", "48"))

# Official storefronts may lag slightly less critically for display warnings,
# but still must not drive confirmed min-price when older than stale window.
_SHOP_FRESH_HOURS: dict[str, float] = {
    "STEAM": float(os.environ.get("OFFER_FRESH_HOURS_STEAM", "36")),
    "STEAM_US": float(os.environ.get("OFFER_FRESH_HOURS_STEAM_US", "36")),
    "GOG": float(os.environ.get("OFFER_FRESH_HOURS_GOG", "36")),
    "EPIC_GAMES": float(os.environ.get("OFFER_FRESH_HOURS_EPIC_GAMES", "36")),
}
_SHOP_STALE_HOURS: dict[str, float] = {
    "STEAM": float(os.environ.get("OFFER_STALE_HOURS_STEAM", "72")),
    "STEAM_US": float(os.environ.get("OFFER_STALE_HOURS_STEAM_US", "72")),
    "GOG": float(os.environ.get("OFFER_STALE_HOURS_GOG", "72")),
    "EPIC_GAMES": float(os.environ.get("OFFER_STALE_HOURS_EPIC_GAMES", "72")),
}


def _shop_key(shop_name: str | None) -> str:
    return (shop_name or "").strip().upper().replace(" ", "_")


def fresh_hours_for_shop(shop_name: str | None) -> float:
    key = _shop_key(shop_name)
    env = os.environ.get(f"OFFER_FRESH_HOURS_{key}")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return _SHOP_FRESH_HOURS.get(key, DEFAULT_FRESH_HOURS)


def stale_hours_for_shop(shop_name: str | None) -> float:
    key = _shop_key(shop_name)
    env = os.environ.get(f"OFFER_STALE_HOURS_{key}")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return _SHOP_STALE_HOURS.get(key, DEFAULT_STALE_HOURS)


def _as_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


@dataclass(frozen=True)
class OfferFreshness:
    status: FreshnessStatus
    age_hours: float | None
    fresh_hours: float
    stale_hours: float
    updated_at: datetime | None

    @property
    def is_fresh(self) -> bool:
        return self.status == "fresh"

    @property
    def may_confirm_best_price(self) -> bool:
        """Fresh or warning band — legacy; not used for Najniższa potwierdzona."""
        return self.status in {"fresh", "stale_warning"}

    @property
    def is_confirmed_fresh(self) -> bool:
        """Strict fresh window for hero price + KUP TERAZ."""
        return self.status == "fresh"

    @property
    def needs_warning(self) -> bool:
        return self.status == "stale_warning"


def evaluate_offer_freshness(
    updated_at: datetime | None,
    *,
    shop_name: str | None = None,
    now: datetime | None = None,
) -> OfferFreshness:
    fresh_h = fresh_hours_for_shop(shop_name)
    stale_h = max(fresh_h, stale_hours_for_shop(shop_name))
    ts = _as_naive_utc(updated_at)
    now_n = _as_naive_utc(now) or datetime.utcnow()
    if ts is None:
        return OfferFreshness("unknown", None, fresh_h, stale_h, None)
    age = max(0.0, (now_n - ts).total_seconds() / 3600.0)
    if age <= fresh_h:
        status: FreshnessStatus = "fresh"
    elif age <= stale_h:
        status = "stale_warning"
    else:
        status = "too_old"
    return OfferFreshness(status, age, fresh_h, stale_h, ts)


def offer_may_confirm_best_price(
    updated_at: datetime | None,
    *,
    shop_name: str | None = None,
    now: datetime | None = None,
) -> bool:
    return evaluate_offer_freshness(
        updated_at, shop_name=shop_name, now=now
    ).may_confirm_best_price


def offer_is_confirmed_fresh(
    updated_at: datetime | None,
    *,
    shop_name: str | None = None,
    now: datetime | None = None,
) -> bool:
    return evaluate_offer_freshness(
        updated_at, shop_name=shop_name, now=now
    ).is_confirmed_fresh


def format_last_checked_pl(updated_at: datetime | None) -> str | None:
    ts = _as_naive_utc(updated_at)
    if ts is None:
        return None
    return ts.strftime("%d.%m.%Y %H:%M")


def freshness_warning_pl(freshness: OfferFreshness) -> str | None:
    if freshness.status == "stale_warning":
        checked = format_last_checked_pl(freshness.updated_at)
        if checked:
            return f"Oferta wymaga aktualizacji (ostatnia weryfikacja: {checked})"
        return "Oferta wymaga aktualizacji"
    if freshness.status == "too_old":
        checked = format_last_checked_pl(freshness.updated_at)
        if checked:
            return f"Brak aktualnych ofert (ostatnia weryfikacja: {checked})"
        return "Brak aktualnych ofert"
    if freshness.status == "unknown":
        return "Brak aktualnych ofert"
    return None


def confirmed_unavailable_pl(*, last_checked: str | None = None) -> str:
    if last_checked:
        return f"Brak aktualnych potwierdzonych ofert (ostatnia weryfikacja: {last_checked})"
    return "Brak aktualnych potwierdzonych ofert"
