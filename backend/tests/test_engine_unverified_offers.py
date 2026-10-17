"""Unverified PE offers stay separate from confirmed best-price rows."""
from __future__ import annotations

from types import SimpleNamespace

from app.core.price_engine import unverified_offers_from_result as _engine_unverified_offers


def test_engine_unverified_offers_excludes_confirmed_and_oos():
    confirmed = SimpleNamespace(id=1, in_stock=True, price_pln=199.99, shop_name="Steam")
    stale = SimpleNamespace(id=2, in_stock=True, price_pln=180.0, shop_name="Epic Games")
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
    # Stale + excluded-unverified when confirmed exists; OOS omitted.
    assert {o.id for o, _ in out} == {2, 3}
    by_id = {o.id: reason for o, reason in out}
    assert by_id[2] == "stale"
    assert by_id[3] == "not_eligible"
    # Cheapest unverified first
    assert out[0][0].id == 3


def test_engine_unverified_offers_none_engine():
    assert _engine_unverified_offers(None) == []
