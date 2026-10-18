"""Confirmed F2P games must show free status, not no_confirmed."""
from __future__ import annotations

from app.core.catalog_price_status import catalog_price_status as _catalog_price_status
from app.models.models import Game, Offer


def test_free_game_price_status_is_free():
    g = Game(title="CS2", slug="cs2", is_free=True)
    assert _catalog_price_status(g, None) == "free"


def test_paid_game_with_offers_no_best_is_no_confirmed():
    g = Game(title="Paid", slug="paid", is_free=False)
    g.offers = [
        Offer(
            game_id=1,
            shop_name="Steam",
            price_pln=50.0,
            in_stock=True,
            affiliate_url="https://store.steampowered.com/app/1",
        )
    ]
    assert _catalog_price_status(g, None) == "no_confirmed"


def test_zero_offer_alone_does_not_make_free_without_flag():
    g = Game(title="Weird", slug="weird", is_free=False)
    best = Offer(
        game_id=1,
        shop_name="Steam",
        price_pln=0.0,
        in_stock=True,
        affiliate_url="https://store.steampowered.com/app/1",
    )
    # best with 0 still returns confirmed path only if best is passed with price;
    # free flag is the only free status source.
    assert _catalog_price_status(g, best) == "confirmed"
