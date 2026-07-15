"""Fetch public Steam wishlists by profile URL, vanity name, or SteamID64."""
from __future__ import annotations

import logging
import re
from typing import Any

import requests

logger = logging.getLogger("steam_wishlist")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    "Accept": "application/json,text/javascript,*/*;q=0.9",
    "Referer": "https://store.steampowered.com/",
}


class SteamWishlistError(Exception):
    def __init__(self, code: str, message: str, *, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def resolve_steam_id64(profile_input: str) -> int:
    """Resolve SteamID64 from URL, vanity name, or raw id."""
    raw = (profile_input or "").strip()
    if not raw:
        raise SteamWishlistError("empty_input", "Podaj link do profilu Steam lub SteamID64.")

    if re.fullmatch(r"\d{17}", raw):
        return int(raw)

    for pattern in (
        r"steamcommunity\.com/profiles/(\d{17})",
        r"store\.steampowered\.com/wishlist/profiles/(\d{17})",
        r"/profiles/(\d{17})",
    ):
        match = re.search(pattern, raw, re.I)
        if match:
            return int(match.group(1))

    vanity_match = re.search(r"steamcommunity\.com/id/([^/?#\s]+)", raw, re.I)
    vanity = vanity_match.group(1) if vanity_match else None
    if not vanity and re.fullmatch(r"[\w-]{2,64}", raw):
        vanity = raw

    if vanity:
        return _resolve_vanity(vanity)

    raise SteamWishlistError(
        "invalid_profile",
        "Nie rozpoznano profilu Steam. Wklej pełny link lub 17-cyfrowy SteamID64.",
    )


def _resolve_vanity(vanity: str) -> int:
    url = f"https://steamcommunity.com/id/{requests.utils.quote(vanity)}/?xml=1"
    try:
        response = requests.get(url, headers=_HEADERS, timeout=20)
    except requests.RequestException as exc:
        raise SteamWishlistError("network_error", f"Błąd połączenia ze Steam: {exc}") from exc

    if response.status_code == 404:
        raise SteamWishlistError("profile_not_found", f"Nie znaleziono profilu Steam „{vanity}”.")
    if response.status_code != 200:
        raise SteamWishlistError(
            "profile_lookup_failed",
            f"Steam zwrócił HTTP {response.status_code} przy wyszukiwaniu profilu.",
        )

    match = re.search(r"<steamID64>(\d{17})</steamID64>", response.text)
    if match:
        return int(match.group(1))

    raise SteamWishlistError(
        "profile_not_found",
        f"Nie udało się odczytać SteamID64 dla „{vanity}”.",
    )


def fetch_wishlist_appids(steam_id64: int) -> list[int]:
    """Return wishlist appids for a public Steam profile."""
    url = f"https://store.steampowered.com/wishlist/profiles/{steam_id64}/wishlistdata/?p=0"
    try:
        response = requests.get(url, headers=_HEADERS, timeout=25)
    except requests.RequestException as exc:
        raise SteamWishlistError("network_error", f"Błąd pobierania wishlisty: {exc}") from exc

    if response.status_code in (401, 403):
        raise SteamWishlistError(
            "wishlist_private",
            "Lista życzeń jest prywatna lub profil nie jest publiczny.",
            hint="Ustaw profil i listę życzeń jako publiczne w Steam (instrukcja w panelu).",
        )
    if response.status_code != 200:
        raise SteamWishlistError(
            "wishlist_fetch_failed",
            f"Steam zwrócił HTTP {response.status_code} przy pobieraniu wishlisty.",
        )

    try:
        data: Any = response.json()
    except ValueError as exc:
        raise SteamWishlistError(
            "wishlist_private",
            "Nie udało się odczytać wishlisty — prawdopodobnie profil jest prywatny.",
            hint="Sprawdź ustawienia prywatności w Steam.",
        ) from exc

    if data is None:
        return []

    if not isinstance(data, dict):
        raise SteamWishlistError("wishlist_invalid", "Nieoczekiwany format odpowiedzi Steam.")

    appids: list[int] = []
    for key in data:
        if str(key).isdigit():
            appids.append(int(key))

    if not appids and _profile_wishlist_private(steam_id64):
        raise SteamWishlistError(
            "wishlist_private",
            "Lista życzeń jest prywatna.",
            hint="Ustaw „Lista życzeń” na Publiczną w ustawieniach prywatności Steam.",
        )

    return appids


def _profile_wishlist_private(steam_id64: int) -> bool:
    """Heuristic: community profile without public games/wishlist."""
    url = f"https://steamcommunity.com/profiles/{steam_id64}/?xml=1"
    try:
        response = requests.get(url, headers=_HEADERS, timeout=15)
        if response.status_code != 200:
            return True
        text = response.text.lower()
        if "this profile is private" in text or "<visibilitystate>1</visibilitystate>" in text:
            return True
    except requests.RequestException:
        return False
    return False
