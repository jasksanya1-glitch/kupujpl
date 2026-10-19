"""Regression: Steam AppID resolution must never guess among verified IDs."""
from __future__ import annotations

from tools.igdb_discovery.steam_resolve import SteamExternalHit, resolve_steam_appid
from tools.igdb_discovery.steam_verify import SteamCheck, SteamVerifier


class FakeVerifier(SteamVerifier):
    def __init__(self, mapping: dict[int, SteamCheck]):
        super().__init__(pause_sec=0)
        self._map = mapping

    def check(self, appid, igdb_name):  # noqa: ANN001
        if not appid:
            return SteamCheck(steam_appid=0, available=False, unverified=False, error="missing")
        return self._map[int(appid)]


def _game_check(appid: int, name: str = "Risk of Rain 2") -> SteamCheck:
    return SteamCheck(
        steam_appid=appid,
        available=True,
        unverified=False,
        steam_name=name,
        app_type="game",
        title_ok=True,
        title_reason="exact",
        windows=True,
        is_free=False,
        coming_soon=False,
        release_date="Aug 11, 2020",
        recommendations=241955,
    )


def test_ror2_unique_catalog_match_not_lowest_guess():
    hits = [
        SteamExternalHit(28512, 632360, 1615017, "Risk of Rain 2", 6, "external_game_source"),
        SteamExternalHit(28512, 3885090, 3183505, "Risk of Rain 2", None, "external_game_source"),
    ]
    verifier = FakeVerifier({632360: _game_check(632360), 3885090: _game_check(3885090)})
    res = resolve_steam_appid(
        igdb_game_id=28512,
        igdb_name="Risk of Rain 2",
        hits=hits,
        verifier=verifier,
        catalog_steam_ids={632360},
    )
    assert res.status == "verified"
    assert res.appid == 632360
    assert "unique_match_in_quenly_catalog" in res.preferred_because


def test_ror2_without_catalog_is_ambiguous_manual_review():
    """Multiple verified AppIDs and no unique Quenly hit → do NOT pick lowest."""
    hits = [
        SteamExternalHit(28512, 3885090, 3183505, "Risk of Rain 2", None, "external_game_source"),
        SteamExternalHit(28512, 632360, 1615017, "Risk of Rain 2", 6, "external_game_source"),
    ]
    verifier = FakeVerifier({632360: _game_check(632360), 3885090: _game_check(3885090)})
    res = resolve_steam_appid(
        igdb_game_id=28512,
        igdb_name="Risk of Rain 2",
        hits=hits,
        verifier=verifier,
        catalog_steam_ids=set(),
    )
    assert res.status == "ambiguous_manual_review"
    assert res.appid is None
    assert set(res.ambiguous_appids) == {632360, 3885090}


def test_same_title_different_editions_ambiguous():
    hits = [
        SteamExternalHit(1, 100, 1, "Dark Souls", 6, "external_game_source"),
        SteamExternalHit(1, 200, 2, "Dark Souls Remastered", 6, "external_game_source"),
    ]
    verifier = FakeVerifier(
        {
            100: _game_check(100, "Dark Souls"),
            200: _game_check(200, "Dark Souls Remastered"),
        }
    )
    # Title filter should reject remaster mismatch for base name.
    res = resolve_steam_appid(
        igdb_game_id=1,
        igdb_name="Dark Souls",
        hits=hits,
        verifier=verifier,
        catalog_steam_ids=set(),
    )
    # Remastered fails titles_compatible; only 100 remains → verified.
    assert res.status == "verified"
    assert res.appid == 100


def test_two_identical_edition_names_ambiguous():
    hits = [
        SteamExternalHit(9, 111, 1, "Foo Complete Edition", 6, "external_game_source"),
        SteamExternalHit(9, 222, 2, "Foo Complete Edition", 6, "external_game_source"),
    ]
    verifier = FakeVerifier(
        {
            111: _game_check(111, "Foo Complete Edition"),
            222: _game_check(222, "Foo Complete Edition"),
        }
    )
    res = resolve_steam_appid(
        igdb_game_id=9,
        igdb_name="Foo Complete Edition",
        hits=hits,
        verifier=verifier,
        catalog_steam_ids=set(),
    )
    assert res.status == "ambiguous_manual_review"
    assert res.appid is None
    assert set(res.ambiguous_appids) == {111, 222}


def test_single_verified_accepted():
    hits = [SteamExternalHit(1, 50, 1, "Solo", 6, "external_game_source")]
    res = resolve_steam_appid(
        igdb_game_id=1,
        igdb_name="Solo",
        hits=hits,
        verifier=FakeVerifier({50: _game_check(50, "Solo")}),
    )
    assert res.status == "verified"
    assert res.appid == 50


def test_horizon_base_no_steam_external():
    res = resolve_steam_appid(
        igdb_game_id=112874,
        igdb_name="Horizon Forbidden West",
        hits=[],
        verifier=FakeVerifier({}),
    )
    assert res.status == "none"
    assert res.appid is None


def test_rejects_demo_type():
    hits = [SteamExternalHit(1, 99, 1, "Foo Demo", 6, "external_game_source")]
    demo = SteamCheck(
        steam_appid=99,
        available=True,
        unverified=False,
        steam_name="Foo Demo",
        app_type="demo",
        title_ok=True,
        windows=True,
    )
    res = resolve_steam_appid(
        igdb_game_id=1,
        igdb_name="Foo",
        hits=hits,
        verifier=FakeVerifier({99: demo}),
    )
    assert res.status == "rejected_non_game"
    assert res.appid is None


def test_title_mismatch_not_accepted():
    hits = [SteamExternalHit(1, 50, 1, "Other", 6, "external_game_source")]
    bad = SteamCheck(
        steam_appid=50,
        available=True,
        unverified=False,
        steam_name="Completely Different Game",
        app_type="game",
        title_ok=False,
        title_reason="title_mismatch",
        windows=True,
    )
    res = resolve_steam_appid(
        igdb_game_id=1,
        igdb_name="My Game",
        hits=hits,
        verifier=FakeVerifier({50: bad}),
    )
    assert res.appid is None
