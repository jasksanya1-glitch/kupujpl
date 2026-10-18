"""Shop auth recovery: Fanatical/CDKeys blockers + Kinguin DEGRADED status."""
from __future__ import annotations

from app.core.offer_verification import shop_auth_blocker, shop_data_source_status
from app.parsers import affiliate_feeds as af
from app.parsers import cdkeys_parser as cd
from app.parsers.scanner_panel_detail import _human_status


def test_kinguin_never_auth_blocks_when_html_fallback_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(af, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(af, "_FEED_FAIL_UNTIL", {"Kinguin": 9e12})
    status = shop_data_source_status("Kinguin")
    assert status["block_scan"] is False
    assert status.get("html_fallback") is True
    assert status.get("degraded_reason")
    assert shop_auth_blocker("Kinguin") is None


def test_fanatical_blocks_without_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(af, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(af, "_FEED_FAIL_UNTIL", {})
    monkeypatch.setattr(af, "_awin_api_key", lambda: "")
    monkeypatch.setattr(af, "_feed_id", lambda shop: None)
    monkeypatch.setattr(af, "_custom_feed_urls", lambda shop: [])
    monkeypatch.setattr(af, "_merchant_id", lambda shop: "118821")
    monkeypatch.setattr(af, "_catalog_entry_for_merchant", lambda mid: None)
    status = shop_data_source_status("Fanatical")
    assert status["block_scan"] is True
    assert shop_auth_blocker("Fanatical")
    assert "AWIN_DATAFEED_API_KEY" in (status.get("owner_action") or "")


def test_cdkeys_blocks_without_algolia_or_feed(monkeypatch, tmp_path):
    monkeypatch.setattr(af, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(af, "_merchant_id", lambda shop: None)
    monkeypatch.setattr(af, "_custom_feed_urls", lambda shop: [])
    monkeypatch.setattr(cd, "_get_algolia_api_key", lambda: None)
    status = shop_data_source_status("CDKeys")
    assert status["block_scan"] is True
    assert "Algolia" in (status.get("block_reason") or "")
    assert shop_auth_blocker("CDKeys")


def test_cdkeys_allows_scan_when_feed_cache_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(af, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(cd, "_get_algolia_api_key", lambda: None)

    cache = tmp_path / "cdkeys.csv"
    cache.write_text("x", encoding="utf-8")
    monkeypatch.setattr(af, "_cache_path", lambda shop: cache)
    monkeypatch.setattr(af, "_read_cache_rows", lambda shop: [object()])
    status = shop_data_source_status("CDKeys")
    assert status["block_scan"] is False
    assert status.get("degraded_reason")
    assert shop_auth_blocker("CDKeys") is None


def test_human_status_degraded_not_auth_when_fallback_works():
    human = _human_status(
        is_active="active",
        sub_state="running",
        paused=False,
        auth_blocker=None,
        phase="running",
        heartbeat_age_sec=5.0,
        last_check_status="verified",
        verified_1h=12,
        degraded_reason="Awin feed unavailable; HTML search active",
    )
    assert human["status"] == "DEGRADED"
    assert human["code"] == "degraded"


def test_human_status_auth_when_truly_blocked():
    human = _human_status(
        is_active="active",
        sub_state="running",
        paused=False,
        auth_blocker="Fanatical affiliate feed unavailable",
        phase="auth_failed",
        heartbeat_age_sec=5.0,
        last_check_status="auth_failed",
        verified_1h=0,
        degraded_reason=None,
    )
    assert human["status"] == "AUTH_REQUIRED"


def test_stale_auth_phase_cleared_by_live_verifies():
    human = _human_status(
        is_active="active",
        sub_state="running",
        paused=False,
        auth_blocker=None,
        phase="auth_failed",
        heartbeat_age_sec=5.0,
        last_check_status="auth_failed",
        verified_1h=8,
        degraded_reason=None,
    )
    assert human["status"] == "WORKING"
