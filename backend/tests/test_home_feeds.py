"""Tests for production home_feeds helpers (homepage deals / DLC)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core import home_feeds
from app.core.home_feeds import (
    deal_age_label,
    games_at_historical_low,
    games_freebies,
    games_new_deals,
    parent_game_for_dlc,
    related_dlc_games,
)
from app.models.models import Base, Game, Offer


@pytest.fixture
def db(monkeypatch) -> Session:
    monkeypatch.setattr(home_feeds, "_display_shops", lambda: ["Steam", "GOG", "Epic Games"])
    monkeypatch.setattr(home_feeds, "_steam_appdetails", lambda appid: None)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_home_feeds_exports_exist():
    for name in (
        "deal_age_label",
        "games_at_historical_low",
        "games_freebies",
        "games_new_deals",
        "parent_game_for_dlc",
        "related_dlc_games",
    ):
        assert callable(getattr(home_feeds, name))


def test_historical_low_and_freebies_structures(db: Session, monkeypatch):
    low = Game(
        title="Low Deal",
        slug="low-deal",
        steam_appid=101,
        is_free=False,
        lowest_ever_pln=19.99,
        steam_review_count=100,
    )
    free = Game(
        title="Free Game",
        slug="free-game",
        steam_appid=102,
        is_free=True,
        steam_review_count=50,
    )
    db.add_all([low, free])
    db.flush()
    db.add(
        Offer(
            game_id=low.id,
            shop_name="Steam",
            price_pln=19.99,
            affiliate_url="https://store.steampowered.com/app/101",
            in_stock=True,
            is_official=True,
        )
    )
    db.add(
        Offer(
            game_id=free.id,
            shop_name="Steam",
            price_pln=0.0,
            affiliate_url="https://store.steampowered.com/app/102",
            in_stock=True,
            is_official=True,
        )
    )
    db.commit()

    monkeypatch.setattr(
        "app.parsers.free_giveaways.get_free_giveaways",
        lambda _db: {"current": []},
    )

    hist = games_at_historical_low(db, limit=10)
    assert isinstance(hist, list)
    assert any(g.slug == "low-deal" for g in hist)

    freebies = games_freebies(db, limit=10)
    assert isinstance(freebies, list)
    assert any(g.slug == "free-game" for g in freebies)

    new_rows = games_new_deals(db, limit=10, hours=48)
    assert isinstance(new_rows, list)
    assert all(isinstance(row, tuple) and len(row) == 2 for row in new_rows)

    assert deal_age_label(None) is None


def test_dlc_helpers_do_not_crash(db: Session, monkeypatch):
    base = Game(
        title="Base Adventure",
        slug="base-adventure",
        steam_appid=201,
        steam_app_type="game",
        steam_review_count=20,
    )
    dlc = Game(
        title="Base Adventure: Extra Pack",
        slug="base-adventure-dlc",
        steam_appid=202,
        steam_app_type="dlc",
        steam_review_count=5,
    )
    db.add_all([base, dlc])
    db.commit()

    monkeypatch.setattr(
        home_feeds,
        "_steam_appdetails",
        lambda appid: {"fullgame": {"appid": 201}, "dlc": [202]} if appid == 202 else {"dlc": [202]},
    )

    parent = parent_game_for_dlc(db, dlc)
    assert parent is not None
    assert parent.slug == "base-adventure"

    related = related_dlc_games(db, base, limit=5)
    assert isinstance(related, list)
    assert any(g.slug == "base-adventure-dlc" for g in related)

    # Non-DLC parent lookup is a no-op
    assert parent_game_for_dlc(db, base) is None
