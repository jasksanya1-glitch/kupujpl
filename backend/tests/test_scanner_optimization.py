"""Scanner optimization: CDKeys expiry, feed fail cache, shop queues."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import Base, Game, Offer
from app.parsers import affiliate_feeds as af
from app.parsers import cdkeys_parser as cd
from app.parsers.shop_scan_queue import (
    select_stale_game_ids_for_shop,
    shop_budget,
)


def test_cdkeys_rejects_expired_env_key(monkeypatch):
    # Build a fake secured key blob with expired validUntil.
    import base64

    expired = base64.b64encode(b"validUntil=1000").decode("ascii")
    monkeypatch.setenv("CDKEYS_ALGOLIA_API_KEY", expired)
    monkeypatch.setattr(cd, "_DEFAULT_ALGOLIA_KEY", "")
    monkeypatch.setattr(cd, "_cached_api_key", None)
    monkeypatch.setattr(cd, "_no_key_until", 0.0)
    monkeypatch.setattr(cd, "_circuit_open_until", 0.0)
    monkeypatch.setattr(cd, "_FETCH_URLS", ())
    assert cd._key_is_expired(expired)
    assert cd._get_algolia_api_key() is None


def test_affiliate_feed_url_redaction():
    url = "https://productdata.awin.com/datafeed/download/apikey/SECRETKEY123/fid/1"
    assert "SECRETKEY123" not in af._redact_feed_url(url)
    assert "REDACTED" in af._redact_feed_url(url)


def test_affiliate_negative_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(af, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(af, "_FEED_FAIL_BACKOFF_SEC", 60)
    af._FEED_FAIL_UNTIL.clear()
    af._mark_feed_fail("Fanatical", "HTTP 404")
    assert af._feed_fail_active("Fanatical")
    marker = tmp_path / "fanatical.fail"
    assert marker.is_file()
    af._FEED_FAIL_UNTIL.clear()
    af._load_fail_marker("Fanatical")
    assert af._feed_fail_active("Fanatical")


def test_shop_budget_and_stale_selection():
    b = shop_budget("Steam")
    assert b.concurrency >= 1 and b.rps > 0
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        now = datetime.utcnow()
        g1 = Game(title="Old", slug="old", steam_appid=1)
        g2 = Game(title="Fresh", slug="fresh", steam_appid=2)
        db.add_all([g1, g2])
        db.flush()
        db.add_all(
            [
                Offer(
                    game_id=g1.id,
                    shop_name="Steam",
                    price_pln=10,
                    affiliate_url="https://store.steampowered.com/app/1",
                    in_stock=True,
                    updated_at=now - timedelta(days=5),
                ),
                Offer(
                    game_id=g2.id,
                    shop_name="Steam",
                    price_pln=10,
                    affiliate_url="https://store.steampowered.com/app/2",
                    in_stock=True,
                    updated_at=now - timedelta(hours=1),
                ),
            ]
        )
        db.commit()
        ids = select_stale_game_ids_for_shop(
            db, "Steam", limit=10, stale_hours=24, tier_a_only=False
        )
        assert g1.id in ids
        assert g2.id not in ids
    finally:
        db.close()
        engine.dispose()
