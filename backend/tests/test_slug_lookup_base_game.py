"""Short slug must resolve to the base game, not a higher-appid DLC/pack."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.slug_lookup import resolve_game_slug
from app.models.models import Base, Game, Offer


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_short_slug_prefers_base_rogue_trader_over_voidfarer_pack(db):
    base = Game(
        title="Warhammer 40,000: Rogue Trader",
        slug="warhammer-40000-rogue-trader-2186680",
        steam_appid=2186680,
        steam_enriched=True,
        steam_review_count=44349,
        platform="pc",
    )
    pack = Game(
        title="Warhammer 40,000: Rogue Trader - Voidfarer Pack",
        slug="warhammer-40000-rogue-trader-voidfarer-pack-2682670",
        steam_appid=2682670,
        steam_enriched=True,
        steam_review_count=68,
        platform="pc",
    )
    db.add_all([base, pack])
    db.flush()
    db.add(
        Offer(
            game_id=base.id,
            shop_name="Steam",
            price_pln=199.99,
            affiliate_url="https://store.steampowered.com/app/2186680",
            is_official=True,
            in_stock=True,
        )
    )
    db.add(
        Offer(
            game_id=pack.id,
            shop_name="Steam",
            price_pln=14.99,
            affiliate_url="https://store.steampowered.com/app/2682670",
            is_official=True,
            in_stock=True,
        )
    )
    db.commit()

    resolved = resolve_game_slug(db, "warhammer-40000-rogue-trader")
    assert resolved is not None
    assert resolved.steam_appid == 2186680
    assert resolved.id == base.id


def test_exact_slug_still_wins_when_present(db):
    pack = Game(
        title="Warhammer 40,000: Rogue Trader - Voidfarer Pack",
        slug="warhammer-40000-rogue-trader-voidfarer-pack-2682670",
        steam_appid=2682670,
        steam_enriched=True,
        steam_review_count=68,
        platform="pc",
    )
    db.add(pack)
    db.commit()
    resolved = resolve_game_slug(
        db, "warhammer-40000-rogue-trader-voidfarer-pack-2682670"
    )
    assert resolved is not None
    assert resolved.steam_appid == 2682670
