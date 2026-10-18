"""Independent per-shop scanner worker (one Linux process / systemd instance).

Usage:
  python -m app.parsers.independent_scanner --shop Steam
  python -m app.parsers.independent_scanner --slug steam

Respects pause flags under tmp/scanner_control/. Uses existing scan_shop_batch
with hard deadlines. Auth-blocked shops sleep longer instead of HTTP storms.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

from app.core.offer_verification import shop_auth_blocker
from app.parsers.scanner_control import (
    is_paused,
    pause_reason,
    shop_to_slug,
    slug_to_shop,
)
from app.parsers.shop_scan_queue import (
    release_shop_lock,
    scan_shop_batch,
    write_heartbeat,
)
from app.parsers.shop_scan_stats import ShopScanStats

logger = logging.getLogger("independent_scanner")

_STOP = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _handle_stop(signum: int, _frame: Any) -> None:
    global _STOP
    logger.info("signal %s — graceful stop", signum)
    _STOP = True


def _idle_sleep(seconds: float) -> None:
    end = time.monotonic() + max(0.0, seconds)
    while not _STOP and time.monotonic() < end:
        time.sleep(min(2.0, end - time.monotonic()))


def run_shop_loop(
    shop: str,
    *,
    batch_size: int = 50,
    deadline_sec: float = 300.0,
    idle_sec: float = 15.0,
    auth_idle_sec: float = 600.0,
    pause_poll_sec: float = 10.0,
) -> int:
    slug = shop_to_slug(shop)
    os.environ.setdefault("OFFER_REFRESH_INNER_SERIAL", "1")
    os.environ.setdefault("SCAN_V2", "1")
    os.environ.setdefault("SCAN_V2_VERIFICATION", "1")

    logger.info(
        "scanner start shop=%s slug=%s batch=%s deadline=%ss",
        shop,
        slug,
        batch_size,
        deadline_sec,
    )
    write_heartbeat(phase="scanner_start", detail={"shop": shop, "slug": slug})

    cycles = 0
    while not _STOP:
        if is_paused(slug):
            reason = pause_reason(slug) or "paused"
            write_heartbeat(
                phase="paused",
                detail={"shop": shop, "slug": slug, "reason": reason},
            )
            _idle_sleep(pause_poll_sec)
            continue

        auth = shop_auth_blocker(shop)
        if auth:
            logger.warning("shop %s AUTH_REQUIRED: %s", shop, auth)
            write_heartbeat(
                phase="auth_required",
                detail={"shop": shop, "reason": auth[:200]},
            )
            # Persist durable status for admin UI without hammering APIs.
            release_shop_lock(shop)
            from app.parsers.shop_scan_queue import save_shop_progress, shop_budget

            save_shop_progress(
                shop,
                {
                    "phase": "auth_failed",
                    "last_check_status": "auth_failed",
                    "message": auth[:200],
                    "method": shop_budget(shop).method,
                    "last_batch_size": 0,
                    "last_batch_verified": 0,
                    "verified_per_min": 0.0,
                },
            )
            _idle_sleep(auth_idle_sec)
            continue

        stats = ShopScanStats()
        try:
            result = scan_shop_batch(
                shop,
                limit=batch_size,
                force=False,
                stats=stats,
                deadline_sec=deadline_sec,
            )
        except Exception as exc:
            logger.exception("shop %s batch crashed: %s", shop, exc)
            release_shop_lock(shop)
            write_heartbeat(
                phase="error",
                detail={"shop": shop, "error": str(exc)[:200]},
            )
            _idle_sleep(idle_sec)
            continue

        cycles += 1
        verified = int(result.get("last_batch_verified") or 0)
        attempted = int(result.get("last_batch_size") or 0)
        phase = result.get("phase")
        write_heartbeat(
            phase="batch_done",
            detail={
                "shop": shop,
                "cycles": cycles,
                "attempted": attempted,
                "verified": verified,
                "phase": phase,
                "vpm": result.get("verified_per_min"),
            },
        )
        logger.info(
            "shop=%s cycle=%s attempted=%s verified=%s phase=%s sec=%s",
            shop,
            cycles,
            attempted,
            verified,
            phase,
            result.get("last_batch_sec"),
        )

        # Empty queue: brief pause then retry (stale set refills as offers age).
        # Do NOT sleep 60s — that was the Steam verified/hour killer after cursor
        # wrap falsely reported no_stale_games. Auth failures still back off hard.
        if phase == "auth_failed":
            try:
                from app.parsers.scanner_metrics import record_idle

                record_idle(shop, auth_idle_sec)
            except Exception:
                pass
            _idle_sleep(auth_idle_sec)
        elif attempted == 0 or phase == "idle":
            empty_idle = min(max(idle_sec, 5.0), 15.0)
            try:
                from app.parsers.scanner_metrics import record_idle

                record_idle(shop, empty_idle)
            except Exception:
                pass
            _idle_sleep(empty_idle)
        else:
            try:
                from app.parsers.scanner_metrics import record_idle

                record_idle(shop, idle_sec)
            except Exception:
                pass
            _idle_sleep(idle_sec)

    write_heartbeat(phase="scanner_stop", detail={"shop": shop, "cycles": cycles})
    logger.info("scanner exit shop=%s cycles=%s", shop, cycles)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="KupujPL independent shop scanner")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--shop", help='Offer shop_name, e.g. "Steam"')
    g.add_argument("--slug", help="systemd instance slug, e.g. steam")
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("SCAN_BATCH_SIZE", "50")))
    parser.add_argument(
        "--deadline-sec",
        type=float,
        default=float(os.environ.get("SCAN_SHOP_BATCH_DEADLINE_SEC", "300")),
    )
    parser.add_argument(
        "--idle-sec",
        type=float,
        default=float(os.environ.get("SCAN_IDLE_SEC", "15")),
    )
    parser.add_argument(
        "--auth-idle-sec",
        type=float,
        default=float(os.environ.get("SCAN_AUTH_IDLE_SEC", "600")),
    )
    args = parser.parse_args(argv)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    if args.slug:
        shop = slug_to_shop(args.slug)
    else:
        shop = args.shop
        # validate mapping exists
        shop_to_slug(shop)

    return run_shop_loop(
        shop,
        batch_size=max(1, args.batch_size),
        deadline_sec=max(30.0, args.deadline_sec),
        idle_sec=max(5.0, args.idle_sec),
        auth_idle_sec=max(60.0, args.auth_idle_sec),
    )


if __name__ == "__main__":
    raise SystemExit(main())
