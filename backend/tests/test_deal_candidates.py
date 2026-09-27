"""Phase 2 Deal Candidate Engine tests — false-positive hardened."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core import discover_candidates as dc
from app.core.articles import publish_article
from app.core.discover_candidates import (
    TYPE_BIG,
    TYPE_DROP,
    TYPE_EXPIRE,
    TYPE_FREE,
    TYPE_HIST,
    _fingerprint,
    _history_is_proven,
    _is_significant_drop,
    draft_from_candidate,
    ignore_candidate,
    list_candidates,
    scan_deal_candidates,
)
from app.models.models import Article, Base, DiscoverCandidate, Game, Offer, PriceSnapshot


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
    defaults = dict(
        title="Test Game",
        slug=f"test-game-{db.query(Game).count() + 1}",
        steam_appid=1000 + db.query(Game).count(),
        is_free=False,
        steam_review_count=100,
        steam_app_type="game",
    )
    defaults.update(kwargs)
    g = Game(**defaults)
    db.add(g)
    db.flush()
    return g


def _steam_url(game: Game) -> str:
    return f"https://store.steampowered.com/app/{game.steam_appid}"


def _same_shop_history(db: Session, game: Game, shop: str, prices: list[tuple[int, float]], now: datetime) -> None:
    for day, price in prices:
        db.add(
            PriceSnapshot(
                game_id=game.id,
                shop_name=shop,
                price_pln=price,
                in_stock=True,
                recorded_at=now - timedelta(days=day),
            )
        )


def test_free_game_with_same_shop_prior_snapshot(db: Session):
    g = _game(db, title="Promo Free", slug="promo-free")
    now = datetime.utcnow()
    for days, price in ((10, 95.0), (3, 89.0)):
        db.add(
            PriceSnapshot(
                game_id=g.id,
                shop_name="Epic Games",
                price_pln=price,
                in_stock=True,
                recorded_at=now - timedelta(days=days),
            )
        )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Epic Games",
            price_pln=0.0,
            original_price_pln=None,
            affiliate_url="https://example.com/free",
            in_stock=True,
            updated_at=now,
        )
    )
    db.commit()
    stats = scan_deal_candidates(db, limit=20)
    assert stats["by_type"].get(TYPE_FREE, 0) >= 1
    row = db.query(DiscoverCandidate).filter(DiscoverCandidate.reason == TYPE_FREE).first()
    assert row is not None
    assert row.price_previous == 89.0


def test_zero_weak_single_snapshot_no_free(db: Session):
    """Mechabellum-style: one ancient same-shop paid scrape is not enough."""
    g = _game(db, title="Weak Free", slug="weak-free")
    now = datetime.utcnow()
    db.add(
        PriceSnapshot(
            game_id=g.id,
            shop_name="Epic Games",
            price_pln=55.0,
            in_stock=True,
            recorded_at=now - timedelta(days=60),
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Epic Games",
            price_pln=0.0,
            original_price_pln=None,
            affiliate_url="https://example.com/weak",
            in_stock=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert db.query(DiscoverCandidate).filter(DiscoverCandidate.reason == TYPE_FREE).count() == 0


def test_out_of_stock_zero_no_free(db: Session):
    g = _game(db, title="OOS", slug="oos")
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=0.0,
            original_price_pln=40.0,
            affiliate_url="https://example.com/oos",
            in_stock=False,
            updated_at=datetime.utcnow(),
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert db.query(DiscoverCandidate).filter(DiscoverCandidate.reason == TYPE_FREE).count() == 0


def test_permanent_is_free_no_candidate(db: Session):
    g = _game(db, title="F2P", slug="f2p", is_free=True)
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=0.0,
            original_price_pln=20.0,
            affiliate_url="https://example.com/f2p",
            in_stock=True,
            updated_at=datetime.utcnow(),
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert db.query(DiscoverCandidate).filter(DiscoverCandidate.reason == TYPE_FREE).count() == 0


def test_stale_zero_offer_rejected(db: Session):
    g = _game(db, title="Stale Zero", slug="stale-zero")
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=0.0,
            original_price_pln=27.0,
            affiliate_url="https://store.steampowered.com/app/1",
            in_stock=True,
            updated_at=datetime.utcnow() - timedelta(days=30),
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert db.query(DiscoverCandidate).filter(DiscoverCandidate.reason == TYPE_FREE).count() == 0


def test_zero_with_only_other_shop_paid_rejected(db: Session):
    """PoE2-style: Epic 0 must not use Gamivo paid as previous."""
    g = _game(db, title="Cross Shop", slug="cross-shop")
    now = datetime.utcnow()
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Epic Games",
            price_pln=0.0,
            original_price_pln=None,
            affiliate_url="https://store.epicgames.com/pl/p/x",
            in_stock=True,
            updated_at=now,
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Gamivo",
            price_pln=98.0,
            affiliate_url="https://gamivo.example/x",
            in_stock=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert db.query(DiscoverCandidate).filter(DiscoverCandidate.reason == TYPE_FREE).count() == 0


def test_friends_pass_rejected(db: Session):
    g = _game(db, title="It Takes Two Friend's Pass", slug="friends-pass")
    now = datetime.utcnow()
    db.add(
        PriceSnapshot(
            game_id=g.id,
            shop_name="Epic Games",
            price_pln=40.0,
            in_stock=True,
            recorded_at=now - timedelta(days=2),
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Epic Games",
            price_pln=0.0,
            original_price_pln=40.0,
            affiliate_url="https://example.com/fp",
            in_stock=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert db.query(DiscoverCandidate).count() == 0


def test_dlc_type_rejected(db: Session):
    g = _game(db, title="Some Expansion", slug="dlc-x", steam_app_type="dlc")
    now = datetime.utcnow()
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=5.0,
            original_price_pln=20.0,
            affiliate_url="https://example.com/dlc",
            in_stock=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert db.query(DiscoverCandidate).count() == 0


def test_big_discount_uses_original_not_called_snapshot_drop(db: Session):
    g = _game(db, title="Half Off", slug="half-off")
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=50.0,
            original_price_pln=100.0,
            affiliate_url="https://example.com/50",
            in_stock=True,
            is_official=True,
            updated_at=datetime.utcnow(),
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    row = db.query(DiscoverCandidate).filter(DiscoverCandidate.reason == TYPE_BIG).first()
    assert row is not None
    assert row.discount_percent == 50
    assert "katalogowej" in (row.payload_json or "")
    assert '"confidence": "HIGH"' in (row.payload_json or "")


def test_keyshop_vs_steam_msrp_only_excluded(db: Session):
    g = _game(db, title="MSRP Gap", slug="msrp-gap", steam_review_count=9000)
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=100.0,
            original_price_pln=100.0,
            affiliate_url="https://store.steampowered.com/app/1",
            in_stock=True,
            is_official=True,
            updated_at=datetime.utcnow(),
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Instant Gaming",
            price_pln=8.0,
            original_price_pln=None,
            affiliate_url="https://example.com/ig",
            in_stock=True,
            is_official=False,
            updated_at=datetime.utcnow(),
        )
    )
    db.commit()
    stats = scan_deal_candidates(db, limit=40, dry_run=True)
    assert stats["msrp_excluded"] >= 1
    assert stats["by_type"].get(TYPE_BIG, 0) == 0


def test_keyshop_same_shop_prior_drop_included(db: Session):
    g = _game(db, title="IG Drop", slug="ig-drop")
    now = datetime.utcnow()
    db.add(
        PriceSnapshot(
            game_id=g.id,
            shop_name="Instant Gaming",
            price_pln=80.0,
            in_stock=True,
            recorded_at=now - timedelta(days=5),
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Instant Gaming",
            price_pln=30.0,
            original_price_pln=None,
            affiliate_url="https://example.com/igdrop",
            in_stock=True,
            is_official=False,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    row = (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_BIG)
        .first()
    )
    assert row is not None
    assert row.price_previous == 80.0
    assert '"evidence_source": "same_shop_prior"' in (row.payload_json or "")


def test_keyshop_trustworthy_original_included(db: Session):
    g = _game(db, title="IG Orig", slug="ig-orig")
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Kinguin",
            price_pln=20.0,
            original_price_pln=60.0,
            affiliate_url="https://example.com/korig",
            in_stock=True,
            is_official=False,
            match_confidence=0.9,
            updated_at=datetime.utcnow(),
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    row = db.query(DiscoverCandidate).filter(DiscoverCandidate.reason == TYPE_BIG).first()
    assert row is not None
    assert '"confidence": "MEDIUM"' in (row.payload_json or "")


def test_official_store_original_included(db: Session):
    g = _game(db, title="Steam Sale", slug="steam-sale")
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=24.99,
            original_price_pln=99.99,
            affiliate_url="https://store.steampowered.com/app/2",
            in_stock=True,
            is_official=True,
            updated_at=datetime.utcnow(),
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    row = db.query(DiscoverCandidate).filter(DiscoverCandidate.reason == TYPE_BIG).first()
    assert row is not None
    assert row.discount_percent >= 70
    assert '"confidence": "HIGH"' in (row.payload_json or "")


def test_original_lte_current_excluded(db: Session):
    g = _game(db, title="Bad Orig", slug="bad-orig")
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=50.0,
            original_price_pln=40.0,
            affiliate_url="https://example.com/badorig",
            in_stock=True,
            is_official=True,
            updated_at=datetime.utcnow(),
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert db.query(DiscoverCandidate).filter(DiscoverCandidate.reason == TYPE_BIG).count() == 0


def test_corrupt_20x_original_excluded(db: Session):
    g = _game(db, title="Ratio Boom", slug="ratio-boom")
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=5.0,
            original_price_pln=200.0,  # 40x
            affiliate_url="https://example.com/ratio",
            in_stock=True,
            is_official=True,
            updated_at=datetime.utcnow(),
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert db.query(DiscoverCandidate).filter(DiscoverCandidate.reason == TYPE_BIG).count() == 0


def test_stale_prior_snapshot_excluded_from_promo(db: Session):
    g = _game(db, title="Ancient Prior", slug="ancient-prior")
    now = datetime.utcnow()
    db.add(
        PriceSnapshot(
            game_id=g.id,
            shop_name="GOG",
            price_pln=90.0,
            in_stock=True,
            recorded_at=now - timedelta(days=90),
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="GOG",
            price_pln=30.0,
            original_price_pln=None,
            affiliate_url="https://example.com/ancient",
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason.in_([TYPE_BIG, TYPE_DROP]))
        .count()
        == 0
    )


def test_extreme_same_shop_cliff_excluded(db: Session):
    """Wrong-SKU style GOG cliff (163→9) must not become big_discount."""
    g = _game(db, title="Cliff Game", slug="cliff-game")
    now = datetime.utcnow()
    db.add(
        PriceSnapshot(
            game_id=g.id,
            shop_name="GOG",
            price_pln=163.99,
            in_stock=True,
            recorded_at=now - timedelta(days=10),
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="GOG",
            price_pln=8.99,
            original_price_pln=None,
            affiliate_url="https://example.com/cliff",
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id)
        .count()
        == 0
    )


def test_fresh_same_shop_drop_included(db: Session):
    g = _game(db, title="Fresh Drop", slug="fresh-drop")
    now = datetime.utcnow()
    db.add(
        PriceSnapshot(
            game_id=g.id,
            shop_name="Epic Games",
            price_pln=70.0,
            in_stock=True,
            recorded_at=now - timedelta(days=10),
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Epic Games",
            price_pln=55.0,
            affiliate_url="https://example.com/fresh",
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    row = (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_DROP)
        .first()
    )
    assert row is not None


def test_msrp_only_no_editorial_score():
    assert dc._editorial_score(45, type("G", (), {"steam_review_count": 99999})(), dc.CONF_LOW) == 0
    assert dc._editorial_score(35, type("G", (), {"steam_review_count": None})(), dc.CONF_HIGH) == 35 + dc.SCORE_CONF_HIGH


def test_default_panel_excludes_low(db: Session):
    g = _game(db, title="Low Conf", slug="low-conf")
    db.add(
        DiscoverCandidate(
            fingerprint="lowconf" + "0" * 32,
            game_id=g.id,
            reason=TYPE_BIG,
            score=99,
            shop_name="G2A",
            price_current=10.0,
            price_previous=100.0,
            discount_percent=90,
            status="open",
            payload_json='{"confidence":"LOW","reason_text":"msrp only"}',
        )
    )
    db.add(
        DiscoverCandidate(
            fingerprint="highconf" + "0" * 31,
            game_id=g.id,
            reason=TYPE_BIG,
            score=40,
            shop_name="Steam",
            price_current=20.0,
            price_previous=80.0,
            discount_percent=75,
            status="open",
            payload_json='{"confidence":"HIGH","reason_text":"real sale"}',
        )
    )
    db.commit()
    rows = list_candidates(db, status="open", limit=20)
    assert all('"confidence": "LOW"' not in (r.payload_json or "") for r in rows)
    assert any(r.score == 40 for r in rows)
    all_rows = list_candidates(db, status="open", limit=20, include_low_confidence=True)
    assert len(all_rows) >= 2


def test_price_drop_uses_prior_snapshot(db: Session):
    g = _game(db, title="Dropper", slug="dropper")
    now = datetime.utcnow()
    db.add(
        PriceSnapshot(
            game_id=g.id,
            shop_name="GOG",
            price_pln=80.0,
            in_stock=True,
            recorded_at=now - timedelta(days=2),
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="GOG",
            price_pln=60.0,
            affiliate_url="https://example.com/drop",
            in_stock=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    row = (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_DROP)
        .first()
    )
    assert row is not None
    assert row.price_previous == 80.0


def test_noise_price_drop_ignored():
    assert _is_significant_drop(100.0, 99.0) is False
    assert _is_significant_drop(100.0, 80.0) is True


def test_strictly_lower_than_prior_minimum_historical_low(db: Session):
    g = _game(db, title="New Low", slug="new-low")
    now = datetime.utcnow()
    _same_shop_history(
        db, g, "Steam", [(30, 50.0), (24, 49.0), (18, 48.0), (12, 47.0), (8, 46.0)], now
    )
    # Confirm current price (same timestamp as offer → excluded from prior via `< before`)
    db.add(
        PriceSnapshot(
            game_id=g.id,
            shop_name="Steam",
            price_pln=40.0,
            in_stock=True,
            recorded_at=now,
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=40.0,
            original_price_pln=46.0,
            affiliate_url=_steam_url(g),
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    row = (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .first()
    )
    assert row is not None
    assert row.historical_minimum == 46.0
    assert row.price_current == 40.0
    assert "KupujPL" in (row.payload_json or "")


def test_current_snapshot_excluded_from_historical_baseline(db: Session):
    """If only the current low exists in history inclusive, prior min stays higher."""
    g = _game(db, title="Exclude Self", slug="exclude-self")
    now = datetime.utcnow()
    for day in (28, 21, 14, 8):
        db.add(
            PriceSnapshot(
                game_id=g.id,
                shop_name="Steam",
                price_pln=60.0,
                in_stock=True,
                recorded_at=now - timedelta(days=day),
            )
        )
    # A snapshot at/after offer time must not lower the prior baseline
    db.add(
        PriceSnapshot(
            game_id=g.id,
            shop_name="Steam",
            price_pln=30.0,
            in_stock=True,
            recorded_at=now,
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=30.0,
            original_price_pln=60.0,
            affiliate_url=_steam_url(g),
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    row = (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .first()
    )
    assert row is not None
    assert row.historical_minimum == 60.0


def test_equal_to_old_minimum_no_historical_low(db: Session):
    g = _game(db, title="Flat Low", slug="flat-low")
    now = datetime.utcnow()
    for day in (28, 21, 14, 10, 8):
        db.add(
            PriceSnapshot(
                game_id=g.id,
                shop_name="Steam",
                price_pln=40.0,
                in_stock=True,
                recorded_at=now - timedelta(days=day),
            )
        )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=40.0,
            affiliate_url=_steam_url(g),
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .count()
        == 0
    )


def test_extreme_one_snapshot_drop_excluded(db: Session):
    """163→8.99 style: one offer scrape without confirmation is not hist-low."""
    g = _game(db, title="Cliff Game", slug="cliff-game")
    now = datetime.utcnow()
    _same_shop_history(db, g, "Steam", [(40, 163.99), (30, 163.99), (20, 163.99), (10, 163.99)], now)
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=8.99,
            affiliate_url=_steam_url(g),
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    stats = scan_deal_candidates(db, limit=20)
    assert (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .count()
        == 0
    )
    assert stats.get("suspicious_hist_excluded", 0) >= 1


def test_same_entity_repeated_confirmation_allows_extreme(db: Session):
    """Extreme ratio with 2 consecutive current snaps + original may pass under cliff*1.2."""
    g = _game(db, title="Confirmed Cliff", slug="confirmed-cliff")
    now = datetime.utcnow()
    # ratio 9.5 — between P95 and P99, needs confirmation
    _same_shop_history(db, g, "Steam", [(40, 95.0), (30, 95.0), (20, 95.0), (10, 95.0)], now)
    for minutes in (20, 5):
        db.add(
            PriceSnapshot(
                game_id=g.id,
                shop_name="Steam",
                price_pln=10.0,
                in_stock=True,
                recorded_at=now,  # not before offer.updated_at
            )
        )
    # bump second snap slightly after first for ordering; still not < before if before==now
    # Use identical `now` — prior filter is strict `<`.
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=10.0,
            original_price_pln=95.0,
            affiliate_url=_steam_url(g),
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .count()
        == 1
    )


def test_different_sku_entity_snapshots_excluded(db: Session):
    """GOG URL for a different product must not create hist-low."""
    g = _game(
        db,
        title="Warhammer 40,000: Dawn of War IV",
        slug="warhammer-40000-dawn-of-war-iv",
        steam_appid=2272360,
    )
    now = datetime.utcnow()
    _same_shop_history(db, g, "GOG", [(40, 163.99), (30, 163.99), (20, 163.99), (10, 163.99)], now)
    db.add(
        Offer(
            game_id=g.id,
            shop_name="GOG",
            price_pln=8.99,
            affiliate_url="https://www.gog.com/pl/game/warhammer_40000_dawn_of_war_anniversary_edition",
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .count()
        == 0
    )


def test_official_store_alone_not_sufficient(db: Session):
    """Steam without matching app URL / confirmation is not enough."""
    g = _game(db, title="No Identity", slug="no-identity")
    now = datetime.utcnow()
    _same_shop_history(db, g, "Steam", [(30, 50.0), (24, 49.0), (18, 48.0), (8, 46.0)], now)
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=20.0,
            affiliate_url="https://example.com/not-steam",
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    stats = scan_deal_candidates(db, limit=20)
    assert (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .count()
        == 0
    )
    assert stats.get("suspicious_hist_excluded", 0) >= 1


def test_ratio_cliff_guard_excludes(db: Session):
    g = _game(db, title="Hard Cliff", slug="hard-cliff")
    now = datetime.utcnow()
    _same_shop_history(db, g, "Steam", [(40, 200.0), (30, 200.0), (20, 200.0), (10, 200.0)], now)
    for _ in range(2):
        db.add(
            PriceSnapshot(
                game_id=g.id,
                shop_name="Steam",
                price_pln=10.0,
                in_stock=True,
                recorded_at=now,
            )
        )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=10.0,
            original_price_pln=200.0,
            affiliate_url=_steam_url(g),
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    # 20x > P99 cliff (10x) — excluded even with confirms (20 > 10*1.2)
    scan_deal_candidates(db, limit=20)
    assert (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .count()
        == 0
    )


def test_normal_genuine_lower_price_allowed(db: Session):
    g = _game(db, title="Genuine Low", slug="genuine-low")
    now = datetime.utcnow()
    _same_shop_history(db, g, "Steam", [(28, 80.0), (21, 75.0), (14, 70.0), (7, 70.0)], now)
    db.add(
        PriceSnapshot(
            game_id=g.id,
            shop_name="Steam",
            price_pln=55.0,
            in_stock=True,
            recorded_at=now,
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=55.0,
            original_price_pln=70.0,
            affiliate_url=_steam_url(g),
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .count()
        == 1
    )


def test_offer_without_current_snapshot_pending(db: Session):
    """Original_price alone without a current-price snapshot is not enough."""
    g = _game(db, title="Pending Confirm", slug="pending-confirm")
    now = datetime.utcnow()
    _same_shop_history(db, g, "Steam", [(28, 90.0), (21, 90.0), (14, 90.0), (7, 90.0)], now)
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=22.0,
            original_price_pln=90.0,
            affiliate_url=_steam_url(g),
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    stats = scan_deal_candidates(db, limit=20)
    assert (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .count()
        == 0
    )
    assert stats.get("suspicious_hist_excluded", 0) >= 1


def test_cross_shop_prior_not_used_for_hist(db: Session):
    """Game-wide cheap keyshop history must not seed Steam hist-low."""
    g = _game(db, title="Cross Shop", slug="cross-shop")
    now = datetime.utcnow()
    _same_shop_history(db, g, "Steam", [(28, 100.0), (21, 100.0), (14, 100.0), (7, 100.0)], now)
    # Keyshop history lower — must be ignored for Steam hist baseline
    for day in (25, 15, 8):
        db.add(
            PriceSnapshot(
                game_id=g.id,
                shop_name="Gamivo",
                price_pln=20.0,
                in_stock=True,
                recorded_at=now - timedelta(days=day),
            )
        )
    db.add(
        PriceSnapshot(
            game_id=g.id,
            shop_name="Steam",
            price_pln=80.0,
            in_stock=True,
            recorded_at=now,
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=80.0,
            original_price_pln=100.0,
            affiliate_url=_steam_url(g),
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    row = (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .first()
    )
    assert row is not None
    assert row.historical_minimum == 100.0


def test_stale_snapshots_excluded_from_hist(db: Session):
    """Offer older than MAX_OFFER_AGE cannot become hist-low."""
    g = _game(db, title="Stale Hist", slug="stale-hist")
    now = datetime.utcnow()
    _same_shop_history(db, g, "Steam", [(60, 50.0), (50, 50.0), (40, 50.0), (30, 50.0)], now)
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=20.0,
            original_price_pln=50.0,
            affiliate_url=_steam_url(g),
            in_stock=True,
            is_official=True,
            updated_at=now - timedelta(hours=100),
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .count()
        == 0
    )


def test_keyshop_alone_no_historical_low(db: Session):
    """Keyshop dump must not create historical_low editorial candidates."""
    g = _game(db, title="Keyshop Low", slug="keyshop-low")
    now = datetime.utcnow()
    for day, price in ((30, 50.0), (24, 49.0), (18, 48.0), (12, 47.0), (8, 46.0)):
        db.add(
            PriceSnapshot(
                game_id=g.id,
                shop_name="Steam",
                price_pln=price,
                in_stock=True,
                recorded_at=now - timedelta(days=day),
            )
        )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Gamivo",
            price_pln=5.0,
            affiliate_url="https://example.com/kv",
            in_stock=True,
            is_official=False,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .count()
        == 0
    )


def test_steam_us_alone_no_historical_low(db: Session):
    """Steam US FX mirrors are excluded from historical_low (PLN-first)."""
    g = _game(db, title="US Low", slug="us-low")
    now = datetime.utcnow()
    for day, price in ((30, 50.0), (24, 49.0), (18, 48.0), (12, 47.0), (8, 46.0)):
        db.add(
            PriceSnapshot(
                game_id=g.id,
                shop_name="Steam",
                price_pln=price,
                in_stock=True,
                recorded_at=now - timedelta(days=day),
            )
        )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam US",
            price_pln=10.0,
            affiliate_url="https://example.com/us",
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_HIST)
        .count()
        == 0
    )


def test_invalid_negative_null_rejected(db: Session):
    g = _game(db, title="Bad", slug="bad")
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=-1.0,
            original_price_pln=50.0,
            affiliate_url="https://example.com/neg",
            in_stock=True,
            updated_at=datetime.utcnow(),
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=20)
    assert db.query(DiscoverCandidate).count() == 0


def test_popularity_threshold():
    g_hi = Game(title="A", slug="a", steam_review_count=5000)
    g_lo = Game(title="B", slug="b", steam_review_count=4999)
    g_none = Game(title="C", slug="c", steam_review_count=None)
    assert dc._popular_bonus(g_hi) == 20
    assert dc._popular_bonus(g_lo) == 0
    assert dc._popular_bonus(g_none) == 0


def test_dedupe_idempotency(db: Session):
    g = _game(db, title="Dup", slug="dup")
    now = datetime.utcnow()
    db.add(
        PriceSnapshot(
            game_id=g.id,
            shop_name="Eneba",
            price_pln=100.0,
            in_stock=True,
            recorded_at=now - timedelta(days=2),
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Eneba",
            price_pln=40.0,
            original_price_pln=100.0,
            affiliate_url="https://example.com/d",
            in_stock=True,
            updated_at=now,
        )
    )
    db.commit()
    s1 = scan_deal_candidates(db, limit=20)
    s2 = scan_deal_candidates(db, limit=20)
    assert s1["created"] >= 1
    assert s2["created"] == 0
    assert s2["duplicates"] + s2["skipped"] >= 1


def test_lower_price_bypasses_cooldown(db: Session):
    g = _game(db, title="Lower", slug="lower")
    fp = _fingerprint(g.id, TYPE_BIG, "Eneba", 50.0)
    db.add(
        DiscoverCandidate(
            fingerprint=fp,
            game_id=g.id,
            reason=TYPE_BIG,
            score=25,
            shop_name="Eneba",
            price_current=50.0,
            price_previous=100.0,
            discount_percent=50,
            status="open",
            detected_at=datetime.utcnow(),
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Eneba",
            price_pln=30.0,
            original_price_pln=100.0,
            affiliate_url="https://example.com/l",
            in_stock=True,
            updated_at=datetime.utcnow(),
        )
    )
    db.commit()
    stats = scan_deal_candidates(db, limit=20)
    assert stats["created"] >= 1
    prices = [
        r.price_current
        for r in db.query(DiscoverCandidate).filter(DiscoverCandidate.game_id == g.id)
    ]
    assert 30.0 in prices


def test_candidate_to_draft_not_published(db: Session):
    g = _game(db, title="Draft Me", slug="draft-me")
    row = DiscoverCandidate(
        fingerprint=_fingerprint(g.id, TYPE_BIG, "Steam", 20.0),
        game_id=g.id,
        reason=TYPE_BIG,
        score=40,
        shop_name="Steam",
        price_current=20.0,
        price_previous=100.0,
        discount_percent=80,
        status="open",
        payload_json='{"reason_text":"test reason","game_title":"Draft Me","confidence":"HIGH"}',
    )
    db.add(row)
    db.commit()
    art = draft_from_candidate(db, row.id)
    assert art is not None
    assert art.status == "draft"
    assert art.date_published is None
    db.refresh(row)
    assert row.status == "drafted"
    assert row.article_id == art.id
    # Duplicate create-draft is blocked/idempotent — same draft article.
    art2 = draft_from_candidate(db, row.id)
    assert art2 is not None and art2.id == art.id
    assert art2.status == "draft"
    assert db.query(Article).filter(Article.game_id == g.id).count() == 1
    # Manual publish remains a separate step.
    publish_article(db, art)
    assert art.status == "published"


def test_steam_steam_us_editorial_collapse(db: Session):
    g = _game(db, title="Twin Steam", slug="twin-steam", steam_review_count=8000)
    now = datetime.utcnow()
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=24.99,
            original_price_pln=99.99,
            affiliate_url="https://store.steampowered.com/app/t",
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam US",
            price_pln=27.50,
            original_price_pln=110.0,
            affiliate_url="https://store.steampowered.com/app/t?cc=us",
            in_stock=True,
            is_official=True,
            updated_at=now - timedelta(hours=1),
        )
    )
    db.commit()
    stats = scan_deal_candidates(db, limit=40)
    assert stats.get("editorial_duplicates_collapsed", 0) >= 1
    rows = (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_BIG)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].shop_name == "Steam"
    assert "alternate_offers" in (rows[0].payload_json or "")
    assert "Steam US" in (rows[0].payload_json or "")


def test_gog_not_merged_with_steam(db: Session):
    g = _game(db, title="Cross Store", slug="cross-store")
    now = datetime.utcnow()
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=40.0,
            original_price_pln=100.0,
            affiliate_url="https://store.steampowered.com/app/c",
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="GOG",
            price_pln=35.0,
            original_price_pln=90.0,
            affiliate_url="https://www.gog.com/game/c",
            in_stock=True,
            is_official=True,
            updated_at=now,
        )
    )
    db.commit()
    scan_deal_candidates(db, limit=40)
    rows = (
        db.query(DiscoverCandidate)
        .filter(DiscoverCandidate.game_id == g.id, DiscoverCandidate.reason == TYPE_BIG)
        .all()
    )
    shops = {r.shop_name for r in rows}
    assert "Steam" in shops and "GOG" in shops


def test_ignored_blocks_draft(db: Session):
    g = _game(db, title="Ign", slug="ign")
    row = DiscoverCandidate(
        fingerprint=_fingerprint(g.id, TYPE_FREE, "Epic Games", 0.0),
        game_id=g.id,
        reason=TYPE_FREE,
        score=50,
        shop_name="Epic Games",
        price_current=0.0,
        price_previous=40.0,
        status="open",
    )
    db.add(row)
    db.commit()
    ignore_candidate(db, row.id)
    assert draft_from_candidate(db, row.id) is None


def test_expiry_requires_ends_at(db: Session, monkeypatch):
    g = _game(db, title="Expire", slug="expire-me")
    now = datetime.utcnow()

    def fake_giveaways(_db):
        return {
            "current": [
                {
                    "slug": g.slug,
                    "shop": "Epic Games",
                    "ends_at": (now + timedelta(hours=12)).isoformat() + "Z",
                    "original_price_pln": 59.0,
                }
            ]
        }

    monkeypatch.setattr("app.parsers.free_giveaways.get_free_giveaways", fake_giveaways)
    scan_deal_candidates(db, limit=20)
    row = db.query(DiscoverCandidate).filter(DiscoverCandidate.reason == TYPE_EXPIRE).first()
    assert row is not None
    assert row.valid_until is not None


def test_dry_run_writes_nothing(db: Session):
    g = _game(db, title="Dry", slug="dry")
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Gamivo",
            price_pln=25.0,
            original_price_pln=100.0,
            affiliate_url="https://example.com/dry",
            in_stock=True,
            updated_at=datetime.utcnow(),
        )
    )
    db.commit()
    stats = scan_deal_candidates(db, limit=20, dry_run=True)
    assert stats["dry_run"] is True
    assert stats["created"] >= 1
    assert db.query(DiscoverCandidate).count() == 0
