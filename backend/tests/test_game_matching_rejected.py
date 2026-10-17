"""Regression: wrong SKU / DLC / edition / bad URL must be REJECTED, not buyable unverified."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.price_engine import (
    evaluate_game_prices,
    offer_row_display_tier,
    rejected_offers_from_result,
    unverified_offers_from_result,
)
from app.core.product_matching import MatchStatus, evaluate_product_match
from app.core.url_validation import validate_offer_url
from app.models.models import Base, Game, Offer
from app.parsers.keyshop_common import title_mismatch

NOW = datetime(2026, 10, 17, 12, 0, 0)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def test_rogue_trader_dawn_of_war_gog_is_title_mismatch():
    assert title_mismatch(
        "Warhammer 40,000: Rogue Trader",
        "warhammer 40000 dawn of war anniversary edition",
    )
    g = Game(title="Warhammer 40,000: Rogue Trader", slug="rogue-trader", steam_appid=2186680)
    o = Offer(
        game_id=1,
        shop_name="GOG",
        price_pln=8.99,
        affiliate_url="https://www.gog.com/pl/game/warhammer_40000_dawn_of_war_anniversary_edition",
        is_official=True,
        in_stock=True,
        match_confidence=1.0,
        updated_at=NOW,
    )
    verdict = evaluate_product_match(o, g, steam_price_pln=199.99, now=NOW)
    assert verdict.status == MatchStatus.VERIFIED_MISMATCH
    assert verdict.edition_ok is False


def test_rogue_trader_gog_wrong_sku_rejected_not_unverified():
    db, engine = _session()
    try:
        g = Game(
            title="Warhammer 40,000: Rogue Trader",
            slug="rogue-trader",
            steam_appid=2186680,
        )
        db.add(g)
        db.flush()
        db.add_all(
            [
                Offer(
                    game_id=g.id,
                    shop_name="Steam",
                    price_pln=199.99,
                    affiliate_url="https://store.steampowered.com/app/2186680/",
                    is_official=True,
                    in_stock=True,
                    match_confidence=1.0,
                    updated_at=NOW,
                ),
                Offer(
                    game_id=g.id,
                    shop_name="Epic Games",
                    price_pln=199.99,
                    affiliate_url="https://store.epicgames.com/pl/p/warhammer-40000-rogue-trader",
                    is_official=True,
                    in_stock=True,
                    match_confidence=1.0,
                    updated_at=NOW,
                ),
                Offer(
                    game_id=g.id,
                    shop_name="GOG",
                    price_pln=8.99,
                    affiliate_url=(
                        "https://www.gog.com/pl/game/"
                        "warhammer_40000_dawn_of_war_anniversary_edition"
                    ),
                    is_official=True,
                    in_stock=True,
                    match_confidence=1.0,
                    updated_at=NOW,
                ),
            ]
        )
        db.commit()
        offers = db.query(Offer).filter(Offer.game_id == g.id).all()
        result = evaluate_game_prices(g, offers, now=NOW)
        gog = next(r for r in result.rows if r.offer.shop_name == "GOG")
        assert offer_row_display_tier(gog) == "rejected"
        unverified_shops = {o.shop_name for o, _ in unverified_offers_from_result(result)}
        assert "GOG" not in unverified_shops
        rejected_shops = {o.shop_name for o, _ in rejected_offers_from_result(result)}
        assert "GOG" in rejected_shops
        assert result.best_confirmed_offer is not None
        assert result.best_confirmed_offer.shop_name in {"Epic Games", "Steam"}
    finally:
        db.close()
        engine.dispose()


def test_kinguin_awin_url_allowed_with_kp_title():
    url = (
        "https://www.awin1.com/pclick.php?p=44982020025&a=2936531&m=125776"
        "#kp_title=Warhammer+40%2C000%3A+Rogue+Trader+EU+Steam+CD+Key"
    )
    assert validate_offer_url(url, "Kinguin").ok


def test_edition_dlc_url_rejected(db_factory=None):
    db, engine = _session()
    try:
        g = Game(title="Assetto Corsa", slug="assetto-corsa")
        db.add(g)
        db.flush()
        bad = Offer(
            game_id=g.id,
            shop_name="Fanatical",
            price_pln=57.0,
            affiliate_url="https://www.fanatical.com/pl/game/assetto-corsa-ultimate-edition",
            is_official=True,
            in_stock=True,
            match_confidence=1.0,
            updated_at=NOW,
        )
        db.add(bad)
        db.commit()
        result = evaluate_game_prices(g, [bad], now=NOW)
        row = result.rows[0]
        assert offer_row_display_tier(row) == "rejected"
        assert unverified_offers_from_result(result) == []
    finally:
        db.close()
        engine.dispose()


def test_private_url_rejected():
    db, engine = _session()
    try:
        g = Game(title="Bad URL", slug="bad-url")
        db.add(g)
        db.flush()
        o = Offer(
            game_id=g.id,
            shop_name="Kinguin",
            price_pln=10.0,
            affiliate_url="http://127.0.0.1/deal",
            in_stock=True,
            match_confidence=0.9,
            updated_at=NOW,
        )
        db.add(o)
        db.commit()
        result = evaluate_game_prices(g, [o], now=NOW)
        assert offer_row_display_tier(result.rows[0]) == "rejected"
        assert unverified_offers_from_result(result) == []
    finally:
        db.close()
        engine.dispose()
