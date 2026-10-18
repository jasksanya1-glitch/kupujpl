"""Miss stubs + unavailable backoff must rotate the queue (no forever OOS spin)."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.offer_verification import record_attempt
from app.models.models import Game, Offer
from app.parsers.game_offers import _deactivate_shop_offer
from app.parsers.gog_parser import _strip_remaster_label, pick_best_gog_product
from app.parsers.shop_scan_queue import STATUS_BACKOFF_HOURS, select_stale_game_ids_for_shop


def test_deactivate_creates_unavailable_stub_without_verified(db: Session):
    g = Game(
        title="No Stock Title",
        slug="no-stock-title-ig",
        steam_appid=9_001_001,
        platform="pc",
        steam_review_count=50_000,
        steam_enriched=True,
    )
    db.add(g)
    db.flush()
    assert (
        db.query(Offer)
        .filter(Offer.game_id == g.id, Offer.shop_name == "Instant Gaming")
        .first()
        is None
    )
    _deactivate_shop_offer(db, g, "Instant Gaming")
    db.commit()
    row = (
        db.query(Offer)
        .filter(Offer.game_id == g.id, Offer.shop_name == "Instant Gaming")
        .one()
    )
    assert row.in_stock is False
    assert float(row.price_pln) == 0.0
    # Default miss without explicit OOS signal is not_found (search completed, no match).
    assert row.last_check_status in {"unavailable", "not_found"}
    assert row.last_attempt_at is not None
    assert row.last_verified_at is None


def test_unavailable_recent_attempt_excluded_from_stale_queue(db: Session):
    g = Game(
        title="Backoff Title",
        slug="backoff-title-ig",
        steam_appid=9_001_002,
        platform="pc",
        steam_review_count=80_000,
        steam_enriched=True,
    )
    db.add(g)
    db.flush()
    offer = Offer(
        game_id=g.id,
        shop_name="Instant Gaming",
        price_pln=0.0,
        affiliate_url="https://www.instant-gaming.com/pl/",
        is_official=False,
        in_stock=False,
    )
    db.add(offer)
    db.flush()
    record_attempt(offer, status="unavailable", source="instant_gaming")
    db.commit()

    ids = select_stale_game_ids_for_shop(db, "Instant Gaming", limit=200, after_game_id=0)
    assert g.id not in ids

    # After backoff window elapses, it may re-enter.
    offer.last_attempt_at = datetime.utcnow() - timedelta(hours=STATUS_BACKOFF_HOURS + 1)
    db.commit()
    ids2 = select_stale_game_ids_for_shop(db, "Instant Gaming", limit=200, after_game_id=0)
    assert g.id in ids2


def test_gog_remaster_matches_base_title():
    assert _strip_remaster_label("The Witcher 3: Wild Hunt — Remastered") == (
        "The Witcher 3: Wild Hunt"
    )
    products = [
        {
            "id": "1207664663",
            "slug": "the_witcher_3_wild_hunt_game_of_the_year_edition",
            "title": "The Witcher 3: Wild Hunt — Remastered",
            "productType": "game",
        }
    ]
    best = pick_best_gog_product("The Witcher 3: Wild Hunt", products)
    assert best is not None
    assert best["id"] == "1207664663"
