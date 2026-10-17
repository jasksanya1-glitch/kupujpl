"""Unverified PE offers stay separate from confirmed best-price rows."""
from __future__ import annotations

from types import SimpleNamespace

from app.core.price_engine import unverified_offers_from_result as _engine_unverified_offers


def test_engine_unverified_offers_excludes_confirmed_and_oos():
    confirmed = SimpleNamespace(id=1, in_stock=True, price_pln=199.99, shop_name="Steam")
    stale = SimpleNamespace(id=2, in_stock=True, price_pln=199.99, shop_name="Epic Games")
    cheap = SimpleNamespace(id=3, in_stock=True, price_pln=33.46, shop_name="Kinguin")
    oos = SimpleNamespace(id=4, in_stock=False, price_pln=31.0, shop_name="CDKeys")

    engine = SimpleNamespace(
        confirmed_offers=[confirmed],
        stale_offers=[stale],
        rows=[
            SimpleNamespace(offer=confirmed, bucket="confirmed", exclusion_reason=None),
            SimpleNamespace(offer=stale, bucket="stale", exclusion_reason="stale"),
            SimpleNamespace(offer=cheap, bucket="excluded", exclusion_reason="not_eligible"),
            SimpleNamespace(offer=oos, bucket="excluded", exclusion_reason="not_eligible"),
        ],
    )
    out = _engine_unverified_offers(engine)
    assert len(out) == 1
    offer, reason = out[0]
    assert offer.id == 3
    assert reason == "not_eligible"


def test_engine_unverified_offers_none_engine():
    assert _engine_unverified_offers(None) == []
