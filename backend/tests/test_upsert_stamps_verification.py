"""Successful offer upserts must refresh PE freshness even when price is unchanged."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.models import Base, Game, Offer
from app.parsers.keyshop_common import upsert_keyshop_offer
from app.parsers.steam_catalog import _upsert_steam_offer


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


def test_keyshop_upsert_same_price_bumps_verified_at(db: Session, monkeypatch):
    monkeypatch.setattr(
        "app.parsers.keyshop_common.make_affiliate_link",
        lambda url, shop: url,
    )
    g = Game(
        title="Parity Stamp",
        slug="parity-stamp-999001",
        steam_appid=999001,
        steam_app_type="game",
        platform="pc",
        is_free=False,
        steam_enriched=True,
    )
    db.add(g)
    db.flush()
    old = datetime.utcnow() - timedelta(days=5)
    offer = Offer(
        game_id=g.id,
        shop_name="Instant Gaming",
        price_pln=55.0,
        affiliate_url="https://www.instant-gaming.com/pl/parity-stamp-game/",
        is_official=False,
        in_stock=True,
        match_confidence=1.5,
        activation_region="global",
        updated_at=old,
        last_verified_at=old,
        last_check_status="verified",
    )
    db.add(offer)
    db.flush()
    ok = upsert_keyshop_offer(
        db,
        g,
        "Instant Gaming",
        "https://www.instant-gaming.com/pl/parity-stamp-game/",
        55.0,
        match_confidence=1.5,
        activation_region="global",
        product_title="Parity Stamp",
    )
    assert ok is True
    db.refresh(offer)
    assert offer.last_check_status == "verified"
    assert offer.last_verified_at is not None
    assert offer.last_verified_at > old
    assert offer.updated_at is not None
    assert offer.updated_at > old


def test_steam_upsert_same_price_bumps_verified_at(db: Session):
    g = Game(
        title="Steam Stamp",
        slug="steam-stamp-999002",
        steam_appid=999002,
        steam_app_type="game",
        platform="pc",
        is_free=False,
        steam_enriched=True,
    )
    db.add(g)
    db.flush()
    old = datetime.utcnow() - timedelta(days=3)
    offer = Offer(
        game_id=g.id,
        shop_name="Steam",
        price_pln=100.0,
        affiliate_url="https://store.steampowered.com/app/999002",
        is_official=True,
        in_stock=True,
        updated_at=old,
        last_verified_at=None,
    )
    db.add(offer)
    db.flush()
    data = {
        "price_overview": {
            "currency": "PLN",
            "final": 10000,
            "initial": 10000,
        },
        "is_free": False,
    }
    _upsert_steam_offer(db, g, 999002, data)
    db.refresh(offer)
    assert offer.last_verified_at is not None
    assert offer.last_verified_at > old
    assert offer.last_check_status == "verified"
    assert float(offer.price_pln) == pytest.approx(100.0)


def test_keyshop_replay_does_not_stamp_verification(db: Session, monkeypatch):
    monkeypatch.setattr(
        "app.parsers.keyshop_common.make_affiliate_link",
        lambda url, shop: url,
    )
    g = Game(
        title="Replay Stamp",
        slug="replay-stamp-999003",
        steam_appid=999003,
        steam_app_type="game",
        platform="pc",
        is_free=False,
        steam_enriched=True,
    )
    db.add(g)
    db.flush()
    old = datetime.utcnow() - timedelta(days=2)
    offer = Offer(
        game_id=g.id,
        shop_name="Instant Gaming",
        price_pln=40.0,
        affiliate_url="https://www.instant-gaming.com/pl/replay-stamp/",
        is_official=False,
        in_stock=True,
        match_confidence=1.5,
        activation_region="global",
        updated_at=old,
        last_verified_at=old,
        last_check_status="verified",
    )
    db.add(offer)
    db.flush()
    ok = upsert_keyshop_offer(
        db,
        g,
        "Instant Gaming",
        "https://www.instant-gaming.com/pl/replay-stamp/",
        42.0,
        match_confidence=1.5,
        activation_region="global",
        product_title="Replay Stamp",
        live_fetch=False,
    )
    assert ok is True
    db.refresh(offer)
    assert float(offer.price_pln) == pytest.approx(42.0)
    assert offer.last_verified_at == old
    assert offer.last_check_status == "skipped"
