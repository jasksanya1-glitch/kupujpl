"""Out-of-order / replay verification must not clobber newer stamps."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.offer_verification import record_verified_price
from app.models.models import Base, Game, Offer
from app.parsers.keyshop_common import upsert_keyshop_offer


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_record_verified_refuses_older_observed_at():
    db = _db()
    try:
        g = Game(title="OO", slug="oo", steam_appid=1, is_free=False)
        db.add(g)
        db.flush()
        newer = datetime.utcnow()
        older = newer - timedelta(hours=2)
        o = Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=50.0,
            affiliate_url="https://store.steampowered.com/app/1",
            in_stock=True,
            last_verified_at=newer,
            last_check_status="verified",
            updated_at=newer,
        )
        db.add(o)
        db.flush()
        changed = record_verified_price(
            o, price_pln=40.0, source="steam", previous_price=50.0, now=older
        )
        assert changed is False
        assert float(o.price_pln) == 50.0
        assert o.last_verified_at == newer
    finally:
        db.close()


def test_live_fetch_false_does_not_bump_verified(monkeypatch):
    db = _db()
    monkeypatch.setattr(
        "app.parsers.keyshop_common.make_affiliate_link",
        lambda url, shop: url,
    )
    try:
        g = Game(
            title="Replay",
            slug="replay",
            steam_appid=2,
            is_free=False,
            steam_enriched=True,
        )
        db.add(g)
        db.flush()
        old = datetime.utcnow() - timedelta(days=1)
        o = Offer(
            game_id=g.id,
            shop_name="Instant Gaming",
            price_pln=10.0,
            affiliate_url="https://www.instant-gaming.com/pl/x/",
            in_stock=True,
            match_confidence=1.5,
            activation_region="global",
            last_verified_at=old,
            last_check_status="verified",
            updated_at=old,
        )
        db.add(o)
        db.flush()
        upsert_keyshop_offer(
            db,
            g,
            "Instant Gaming",
            "https://www.instant-gaming.com/pl/x/",
            12.0,
            match_confidence=1.5,
            activation_region="global",
            product_title="Replay",
            live_fetch=False,
        )
        db.refresh(o)
        assert o.last_verified_at == old
        assert float(o.price_pln) == 12.0
    finally:
        db.close()
