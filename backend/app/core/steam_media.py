"""Steam CDN cover image URLs (no API call needed)."""

import re

STEAM_HEADER = (
    "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
)
STEAM_CAPSULE = "https://shared.cloudflare.steamstatic.com/steam/apps/{appid}/capsule_616x353.jpg"
STEAM_LIBRARY = (
    "https://shared.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"
)
LEGACY_HEADER = "https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg"
LEGACY_CAPSULE = "https://cdn.akamai.steamstatic.com/steam/apps/{appid}/capsule_616x353.jpg"
PLACEHOLDER = "https://via.placeholder.com/460x215?text=Brak+Ok%C5%82adki"

_LOW_RES_MARKERS = (
    "capsule_sm_120",
    "capsule_sm_",
    "231x87",
    "467x181",
    "_120.jpg",
    "capsule_sm_120_alt",
)

_HASHED_STEAM_ASSET = re.compile(r"/apps/\d+/[a-f0-9]{40}/", re.IGNORECASE)
_BARE_STEAM_ASSET = re.compile(
    r"/apps/\d+/(?:header|capsule_616x353|library_600x900)\.jpg(?:\?|$)",
    re.IGNORECASE,
)


def normalize_cover_url(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    normalized = url.strip()
    normalized = normalized.replace(
        "shared.akamai.steamstatic.com", "shared.cloudflare.steamstatic.com"
    )
    normalized = normalized.replace(
        "cdn.akamai.steamstatic.com", "shared.cloudflare.steamstatic.com"
    )
    normalized = normalized.replace(
        "shared.fastly.steamstatic.com", "shared.cloudflare.steamstatic.com"
    )
    return normalized


def is_low_res_steam_cover(url: str | None) -> bool:
    if not url:
        return True
    lower = url.lower()
    return any(marker in lower for marker in _LOW_RES_MARKERS)


def is_bare_steam_cover_url(url: str | None) -> bool:
    """True for template CDN paths without a content hash (often 404 for unreleased games)."""
    if not url:
        return False
    normalized = normalize_cover_url(url) or url
    if _HASHED_STEAM_ASSET.search(normalized):
        return False
    return bool(_BARE_STEAM_ASSET.search(normalized))


def cover_from_steam_appdetails(data: dict | None, appid: int | None = None) -> str | None:
    """Best cover URL from Steam appdetails payload (hashed assets when available)."""
    if data:
        for key in (
            "header_image",
            "capsule_image",
            "capsule_imagev5",
            "background",
            "background_raw",
        ):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return normalize_cover_url(val.strip())
    return steam_cover_url(appid) if appid else None


def pick_list_cover_url(
    *candidates: str | None,
    steam_appid: int | None = None,
) -> str:
    """Prefer verified hashed Steam art over bare template URLs."""
    normalized = [normalize_cover_url(c) for c in candidates if c]
    for url in normalized:
        if url and not is_low_res_steam_cover(url) and not is_bare_steam_cover_url(url):
            return url
    for url in normalized:
        if url and not is_low_res_steam_cover(url):
            return url
    return effective_cover(normalized[0] if normalized else None, steam_appid)


def _hd_cover_candidates(appid: int | str) -> list[str]:
    aid = str(appid)
    return [
        STEAM_HEADER.format(appid=aid),
        f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{aid}/capsule_616x353.jpg",
        STEAM_CAPSULE.format(appid=aid),
        STEAM_LIBRARY.format(appid=aid),
        LEGACY_HEADER.format(appid=aid),
        LEGACY_CAPSULE.format(appid=aid),
    ]


def steam_cover_url(appid: int | None, *, kind: str = "header") -> str | None:
    if not appid:
        return None
    templates = {
        "header": STEAM_HEADER,
        "capsule": STEAM_CAPSULE,
        "library": STEAM_LIBRARY,
    }
    tpl = templates.get(kind, STEAM_HEADER)
    return tpl.format(appid=appid)


def list_cover_image(cover_image: str | None, steam_appid: int | None) -> str:
    """Best cover URL for cards — prefers HD header over low-res Steam thumbs."""
    return effective_cover(cover_image, steam_appid)


def effective_cover(cover_image: str | None, steam_appid: int | None) -> str:
    """Best single cover URL (game detail pages)."""
    stored = normalize_cover_url(cover_image)
    if (
        stored
        and not is_low_res_steam_cover(stored)
        and not is_bare_steam_cover_url(stored)
    ):
        return stored
    chain = cover_fallback_chain(steam_appid, cover_image)
    return chain[0] if chain else PLACEHOLDER


def cover_fallback_chain(
    steam_appid: int | None, cover_image: str | None = None
) -> list[str]:
    chain: list[str] = []
    stored = normalize_cover_url(cover_image)

    stored_unreliable = is_low_res_steam_cover(stored) or is_bare_steam_cover_url(stored)
    if steam_appid and stored_unreliable:
        chain.extend(_hd_cover_candidates(steam_appid))
        if stored:
            chain.append(stored)
    else:
        if stored:
            chain.append(stored)
        if steam_appid:
            chain.extend(_hd_cover_candidates(steam_appid))

    if not chain:
        chain.append(PLACEHOLDER)
    seen: set[str] = set()
    out: list[str] = []
    for url in chain:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out
