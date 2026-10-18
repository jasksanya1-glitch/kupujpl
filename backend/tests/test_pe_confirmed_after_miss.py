"""PE V2 must keep confirmed offers through search miss / timeout until freshness expires."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.offer_verification import record_verified_price
from app.core.price_engine import best_offers_map_v2, evaluate_game_prices
from app.models.models import Base, Game, Offer
from app.parsers.game_offers import _record_shop_miss
from app.parsers.shop_scan_queue import (
    NEVER_LISTED_BACKOFF_HOURS,
    STATUS_BACKOFF_HOURS,
    TIER_B_MIN_REVIEWS,
    select_stale_game_ids_for_shop,
)


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setenv("PRICE_ENGINE_V2", "1")
    monkeypatch.setenv("SCAN_V2", "1")
    monkeypatch.setenv("SCAN_V2_VERIFICATION", "1")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _game(session, *, slug: str, reviews: int = 50_000) -> Game:
    g = Game(
        title=slug.replace("-", " ").title(),
        slug=slug,
        steam_appid=abs(hash(slug)) % 8_000_000 + 1,
        platform="pc",
        steam_review_count=reviews,
        steam_enriched=True,
    )
    session.add(g)
    session.flush()
    return g


def _verified_ig(session, game: Game, price: float = 55.0) -> Offer:
    offer = Offer(
        game_id=game.id,
        shop_name="Instant Gaming",
        price_pln=price,
        affiliate_url=f"https://www.instant-gaming.com/pl/{game.slug}-game/",
        is_official=False,
        in_stock=True,
        match_confidence=1.2,
    )
    session.add(offer)
    session.flush()
    record_verified_price(offer, price_pln=price, source="instant_gaming", previous_price=None)
    session.commit()
    session.refresh(offer)
    return offer


def test_confirmed_survives_not_found_until_freshness_expires(db):
    g = _game(db, slug="pe-keep-after-not-found")
    offer = _verified_ig(db, g, 55.0)
    verified_at = offer.last_verified_at
    assert verified_at is not None

    before = evaluate_game_prices(g, [offer], now=datetime.utcnow())
    assert before.best_confirmed_offer is not None
    assert before.best_confirmed_offer.id == offer.id

    _record_shop_miss(db, g, "Instant Gaming", status="not_found")
    db.commit()
    db.refresh(offer)
    assert offer.in_stock is True
    assert offer.last_verified_at == verified_at
    assert offer.last_check_status == "not_found"

    after = evaluate_game_prices(g, [offer], now=datetime.utcnow())
    assert after.best_confirmed_offer is not None
    assert after.best_confirmed_offer.id == offer.id
    row = next(r for r in after.rows if r.offer.id == offer.id)
    assert row.bucket == "confirmed"

    # Catalog best map must still surface the offer.
    mapping = best_offers_map_v2(db, [g.id], games={g.id: g}, now=datetime.utcnow())
    assert mapping.get(g.id) is not None
    assert mapping[g.id].id == offer.id


def test_confirmed_survives_timeout_until_freshness_expires(db):
    g = _game(db, slug="pe-keep-after-timeout")
    offer = _verified_ig(db, g, 40.0)
    verified_at = offer.last_verified_at
    _record_shop_miss(db, g, "Instant Gaming", status="timeout")
    db.commit()
    db.refresh(offer)
    assert offer.in_stock is True
    assert offer.last_verified_at == verified_at
    assert offer.last_check_status == "timeout"

    result = evaluate_game_prices(g, [offer], now=datetime.utcnow())
    assert result.best_confirmed_offer is not None
    assert result.best_confirmed_offer.id == offer.id


def test_confirmed_drops_after_freshness_expiry_following_not_found(db):
    g = _game(db, slug="pe-expire-after-not-found")
    offer = _verified_ig(db, g, 42.0)
    # Age verification beyond Instant Gaming fresh window (default 24h).
    offer.last_verified_at = datetime.utcnow() - timedelta(hours=30)
    db.commit()
    _record_shop_miss(db, g, "Instant Gaming", status="not_found")
    db.commit()
    db.refresh(offer)
    assert offer.in_stock is True
    assert offer.last_check_status == "not_found"

    result = evaluate_game_prices(g, [offer], now=datetime.utcnow())
    assert result.best_confirmed_offer is None
    row = next(r for r in result.rows if r.offer.id == offer.id)
    assert row.bucket in {"stale", "excluded"}


def test_explicit_oos_removes_confirmed(db):
    g = _game(db, slug="pe-oos-drops-confirmed")
    offer = _verified_ig(db, g, 19.5)
    _record_shop_miss(db, g, "Instant Gaming", status="unavailable")
    db.commit()
    db.refresh(offer)
    assert offer.in_stock is False
    result = evaluate_game_prices(g, [offer], now=datetime.utcnow())
    assert result.best_confirmed_offer is None


def test_tier_c_never_listed_uses_longer_backoff(db, monkeypatch):
    monkeypatch.setenv("SCAN_V2", "1")
    monkeypatch.setenv("SCAN_V2_VERIFICATION", "1")
    # Low-review = Tier C; never verified; recent not_found.
    g = _game(db, slug="ig-never-listed-c", reviews=50)
    assert g.steam_review_count < TIER_B_MIN_REVIEWS
    _record_shop_miss(db, g, "Instant Gaming", status="not_found")
    db.commit()
    ids = select_stale_game_ids_for_shop(db, "Instant Gaming", limit=300, after_game_id=0)
    assert g.id not in ids

    offer = (
        db.query(Offer)
        .filter(Offer.game_id == g.id, Offer.shop_name == "Instant Gaming")
        .one()
    )
    # Past short backoff but still inside never-listed window → still excluded.
    offer.last_attempt_at = datetime.utcnow() - timedelta(hours=STATUS_BACKOFF_HOURS + 1)
    db.commit()
    ids2 = select_stale_game_ids_for_shop(db, "Instant Gaming", limit=300, after_game_id=0)
    assert g.id not in ids2

    # Past never-listed window → re-enters (not infinite exclusion).
    offer.last_attempt_at = datetime.utcnow() - timedelta(
        hours=NEVER_LISTED_BACKOFF_HOURS + 1
    )
    db.commit()
    ids3 = select_stale_game_ids_for_shop(db, "Instant Gaming", limit=300, after_game_id=0)
    assert g.id in ids3


def test_tier_a_never_listed_keeps_short_backoff(db, monkeypatch):
    monkeypatch.setenv("SCAN_V2", "1")
    monkeypatch.setenv("SCAN_V2_VERIFICATION", "1")
    g = _game(db, slug="ig-never-listed-a", reviews=90_000)
    _record_shop_miss(db, g, "Instant Gaming", status="not_found")
    db.commit()
    offer = (
        db.query(Offer)
        .filter(Offer.game_id == g.id, Offer.shop_name == "Instant Gaming")
        .one()
    )
    offer.last_attempt_at = datetime.utcnow() - timedelta(hours=STATUS_BACKOFF_HOURS + 1)
    db.commit()
    ids = select_stale_game_ids_for_shop(db, "Instant Gaming", limit=300, after_game_id=0)
    assert g.id in ids
