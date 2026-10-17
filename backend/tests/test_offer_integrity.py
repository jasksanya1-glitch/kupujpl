"""Price integrity + product matching regression (20 cases)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.price_engine import evaluate_game_prices, get_best_verified_offer
from app.core.price_engine_config import price_engine_v2_enabled
from app.core.product_matching import MatchStatus, evaluate_product_match
from app.core.url_validation import validate_offer_url
from app.models.models import Base, Game, Offer

NOW = datetime(2026, 10, 16, 12, 0, 0)


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


def game(db: Session, title: str, **kwargs) -> Game:
    g = Game(title=title, slug=title.lower().replace(" ", "-"), **kwargs)
    db.add(g)
    db.flush()
    return g


def _shop_url(shop: str, title: str) -> str:
    slug = title.lower().replace(" ", "-")
    templates = {
        "Instant Gaming": f"https://www.instant-gaming.com/pl/{slug}-game/",
        "Kinguin": f"https://www.kinguin.net/pl/{slug}-key",
        "Gamivo": f"https://www.gamivo.com/pl/{slug}-steam-key",
        "G2A": f"https://www.g2a.com/pl/{slug}-steam-key",
        "CDKeys": f"https://www.cdkeys.com/pl/{slug}-pc-steam",
        "Fanatical": f"https://www.fanatical.com/pl/game/{slug}",
        "GOG": f"https://www.gog.com/game/{slug}",
        "Epic Games": f"https://store.epicgames.com/pl/p/{slug}",
        "Steam": f"https://store.steampowered.com/app/123456/{slug}/",
    }
    return templates.get(shop, f"https://www.kinguin.net/pl/{slug}")


def offer(
    db: Session,
    g: Game,
    *,
    shop: str,
    price: float,
    updated_hours_ago: float = 1.0,
    confidence: float | None = 0.9,
    official: bool = False,
    url: str | None = None,
    in_stock: bool = True,
) -> Offer:
    o = Offer(
        game_id=g.id,
        shop_name=shop,
        price_pln=price,
        affiliate_url=url or _shop_url(shop, g.title),
        is_official=official,
        in_stock=in_stock,
        match_confidence=confidence,
        updated_at=NOW - timedelta(hours=updated_hours_ago),
    )
    db.add(o)
    db.flush()
    return o


def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("PRICE_ENGINE_V2", raising=False)
    assert price_engine_v2_enabled() is False


def test_url_allowlist_ok():
    assert validate_offer_url("https://store.steampowered.com/app/570/", "Steam").ok


def test_url_blocks_private_host():
    assert validate_offer_url("http://127.0.0.1/x", "Steam").result == "blocked_host"


def test_url_unknown_shop_blocked():
    assert validate_offer_url("https://evil.example/x", "Kinguin").result == "blocked_host"


def test_verified_match_fresh_keyshop(db: Session):
    g = game(db, "Hades II")
    o = offer(db, g, shop="Instant Gaming", price=117.0)
    verdict = evaluate_product_match(o, g, now=NOW)
    assert verdict.status == MatchStatus.VERIFIED_MATCH


def test_stale_becomes_pending_not_verified_min(db: Session):
    g = game(db, "Assetto Corsa")
    offer(db, g, shop="Instant Gaming", price=15.25, updated_hours_ago=80)
    result = evaluate_game_prices(g, g.offers, now=NOW)
    assert result.best_verified_offer is None
    assert result.stale_offers


def test_edition_mismatch_excluded(db: Session):
    g = game(db, "Assetto Corsa")
    bad_url = "https://www.fanatical.com/pl/game/assetto-corsa-ultimate-edition"
    offer(db, g, shop="Fanatical", price=57.0, official=True, url=bad_url)
    result = evaluate_game_prices(g, g.offers, now=NOW)
    assert result.best_verified_offer is None


def test_official_epic_not_peer_outlier(db: Session):
    g = game(db, "Rust")
    offer(db, g, shop="Steam", price=120.0, official=True, url="https://store.steampowered.com/app/252490/")
    offer(
        db,
        g,
        shop="Epic Games",
        price=56.99,
        official=True,
        url="https://store.epicgames.com/pl/p/rust",
    )
    result = evaluate_game_prices(g, g.offers, now=NOW)
    assert result.best_verified_price == 56.99


def test_low_confidence_keyshop_not_verified(db: Session):
    g = game(db, "Guacamelee")
    offer(db, g, shop="Kinguin", price=8.01, confidence=0.2)
    offer(
        db,
        g,
        shop="GOG",
        price=16.99,
        official=True,
        url="https://www.gog.com/game/guacamelee",
    )
    best = get_best_verified_offer(g, g.offers, now=NOW)
    assert best is not None
    assert best.shop_name == "GOG"


def test_free_game_epic_preferred(db: Session):
    g = game(db, "Rocket League", is_free=True, steam_appid=252950)
    offer(db, g, shop="Steam", price=0.0, official=True, url="https://store.steampowered.com/app/252950/")
    offer(
        db,
        g,
        shop="Epic Games",
        price=0.0,
        official=True,
        url="https://store.epicgames.com/pl/p/rocket-league",
    )
    result = evaluate_game_prices(g, g.offers, now=NOW)
    assert result.best_verified_offer is not None
    assert result.best_verified_offer.shop_name == "Epic Games"


def test_out_of_stock_ignored(db: Session):
    g2 = game(db, "Simulacra2")
    o1 = offer(db, g2, shop="Gamivo", price=1.85, in_stock=False)
    o2 = offer(db, g2, shop="Kinguin", price=3.40)
    result = evaluate_game_prices(g2, [o1, o2], now=NOW)
    assert result.best_verified_price == 3.40


def test_zero_price_paid_game_ignored(db: Session):
    g = game(db, "Paid Game", is_free=False)
    offer(db, g, shop="G2A", price=0.0, confidence=0.9)
    offer(db, g, shop="Kinguin", price=20.0)
    result = evaluate_game_prices(g, g.offers, now=NOW)
    assert result.best_verified_price == 20.0


def test_insufficient_data_without_confidence(db: Session):
    g = game(db, "Mystery")
    o = offer(db, g, shop="CDKeys", price=10.0, confidence=None)
    verdict = evaluate_product_match(o, g, now=NOW)
    assert verdict.status in {MatchStatus.INSUFFICIENT_DATA, MatchStatus.VERIFIED_MISMATCH}


def test_recommended_official_within_tolerance(db: Session):
    g = game(db, "Civ V")
    offer(db, g, shop="Instant Gaming", price=96.11)
    offer(
        db,
        g,
        shop="Steam",
        price=99.0,
        official=True,
        url="https://store.steampowered.com/app/8930/",
    )
    result = evaluate_game_prices(g, g.offers, now=NOW)
    assert result.recommended_offer is not None
    assert result.recommended_offer.shop_name in {"Instant Gaming", "Steam"}


def test_catalog_map_uses_verified_only(monkeypatch, db: Session):
    monkeypatch.setenv("PRICE_ENGINE_V2", "1")
    from app.core.game_offer_selection import best_offers_map

    g = game(db, "HOI4")
    offer(db, g, shop="Fanatical", price=35.56, updated_hours_ago=80)
    offer(db, g, shop="Instant Gaming", price=41.92)
    # Pin evaluation clock to the same NOW used by offer fixtures.
    m = best_offers_map(db, [g.id], now=NOW)
    assert m[g.id].shop_name == "Instant Gaming"


def test_stale_warning_still_verified(db: Session):
    g = game(db, "Schedule I")
    offer(db, g, shop="Instant Gaming", price=91.99, updated_hours_ago=30)
    result = evaluate_game_prices(g, g.offers, now=NOW)
    assert result.best_verified_offer is not None


def test_url_invalid_mismatch(db: Session):
    g = game(db, "Bad URL")
    o = offer(db, g, shop="Kinguin", price=10.0, url="http://127.0.0.1/deal")
    assert evaluate_product_match(o, g, now=NOW).status == MatchStatus.VERIFIED_MISMATCH


def test_empty_offers_no_crash(db: Session):
    g = game(db, "Empty")
    result = evaluate_game_prices(g, [], now=NOW)
    assert result.best_verified_offer is None


def test_history_eligible_uses_confidence(db: Session):
    g = game(db, "History")
    offer(db, g, shop="Kinguin", price=5.0, confidence=0.1)
    offer(db, g, shop="GOG", price=20.0, official=True, url="https://www.gog.com/game/history")
    result = evaluate_game_prices(g, g.offers, now=NOW)
    assert result.best_verified_price == 20.0


def test_deterministic_tie_break(db: Session):
    g = game(db, "Tie")
    offer(db, g, shop="Gamivo", price=10.0)
    offer(db, g, shop="Kinguin", price=10.0)
    a = get_best_verified_offer(g, g.offers, now=NOW)
    b = get_best_verified_offer(g, g.offers, now=NOW)
    assert a is not None and b is not None
    assert a.shop_name == b.shop_name
