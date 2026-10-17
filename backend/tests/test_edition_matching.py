"""Wrong editions must not match base-game catalog pages."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.game_offer_selection import best_offers_map
from app.core.offer_quality import offer_edition_verified, offer_eligible_for_best_price
from app.models.models import Base, Game, Offer
from app.parsers.keyshop_common import classify_keyshop_product, edition_markers_mismatch


def test_ultimate_edition_rejected_for_standard_title():
    assert edition_markers_mismatch("Assetto Corsa", "Assetto Corsa Ultimate Edition")
    verdict = classify_keyshop_product(
        "Assetto Corsa",
        "Assetto Corsa Ultimate Edition",
        "https://www.awin1.com/pclick.php?p=1#kp_title=Assetto+Corsa+Ultimate+Edition",
    )
    assert verdict["valid"] is False
    assert verdict["reason"] == "edition_mismatch"


def test_standard_instant_gaming_accepted():
    verdict = classify_keyshop_product(
        "Assetto Corsa",
        "assetto corsa",
        "https://www.instant-gaming.com/pl/1263-assetto-corsa-pc-steam/",
    )
    assert verdict["valid"] is True


def test_best_offer_skips_ultimate_edition(monkeypatch):
    # Exercise edition filtering on the legacy selection path; PE V2 product-match
    # may independently exclude Instant Gaming (url/match), which is out of scope here.
    monkeypatch.setenv("PRICE_ENGINE_V2", "0")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    now = datetime.utcnow()
    try:
        game = Game(title="Assetto Corsa", slug="assetto-corsa-244210", steam_appid=244210)
        db.add(game)
        db.flush()
        db.add_all(
            [
                Offer(
                    game_id=game.id,
                    shop_name="Fanatical",
                    price_pln=57.55,
                    affiliate_url="https://www.awin1.com/pclick.php?p=1#kp_title=Assetto+Corsa+Ultimate+Edition",
                    in_stock=True,
                    match_confidence=1.35,
                    updated_at=now - timedelta(hours=6),
                ),
                Offer(
                    game_id=game.id,
                    shop_name="Instant Gaming",
                    # Clear PE ratio/outlier floors vs Steam 71.99 so only edition
                    # filtering decides Fanatical Ultimate is skipped.
                    price_pln=30.00,
                    affiliate_url="https://www.instant-gaming.com/pl/1263-assetto-corsa-pc-steam/",
                    in_stock=True,
                    match_confidence=1.5,
                    updated_at=now - timedelta(hours=6),
                ),
                Offer(
                    game_id=game.id,
                    shop_name="Steam",
                    price_pln=71.99,
                    affiliate_url="https://store.steampowered.com/app/244210",
                    in_stock=True,
                    is_official=True,
                    updated_at=now - timedelta(hours=6),
                ),
            ]
        )
        db.commit()
        best = best_offers_map(db, [game.id]).get(game.id)
        assert best is not None
        assert best.shop_name == "Instant Gaming"
        assert best.price_pln == 30.00
        assert not offer_edition_verified(
            db.query(Offer).filter(Offer.shop_name == "Fanatical").one(),
            game_title="Assetto Corsa",
        )
    finally:
        db.close()
        engine.dispose()


def test_stale_offer_cannot_confirm_best_price():
    offer = Offer(
        game_id=1,
        shop_name="Kinguin",
        price_pln=100.0,
        affiliate_url="https://www.kinguin.net/pl/category/1/resonance",
        in_stock=True,
        match_confidence=1.35,
        updated_at=datetime(2026, 9, 1),
    )
    assert not offer_eligible_for_best_price(
        offer,
        steam_price_pln=149.99,
        peer_prices=[110.0, 120.0],
        game_title="Resonance: A Plague Tale Legacy",
        now=datetime(2026, 10, 15),
    )
