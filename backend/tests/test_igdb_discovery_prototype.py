"""Tests for IGDB discovery v2 (no live API required for unit suite)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tools.igdb_discovery.classify import (
    BUCKET_ALREADY,
    BUCKET_APPROVABLE,
    BUCKET_F2P,
    BUCKET_NEEDS_REVIEW,
    BUCKET_QUARANTINE,
    BUCKET_REJECTED,
    classify,
)
from tools.igdb_discovery.client import IgdbClient
from tools.igdb_discovery.fetchers import IgdbCandidate, is_pc_mainline
from tools.igdb_discovery.matching import CatalogIndex, looks_like_edition_or_dlc, normalize_title
from tools.igdb_discovery.popularity import normalize_within
from tools.igdb_discovery.steam_verify import SteamCheck, titles_compatible
from tools.igdb_discovery.staging import StagingStore
# SteamCheck used in classify bucket tests below


def _cand(**kwargs) -> IgdbCandidate:
    base = dict(
        igdb_id=1,
        name="Test Game",
        slug="test-game",
        game_type=0,
        first_release_date=1_700_000_000,
        steam_appid=111,
        source="popular",
    )
    base.update(kwargs)
    return IgdbCandidate(**base)


def test_normalize_title():
    assert normalize_title("Cyberpunk 2077!") == "cyberpunk 2077"
    assert normalize_title("  Baldur's Gate III ") == "baldur s gate iii"


def test_is_pc_mainline_filters_dlc_and_non_pc():
    ok, reason = is_pc_mainline(
        {"id": 1, "name": "Foo", "platforms": [6], "game_type": 0, "version_parent": None}
    )
    assert ok and reason == "ok"
    ok, reason = is_pc_mainline(
        {"id": 2, "name": "Foo DLC", "platforms": [6], "game_type": 1, "parent_game": 1}
    )
    assert not ok
    ok, reason = is_pc_mainline(
        {"id": 3, "name": "Console Only", "platforms": [48], "game_type": 0}
    )
    assert not ok and reason == "not_pc"


def test_edition_markers():
    assert looks_like_edition_or_dlc("Game Deluxe Edition")
    assert looks_like_edition_or_dlc("Game Soundtrack")
    assert not looks_like_edition_or_dlc("Elden Ring")


def test_titles_compatible_rejects_remaster_mismatch():
    ok, reason = titles_compatible("Dark Souls", "Dark Souls Remastered")
    assert not ok
    assert "edition_token" in reason
    ok, _ = titles_compatible("Elden Ring", "Elden Ring")
    assert ok


def test_normalize_within_metric_only():
    assert normalize_within([10, 20, 30]) == [0.0, 0.5, 1.0]
    assert normalize_within([5, 5, 5]) == [1.0, 1.0, 1.0]
    assert normalize_within([0, 0, 0]) == [0.0, 0.0, 0.0]
    assert normalize_within([10, None, 30])[1] is None


def test_catalog_match_primary_steam_and_quarantine(tmp_path: Path):
    db = tmp_path / "games.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, steam_appid INTEGER, "
        "platform TEXT, steam_app_type TEXT)"
    )
    con.execute("INSERT INTO games VALUES (1, 'Elden Ring', 1245620, 'pc', 'game')")
    con.execute("INSERT INTO games VALUES (2, 'PS Stub', NULL, 'ps', NULL)")
    con.commit()
    con.close()

    idx = CatalogIndex(db)
    assert idx.stats.without_steam == 1
    assert idx.stats.duplicate_steam_appids == 0

    hit = idx.match(_cand(name="Elden Ring", steam_appid=1245620))
    assert hit.status == "already_in_catalog"
    assert hit.match_method == "steam_appid"

    miss = idx.match(_cand(name="Brand New Indie", steam_appid=9990001, igdb_id=99))
    assert miss.status == "new_candidate"

    q = idx.match(_cand(name="Epic Only Title", steam_appid=None, igdb_id=12))
    assert q.status == "quarantine_no_steam"

    # Fuzzy must not auto-merge
    fuzzy = idx.match(_cand(name="Elden Ring Shadow", steam_appid=555, igdb_id=13))
    assert fuzzy.status in {"new_candidate", "ambiguous"}
    if fuzzy.status == "ambiguous":
        assert fuzzy.match_method == "fuzzy_manual_only"


def test_same_title_different_steam_is_ambiguous(tmp_path: Path):
    db = tmp_path / "games.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, steam_appid INTEGER, "
        "platform TEXT, steam_app_type TEXT)"
    )
    con.execute("INSERT INTO games VALUES (1, 'Portal', 400, 'pc', 'game')")
    con.commit()
    con.close()
    idx = CatalogIndex(db)
    m = idx.match(_cand(name="Portal", steam_appid=999888, igdb_id=7))
    assert m.status == "ambiguous"
    assert "different_steam" in m.reason


def test_related_edition_not_auto_merged(tmp_path: Path):
    db = tmp_path / "games.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, steam_appid INTEGER, "
        "platform TEXT, steam_app_type TEXT)"
    )
    con.execute(
        "INSERT INTO games VALUES (1, \"DEATH STRANDING DIRECTOR'S CUT\", 1850570, 'pc', 'game')"
    )
    con.commit()
    con.close()
    idx = CatalogIndex(db)
    m = idx.match(_cand(name="Death Stranding", steam_appid=1190460, igdb_id=19564))
    assert m.status == "ambiguous"
    assert "related_edition" in m.reason
    assert m.matched_steam_appid == 1850570
    assert m.match_method == "fuzzy_manual_only"


def test_classify_buckets():
    from tools.igdb_discovery.matching import MatchResult

    new = MatchResult(status="new_candidate", confidence=0.8, reason="x")
    already = MatchResult(status="already_in_catalog", confidence=1.0, reason="steam")

    assert classify(_cand(steam_appid=None), new, None).bucket == BUCKET_QUARANTINE
    assert classify(_cand(), already, None).bucket == BUCKET_ALREADY

    unverified = SteamCheck(steam_appid=1, available=False, unverified=True, error="429")
    assert classify(_cand(), new, unverified).bucket == BUCKET_NEEDS_REVIEW

    dlc = SteamCheck(
        steam_appid=1,
        available=True,
        unverified=False,
        steam_name="Test Game",
        app_type="dlc",
        title_ok=True,
        windows=True,
        is_free=False,
    )
    assert classify(_cand(), new, dlc).bucket == BUCKET_REJECTED

    f2p = SteamCheck(
        steam_appid=1,
        available=True,
        unverified=False,
        steam_name="Test Game",
        app_type="game",
        title_ok=True,
        windows=True,
        is_free=True,
        coming_soon=False,
        release_date="1 Jan 2024",
    )
    assert classify(_cand(), new, f2p).bucket == BUCKET_F2P

    paid = SteamCheck(
        steam_appid=1,
        available=True,
        unverified=False,
        steam_name="Test Game",
        app_type="game",
        title_ok=True,
        windows=True,
        is_free=False,
        coming_soon=False,
        release_date="1 Jan 2024",
        recommendations=100,
    )
    assert (
        classify(
            _cand(),
            new,
            paid,
            category="popular",
            metric_norm=0.8,
            steam_resolution_status="verified",
        ).bucket
        == BUCKET_APPROVABLE
    )

    low = SteamCheck(
        steam_appid=1,
        available=True,
        unverified=False,
        steam_name="Test Game",
        app_type="game",
        title_ok=True,
        windows=True,
        is_free=False,
        coming_soon=True,
        release_date="Coming soon",
        recommendations=0,
    )
    assert (
        classify(
            _cand(),
            new,
            low,
            category="upcoming",
            metric_norm=0.0,
            steam_resolution_status="verified",
        ).bucket
        == BUCKET_NEEDS_REVIEW
    )


def test_appid_without_resolution_not_verified():
    from tools.igdb_discovery.matching import MatchResult

    new = MatchResult(status="new_candidate", confidence=0.8, reason="x")
    steam = SteamCheck(
        steam_appid=1,
        available=True,
        unverified=False,
        steam_name="Test Game",
        app_type="game",
        title_ok=True,
        windows=True,
        is_free=False,
        release_date="1 Jan 2024",
        recommendations=100,
    )
    v = classify(
        _cand(),
        new,
        steam,
        category="popular",
        metric_norm=0.9,
        steam_resolution_status="unverified",
    )
    assert v.bucket == BUCKET_NEEDS_REVIEW
    assert v.steam_verified is False


def test_complete_edition_allowed_by_pc_filter():
    ok, reason = is_pc_mainline(
        {
            "id": 268842,
            "name": "Horizon Forbidden West: Complete Edition",
            "platforms": [6],
            "game_type": 3,
            "version_parent": 112874,
        }
    )
    assert ok
    assert "edition" in reason or reason.startswith("ok_")


def test_title_mismatch_rejected():
    from tools.igdb_discovery.matching import MatchResult

    new = MatchResult(status="new_candidate", confidence=0.8, reason="x")
    mismatch = SteamCheck(
        steam_appid=1,
        available=True,
        unverified=False,
        steam_name="Totally Different",
        app_type="game",
        title_ok=False,
        title_reason="title_mismatch",
        windows=True,
        is_free=False,
    )
    assert (
        classify(_cand(), new, mismatch, steam_resolution_status="verified").bucket
        == BUCKET_REJECTED
    )


def test_staging_upsert_isolated(tmp_path: Path):
    store = StagingStore(tmp_path / "staging.sqlite3")
    store.upsert_row(
        {
            "igdb_id": 42,
            "name": "Test Game",
            "steam_appid": 123,
            "source": "popular",
            "category": "popular",
            "match_status": "new_candidate",
            "match_confidence": 0.8,
            "match_reason": "test",
            "review_bucket": "APPROVABLE",
            "review_reason": "ok",
            "steam_verified": True,
            "scan_priority": 12.5,
            "staging_status": "pending_review",
            "payload": {"igdb_id": 42},
        }
    )
    summary = store.summary()
    assert summary["by_review_bucket"]["APPROVABLE"] == 1


def test_assert_prototype_safety_blocks_prod_flags(monkeypatch):
    from tools.igdb_discovery import config

    monkeypatch.setattr(config, "WRITE_PRODUCTION", True)
    with pytest.raises(RuntimeError):
        config.assert_prototype_safety()


def test_missing_credentials(monkeypatch):
    from tools.igdb_discovery import config

    monkeypatch.setattr(config, "IGDB_CLIENT_ID", "")
    monkeypatch.setattr(config, "IGDB_CLIENT_SECRET", "")
    with pytest.raises(RuntimeError, match="Missing IGDB"):
        config.require_credentials()


def test_client_retries_429(monkeypatch):
    client = IgdbClient()
    monkeypatch.setattr(client, "ensure_token", lambda: "tok")
    monkeypatch.setattr(
        "tools.igdb_discovery.client.config.require_credentials",
        lambda: ("cid", "sec"),
    )

    calls = {"n": 0}

    class Resp:
        def __init__(self, code, payload=None):
            self.status_code = code
            self._payload = payload or []

        def raise_for_status(self):
            if self.status_code >= 400 and self.status_code != 429:
                raise RuntimeError(f"http {self.status_code}")

        def json(self):
            return self._payload

    def fake_post(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return Resp(429)
        return Resp(200, [{"id": 1}])

    client._session.post = fake_post  # type: ignore[method-assign]
    monkeypatch.setattr("tools.igdb_discovery.client.time.sleep", lambda *_: None)
    monkeypatch.setattr(client, "_throttle", lambda: None)
    out = client.query("games", "fields id;")
    assert out == [{"id": 1}]
    assert calls["n"] == 3


def test_dry_run_does_not_write_staging(tmp_path: Path, monkeypatch):
    """dry-run must not upsert staging candidates."""
    from tools.igdb_discovery import pipeline as pl

    staging_path = tmp_path / "stage.sqlite3"
    monkeypatch.setattr(pl.config, "STAGING_DB", staging_path)
    monkeypatch.setattr(pl.config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(pl.config, "CATALOG_DB", tmp_path / "games.db")
    monkeypatch.setattr(pl.config, "assert_prototype_safety", lambda: None)

    # Minimal catalog
    con = sqlite3.connect(tmp_path / "games.db")
    con.execute(
        "CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, steam_appid INTEGER, "
        "platform TEXT, steam_app_type TEXT)"
    )
    con.commit()
    con.close()

    monkeypatch.setattr(pl, "verify_prior_30", lambda *a, **k: [])
    monkeypatch.setattr(
        pl,
        "collect_categorized",
        lambda *a, **k: ([], {"categories": {}}),
    )
    monkeypatch.setattr(pl, "_process_scored", lambda *a, **k: [])

    class FakeClient:
        def ensure_token(self):
            return "x"

    monkeypatch.setattr(pl, "IgdbClient", FakeClient)
    monkeypatch.setattr(pl, "SteamVerifier", lambda *a, **k: MagicMock())

    report = pl.run_discovery(mode="dry-run", limit=5, verify_steam=False)
    assert report["wrote_staging"] is False
    assert not staging_path.exists() or StagingStore(staging_path).count_by_igdb() == 0
