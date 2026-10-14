"""SEO landings must use the same quality best-price rules as /gra/{slug}."""
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
        steam_appid=700000 + n,
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
    if steam_price and best_price and best_price < steam_price:
        savings_pct = int(round(((steam_price - best_price) / steam_price) * 100))
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


def test_budget_landing_rejects_marketplace_outlier_like_neo_cab(db: Session):
    """Raw Kinguin 0.37 must not win over GOG 10.19 on gry-pc-do-30-zl."""
    g = _game(db, title="Neo Cab", slug="neo-cab-794540", steam_appid=794540)
    _offer(db, g, "Kinguin", 0.37, is_official=False, match_confidence=1.35)
    # Cluster peers so GOG is not false-flagged as a peer outlier vs Steam alone.
    _offer(db, g, "Gamivo", 1.94, is_official=False, match_confidence=1.35)
    _offer(db, g, "G2A", 2.58, is_official=False, match_confidence=1.25)
    _offer(db, g, "Instant Gaming", 4.37, is_official=False, match_confidence=1.5)
    _offer(db, g, "GOG", 10.19, is_official=True)
    _offer(db, g, "Steam", 67.99, is_official=True)

    quality = best_offers_map(db, [g.id], region="pl")
    assert g.id in quality
    assert float(quality[g.id].price_pln) == pytest.approx(10.19)

    landing = SeoLanding("gry-pc-do-30-zl", "budget", "Gry PC do 30 zł", "cena", max_price=30)
    items = collect_landing_items(db, landing, build_item=_build_item, limit=60)
    by_slug = {i.slug: i for i in items}
    assert "neo-cab-794540" in by_slug
    assert by_slug["neo-cab-794540"].best_price_pln == pytest.approx(10.19)
    assert by_slug["neo-cab-794540"].best_shop_name == "GOG"


def test_budget_landing_drops_game_when_only_outlier_is_under_cap(db: Session):
    """If quality best is above budget, game must not appear even with a raw outlier under cap."""
    g = _game(db, title="Expensive Base", slug="expensive-base", steam_appid=900001)
    _offer(db, g, "Kinguin", 0.50, is_official=False, match_confidence=1.2)
    _offer(db, g, "Steam", 199.0, is_official=True)
    # No other eligible marketplace; Steam 199 is quality best → over 30 zł.

    landing = SeoLanding("gry-pc-do-30-zl", "budget", "Gry PC do 30 zł", "cena", max_price=30)
    items = collect_landing_items(db, landing, build_item=_build_item, limit=60)
    assert all(i.slug != "expensive-base" for i in items)


def test_landing_price_matches_canonical_best_map(db: Session):
    g = _game(db, title="Fair Deal", slug="fair-deal", steam_appid=900002)
    _offer(db, g, "Instant Gaming", 18.0, is_official=False, match_confidence=0.9)
    _offer(db, g, "Fanatical", 19.5, is_official=False, match_confidence=0.95)
    _offer(db, g, "Steam", 40.0, is_official=True)

    landing = SeoLanding("gry-pc-do-30-zl", "budget", "Gry PC do 30 zł", "cena", max_price=30)
    items = collect_landing_items(db, landing, build_item=_build_item, limit=60)
    quality = best_offers_map(db, [g.id], region="pl")[g.id]
    item = next(i for i in items if i.slug == "fair-deal")
    assert item.best_price_pln == pytest.approx(float(quality.price_pln))
    assert item.best_shop_name == quality.shop_name
