"""Tier A/B/C mix must not starve Tier C and must not default to tier_a_only."""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import Base, Game, Offer
from app.parsers import shop_scan_queue as ssq


def test_select_stale_default_is_not_tier_a_only():
    sig = inspect.signature(ssq.select_stale_game_ids_for_shop)
    assert sig.parameters["tier_a_only"].default is False


def test_scan_shop_batch_passes_tier_a_only_false():
    src = inspect.getsource(ssq.scan_shop_batch)
    assert "tier_a_only=False" in src
    assert "after_game_id=0" in src


def test_tier_c_appears_in_mixed_batch(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        now = datetime.utcnow()
        old = now - timedelta(days=3)
        # Tier A-like (high reviews), Tier B, Tier C (low reviews)
        games = []
        for i, reviews in enumerate([20000, 800, 10, 5, 2, 1]):
            g = Game(
                title=f"G{i}",
                slug=f"g-{i}",
                steam_appid=1000 + i,
                steam_review_count=reviews,
            )
            db.add(g)
            games.append(g)
        db.flush()
        for g in games:
            db.add(
                Offer(
                    game_id=g.id,
                    shop_name="Steam",
                    price_pln=10.0,
                    affiliate_url=f"https://store.steampowered.com/app/{g.steam_appid}",
                    in_stock=True,
                    updated_at=old,
                    last_verified_at=old,
                    last_check_status="verified",
                )
            )
        db.commit()
        monkeypatch.setattr(ssq, "TIER_A_BATCH_PCT", 40)
        monkeypatch.setattr(ssq, "TIER_B_BATCH_PCT", 30)
        monkeypatch.setattr(ssq, "TIER_C_BATCH_PCT", 30)
        monkeypatch.setattr(ssq, "_tier_a_rank_map", lambda: {})
        monkeypatch.setattr(ssq, "_favorite_game_ids", lambda _db: set())
        ids = ssq.select_stale_game_ids_for_shop(
            db, "Steam", limit=6, stale_hours=24, tier_a_only=False
        )
        assert len(ids) == 6
        # At least one low-review (Tier C) game must be present
        review_by_id = {g.id: int(g.steam_review_count or 0) for g in games}
        assert any(review_by_id[i] < 500 for i in ids)
        # Mid-band (800 reviews) must classify as B when not in hot cache
        from app.parsers.shop_scan_queue import _classify_scan_tier

        mid = next(g for g in games if int(g.steam_review_count or 0) == 800)
        assert (
            _classify_scan_tier(
                mid.id, 800, tier_rank={}, favorite_ids=set()
            )
            == "B"
        )
    finally:
        db.close()
        engine.dispose()
