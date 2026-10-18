"""Unavailable / not_found / error stubs must not corrupt PE or price history."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.offer_verification import record_verified_price
from app.core.price_engine import evaluate_game_prices
from app.core.price_history import (
    compute_trusted_history_rollups,
    record_offer_price_change,
    update_game_price_rollups,
)
from app.models.models import Game, Offer
from app.parsers.game_offers import _record_shop_miss
from app.parsers.gog_parser import pick_best_gog_product
from app.parsers.shop_scan_queue import STATUS_BACKOFF_HOURS, select_stale_game_ids_for_shop


def _game(db: Session, *, slug: str, reviews: int = 1000) -> Game:
    g = Game(
        title=slug.replace("-", " ").title(),
        slug=slug,
        steam_appid=abs(hash(slug)) % 8_000_000 + 1,
        platform="pc",
        steam_review_count=reviews,
        steam_enriched=True,
    )
    db.add(g)
    db.flush()
    return g


def test_error_miss_does_not_mark_existing_offer_oos(db: Session):
    g = _game(db, slug="keep-stock-on-error")
    offer = Offer(
        game_id=g.id,
        shop_name="Instant Gaming",
        price_pln=49.99,
        affiliate_url="https://www.instant-gaming.com/pl/1-keep/",
        is_official=False,
        in_stock=True,
    )
    db.add(offer)
    db.flush()
    record_verified_price(offer, price_pln=49.99, source="instant_gaming", previous_price=None)
    verified_at = offer.last_verified_at
    _record_shop_miss(db, g, "Instant Gaming", status="error")
    db.commit()
    db.refresh(offer)
    assert offer.in_stock is True
    assert float(offer.price_pln) == 49.99
    assert offer.last_check_status == "error"
    assert offer.last_verified_at == verified_at


def test_unavailable_keeps_prior_price_never_zeros_existing(db: Session):
    g = _game(db, slug="oos-keeps-price")
    offer = Offer(
        game_id=g.id,
        shop_name="Instant Gaming",
        price_pln=19.5,
        affiliate_url="https://www.instant-gaming.com/pl/2-oos/",
        is_official=False,
        in_stock=True,
    )
    db.add(offer)
    db.flush()
    _record_shop_miss(db, g, "Instant Gaming", status="unavailable")
    db.commit()
    db.refresh(offer)
    assert offer.in_stock is False
    assert float(offer.price_pln) == 19.5
    assert offer.last_verified_at is None or offer.last_check_status == "unavailable"


def test_not_found_stub_excluded_from_pe_and_history(db: Session):
    g = _game(db, slug="stub-not-in-pe")
    _record_shop_miss(db, g, "Instant Gaming", status="not_found")
    db.commit()
    offers = db.query(Offer).filter(Offer.game_id == g.id).all()
    assert len(offers) == 1
    stub = offers[0]
    assert stub.price_pln == 0.0
    assert stub.in_stock is False
    assert stub.last_check_status == "not_found"
    assert stub.last_verified_at is None

    # PE must ignore stub
    result = evaluate_game_prices(g, offers, now=datetime.utcnow())
    confirmed_ids = {o.id for o in (result.confirmed_offers or [])}
    assert stub.id not in confirmed_ids

    # History must ignore stub (price<=0 / OOS)
    record_offer_price_change(
        db,
        game_id=g.id,
        shop_name="Instant Gaming",
        price_pln=0.0,
        in_stock=False,
    )
    update_game_price_rollups(db, g.id)
    db.commit()
    db.refresh(g)
    assert g.lowest_ever_pln is None
    rollup = compute_trusted_history_rollups(db, g)
    assert rollup.lowest_ever_pln is None


def test_duplicate_miss_does_not_create_second_row(db: Session):
    g = _game(db, slug="no-dup-stub")
    _record_shop_miss(db, g, "GOG", status="not_found")
    _record_shop_miss(db, g, "GOG", status="not_found")
    db.commit()
    assert (
        db.query(Offer)
        .filter(Offer.game_id == g.id, Offer.shop_name == "GOG")
        .count()
        == 1
    )


def test_not_found_backoff_then_reenter(db: Session):
    g = _game(db, slug="backoff-not-found", reviews=90_000)
    _record_shop_miss(db, g, "Instant Gaming", status="not_found")
    db.commit()
    ids = select_stale_game_ids_for_shop(db, "Instant Gaming", limit=300, after_game_id=0)
    assert g.id not in ids
    offer = (
        db.query(Offer)
        .filter(Offer.game_id == g.id, Offer.shop_name == "Instant Gaming")
        .one()
    )
    offer.last_attempt_at = datetime.utcnow() - timedelta(hours=STATUS_BACKOFF_HOURS + 1)
    db.commit()
    ids2 = select_stale_game_ids_for_shop(db, "Instant Gaming", limit=300, after_game_id=0)
    assert g.id in ids2


def test_successful_verify_clears_stub_oos(db: Session):
    g = _game(db, slug="restock-after-stub")
    _record_shop_miss(db, g, "Instant Gaming", status="unavailable")
    db.commit()
    offer = (
        db.query(Offer)
        .filter(Offer.game_id == g.id, Offer.shop_name == "Instant Gaming")
        .one()
    )
    record_verified_price(offer, price_pln=33.0, source="instant_gaming", previous_price=0.0)
    offer.affiliate_url = "https://www.instant-gaming.com/pl/9-restock/"
    db.commit()
    db.refresh(offer)
    assert offer.in_stock is True
    assert float(offer.price_pln) == 33.0
    assert offer.last_check_status == "verified"
    assert offer.last_verified_at is not None


def test_gog_remaster_ok_but_deluxe_rejected():
    products = [
        {
            "id": "1",
            "slug": "the_witcher_3_wild_hunt_game_of_the_year_edition",
            "title": "The Witcher 3: Wild Hunt — Remastered",
            "productType": "game",
        },
        {
            "id": "2",
            "slug": "the_witcher_3_wild_hunt_complete_edition",
            "title": "The Witcher 3: Wild Hunt Complete Edition",
            "productType": "game",
        },
        {
            "id": "3",
            "slug": "the_witcher_2",
            "title": "The Witcher 2: Assassins of Kings Enhanced Edition",
            "productType": "game",
        },
        {
            "id": "4",
            "slug": "cyberpunk_phantom",
            "title": "Cyberpunk 2077: Phantom Liberty",
            "productType": "dlc",
        },
    ]
    best = pick_best_gog_product("The Witcher 3: Wild Hunt", products)
    assert best is not None
    assert best["id"] == "1"
    # Deluxe/complete without query intent must not win over remaster base SKU
    assert pick_best_gog_product(
        "The Witcher 3: Wild Hunt",
        [products[1]],
    ) is None
    assert pick_best_gog_product("The Witcher 3: Wild Hunt", [products[2]]) is None
    assert pick_best_gog_product("Cyberpunk 2077", [products[3]]) is None
