"""Convert foreign shop prices to PLN (NBP table A, cached)."""
from __future__ import annotations

import logging
import time
from typing import Literal

import requests

logger = logging.getLogger("currency_pln")

_NBP_URL = "https://api.nbp.pl/api/exchangerates/rates/a/{currency}/?format=json"
_CACHE: dict[str, tuple[float, float]] = {}
_CACHE_TTL = 6 * 3600


def _fetch_rate(currency: str) -> float | None:
    currency = currency.upper()
    if currency == "PLN":
        return 1.0
    now = time.time()
    cached = _CACHE.get(currency)
    if cached and now - cached[1] < _CACHE_TTL:
        return cached[0]
    try:
        response = requests.get(_NBP_URL.format(currency=currency.lower()), timeout=10)
        if response.status_code != 200:
            logger.warning("NBP rate HTTP %s for %s", response.status_code, currency)
            return cached[0] if cached else None
        data = response.json()
        rate = float(data["rates"][0]["mid"])
        _CACHE[currency] = (rate, now)
        return rate
    except Exception as exc:
        logger.warning("NBP rate fetch failed for %s: %s", currency, exc)
        return cached[0] if cached else None


def to_pln(amount: float, currency: str) -> float | None:
    """Convert amount in given currency to PLN."""
    currency = (currency or "PLN").upper()
    if currency == "PLN":
        return round(amount, 2)
    rate = _fetch_rate(currency)
    if rate is None:
        return None
    return round(amount * rate, 2)


def money_to_pln(
    amount: int | float,
    currency: str,
    *,
    minor_units: bool = True,
) -> float | None:
    """Convert a shop money value to PLN.

    minor_units=True  -> amount is in cents/grosze (integer feeds, e.g. GraphQL).
    minor_units=False -> amount is already a major-unit decimal (e.g. 15.99).
    """
    if amount is None:
        return None
    value = float(amount)
    if minor_units:
        value = value / 100.0
    return to_pln(value, currency)
