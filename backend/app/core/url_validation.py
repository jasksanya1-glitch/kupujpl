"""Affiliate/product URL validation with shop allowlists and anti-SSRF guards.

Live HTTP checks are opt-in (audit CLI only). Import paths use structural validation only.
"""
from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

UrlValidationResult = Literal["ok", "blocked_scheme", "blocked_host", "unknown_shop", "invalid_url"]

# Host suffixes per shop (lowercase). Subdomains must match suffix.
SHOP_ALLOWED_HOST_SUFFIXES: dict[str, tuple[str, ...]] = {
    "Steam": ("steampowered.com", "store.steampowered.com"),
    "Steam US": ("steampowered.com", "store.steampowered.com"),
    "GOG": ("gog.com", "www.gog.com"),
    "Epic Games": ("epicgames.com", "store.epicgames.com"),
    "Fanatical": ("fanatical.com", "www.fanatical.com", "awin1.com", "www.awin1.com"),
    "Instant Gaming": ("instant-gaming.com", "www.instant-gaming.com"),
    "Kinguin": ("kinguin.net", "www.kinguin.net", "awin1.com", "www.awin1.com"),
    "G2A": ("g2a.com", "www.g2a.com", "awin1.com", "www.awin1.com"),
    "Gamivo": ("gamivo.com", "www.gamivo.com"),
    "CDKeys": ("cdkeys.com", "www.cdkeys.com"),
    "Eneba": ("eneba.com", "www.eneba.com"),
    "Humble Store": ("humblebundle.com", "www.humblebundle.com"),
    "PlayStation Store": ("store.playstation.com",),
    "Xbox Store": ("microsoft.com", "xbox.com"),
}

_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "metadata.google.internal",
    }
)

_PRIVATE_NETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
)


def _host_is_private(host: str) -> bool:
    host = host.strip().lower().rstrip(".")
    if host in _BLOCKED_HOSTS:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_NETS)


@dataclass(frozen=True)
class UrlCheck:
    result: UrlValidationResult
    normalized_url: str | None = None
    host: str | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.result == "ok"


def normalize_product_url(url: str) -> str:
    return (url or "").strip()


def validate_offer_url(url: str, shop_name: str | None) -> UrlCheck:
    raw = normalize_product_url(url)
    if not raw or len(raw) > 2000:
        return UrlCheck("invalid_url", reason="empty_or_too_long")
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return UrlCheck("blocked_scheme", reason=scheme or "missing")
    host = (parsed.hostname or "").lower()
    if not host:
        return UrlCheck("invalid_url", reason="missing_host")
    if _host_is_private(host):
        return UrlCheck("blocked_host", host=host, reason="private_or_loopback")
    shop = (shop_name or "").strip()
    suffixes = SHOP_ALLOWED_HOST_SUFFIXES.get(shop)
    if not suffixes:
        # Unknown shop — allow https only if explicitly enabled (legacy).
        if os.environ.get("URL_VALIDATION_ALLOW_UNKNOWN_SHOPS", "0") == "1":
            return UrlCheck("ok", normalized_url=raw, host=host)
        return UrlCheck("unknown_shop", host=host, reason=f"no_allowlist_for:{shop}")
    if not any(host == s or host.endswith("." + s) for s in suffixes):
        return UrlCheck("blocked_host", host=host, reason="not_in_shop_allowlist")
    return UrlCheck("ok", normalized_url=raw, host=host)


def validate_offer_url_for_import(url: str, shop_name: str | None) -> UrlCheck:
    """Hard gate for scanner/worker import — no live HTTP."""
    check = validate_offer_url(url, shop_name)
    if check.ok:
        return check
    if os.environ.get("OFFER_IMPORT_SKIP_URL_VALIDATION", "0") == "1":
        return UrlCheck("ok", normalized_url=normalize_product_url(url), host=check.host, reason="skip_flag")
    return check


def fetch_url_with_redirect_limit(
    url: str,
    *,
    max_redirects: int = 3,
    timeout_sec: float = 8.0,
) -> tuple[int | None, str | None]:
    """Optional live HEAD for audit CLI. Returns (status_code, final_url)."""
    import requests

    check = validate_offer_url(url, None)
    if not check.ok:
        return None, None
    try:
        resp = requests.head(
            url,
            allow_redirects=True,
            timeout=timeout_sec,
            headers={"User-Agent": "KupujPL-OfferAudit/1.0"},
        )
        hops = len(resp.history)
        if hops > max_redirects:
            return None, None
        final = resp.url if resp.url else url
        final_check = validate_offer_url(final, None)
        if not final_check.ok and os.environ.get("URL_VALIDATION_ALLOW_UNKNOWN_SHOPS", "0") != "1":
            return None, None
        return resp.status_code, final
    except requests.RequestException:
        return None, None
