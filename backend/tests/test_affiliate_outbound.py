"""Tests for production affiliate outbound / Awin unwrap behavior (no network)."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

import pytest

from app.core import affiliate
from app.core.affiliate import (
    attach_merchant_fallback,
    make_affiliate_link,
    merchant_fallback_from_url,
    resolve_outbound_url,
)


def test_affiliate_outbound_exports_exist():
    for name in (
        "resolve_outbound_url",
        "unwrap_awin_click_url",
        "attach_merchant_fallback",
        "merchant_fallback_from_url",
        "_wrap_direct_url_with_awin",
        "make_affiliate_link",
        "affiliate_link_configured",
    ):
        assert callable(getattr(affiliate, name))


def test_resolve_outbound_direct_url(monkeypatch):
    monkeypatch.setattr(affiliate, "_wrap_direct_url_with_awin", lambda url, shop: None)
    monkeypatch.setattr(affiliate, "unwrap_awin_click_url", lambda url, timeout=None: None)
    out = resolve_outbound_url("https://store.steampowered.com/app/1", "Steam")
    assert out.startswith("https://store.steampowered.com/app/1")


def test_resolve_outbound_awin_unwrap(monkeypatch):
    awin = "https://www.awin1.com/cread.php?awinmid=1&awinaffid=2&ued=https%3A%2F%2Fkinguin.net%2Fx"
    merchant = "https://www.kinguin.net/category/123?awc=TOKEN"

    monkeypatch.setattr(affiliate, "unwrap_awin_click_url", lambda url, timeout=None: merchant)
    out = resolve_outbound_url(awin, "Kinguin")
    assert out.startswith("https://www.kinguin.net/")
    assert "awc=TOKEN" in out
    assert "awin1.com" not in out


def test_awc_preserved_and_kinguin_referral_not_appended(monkeypatch):
    monkeypatch.setenv("KINGUIN_AFFILIATE_REF", "REF123")
    # Reload constants used by make_affiliate_link
    monkeypatch.setattr(affiliate, "KINGUIN_AFFILIATE_REF", "REF123")
    url = "https://www.kinguin.net/category/1?awc=KEEPME"
    out = make_affiliate_link(url, "Kinguin")
    params = dict(parse_qsl(urlparse(out).query))
    assert params.get("awc") == "KEEPME"
    assert "referral" not in params


def test_kinguin_referral_added_without_awc(monkeypatch):
    monkeypatch.setattr(affiliate, "KINGUIN_AFFILIATE_REF", "REF123")
    url = "https://www.kinguin.net/category/1"
    out = make_affiliate_link(url, "Kinguin")
    params = dict(parse_qsl(urlparse(out).query))
    assert params.get("referral") == "REF123"


def test_merchant_fallback_and_attach():
    awin = "https://www.awin1.com/pclick.php?x=1"
    merchant = "https://www.kinguin.net/category/9"
    attached = attach_merchant_fallback(awin, merchant)
    assert "awin1.com" in attached
    assert merchant_fallback_from_url(attached) == merchant


def test_resolve_outbound_uses_kp_dest_when_unwrap_misses(monkeypatch):
    awin = attach_merchant_fallback(
        "https://www.awin1.com/cread.php?awinmid=1&awinaffid=2",
        "https://www.eneba.com/game-x",
    )
    monkeypatch.setattr(affiliate, "unwrap_awin_click_url", lambda url, timeout=None: None)
    out = resolve_outbound_url(awin, "Eneba")
    assert "eneba.com" in out
    assert "awin1.com" not in out


def test_malformed_and_empty_urls_fail_safe():
    assert resolve_outbound_url("", "Steam") == ""
    # Non-http garbage should not raise
    out = resolve_outbound_url("not-a-url", "Steam")
    assert isinstance(out, str)
    assert merchant_fallback_from_url(":::bad") is None
    assert attach_merchant_fallback("https://www.awin1.com/x", "not-http") == "https://www.awin1.com/x"


def test_affiliate_feeds_row_attaches_merchant_fallback():
    from app.parsers.affiliate_feeds import _row_to_feed_row

    row = _row_to_feed_row(
        {
            "product_name": "Test Game",
            "aw_deep_link": "https://www.awin1.com/pclick.php?x=1",
            "merchant_deep_link": "https://www.kinguin.net/category/42",
            "search_price": "10.00",
            "currency": "PLN",
            "in_stock": "1",
        }
    )
    assert row is not None
    assert "awin1.com" in row.url
    assert merchant_fallback_from_url(row.url) == "https://www.kinguin.net/category/42"
