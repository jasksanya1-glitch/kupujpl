"""Confirmed best-price parity across API helpers for a diverse game sample."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.price_engine import best_offers_map_v2, evaluate_game_prices
from app.models.models import Base, Game, Offer


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


def _mk(db: Session, *, title: str, slug: str, appid: int, shops: list[tuple]) -> Game:
    g = Game(
        title=title,
        slug=slug,
        steam_appid=appid,
        steam_app_type="game",
        platform="pc",
        is_free=False,
        steam_enriched=True,
        steam_review_count=8000,
        steam_review_positive_pct=88.0,
        steam_recommendations=3000,
    )
    db.add(g)
    db.flush()
    now = datetime.utcnow()
    for shop, price, official, conf, url in shops:
        db.add(
            Offer(
                game_id=g.id,
                shop_name=shop,
                price_pln=price,
                in_stock=True,
                is_official=official,
                match_confidence=conf,
                affiliate_url=url,
                updated_at=now,
                last_verified_at=now,
                last_check_status="ok",
            )
        )
    db.flush()
    return g


def test_confirmed_best_matches_across_engine_and_map(db: Session):
    samples = [
        _mk(
            db,
            title="Parity Alpha",
            slug="parity-alpha-1",
            appid=1001,
            shops=[
                ("Steam", 100.0, True, 1.0, "https://store.steampowered.com/app/1001/"),
                (
                    "Instant Gaming",
                    55.0,
                    False,
                    1.5,
                    "https://www.instant-gaming.com/pl/parity-alpha-game/",
                ),
                (
                    "Gamivo",
                    52.0,
                    False,
                    1.4,
                    "https://www.gamivo.com/product/parity-alpha",
                ),
            ],
        ),
        _mk(
            db,
            title="Parity Solo",
            slug="parity-solo-2",
            appid=1002,
            shops=[
                ("Steam", 40.0, True, 1.0, "https://store.steampowered.com/app/1002/"),
            ],
        ),
        _mk(
            db,
            title="Parity Empty",
            slug="parity-empty-3",
            appid=1003,
            shops=[],
        ),
    ]
    # Pad to >= 3 distinct scenarios; expand map coverage.
    for i in range(4, 12):
        samples.append(
            _mk(
                db,
                title=f"Parity Pack {i}",
                slug=f"parity-pack-{i}",
                appid=2000 + i,
                shops=[
                    (
                        "Steam",
                        80.0 + i,
                        True,
                        1.0,
                        f"https://store.steampowered.com/app/{2000 + i}/",
                    ),
                    (
                        "Instant Gaming",
                        40.0 + i,
                        False,
                        1.5,
                        f"https://www.instant-gaming.com/pl/parity-pack-{i}-game/",
                    ),
                ],
            )
        )

    ids = [g.id for g in samples]
    best_map = best_offers_map_v2(db, ids, region="pl")
    mismatches = []
    for g in samples:
        offers = [o for o in g.offers if o.in_stock and o.price_pln and o.price_pln > 0]
        engine = evaluate_game_prices(g, offers, region="pl")
        eng_best = engine.best_confirmed_offer
        map_best = best_map.get(g.id)
        eng_price = float(eng_best.price_pln) if eng_best else None
        map_price = float(map_best.price_pln) if map_best else None
        if eng_price != map_price:
            mismatches.append((g.slug, eng_price, map_price))
    assert mismatches == []
    assert len(samples) >= 10
