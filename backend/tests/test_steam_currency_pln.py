"""Steam price_overview must use explicit currency → PLN (never assume)."""
from __future__ import annotations

from app.parsers.steam_catalog import _steam_price_overview_to_pln


def test_pln_minor_units(monkeypatch):
    monkeypatch.setattr(
        "app.parsers.steam_catalog.money_to_pln",
        lambda amount, currency, minor_units=True: (
            round(float(amount) / 100.0, 2) if currency == "PLN" else None
        ),
    )
    out = _steam_price_overview_to_pln(
        {"currency": "PLN", "final": 19999, "initial": 19999}
    )
    assert out == (199.99, 199.99)


def test_usd_converted_via_fx(monkeypatch):
    def fake_money(amount, currency, minor_units=True):
        value = float(amount) / 100.0 if minor_units else float(amount)
        if currency == "USD":
            return round(value * 4.0, 2)  # test rate only
        if currency == "PLN":
            return round(value, 2)
        return None

    monkeypatch.setattr("app.parsers.steam_catalog.money_to_pln", fake_money)
    out = _steam_price_overview_to_pln(
        {"currency": "USD", "final": 1499, "initial": 4999}
    )
    assert out is not None
    assert out[0] == 59.96  # 14.99 * 4
    assert out[1] == 199.96  # 49.99 * 4


def test_missing_currency_refused():
    assert _steam_price_overview_to_pln({"final": 1499, "initial": 1499}) is None


def test_invalid_currency_refused(monkeypatch):
    monkeypatch.setattr(
        "app.parsers.steam_catalog.money_to_pln",
        lambda *a, **k: None,
    )
    assert (
        _steam_price_overview_to_pln(
            {"currency": "ZZZ", "final": 1000, "initial": 1000}
        )
        is None
    )


def test_eur_converted(monkeypatch):
    monkeypatch.setattr(
        "app.parsers.steam_catalog.money_to_pln",
        lambda amount, currency, minor_units=True: (
            round(float(amount) / 100.0 * 4.3, 2) if currency == "EUR" else None
        ),
    )
    out = _steam_price_overview_to_pln(
        {"currency": "EUR", "final": 4999, "initial": 4999}
    )
    assert out is not None
    assert out[0] == 214.96
