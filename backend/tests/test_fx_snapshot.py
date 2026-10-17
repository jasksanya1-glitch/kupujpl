"""Regression tests for /api/fx backing helper fx_snapshot()."""
from __future__ import annotations

from unittest.mock import patch

from app.parsers import currency_pln


def test_fx_snapshot_returns_pln_base_and_known_currencies():
    currency_pln._CACHE.clear()
    with patch.object(currency_pln, "_fetch_rate", side_effect=lambda c: {"USD": 4.0, "EUR": 4.3, "GBP": 5.0, "UAH": 0.1}.get(c)):
        snap = currency_pln.fx_snapshot()
    assert snap["base"] == "PLN"
    assert snap["rates"]["USD"] == 4.0
    assert snap["rates"]["EUR"] == 4.3
    assert "GBP" in snap["rates"]
    assert "UAH" in snap["rates"]


def test_fx_snapshot_omits_failed_rates_without_inventing():
    currency_pln._CACHE.clear()

    def _fail_nbp(currency: str):
        return None

    with patch.object(currency_pln, "_fetch_rate", side_effect=_fail_nbp):
        snap = currency_pln.fx_snapshot()
    assert snap == {"base": "PLN", "rates": {}}


def test_fetch_rate_keeps_stale_cache_when_nbp_unavailable():
    currency_pln._CACHE.clear()
    currency_pln._CACHE["USD"] = (3.5, 0.0)  # expired timestamp
    with patch.object(currency_pln.requests, "get", side_effect=RuntimeError("nbp down")):
        rate = currency_pln._fetch_rate("USD")
    assert rate == 3.5
