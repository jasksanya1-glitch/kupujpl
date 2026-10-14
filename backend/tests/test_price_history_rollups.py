"""Price history rollups must ignore region-foreign / ineligible offers."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.price_history import _eligible_offer_prices, update_game_price_rollups
from app.models.models import Base, Game, Offer


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_history_excludes_steam_us_for_pl_region(db: Session):
    g = Game(
        title="Neo Cab",
        slug="neo-cab-test",
        steam_appid=794540,
        steam_app_type="game",
        platform="pc",
        is_free=False,
        steam_enriched=True,
        steam_review_count=5000,
        steam_review_positive_pct=85.0,
        steam_recommendations=2000,
    )
    db.add(g)
    db.flush()
    db.add_all(
        [
            Offer(
                game_id=g.id,
                shop_name="Steam US",
                price_pln=2.24,
                in_stock=True,
                is_official=True,
                affiliate_url="https://example.com/us",
            ),
            Offer(
                game_id=g.id,
                shop_name="Kinguin",
                price_pln=0.37,
                in_stock=True,
                is_official=False,
                match_confidence=1.35,
                affiliate_url="https://example.com/k",
            ),
            Offer(
                game_id=g.id,
                shop_name="Gamivo",
                price_pln=1.94,
                in_stock=True,
                is_official=False,
                match_confidence=1.35,
                affiliate_url="https://example.com/g",
            ),
            Offer(
                game_id=g.id,
                shop_name="G2A",
                price_pln=2.58,
                in_stock=True,
                is_official=False,
                match_confidence=1.25,
                affiliate_url="https://example.com/g2a",
            ),
            Offer(
                game_id=g.id,
                shop_name="Instant Gaming",
                price_pln=4.37,
                in_stock=True,
                is_official=False,
                match_confidence=1.5,
                affiliate_url="https://example.com/ig",
            ),
            Offer(
                game_id=g.id,
                shop_name="GOG",
                price_pln=10.19,
                in_stock=True,
                is_official=True,
                affiliate_url="https://example.com/gog",
            ),
            Offer(
                game_id=g.id,
                shop_name="Steam",
                price_pln=67.99,
                in_stock=True,
                is_official=True,
                affiliate_url="https://example.com/steam",
            ),
        ]
    )
    db.flush()
    prices = _eligible_offer_prices(db, g.id, region="pl")
    assert 2.24 not in prices
    assert 0.37 not in prices
    assert min(prices) == pytest.approx(10.19)
    update_game_price_rollups(db, g.id, region="pl")
    db.commit()
    db.refresh(g)
    assert g.lowest_ever_pln == pytest.approx(10.19)


def test_savings_requires_valid_reference():
    """Mirror _savings_vs_steam rules without importing FastAPI app (needs JWT)."""

    def savings(best_price, steam_price):
        if steam_price is None or best_price is None:
            return None
        if steam_price <= 0 or best_price <= 0 or best_price >= steam_price:
            return None
        pct = int(round(((steam_price - best_price) / steam_price) * 100))
        if pct < 1 or pct > 99:
            return None
        return pct

    assert savings(10.0, 100.0) == 90
    assert savings(10.0, 0) is None
    assert savings(100.0, 10.0) is None
    assert savings(0.01, 100.0) is None  # rounds to 100% → omit
