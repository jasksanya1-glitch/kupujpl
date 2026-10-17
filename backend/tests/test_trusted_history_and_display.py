"""Trusted historical lows + PE display separation (confirmed vs stale)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.price_engine import evaluate_game_prices, unverified_offers_from_result
from app.core.price_history import (
    compute_trusted_history_rollups,
    update_game_price_rollups,
)
from app.core.worth_buy import compute_worth_buy
from app.models.models import Base, Game, Offer, PriceSnapshot


@pytest.fixture
def db(monkeypatch) -> Session:
    monkeypatch.setenv("PRICE_ENGINE_V2", "1")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_game(db: Session) -> Game:
    g = Game(
        title="Guacamelee Test",
        slug="guacamelee-test",
        steam_appid=275390,
        steam_app_type="game",
        platform="pc",
        is_free=False,
        steam_enriched=True,
        steam_review_count=5000,
        steam_review_positive_pct=90.0,
        steam_recommendations=2000,
        lowest_ever_pln=2.29,
    )
    db.add(g)
    db.flush()
    return g


def test_trusted_history_excludes_pre_v2_junk_low(db: Session):
    g = _add_game(db)
    now = datetime.utcnow()
    db.add_all(
        [
            Offer(
                game_id=g.id,
                shop_name="Steam",
                price_pln=15.99,
                in_stock=True,
                is_official=True,
                affiliate_url="https://store.steampowered.com/app/275390/",
                updated_at=now,
            ),
            Offer(
                game_id=g.id,
                shop_name="Kinguin",
                price_pln=4.80,
                in_stock=True,
                is_official=False,
                match_confidence=1.4,
                affiliate_url="https://www.kinguin.net/pl/guacamelee-key",
                updated_at=now,
            ),
            PriceSnapshot(
                game_id=g.id,
                shop_name="Gamivo",
                price_pln=2.29,
                in_stock=True,
                recorded_at=now - timedelta(days=40),
            ),
            PriceSnapshot(
                game_id=g.id,
                shop_name="Kinguin",
                price_pln=4.80,
                in_stock=True,
                recorded_at=now - timedelta(days=5),
            ),
        ]
    )
    db.flush()
    rollup = compute_trusted_history_rollups(db, g, region="pl")
    assert rollup.discarded_stored_low_pln == pytest.approx(2.29)
    assert rollup.lowest_ever_pln is not None
    assert rollup.lowest_ever_pln >= 4.0
    update_game_price_rollups(db, g.id, region="pl")
    db.flush()
    db.refresh(g)
    assert g.lowest_ever_pln == pytest.approx(rollup.lowest_ever_pln)


def test_stale_cheaper_offer_is_unverified_not_confirmed_best(db: Session):
    g = Game(
        title="Satisfactory",
        slug="satisfactory-test",
        steam_appid=526870,
        steam_app_type="game",
        platform="pc",
        is_free=False,
        steam_enriched=True,
        steam_review_count=50000,
        steam_review_positive_pct=95.0,
        steam_recommendations=10000,
    )
    db.add(g)
    db.flush()
    fresh = datetime.utcnow()
    stale_ts = fresh - timedelta(days=20)
    db.add_all(
        [
            Offer(
                game_id=g.id,
                shop_name="Steam",
                price_pln=159.99,
                in_stock=True,
                is_official=True,
                affiliate_url="https://store.steampowered.com/app/526870/",
                updated_at=fresh,
            ),
            Offer(
                game_id=g.id,
                shop_name="Instant Gaming",
                price_pln=97.94,
                in_stock=True,
                is_official=False,
                match_confidence=1.5,
                affiliate_url="https://www.instant-gaming.com/pl/satisfactory-game/",
                updated_at=fresh,
                last_verified_at=fresh,
                last_check_status="ok",
            ),
            Offer(
                game_id=g.id,
                shop_name="Gamivo",
                price_pln=93.25,
                in_stock=True,
                is_official=False,
                match_confidence=1.4,
                affiliate_url="https://www.gamivo.com/product/satisfactory",
                updated_at=stale_ts,
                last_verified_at=stale_ts,
                last_check_status="ok",
            ),
        ]
    )
    db.flush()
    offers = list(g.offers)
    result = evaluate_game_prices(g, offers, region="pl")
    assert result.best_confirmed_offer is not None
    assert result.best_confirmed_offer.shop_name == "Instant Gaming"
    assert float(result.best_confirmed_offer.price_pln) == pytest.approx(97.94)
    unv = unverified_offers_from_result(result)
    shops = {o.shop_name for o, _ in unv}
    # Cheaper Gamivo must not be confirmed; may appear as unverified/stale.
    assert "Instant Gaming" not in shops or all(
        o.shop_name != "Instant Gaming" for o, _ in unv
    )
    if result.confirmed_offers:
        assert all(o.shop_name != "Gamivo" for o in result.confirmed_offers)


def test_worth_buy_ignores_poisoned_historical_low():
    """Trusted hist low must not force a false wait; junk-only hist still waits."""
    # Junk hist alone (no steam/avg rescue) → wait
    poisoned = compute_worth_buy(
        current_price=4.80,
        lowest_ever_pln=2.29,
        history_points=10,
        offer_verified=True,
    )
    assert poisoned is not None
    assert poisoned.tier == "wait"

    # Trusted: hist low matches confirmed band → buy
    fixed = compute_worth_buy(
        current_price=4.80,
        lowest_ever_pln=4.80,
        avg_best_price_30d=5.5,
        steam_price_pln=15.99,
        savings_pct=70,
        at_historical_low=True,
        history_points=10,
        offer_verified=True,
    )
    assert fixed is not None
    assert fixed.tier == "buy"


def test_worth_buy_thin_history_caps_buy_now():
    result = compute_worth_buy(
        current_price=10.0,
        lowest_ever_pln=10.0,
        avg_best_price_30d=12.0,
        steam_price_pln=40.0,
        savings_pct=75,
        at_historical_low=True,
        history_points=1,
        offer_verified=True,
    )
    assert result is not None
    assert result.score <= 74
    assert result.tier != "buy"
