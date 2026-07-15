"""Fetch shop prices for a game title (no DB) — for local PC worker."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from typing import TYPE_CHECKING

from app.parsers.cdkeys_parser import search_cdkeys_price
from app.parsers.gamivo_parser import peek_gamivo_fetch_error, search_gamivo_price
from app.parsers.fanatical_parser import search_fanatical_price
from app.parsers.eneba_parser import search_eneba_price
from app.parsers.instant_gaming_parser import search_instant_gaming_price
from app.parsers.epic_parser import search_epic_price
from app.parsers.g2a_parser import peek_g2a_fetch_error, search_g2a_price
from app.parsers.gog_parser import search_gog_price
from app.parsers.kinguin_parser import peek_kinguin_fetch_error, search_kinguin_price
from app.parsers.keyshop_common import classify_keyshop_product, product_title_from_url, slugify
from app.parsers.shop_scan_config import get_active_scan_shops

if TYPE_CHECKING:
    from app.parsers.shop_scan_stats import ShopScanStats

logger = logging.getLogger("offer_fetch_remote")

_OFFICIAL = (
    ("GOG", search_gog_price, True),
    ("Epic Games", search_epic_price, True),
)

_KEYSHOPS = (
    ("Instant Gaming", search_instant_gaming_price, False),
    ("Eneba", search_eneba_price, False),
    ("Kinguin", search_kinguin_price, False),
    ("CDKeys", search_cdkeys_price, False),
    ("G2A", search_g2a_price, False),
    ("Gamivo", search_gamivo_price, False),
    ("Fanatical", search_fanatical_price, False),
)

_PEEK_ERROR = {
    "G2A": peek_g2a_fetch_error,
    "Kinguin": peek_kinguin_fetch_error,
    "Gamivo": peek_gamivo_fetch_error,
}


def _shop_error_status(name: str) -> tuple[str, str | None]:
    peek = _PEEK_ERROR.get(name)
    if not peek:
        return "miss", None
    err = peek()
    if not err:
        return "miss", None
    if err.startswith("HTTP 403"):
        return "http_403", err
    if err.startswith("HTTP 429"):
        return "http_429", err
    if err.startswith("HTTP "):
        return "http_error", err
    if err == "fetch failed":
        return "fetch_failed", err
    return "error", err


def _record_shop(stats: ShopScanStats | None, name: str, status: str, *, error: str | None = None) -> None:
    if stats is not None:
        stats.record(name, status, error=error)


def _run_one(
    name: str,
    fn,
    title: str,
    slug: str,
    official: bool,
    stats: ShopScanStats | None = None,
) -> dict | None:
    confidence = None
    try:
        if official:
            result = fn(title)
        else:
            result = fn(title, slug)
        if len(result) >= 3:
            url, price, confidence = result[0], result[1], result[2]
        else:
            url, price = result[0], result[1]
    except Exception as exc:
        logger.debug("%s fetch error for %s: %s", name, title, exc)
        _record_shop(stats, name, "exception", error=str(exc)[:120])
        return None
    if not url or price is None:
        status, err = _shop_error_status(name)
        _record_shop(stats, name, status, error=err)
        return None
    verdict = classify_keyshop_product(title, product_title_from_url(str(url)), str(url))
    if not verdict["valid"]:
        _record_shop(stats, name, "rejected", error=str(verdict["reason"]))
        logger.info("Rejected %s offer for %s: %s", name, title, verdict["reason"])
        return None
    _record_shop(stats, name, "hit")
    return {
        "shop_name": name,
        "price_pln": round(float(price), 2),
        "product_url": url,
        "is_official": official,
        "match_confidence": confidence,
    }


def fetch_remote_offers(
    title: str,
    *,
    shops: tuple[str, ...] | None = None,
    stats: ShopScanStats | None = None,
    game_slug: str | None = None,
) -> list[dict]:
    """Query configured shops for one game title."""
    slug = game_slug or slugify(title)
    want = set(shops) if shops else None
    tasks: list[tuple[str, object, bool]] = []
    for name, fn, official in _OFFICIAL + _KEYSHOPS:
        if name not in get_active_scan_shops():
            continue
        if want is not None and name not in want:
            continue
        tasks.append((name, fn, official))

    found: list[dict] = []
    if not tasks:
        return found

    g2a_tasks = [t for t in tasks if t[0] == "G2A"]
    gamivo_tasks = [t for t in tasks if t[0] == "Gamivo"]
    other_tasks = [t for t in tasks if t[0] not in ("G2A", "Gamivo")]

    if other_tasks:
        with ThreadPoolExecutor(max_workers=min(12, len(other_tasks))) as pool:
            futures = {
                pool.submit(_run_one, name, fn, title, slug, official, stats): name
                for name, fn, official in other_tasks
            }
            for future in as_completed(futures):
                row = future.result()
                if row:
                    found.append(row)

    g2a_timeout = float(os.environ.get("G2A_GAME_TIMEOUT_SEC", "45"))
    for name, fn, official in g2a_tasks:
        row = None
        if g2a_timeout > 0:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_run_one, name, fn, title, slug, official, stats)
                try:
                    row = future.result(timeout=g2a_timeout)
                except FuturesTimeoutError:
                    logger.warning("G2A timed out after %.0fs for %s", g2a_timeout, title[:60])
                    _record_shop(stats, name, "timeout", error=f"timeout {g2a_timeout:.0f}s")
        else:
            row = _run_one(name, fn, title, slug, official, stats)
        if row:
            found.append(row)

    for name, fn, official in gamivo_tasks:
        row = _run_one(name, fn, title, slug, official, stats)
        if row:
            found.append(row)

    return found
