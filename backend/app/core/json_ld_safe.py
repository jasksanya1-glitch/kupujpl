"""Safe JSON-LD embedding and absolute public asset URLs."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin, urlparse

from app.core.site_config import SITE_ORIGIN


def ensure_valid_json_ld(data: Any) -> str:
    """Serialize JSON-LD for safe embedding inside <script type=\"application/ld+json\">.

    Escapes ``<``, ``>``, ``&``, U+2028 and U+2029 after json.dumps so a malicious
    headline cannot break out of the script element.
    """
    dumped = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return (
        dumped.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def absolute_public_asset_url(url: str | None, *, fallback: str | None = None) -> str:
    """Normalize asset URLs to absolute https://kupujpl.pl/games/... form."""
    raw = (url or "").strip()
    if not raw:
        return (fallback or f"{SITE_ORIGIN}/og/logo.png").rstrip()
    if raw.startswith("//"):
        return "https:" + raw
    parsed = urlparse(raw)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return raw
    # Absolute site path or relative
    base = SITE_ORIGIN.rstrip("/") + "/"
    if raw.startswith("/games/"):
        # Avoid /games/games double prefix when SITE_ORIGIN already ends with /games
        origin_path = urlparse(SITE_ORIGIN).path.rstrip("/")
        if origin_path == "/games":
            return urljoin(SITE_ORIGIN.rstrip("/") + "/", raw[len("/games/") :])
        return urljoin("https://kupujpl.pl/", raw.lstrip("/"))
    if raw.startswith("/"):
        return urljoin(base, raw.lstrip("/"))
    return urljoin(base, raw)
