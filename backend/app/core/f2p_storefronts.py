"""Verified Free-to-Play primary storefront overrides.

Steam often retains a historical app page for titles that moved to another
store (e.g. Rocket League → Epic Games Store). Primary "play free" CTAs must
use a verified official URL — never an unchecked affiliate / Steam remnant.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FreePlayStorefront:
    shop_name: str
    url: str
    label_pl: str = "Graj za darmo"


# steam_appid → verified official F2P claim URL
VERIFIED_F2P_STOREFRONTS: dict[int, FreePlayStorefront] = {
    # Rocket League left Steam; new players claim on Epic.
    252950: FreePlayStorefront(
        shop_name="Epic Games",
        url="https://store.epicgames.com/pl/p/rocket-league",
    ),
}


def verified_free_play_storefront(steam_appid: int | None) -> FreePlayStorefront | None:
    if steam_appid is None:
        return None
    try:
        appid = int(steam_appid)
    except (TypeError, ValueError):
        return None
    return VERIFIED_F2P_STOREFRONTS.get(appid)


def prefer_epic_over_steam_for_free(steam_appid: int | None) -> bool:
    sf = verified_free_play_storefront(steam_appid)
    return bool(sf and sf.shop_name == "Epic Games")
