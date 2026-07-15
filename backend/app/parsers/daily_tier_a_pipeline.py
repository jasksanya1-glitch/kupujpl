"""Daily Tier A pipeline: rebuild top-5000 → scan official shops on VPS."""
from __future__ import annotations

import argparse
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

from app.core.database import SessionLocal
from app.parsers.game_offers import refresh_offers_for_game
from app.parsers.shop_scan_config import get_shops_for_worker
from app.parsers.tier_a_scan_state import (
    clear_vps_cancel,
    is_vps_cancel_requested,
    load_vps_state,
    save_vps_state,
)
from app.parsers.tier_a_top5000 import (
    TIER_A_SIZE,
    load_tier_a_cache,
    next_tier_a_scan_at,
    rebuild_tier_a_cache,
)

logger = logging.getLogger("daily_tier_a_pipeline")

TIER_A_PARALLEL = max(1, int(os.environ.get("TIER_A_PARALLEL", "4")))
PROGRESS_EVERY = int(os.environ.get("TIER_A_PROGRESS_EVERY", "10"))
def _vps_scan_shops() -> frozenset[str]:
    return frozenset(get_shops_for_worker("vps"))


def _should_skip_scheduled_run() -> bool:
    """Skip automatic Tier A if paused, or a run started/finished within the last N hours."""
    from app.parsers.tier_a_auto_scan import is_auto_scan_paused

    if is_auto_scan_paused():
        logger.info("Tier A pipeline skipped — auto scan paused")
        return True
    hours = float(os.environ.get("TIER_A_MIN_HOURS_BETWEEN_RUNS", "10"))
    state = load_vps_state()
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    for key in ("finished_at", "started_at", "bootstrap_run_at"):
        raw = state.get(key)
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00").replace("+00:00", ""))
            if ts >= cutoff:
                return True
        except ValueError:
            continue
    return False


def _refresh_one(game_id: int) -> tuple[int, bool]:
    try:
        refresh_offers_for_game(
            game_id,
            force=False,
            fill_missing=True,
            shop_names=_vps_scan_shops(),
        )
        return game_id, True
    except Exception as exc:
        logger.warning("Tier A refresh failed for game %s: %s", game_id, exc)
        return game_id, False


def _stop_vps_pipeline(state: dict[str, Any], *, started: datetime) -> dict[str, Any]:
    finished = datetime.utcnow()
    clear_vps_cancel()
    patch = {
        "phase": "stopped",
        "stopped_at": finished.isoformat() + "Z",
        "eta_sec": None,
        "games_per_min": None,
        "current_game": None,
        "duration_sec": round((finished - started).total_seconds(), 1),
    }
    save_vps_state({**state, **patch})
    return {**state, **patch, "stopped": True}


def _fail_vps_pipeline(exc: Exception, *, started: datetime) -> dict[str, Any]:
    finished = datetime.utcnow()
    state = load_vps_state()
    patch = {
        "phase": "failed",
        "failed_at": finished.isoformat() + "Z",
        "phase_error": str(exc)[:500],
        "eta_sec": None,
        "games_per_min": None,
        "current_game": None,
        "duration_sec": round((finished - started).total_seconds(), 1),
        "list_ready": True,
    }
    save_vps_state({**state, **patch})
    logger.exception("Tier A VPS pipeline failed: %s", exc)
    return {"failed": True, **state, **patch}


def run_daily_tier_a_pipeline(*, bootstrap: bool = False, force: bool = False) -> dict[str, Any]:
    started = datetime.utcnow()
    clear_vps_cancel()
    if not bootstrap and not force:
        phase = str(load_vps_state().get("phase") or "idle")
        if phase in ("rebuild_list", "scan_official"):
            logger.info("Tier A pipeline skipped — already running (%s)", phase)
            return {"skipped": True, "reason": "already_running", "phase": phase}
        if _should_skip_scheduled_run():
            logger.info("Tier A pipeline skipped — recent run")
            return {"skipped": True, "reason": "recent_run"}

    try:
        save_vps_state(
            {
                "phase": "rebuild_list",
                "worker": "vps",
                "shops": list(_vps_scan_shops()),
                "games_total": TIER_A_SIZE,
                "games_done": 0,
                "started_at": started.isoformat() + "Z",
                "list_ready": False,
            }
        )

        db = SessionLocal()
        try:
            cache = rebuild_tier_a_cache(db)
        finally:
            db.close()

        if is_vps_cancel_requested():
            return _stop_vps_pipeline(load_vps_state(), started=started)

        game_ids = [g["game_id"] for g in cache.get("games") or []]
        total = len(game_ids)
        save_vps_state(
            {
                "phase": "scan_official",
                "list_ready": True,
                "list_version": cache.get("version"),
                "games_total": total,
                "games_done": 0,
                "games_per_min": 0.0,
                "eta_sec": None,
                "current_game": None,
            }
        )

        done = 0
        errors = 0
        t0 = time.perf_counter()

        def _tick(game_id: int, title: str | None = None) -> None:
            nonlocal done
            done += 1
            if done % PROGRESS_EVERY != 0 and done != total:
                return
            elapsed = max(time.perf_counter() - t0, 0.1)
            rate = done / elapsed * 60.0
            eta = int((total - done) / max(done / elapsed, 0.001)) if done else None
            save_vps_state(
                {
                    "phase": "scan_official",
                    "games_done": done,
                    "games_total": total,
                    "games_per_min": round(rate, 1),
                    "eta_sec": eta,
                    "current_game": title,
                    "list_ready": True,
                }
            )

        id_to_title = {g["game_id"]: g.get("title") for g in cache.get("games") or []}

        if TIER_A_PARALLEL <= 1:
            for gid in game_ids:
                if is_vps_cancel_requested():
                    return _stop_vps_pipeline(load_vps_state(), started=started)
                _gid, ok = _refresh_one(gid)
                if not ok:
                    errors += 1
                _tick(gid, id_to_title.get(gid))
        else:
            with ThreadPoolExecutor(max_workers=TIER_A_PARALLEL) as pool:
                futures = {pool.submit(_refresh_one, gid): gid for gid in game_ids}
                for future in as_completed(futures):
                    if is_vps_cancel_requested():
                        return _stop_vps_pipeline(load_vps_state(), started=started)
                    gid = futures[future]
                    _gid, ok = future.result()
                    if not ok:
                        errors += 1
                    _tick(gid, id_to_title.get(gid))

        clear_vps_cancel()
        finished = datetime.utcnow()
        result: dict[str, Any] = {
            "phase": "done",
            "worker": "vps",
            "games_total": total,
            "games_done": done,
            "errors": errors,
            "duration_sec": round((finished - started).total_seconds(), 1),
            "finished_at": finished.isoformat() + "Z",
            "list_ready": True,
            "next_scheduled_at": next_tier_a_scan_at(),
        }
        if bootstrap:
            result["bootstrap_run_at"] = finished.isoformat() + "Z"
        save_vps_state(result)
        logger.info(
            "Tier A VPS pipeline done: %s/%s games, %s errors, %.1fs",
            done,
            total,
            errors,
            result["duration_sec"],
        )
        return result
    except Exception as exc:
        return _fail_vps_pipeline(exc, started=started)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Daily Tier A scan (VPS official shops)")
    parser.add_argument("--bootstrap", action="store_true", help="First run after deploy")
    args = parser.parse_args()
    if not load_tier_a_cache().get("list_ready") and not args.bootstrap:
        pass
    result = run_daily_tier_a_pipeline(bootstrap=args.bootstrap)
    if result.get("skipped"):
        print("Skipped:", result.get("reason"))
        return 0
    if result.get("failed"):
        print("Failed:", result.get("phase_error"))
        return 1
    print(
        f"Done: {result.get('games_done')}/{result.get('games_total')} "
        f"in {result.get('duration_sec')}s"
    )
    return 0 if result.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
