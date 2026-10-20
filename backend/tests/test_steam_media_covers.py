"""Steam cover URL helpers — bare template vs hashed assets."""
from __future__ import annotations

from app.core.steam_media import (
    cover_from_steam_appdetails,
    is_bare_steam_cover_url,
    pick_list_cover_url,
)


def test_is_bare_steam_cover_url():
    bare = (
        "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/"
        "3764200/header.jpg"
    )
    hashed = (
        "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/"
        "3764200/ce5437442768e38eb575f205ab9397d0264017b0/header.jpg?t=1"
    )
    assert is_bare_steam_cover_url(bare)
    assert not is_bare_steam_cover_url(hashed)


def test_pick_list_cover_url_prefers_hashed_over_bare():
    bare = (
        "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/"
        "3764200/header.jpg"
    )
    hashed = (
        "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/"
        "3764200/ce5437442768e38eb575f205ab9397d0264017b0/header.jpg"
    )
    picked = pick_list_cover_url(bare, hashed, steam_appid=3764200)
    assert "ce5437442768e38eb575f205ab9397d0264017b0" in picked


def test_cover_from_steam_appdetails_header_image():
    data = {
        "header_image": (
            "https://cdn.akamai.steamstatic.com/store_item_assets/steam/apps/"
            "3764200/abc/header.jpg"
        )
    }
    cover = cover_from_steam_appdetails(data, 3764200)
    assert cover is not None
    assert "shared.cloudflare.steamstatic.com" in cover
    assert "/abc/" in cover
