"""Critical SEO/price correctness: matching, F2P, worth-buy, history isolation."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.game_offer_selection import best_offers_map
from app.core.price_history import record_offer_price_change, update_game_price_rollups
from app.core.worth_buy import compute_worth_buy
from app.models.models import Base, Game, Offer, PriceSnapshot  # noqa: F401 — Offer used in upsert tests
from app.parsers.keyshop_common import (
    classify_keyshop_product,
    is_confident_match,
    title_match_score,
    title_mismatch,
)


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


def _add_game(db: Session, **kwargs) -> Game:
    defaults = {
        "platform": "pc",
        "steam_enriched": True,
        "is_free": False,
    }
    defaults.update(kwargs)
    g = Game(**defaults)
    db.add(g)
    db.flush()
    return g


def _add_offer(db: Session, game: Game, **kwargs) -> Offer:
    defaults = {
        "game_id": game.id,
        "shop_name": "Kinguin",
        "price_pln": 49.99,
        "in_stock": True,
        "is_official": False,
        "match_confidence": 0.9,
        "affiliate_url": "https://example.com/offer",
    }
    defaults.update(kwargs)
    o = Offer(**defaults)
    db.add(o)
    db.flush()
    return o


# --- 1–3 matching ---


def test_plague_tale_legacy_rejects_innocence():
    q = "Resonance: A Plague Tale Legacy"
    c = "A Plague Tale: Innocence"
    assert title_mismatch(q, c) is True
    assert title_match_score(q, c) == 0.0
    ok, score = is_confident_match(q, c)
    assert ok is False
    assert score == 0.0
    verdict = classify_keyshop_product(q, c, "https://example.com/a-plague-tale-innocence")
    assert verdict["valid"] is False
    assert verdict["reason"] == "title_mismatch"
    # Real GOG URL that was wrongly attached on production.
    gog = classify_keyshop_product(
        q,
        "a plague tale innocence",
        "https://www.gog.com/pl/game/a_plague_tale_innocence",
    )
    assert gog["valid"] is False
    assert gog["reason"] == "title_mismatch"


def test_plague_tale_siblings_do_not_cross_match():
    pairs = [
        ("A Plague Tale: Innocence", "A Plague Tale: Requiem"),
        ("A Plague Tale: Requiem", "Resonance: A Plague Tale Legacy"),
        ("Resonance: A Plague Tale Legacy", "A Plague Tale: Innocence"),
    ]
    for a, b in pairs:
        assert title_mismatch(a, b) is True, (a, b)
        assert title_match_score(a, b) == 0.0


def test_edition_extras_still_allowed():
    # Deluxe / Ultimate fluff must not hard-reject same base title.
    assert title_mismatch("Cyberpunk 2077", "Cyberpunk 2077 Ultimate Edition") is False
    assert title_match_score("Cyberpunk 2077", "Cyberpunk 2077 Ultimate Edition") > 0.45
    # Epic store URL suffix "-02" is SKU fluff, not a different product.
    assert title_mismatch(
        "Resonance: A Plague Tale Legacy",
        "resonance a plague tale legacy 02",
    ) is False
    epic = classify_keyshop_product(
        "Resonance: A Plague Tale Legacy",
        "resonance a plague tale legacy 02",
        "https://store.epicgames.com/pl/p/resonance-a-plague-tale-legacy-02",
    )
    assert epic["valid"] is True
    assert title_mismatch("Portal", "Portal 2") is True


def test_dlc_not_treated_as_base_game():
    assert title_mismatch("Cyberpunk 2077", "Cyberpunk 2077 Phantom Liberty DLC") is True
    verdict = classify_keyshop_product(
        "Cyberpunk 2077",
        "Cyberpunk 2077 - Phantom Liberty DLC",
        "https://example.com/cyberpunk-2077-phantom-liberty-dlc",
    )
    assert verdict["valid"] is False


def test_paid_game_still_matches_same_title():
    ok, score = is_confident_match("Elden Ring", "ELDEN RING PC")
    assert ok is True
    assert score >= 0.45


def test_localized_title_not_false_positive_mismatch():
    # Polish DB title vs English storefront must not hard-reject.
    assert title_mismatch(
        "Wiedźmin 3: Dziki Gon - Edycja Kompletna",
        "The Witcher 3: Wild Hunt",
    ) is False


def test_weak_shared_token_rejects_unrelated_fortress_games():
    assert title_mismatch(
        "Team Fortress 2",
        "Avadon: The Black Fortress",
    ) is True
    assert title_mismatch(
        "Team Fortress 2",
        "Two Worlds 2 Pirates of the Flying Fortress",
    ) is True


# --- 4–7 F2P pricing ---


def test_cs2_is_free_best_price_zero(db: Session):
    g = _add_game(
        db,
        title="Counter-Strike 2",
        slug="counter-strike-2-730",
        steam_appid=730,
        is_free=True,
    )
    _add_offer(db, g, shop_name="Steam", price_pln=0.0, is_official=True, match_confidence=None)
    _add_offer(db, g, shop_name="Kinguin", price_pln=131.88, match_confidence=0.9)
    best = best_offers_map(db, [g.id], games={g.id: g})
    assert g.id not in best  # paid keyshop must not win


def test_tf2_is_free_best_price_zero(db: Session):
    g = _add_game(
        db,
        title="Team Fortress 2",
        slug="team-fortress-2-440",
        steam_appid=440,
        is_free=True,
    )
    _add_offer(db, g, shop_name="G2A", price_pln=45.0, match_confidence=0.8)
    best = best_offers_map(db, [g.id], games={g.id: g})
    assert g.id not in best


def test_paid_dlc_sibling_does_not_change_f2p_base_best(db: Session):
    base = _add_game(
        db,
        title="Counter-Strike 2",
        slug="counter-strike-2-730",
        steam_appid=730,
        is_free=True,
    )
    dlc = _add_game(
        db,
        title="CS2 Operation Pass",
        slug="cs2-operation-pass-999",
        steam_appid=999,
        is_free=False,
    )
    _add_offer(db, base, shop_name="Kinguin", price_pln=99.0, match_confidence=0.9)
    _add_offer(db, dlc, shop_name="Kinguin", price_pln=29.0, match_confidence=0.9)
    best = best_offers_map(db, [base.id, dlc.id], games={base.id: base, dlc.id: dlc})
    assert base.id not in best
    assert best[dlc.id].price_pln == 29.0


def test_temporary_name_free_does_not_force_is_free(db: Session):
    # is_free comes from Steam metadata, not title heuristics.
    g = _add_game(
        db,
        title="Some Free Weekend Demo",
        slug="some-free-weekend-demo-1",
        steam_appid=111,
        is_free=False,
    )
    _add_offer(db, g, shop_name="Steam", price_pln=59.0, is_official=True)
    best = best_offers_map(db, [g.id], games={g.id: g})
    assert best[g.id].price_pln == 59.0


# --- 8–10 worth-buy / history ---


def test_f2p_worth_buy_is_darmowa_not_kup_teraz():
    result = compute_worth_buy(
        current_price=131.88,
        avg_best_price_30d=140.0,
        lowest_ever_pln=80.0,
        savings_pct=40,
        at_historical_low=True,
        is_free=True,
    )
    assert result is not None
    assert result.tier == "free"
    assert result.label == "DARMOWA GRA"
    assert "KUP TERAZ" not in result.label


def test_paid_game_worth_buy_still_works():
    result = compute_worth_buy(
        current_price=40.0,
        avg_best_price_30d=55.0,
        lowest_ever_pln=38.0,
        steam_price_pln=100.0,
        savings_pct=60,
        at_historical_low=True,
        is_free=False,
        history_points=10,
    )
    assert result is not None
    assert result.tier == "buy"
    assert result.label == "KUP TERAZ"


def test_thin_history_does_not_get_kup_teraz():
    result = compute_worth_buy(
        current_price=114.65,
        avg_best_price_30d=114.65,
        lowest_ever_pln=114.65,
        steam_price_pln=149.99,
        savings_pct=23,
        at_historical_low=True,
        is_free=False,
        history_points=1,
    )
    assert result is not None
    assert result.tier != "buy"
    assert result.label != "KUP TERAZ"


def test_unverified_offer_blocks_kup_teraz():
    result = compute_worth_buy(
        current_price=40.0,
        avg_best_price_30d=55.0,
        lowest_ever_pln=38.0,
        savings_pct=60,
        at_historical_low=True,
        is_free=False,
        history_points=10,
        offer_verified=False,
    )
    assert result is not None
    assert result.tier == "wait"
    assert "KUP TERAZ" not in result.label


def test_f2p_does_not_record_paid_price_history(db: Session):
    g = _add_game(
        db,
        title="Counter-Strike 2",
        slug="counter-strike-2-730-h",
        steam_appid=731,
        is_free=True,
    )
    record_offer_price_change(
        db,
        game_id=g.id,
        shop_name="Kinguin",
        price_pln=131.88,
        previous_price=None,
    )
    snaps = db.query(PriceSnapshot).filter(PriceSnapshot.game_id == g.id).count()
    assert snaps == 0
    update_game_price_rollups(db, g.id)
    db.refresh(g)
    assert g.lowest_ever_pln is None
    assert g.avg_best_price_30d is None


def test_confirmed_same_price_not_error(db: Session):
    g = _add_game(
        db,
        title="Elden Ring",
        slug="elden-ring-hist",
        steam_appid=1245620,
        is_free=False,
    )
    record_offer_price_change(
        db, game_id=g.id, shop_name="Steam", price_pln=199.0, previous_price=None
    )
    # Identical observation must be a no-op, not an error.
    record_offer_price_change(
        db, game_id=g.id, shop_name="Steam", price_pln=199.0, previous_price=199.0
    )
    snaps = db.query(PriceSnapshot).filter(PriceSnapshot.game_id == g.id).all()
    assert len(snaps) == 1
    assert snaps[0].price_pln == 199.0


# --- 11 unverified / low confidence ---


def test_unverified_low_confidence_not_in_best_price(db: Session):
    g = _add_game(
        db,
        title="Hades II",
        slug="hades-ii-test",
        steam_appid=1145350,
        is_free=False,
    )
    _add_offer(db, g, shop_name="Steam", price_pln=120.0, is_official=True, match_confidence=None)
    _add_offer(
        db,
        g,
        shop_name="Kinguin",
        price_pln=10.0,
        match_confidence=0.40,  # below BEST_PRICE_MIN_CONFIDENCE
    )
    best = best_offers_map(db, [g.id], games={g.id: g})
    assert best[g.id].shop_name == "Steam"
    assert best[g.id].price_pln == 120.0


def test_gog_upsert_rejects_and_disables_wrong_franchise_url(db: Session):
    from app.parsers.keyshop_common import upsert_keyshop_offer

    g = _add_game(
        db,
        title="Resonance: A Plague Tale Legacy",
        slug="resonance-a-plague-tale-legacy-2713000",
        steam_appid=2713000,
        is_free=False,
    )
    bad = _add_offer(
        db,
        g,
        shop_name="GOG",
        price_pln=119.99,
        is_official=True,
        match_confidence=0.675,
        affiliate_url="https://www.gog.com/pl/game/a_plague_tale_innocence",
    )
    upsert_keyshop_offer(
        db,
        g,
        "GOG",
        "https://www.gog.com/pl/game/a_plague_tale_innocence",
        119.99,
        is_official=True,
        match_confidence=0.675,
    )
    db.flush()
    db.refresh(bad)
    assert bad.in_stock is False


def test_f2p_upsert_blocks_paid_keyshop(db: Session):
    from app.parsers.keyshop_common import upsert_keyshop_offer

    g = _add_game(
        db,
        title="Counter-Strike 2",
        slug="cs2-upsert-f2p",
        steam_appid=7301,
        is_free=True,
    )
    ok = upsert_keyshop_offer(
        db,
        g,
        "Kinguin",
        "https://www.kinguin.net/counter-strike-2",
        131.88,
        match_confidence=1.0,
    )
    assert ok is False
    steam_ok = upsert_keyshop_offer(
        db,
        g,
        "Steam",
        "https://store.steampowered.com/app/730",
        0.0,
        is_official=True,
    )
    assert steam_ok is True


def test_game_price_context_f2p(db: Session):
    from app.core.canonical_price import game_price_context

    g = _add_game(
        db,
        title="Team Fortress 2",
        slug="tf2-ctx",
        steam_appid=4401,
        is_free=True,
    )
    _add_offer(db, g, shop_name="Steam", price_pln=0.0, is_official=True)
    _add_offer(db, g, shop_name="G2A", price_pln=45.0, match_confidence=0.9)
    ctx = game_price_context(db, g)
    assert ctx.is_free is True
    assert ctx.price_pln == 0.0
    assert ctx.best_offer is None
    assert ctx.worth is not None
    assert ctx.worth.label == "DARMOWA GRA"


def test_epic_sku_suffix_still_upserts(db: Session):
    from app.parsers.keyshop_common import upsert_keyshop_offer

    g = _add_game(
        db,
        title="Resonance: A Plague Tale Legacy",
        slug="resonance-epic-ok",
        steam_appid=2713001,
        is_free=False,
    )
    ok = upsert_keyshop_offer(
        db,
        g,
        "Epic Games",
        "https://store.epicgames.com/pl/p/resonance-a-plague-tale-legacy-02",
        149.99,
        is_official=True,
        product_title="resonance a plague tale legacy 02",
    )
    assert ok is True
    offer = db.query(Offer).filter(Offer.game_id == g.id, Offer.shop_name == "Epic Games").one()
    assert offer.in_stock is True
