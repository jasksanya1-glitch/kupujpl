"""Promocje listing prices must match canonical game-page best."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.game_offer_selection import best_offers_map
from app.core.seo_landings import SeoLanding, collect_landing_items
from app.models.models import Base, Game, Offer
from app.schemas.schemas import GameListResponse


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


def _game(db: Session, **kwargs) -> Game:
    n = db.query(Game).count() + 1
    defaults = dict(
        title=f"Game {n}",
        slug=f"game-{n}",
        steam_appid=800000 + n,
        is_free=False,
        steam_app_type="game",
        platform="pc",
        steam_enriched=True,
        steam_review_count=5000,
        steam_review_positive_pct=85.0,
        steam_recommendations=2000,
    )
    defaults.update(kwargs)
    g = Game(**defaults)
    db.add(g)
    db.flush()
    return g


def _offer(db: Session, game: Game, shop: str, price: float, **kwargs) -> Offer:
    defaults = dict(
        game_id=game.id,
        shop_name=shop,
        price_pln=price,
        in_stock=True,
        is_official=shop in {"Steam", "GOG", "Epic Games"},
        match_confidence=1.0 if shop not in {"Steam", "GOG", "Epic Games"} else None,
        affiliate_url=f"https://example.com/{shop}/{game.slug}",
        activation_region="global",
    )
    defaults.update(kwargs)
    o = Offer(**defaults)
    db.add(o)
    db.flush()
    return o


def _build_item(game: Game, best: Offer | None, steam: Offer | None) -> GameListResponse:
    steam_price = float(steam.price_pln) if steam and steam.price_pln else None
    best_price = float(best.price_pln) if best and best.price_pln else None
    savings_pct = None
    if steam_price and best_price and 0 < best_price < steam_price:
        savings_pct = int(round(((steam_price - best_price) / steam_price) * 100))
        if savings_pct < 1 or savings_pct > 99:
            savings_pct = None
    return GameListResponse(
        id=game.id,
        title=game.title,
        slug=game.slug,
        cover_image=None,
        steam_appid=game.steam_appid,
        platform="pc",
        best_price_pln=best_price,
        best_shop_name=best.shop_name if best else None,
        best_price_is_official=bool(best.is_official) if best else None,
        steam_price_pln=steam_price,
        savings_pct=savings_pct,
    )


def test_promocje_rejects_raw_cdkeys_outlier_like_frostpunk(db: Session):
    g = _game(db, title="Frostpunk 2", slug="frostpunk-2", steam_appid=1601580)
    # Production-style: CDKeys row without confidence must not win the listing.
    _offer(db, g, "CDKeys", 28.49, is_official=False, match_confidence=None)
    _offer(db, g, "Instant Gaming", 48.03, is_official=False, match_confidence=1.4)
    _offer(db, g, "Fanatical", 52.0, is_official=False, match_confidence=1.3)
    _offer(db, g, "Steam", 129.99, is_official=True)

    quality = best_offers_map(db, [g.id], region="pl")[g.id]
    assert float(quality.price_pln) == pytest.approx(48.03)

    landing = SeoLanding("promocje", "promocje", "Promocje", "inne", min_savings_pct=5)
    items = collect_landing_items(db, landing, build_item=_build_item, limit=60)
    by_slug = {i.slug: i for i in items}
    assert "frostpunk-2" in by_slug
    assert by_slug["frostpunk-2"].best_price_pln == pytest.approx(48.03)
    assert by_slug["frostpunk-2"].best_shop_name == "Instant Gaming"
