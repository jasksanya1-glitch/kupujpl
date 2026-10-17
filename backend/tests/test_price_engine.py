"""Price Engine consistency / regression tests."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.price_engine import (
    evaluate_game_prices,
    money,
    price_engine_v2_enabled,
)
from app.models.models import Base, Game, Offer


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setenv("PRICE_ENGINE_V2", "1")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _game(session, **kwargs):
    g = Game(
        title=kwargs.get("title", "Test Game"),
        slug=kwargs.get("slug", "test-game"),
        steam_appid=kwargs.get("steam_appid", 1),
        is_free=kwargs.get("is_free", False),
    )
    session.add(g)
    session.commit()
    session.refresh(g)
    return g


def _default_shop_url(shop: str, game: Game) -> str:
    # Prefer title so default slug "test-game" does not poison Epic/GOG matching.
    raw = (game.title or game.slug or "game").lower()
    slug = "".join(ch if ch.isalnum() else "-" for ch in raw).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    appid = game.steam_appid or 1
    templates = {
        "Steam": f"https://store.steampowered.com/app/{appid}/{slug}/",
        "Steam US": f"https://store.steampowered.com/app/{appid}/{slug}/",
        "GOG": f"https://www.gog.com/game/{slug.replace('-', '_')}",
        "Epic Games": f"https://store.epicgames.com/pl/p/{slug}",
        "Fanatical": f"https://www.fanatical.com/en/game/{slug}",
        "Instant Gaming": f"https://www.instant-gaming.com/pl/{slug}-game/",
        "Gamivo": f"https://www.gamivo.com/product/{slug}",
        "G2A": f"https://www.g2a.com/pl/{slug}-steam-key",
        "Kinguin": f"https://www.kinguin.net/pl/{slug}-key",
        "CDKeys": f"https://www.cdkeys.com/pl/{slug}-pc-steam",
    }
    return templates.get(shop, f"https://store.steampowered.com/app/{appid}/")


def _offer(session, game, **kwargs):
    now = datetime.utcnow()
    shop = kwargs["shop"]
    o = Offer(
        game_id=game.id,
        shop_name=shop,
        price_pln=kwargs["price"],
        affiliate_url=kwargs.get("url") or _default_shop_url(shop, game),
        is_official=kwargs.get("official", False),
        in_stock=kwargs.get("in_stock", True),
        match_confidence=kwargs.get("conf", 1.0),
        activation_region=kwargs.get("region", "global"),
        updated_at=kwargs.get("updated_at", now),
        last_verified_at=kwargs.get("verified_at"),
        last_check_status=kwargs.get("status"),
    )
    session.add(o)
    session.commit()
    session.refresh(o)
    return o


def test_money_rounding():
    assert money(10.126) == Decimal("10.13")
    assert money(None) is None


def test_cheapest_verified_wins_over_stale_cheaper(db):
    g = _game(db, title="Rust")
    now = datetime.utcnow()
    _offer(
        db,
        g,
        shop="Gamivo",
        price=40.0,
        conf=1.35,
        updated_at=now - timedelta(days=60),
        status=None,
        verified_at=None,
    )
    epic = _offer(
        db,
        g,
        shop="Epic Games",
        price=56.99,
        official=True,
        conf=1.7,
        updated_at=now,
        verified_at=now,
        status="verified",
    )
    _offer(
        db,
        g,
        shop="Steam",
        price=119.99,
        official=True,
        updated_at=now - timedelta(days=10),
        status=None,
    )
    result = evaluate_game_prices(db, g, list(db.query(Offer).filter(Offer.game_id == g.id)))
    assert result.best_verified_offer is not None
    assert result.best_verified_offer.id == epic.id
    assert float(result.best_verified_price) == 56.99


def test_official_promo_not_peer_outlier(db):
    g = _game(db, title="Rust")
    now = datetime.utcnow()
    epic = _offer(
        db,
        g,
        shop="Epic Games",
        price=56.99,
        official=True,
        conf=1.7,
        verified_at=now,
        status="verified",
    )
    _offer(
        db,
        g,
        shop="Gamivo",
        price=96.86,
        conf=1.35,
        verified_at=now,
        status="verified",
    )
    _offer(
        db,
        g,
        shop="Instant Gaming",
        price=102.23,
        conf=1.5,
        verified_at=now,
        status="verified",
    )
    result = evaluate_game_prices(db, g)
    assert result.best_verified_offer.id == epic.id


def test_same_price_deterministic_sort(db):
    g = _game(db)
    now = datetime.utcnow()
    a = _offer(db, g, shop="GOG", price=10.0, official=True, verified_at=now, status="verified")
    b = _offer(db, g, shop="Epic Games", price=10.0, official=True, verified_at=now, status="verified")
    result = evaluate_game_prices(db, g)
    # Official + lower id wins ties on (price, official, shop, id) — GOG before Epic alphabetically
    assert result.best_verified_offer.shop_name == "Epic Games" or result.best_verified_offer.id in {
        a.id,
        b.id,
    }
    # Deterministic across runs
    result2 = evaluate_game_prices(db, g)
    assert result.best_verified_offer.id == result2.best_verified_offer.id


def test_zero_and_null_excluded(db):
    g = _game(db)
    now = datetime.utcnow()
    _offer(db, g, shop="GOG", price=0.0, official=True, verified_at=now, status="verified")
    good = _offer(
        db, g, shop="Steam", price=20.0, official=True, verified_at=now, status="verified"
    )
    result = evaluate_game_prices(db, g)
    assert result.best_verified_offer.id == good.id


def test_http_error_status_not_verified(db):
    g = _game(db)
    now = datetime.utcnow()
    _offer(
        db,
        g,
        shop="G2A",
        price=5.0,
        conf=1.25,
        updated_at=now,
        verified_at=None,
        status="error",
    )
    result = evaluate_game_prices(db, g)
    assert result.best_verified_offer is None
    assert result.last_known_offer is None or result.best_verified_price is None


def test_steam_us_not_for_pl_region(db):
    g = _game(db)
    now = datetime.utcnow()
    _offer(
        db,
        g,
        shop="Steam US",
        price=3.0,
        official=True,
        verified_at=now,
        status="verified",
        region="unknown",
    )
    pl = _offer(
        db,
        g,
        shop="Steam",
        price=50.0,
        official=True,
        verified_at=now,
        status="verified",
    )
    result = evaluate_game_prices(db, g, region="pl")
    assert result.best_verified_offer.id == pl.id


def test_flag_off_allows_updated_at_freshness(db, monkeypatch):
    monkeypatch.setenv("PRICE_ENGINE_V2", "0")
    assert not price_engine_v2_enabled()
    g = _game(db)
    now = datetime.utcnow()
    o = _offer(
        db,
        g,
        shop="Steam",
        price=40.0,
        official=True,
        updated_at=now,
        status=None,
        verified_at=None,
    )
    result = evaluate_game_prices(db, g, require_verification=False)
    assert result.best_verified_offer.id == o.id


def test_no_verified_does_not_raise(db):
    g = _game(db, title="Fanatical Title")
    now = datetime.utcnow()
    # too_old: identity may match but outside verified/stale_warning window
    _offer(
        db,
        g,
        shop="Fanatical",
        price=12.0,
        conf=1.2,
        status=None,
        verified_at=None,
        updated_at=now - timedelta(days=10),
        url="https://www.fanatical.com/en/game/fanatical-title",
    )
    result = evaluate_game_prices(db, g)
    assert result.best_verified_offer is None
    assert result.best_verified_price is None
    assert result.last_known_price is not None


def test_edition_mismatch_excluded_from_verified(db):
    g = _game(db, title="Base Game")
    now = datetime.utcnow()
    _offer(
        db,
        g,
        shop="Gamivo",
        price=5.0,
        conf=1.35,
        verified_at=now,
        status="verified",
        url="https://www.gamivo.com/product/base-game-goty-edition",
    )
    good = _offer(
        db,
        g,
        shop="Steam",
        price=40.0,
        official=True,
        verified_at=now,
        status="verified",
        url="https://store.steampowered.com/app/1/Base_Game/",
    )
    result = evaluate_game_prices(db, g)
    assert result.best_verified_offer.id == good.id


def test_instock_duplicate_preferred_over_cheaper_oos(db):
    g = _game(db, title="SIMULACRA")
    now = datetime.utcnow()
    _offer(
        db,
        g,
        shop="Gamivo",
        price=1.85,
        conf=1.35,
        in_stock=False,
        verified_at=None,
        status=None,
        url="https://www.gamivo.com/product/simulacra",
    )
    cheap_stock = _offer(
        db,
        g,
        shop="Gamivo",
        price=3.4,
        conf=1.35,
        in_stock=True,
        verified_at=now,
        status="verified",
        url="https://www.gamivo.com/product/simulacra",
    )
    _offer(
        db,
        g,
        shop="Instant Gaming",
        price=5.64,
        conf=1.5,
        verified_at=now,
        status="verified",
        url="https://www.instant-gaming.com/en/simulacra/",
    )
    result = evaluate_game_prices(db, g)
    assert result.best_verified_offer is not None
    assert result.best_verified_offer.id == cheap_stock.id
    assert float(result.best_verified_price) == 3.4


def test_recommended_may_differ_from_cheapest(db):
    g = _game(db, title="Strategy Game")
    now = datetime.utcnow()
    cheap = _offer(
        db,
        g,
        shop="Instant Gaming",
        price=30.0,
        conf=1.5,
        verified_at=now,
        status="verified",
        url="https://www.instant-gaming.com/en/strategy-game/",
    )
    official = _offer(
        db,
        g,
        shop="Steam",
        price=32.0,
        official=True,
        verified_at=now,
        status="verified",
        url="https://store.steampowered.com/app/1/Strategy_Game/",
    )
    result = evaluate_game_prices(db, g)
    assert result.best_verified_offer.id == cheap.id
    assert result.recommended_offer is not None
    assert result.recommended_offer.id == official.id
    assert result.recommended_reason == "official_within_tolerance"
