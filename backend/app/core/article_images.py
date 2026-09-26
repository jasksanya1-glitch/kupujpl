"""Featured-image checks for Discover (min 1200px width; no silent upscale)."""
from __future__ import annotations

import logging
from io import BytesIO
from typing import Any
from urllib.request import Request, urlopen

logger = logging.getLogger("article_images")

MIN_DISCOVER_WIDTH = 1200
USER_AGENT = "KupujPL-ArticleImageCheck/1.0"


def probe_image_dimensions(url: str, *, timeout: float = 12.0) -> dict[str, Any]:
    """Return {ok, width, height, warn_under_1200, error} without upscaling."""
    out: dict[str, Any] = {
        "ok": False,
        "width": None,
        "height": None,
        "warn_under_1200": False,
        "error": None,
        "url": url,
    }
    if not url or not str(url).startswith(("http://", "https://")):
        out["error"] = "invalid_url"
        return out
    try:
        from PIL import Image
    except ImportError:
        out["error"] = "pillow_missing"
        return out
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read(8_000_000)
        img = Image.open(BytesIO(data))
        w, h = img.size
        out["width"] = int(w)
        out["height"] = int(h)
        out["ok"] = True
        out["warn_under_1200"] = w < MIN_DISCOVER_WIDTH
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug("image probe failed for %s: %s", url[:80], exc)
        out["error"] = str(exc)
        return out


def apply_image_probe_to_article(article, probe: dict[str, Any]) -> None:
    if not probe.get("ok"):
        return
    article.featured_image_width = probe.get("width")
    article.featured_image_height = probe.get("height")
    article.image_warn_under_1200 = bool(probe.get("warn_under_1200"))
