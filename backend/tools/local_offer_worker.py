#!/usr/bin/env python3
"""Local offer worker — max-speed scan from home PC."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.parsers.offer_fetch_remote import fetch_remote_offers  # noqa: E402
from app.parsers.keyshop_common import slugify  # noqa: E402
from app.parsers.shop_scan_stats import ShopScanStats  # noqa: E402

DEFAULT_API = os.environ.get("GAMES_API_URL", "https://kupujpl.pl/games").rstrip("/")
ACCESS_CODE = os.environ.get("PANEL3_ACCESS_CODE", os.environ.get("PANEL3_CODE", "")).strip()
DEFAULT_LIMIT = int(os.environ.get("SCAN_LIMIT", "60"))
DEFAULT_PARALLEL = int(os.environ.get("SCAN_PARALLEL", "8"))
DEFAULT_DELAY = float(os.environ.get("SCAN_DELAY", "0"))
DEFAULT_CYCLE_PAUSE = float(os.environ.get("SCAN_CYCLE_PAUSE", "1"))
DEFAULT_IDLE_PAUSE = float(os.environ.get("SCAN_IDLE_PAUSE", "15"))

_print_lock = threading.Lock()


def _log(msg: str) -> None:
    with _print_lock:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe = msg.encode(enc, errors="replace").decode(enc, errors="replace")
        print(safe, flush=True)


def _api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{DEFAULT_API}/api/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Panel3-Code": ACCESS_CODE,
            "User-Agent": "KupujPL-LocalOfferWorker/2.0",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _shops_for_game(game: dict, shop_filter: set[str] | None) -> tuple[str, ...] | None:
    missing = game.get("missing_shops") or []
    if shop_filter:
        return tuple(sorted(shop_filter))
    if missing:
        return tuple(sorted(missing))
    return None


def _scan_one(
    idx: int,
    total: int,
    game: dict,
    shop_filter: set[str] | None,
    stats: ShopScanStats | None = None,
) -> dict | None:
    title = game.get("title") or ""
    game_id = game.get("game_id")
    game_slug = game.get("slug") or slugify(title)
    shops = _shops_for_game(game, shop_filter)
    t0 = time.perf_counter()
    offers = fetch_remote_offers(title, shops=shops, stats=stats, game_slug=game_slug)
    dt = time.perf_counter() - t0
    if offers:
        names = ", ".join(o["shop_name"] for o in offers)
        _log(f"[{idx}/{total}] {title[:52]} — {len(offers)} ({names}) [{dt:.1f}s]")
        return {"game_id": game_id, "offers": offers}
    _log(f"[{idx}/{total}] {title[:52]} — 0 [{dt:.1f}s]")
    return None


def run_cycle(
    *,
    limit: int,
    shop_filter: set[str] | None,
    delay: float,
    parallel: int,
) -> dict:
    queue = _api("GET", f"admin/offers/queue?limit={limit}")
    items = queue.get("items") or []
    if not items:
        _log("Queue empty — nothing to refresh.")
        return {"games": 0, "offers": 0}

    total = len(items)
    updates: list[dict] = []
    t0 = time.perf_counter()

    workers = max(1, min(parallel, total))
    if workers == 1:
        for idx, game in enumerate(items, 1):
            row = _scan_one(idx, total, game, shop_filter)
            if row:
                updates.append(row)
            if delay > 0 and idx < total:
                time.sleep(delay)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_scan_one, idx, total, game, shop_filter): idx
                for idx, game in enumerate(items, 1)
            }
            for future in as_completed(futures):
                row = future.result()
                if row:
                    updates.append(row)

    scan_sec = time.perf_counter() - t0
    total_offers = sum(len(u["offers"]) for u in updates)
    _log(f"Scanned {total} games in {scan_sec:.1f}s ({total / max(scan_sec, 0.1):.1f} g/s) — hits {len(updates)}")

    if not updates:
        return {"games": 0, "offers": 0}

    result = _api(
        "POST",
        "admin/offers/bulk",
        {
            "source": f"local-pc:{socket.gethostname()}",
            "updates": updates,
        },
    )
    _log(
        f"Uploaded: {result.get('games_touched', 0)} games, "
        f"{result.get('offers_upserted', 0)} offers"
    )
    if result.get("errors"):
        _log("Errors: " + str(result["errors"][:5]))
    return {"games": result.get("games_touched", 0), "offers": result.get("offers_upserted", 0)}


def main() -> int:
    parser = argparse.ArgumentParser(description="KupujPL local offer worker")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="games per batch")
    parser.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL, help="concurrent games")
    parser.add_argument("--cycles", type=int, default=0, help="0 = run until Ctrl+C")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="delay between games (sec)")
    parser.add_argument(
        "--shops",
        type=str,
        default=os.environ.get("SCAN_SHOPS", ""),
        help="comma-separated shop names (default: missing shops from queue)",
    )
    args = parser.parse_args()

    if not ACCESS_CODE:
        print("Set PANEL3_ACCESS_CODE (same as panel3 unlock code).", file=sys.stderr)
        return 1

    if os.environ.get("OFFER_FETCH_FAST", "1").lower() not in ("0", "false", "no"):
        os.environ.setdefault("OFFER_FETCH_FAST", "1")
        os.environ.setdefault("ENEBA_SLUG_DELAY_SEC", "0.35")
        os.environ.setdefault("HTTP_FETCH_TIMEOUT", "12")

    shop_filter = {s.strip() for s in args.shops.split(",") if s.strip()} or None
    _log(f"API: {DEFAULT_API}")
    _log(
        f"Batch: {args.limit} games · parallel={args.parallel} · delay={args.delay}s · "
        f"shops={shop_filter or 'missing from queue'}"
    )

    cycle = 0
    totals = {"games": 0, "offers": 0}
    try:
        while True:
            cycle += 1
            _log(f"\n=== Cycle {cycle} ===")
            try:
                stats = run_cycle(
                    limit=args.limit,
                    shop_filter=shop_filter,
                    delay=args.delay,
                    parallel=args.parallel,
                )
            except urllib.error.HTTPError as exc:
                print(f"HTTP error {exc.code}: {exc.read().decode()[:300]}", file=sys.stderr)
                return 1
            totals["games"] += stats.get("games", 0)
            totals["offers"] += stats.get("offers", 0)
            if args.cycles and cycle >= args.cycles:
                break
            if stats.get("games", 0) == 0 and stats.get("offers", 0) == 0:
                _log(f"Idle — wait {DEFAULT_IDLE_PAUSE:.0f}s…")
                time.sleep(DEFAULT_IDLE_PAUSE)
            else:
                time.sleep(DEFAULT_CYCLE_PAUSE)
    except KeyboardInterrupt:
        _log("\nStopped.")

    _log(f"Total: {totals['games']} games, {totals['offers']} offers uploaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
