#!/usr/bin/env python3
"""Tier A local scan worker — Kinguin/G2A (laptop) or CDKeys (PC) with progress state."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import local_offer_worker as low  # noqa: E402
from app.parsers.g2a_parser import peek_g2a_status  # noqa: E402
from app.parsers.shop_scan_stats import ShopScanStats  # noqa: E402
from app.parsers.shop_scan_config import (  # noqa: E402
    EXPECTED_SHOPS,
    active_shops_for_worker,
    filter_active_shops,
    get_shops_for_worker,
)

_worker = os.environ.get("TIER_A_WORKER", "laptop")
_REMOTE_STOP_CHECKS: dict[str, dict[str, object]] = {}


class StopRequested(Exception):
    """Raised when admin requested the local worker to stop."""


def _worker_log_path(worker: str | None = None) -> Path:
    w = (worker or _worker or "laptop").lower()
    return ROOT / "tmp" / f"{w}_scan_worker.log"


def _wlog(msg: str, worker: str | None = None) -> None:
    low._log(msg)
    path = _worker_log_path(worker)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.utcnow().isoformat()}Z {msg}\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _peek_gamivo_status() -> dict:
    try:
        from app.parsers.gamivo_parser import peek_gamivo_status

        return peek_gamivo_status()
    except ImportError:
        return {}


def _clear_scan_lock(worker: str) -> None:
    if worker != "pc":
        return
    lock = ROOT / "tmp" / "pc_scan.lock"
    if lock.is_file():
        lock.unlink(missing_ok=True)


def _state_path(worker: str | None = None) -> Path:
    w = (worker or _worker or "laptop").lower()
    if w == "pc":
        return ROOT / "tmp" / "pc_scan_state.json"
    return ROOT / "tmp" / "laptop_scan_state.json"


def _save_state(patch: dict, worker: str | None = None) -> None:
    w = (worker or patch.get("worker") or _worker or "laptop").lower()
    path = _state_path(w)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}
    state.update(patch)
    state["worker"] = w
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    _push_state_to_vps(state, w)


def _load_state(worker: str | None = None) -> dict:
    path = _state_path(worker)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _manual_force_enabled() -> bool:
    return os.environ.get("TIER_A_FORCE_SCAN", "").strip().lower() in ("1", "true", "yes")


def _push_state_to_vps(state: dict, worker: str) -> None:
    endpoint = "admin/tier-a/pc-state" if worker == "pc" else "admin/tier-a/laptop-state"
    try:
        low._api("POST", endpoint, state)
    except Exception as exc:
        low._log(f"State push ({worker}): {exc}")


def _remote_stop_requested(worker: str, *, force: bool = False) -> bool:
    now = time.time()
    cached = _REMOTE_STOP_CHECKS.get(worker) or {}
    if not force and now - float(cached.get("checked_at") or 0) < 5:
        return bool(cached.get("requested"))
    requested = False
    try:
        data = low._api("GET", "admin/tier-a/status")
        requested = bool((data.get(worker) or {}).get("cancel_requested"))
    except Exception as exc:
        low._log(f"Stop flag check ({worker}): {exc}")
        requested = bool(cached.get("requested"))
    _REMOTE_STOP_CHECKS[worker] = {"checked_at": now, "requested": requested}
    return requested


def _raise_if_stop_requested(worker: str) -> None:
    if _remote_stop_requested(worker):
        raise StopRequested(f"{worker} scan stop requested by admin")


def _mark_stopped(worker: str, *, total: int, done: int, stats: dict | None = None) -> None:
    stats = stats or {}
    _save_state(
        {
            "phase": "stopped",
            "games_done": done,
            "games_total": total,
            "games_with_hits": stats.get("games_with_hits"),
            "offers_found": stats.get("offers_found"),
            "stopped_at": datetime.utcnow().isoformat() + "Z",
            "current_game": None,
            "eta_sec": None,
            "games_per_min": None,
            "pause_remaining_sec": None,
            "scan_subphase": "stopped by admin",
        },
        worker,
    )


def _wait_list_ready(timeout_sec: int = 7200) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            data = low._api("GET", "admin/tier-a/status")
            if data.get("list_ready"):
                return True
        except urllib.error.HTTPError:
            pass
        except Exception as exc:
            low._log(f"Wait list_ready: {exc}")
        time.sleep(15)
    return False


def _configure_g2a_scan() -> None:
    os.environ.setdefault("G2A_REQUEST_DELAY_SEC", "3.0")
    os.environ.setdefault("G2A_403_COOLDOWN_SEC", "90")
    os.environ.setdefault("G2A_MAX_PRODUCT_TRIES", "2")
    os.environ.setdefault("G2A_403_RETRIES", "1")
    # Bulk Tier A: feed hit only — HTTP scrape hangs on 403 cooldown for PL DLC titles.
    os.environ.setdefault("G2A_FEED_ONLY", "1")


def _configure_gamivo_scan() -> None:
    os.environ.setdefault("GAMIVO_REQUEST_DELAY_SEC", "3.0")
    os.environ.setdefault("GAMIVO_429_COOLDOWN_SEC", "45")
    os.environ.setdefault("GAMIVO_429_RETRIES", "3")


def _phase_pause_sec(phase_shops: set[str]) -> float:
    names = set(phase_shops)
    if names == {"Gamivo"}:
        return float(os.environ.get("GAMIVO_PHASE_PAUSE_SEC", "30"))
    if "G2A" in names:
        return float(os.environ.get("G2A_PHASE_PAUSE_SEC", "120"))
    return float(os.environ.get("TIER_A_PHASE_PAUSE_SEC", "60"))


def _pause_with_heartbeat(pause_sec: float, phase_shops: set[str], worker: str) -> None:
    label = ", ".join(sorted(phase_shops))
    _wlog(f"Pause {pause_sec:.0f}s before {label} phase", worker)
    deadline = time.time() + pause_sec
    while time.time() < deadline:
        _raise_if_stop_requested(worker)
        remaining = max(0, int(deadline - time.time()))
        _save_state(
            {
                "scan_subphase": f"pause_before: {label}",
                "shops": sorted(phase_shops),
                "pause_remaining_sec": remaining,
            },
            worker,
        )
        time.sleep(min(30, max(1, remaining)))


def _upload_updates(
    updates: list[dict],
    *,
    worker: str,
    subphase: str,
    stats: dict,
) -> None:
    if not updates:
        return
    chunk_size = max(1, int(os.environ.get("TIER_A_BULK_CHUNK", "200")))
    for start in range(0, len(updates), chunk_size):
        chunk = updates[start : start + chunk_size]
        result = low._api(
            "POST",
            "admin/offers/bulk",
            {"source": f"tier-a-{worker}", "updates": chunk},
        )
        stats["games_uploaded"] += int(result.get("games_touched") or 0)
        stats["offers_uploaded"] += int(result.get("offers_upserted") or 0)
        _wlog(
            f"Uploaded ({subphase}) chunk {start // chunk_size + 1}: "
            f"{result.get('games_touched', 0)} games",
            worker,
        )


def _scan_phases(shops: set[str], parallel: int) -> list[tuple[set[str], int]]:
    serial: list[tuple[str, int]] = []
    if "G2A" in shops:
        serial.append(
            ("G2A", max(1, int(os.environ.get("TIER_A_G2A_PARALLEL", "1"))))
        )
    if "Gamivo" in shops:
        serial.append(
            ("Gamivo", max(1, int(os.environ.get("TIER_A_GAMIVO_PARALLEL", "1"))))
        )
    if not serial:
        return [(shops, parallel)]

    phases: list[tuple[set[str], int]] = []
    serial_names = {name for name, _ in serial}
    others = shops - serial_names
    if others:
        phases.append((others, parallel))
    for name, phase_parallel in serial:
        phases.append(({name}, phase_parallel))
    return phases


def _run_items_batch(
    items: list[dict],
    *,
    worker: str,
    shops: set[str],
    parallel: int,
    subphase: str,
    t0: float,
    stats: dict,
    shop_stats: ShopScanStats,
    games_done_base: int = 0,
) -> list[dict]:
    total = len(items)
    updates: list[dict] = []
    phase_done = 0
    base_phase_shops = set(shops)

    def _current_shops() -> set[str]:
        return active_shops_for_worker(worker, base_phase_shops)

    def _scan(idx: int, game: dict) -> dict | None:
        shops_now = _current_shops()
        if not shops_now:
            return None
        return low._scan_one(idx, total, game, shops_now, shop_stats)

    def _progress(game: dict) -> None:
        shops_now = _current_shops()
        elapsed = max(time.perf_counter() - t0, 0.1)
        _save_state(
            {
                "phase": "scan_cdkeys" if worker == "pc" else "scan_keyshops",
                "games_done": games_done_base + phase_done,
                "games_with_hits": stats["games_with_hits"],
                "offers_found": stats["offers_found"],
                "games_per_min": round(phase_done / elapsed * 60, 1),
                "eta_sec": int((total - phase_done) / max(phase_done / elapsed, 0.001))
                if phase_done
                else None,
                "current_game": game.get("title"),
                "scan_subphase": ", ".join(sorted(shops_now)) if shops_now else subphase,
                "shops": sorted(shops_now) if shops_now else [],
                "parallel": parallel,
                "shop_stats": shop_stats.to_dict(),
            },
            worker,
        )

    workers = max(1, min(parallel, total))
    progress_every = 1 if workers == 1 else 10
    if workers == 1:
        for idx, game in enumerate(items, 1):
            _raise_if_stop_requested(worker)
            if not _current_shops():
                _wlog(f"Shops disabled — stop phase at {idx - 1}/{total}", worker)
                break
            shops_now = _current_shops()
            patch = {
                "phase": "scan_cdkeys" if worker == "pc" else "scan_keyshops",
                "games_done": games_done_base + phase_done,
                "current_game": game.get("title"),
                "scan_subphase": ", ".join(sorted(shops_now)) if shops_now else subphase,
                "shops": sorted(shops_now) if shops_now else [],
                "parallel": parallel,
                "shop_stats": shop_stats.to_dict(),
            }
            if "G2A" in shops_now:
                patch["g2a_status"] = peek_g2a_status()
            if "Gamivo" in shops_now:
                patch["gamivo_status"] = _peek_gamivo_status()
            _save_state(patch, worker)
            row = _scan(idx, game)
            if row:
                updates.append(row)
                stats["games_with_hits"] += 1
                stats["offers_found"] += len(row.get("offers") or [])
            phase_done += 1
            if phase_done % progress_every == 0 or phase_done == total:
                _progress(game)
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=workers) as pool:
            _raise_if_stop_requested(worker)
            futures = {
                pool.submit(_scan, idx, game): (idx, game)
                for idx, game in enumerate(items, 1)
            }
            for future in as_completed(futures):
                idx, game = futures[future]
                if _remote_stop_requested(worker):
                    _wlog(f"Stop requested — cancel phase at {phase_done}/{total}", worker)
                    for f in futures:
                        f.cancel()
                    raise StopRequested(f"{worker} scan stop requested by admin")
                if not _current_shops():
                    _wlog(f"Shops disabled — stop phase at {phase_done}/{total}", worker)
                    for f in futures:
                        f.cancel()
                    break
                try:
                    row = future.result()
                except Exception as exc:
                    low._log(f"[{idx}/{total}] scan error: {exc}")
                    row = None
                if row:
                    updates.append(row)
                    stats["games_with_hits"] += 1
                    stats["offers_found"] += len(row.get("offers") or [])
                phase_done += 1
                if phase_done % 10 == 0 or phase_done == total:
                    _progress(game)

    return updates


def run_tier_a_scan(
    *,
    worker: str,
    shops: set[str],
    limit: int,
    parallel: int,
) -> dict:
    if not _wait_list_ready():
        _wlog("Timeout waiting for list_ready", worker)
        _clear_scan_lock(worker)
        return {"error": "list_ready_timeout"}

    queue = low._api("GET", f"admin/offers/queue?tier=top5000&limit={limit}")
    items = queue.get("items") or []
    total = len(items)
    if not total:
        _wlog("Tier A queue empty", worker)
        return {"games": 0, "offers": 0}

    _wlog(
        f"Tier A {worker} start: {total} games, shops={sorted(shops)}, parallel={parallel}",
        worker,
    )

    _save_state(
        {
            "phase": "scan_cdkeys" if worker == "pc" else "scan_keyshops",
            "worker": worker,
            "shops": sorted(shops),
            "parallel": parallel,
            "games_total": total,
            "games_done": 0,
            "games_with_hits": 0,
            "offers_found": 0,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "scan_subphase": None,
            "phase_error": None,
            "duration_sec": None,
            "shop_stats": {},
            "finished_at": None,
            "stopped_at": None,
            "manual_force": _manual_force_enabled(),
        },
        worker,
    )

    t0 = time.perf_counter()
    shop_stats = ShopScanStats()
    stats = {
        "games_done": 0,
        "games_with_hits": 0,
        "offers_found": 0,
        "games_uploaded": 0,
        "offers_uploaded": 0,
    }

    phases = _scan_phases(shops, parallel)
    if "G2A" in shops:
        _configure_g2a_scan()
    if "Gamivo" in shops:
        _configure_gamivo_scan()

    for phase_idx, (phase_shops, phase_parallel) in enumerate(phases):
        subphase = ", ".join(sorted(phase_shops)) or f"phase {phase_idx + 1}"
        try:
            _raise_if_stop_requested(worker)
            phase_shops = active_shops_for_worker(worker, phase_shops)
            if not phase_shops:
                _wlog(f"Skip phase {phase_idx + 1}: no active shops", worker)
                continue
            games_done_base = phase_idx * total
            if phase_idx > 0:
                _pause_with_heartbeat(_phase_pause_sec(phase_shops), phase_shops, worker)
            subphase = ", ".join(sorted(phase_shops))
            _wlog(
                f"=== Phase {phase_idx + 1}/{len(phases)}: {subphase} "
                f"(parallel {phase_parallel}) ===",
                worker,
            )
            _save_state(
                {
                    "phase": "scan_cdkeys" if worker == "pc" else "scan_keyshops",
                    "scan_subphase": subphase,
                    "parallel": phase_parallel,
                    "shops": sorted(phase_shops),
                    "current_game": None,
                    "games_done": games_done_base,
                    "pause_remaining_sec": None,
                },
                worker,
            )
            updates = _run_items_batch(
                items,
                worker=worker,
                shops=phase_shops,
                parallel=phase_parallel,
                subphase=subphase,
                t0=t0,
                stats=stats,
                shop_stats=shop_stats,
                games_done_base=games_done_base,
            )
            _upload_updates(updates, worker=worker, subphase=subphase, stats=stats)
        except StopRequested as exc:
            state = _load_state(worker)
            done = int(state.get("games_done") or 0)
            _wlog(str(exc), worker)
            _mark_stopped(worker, total=total, done=done, stats=stats)
            _clear_scan_lock(worker)
            return {"stopped": True, "games": stats["games_uploaded"], "offers": stats["offers_uploaded"]}
        except Exception as exc:
            _wlog(f"Phase {subphase} failed: {exc}", worker)
            _save_state(
                {
                    "phase_error": str(exc)[:300],
                    "scan_subphase": f"error: {subphase}",
                },
                worker,
            )
            continue

    duration_sec = round(time.perf_counter() - t0, 1)
    _save_state(
        {
            "phase": "done",
            "games_done": total,
            "games_with_hits": stats["games_with_hits"],
            "offers_found": stats["offers_found"],
            "offers_uploaded": stats["offers_uploaded"],
            "games_uploaded": stats["games_uploaded"],
            "finished_at": datetime.utcnow().isoformat() + "Z",
            "duration_sec": duration_sec,
            "scan_subphase": None,
            "current_game": None,
            "eta_sec": None,
            "games_per_min": None,
            "pause_remaining_sec": None,
            "shops": sorted(shops),
            "shop_stats": shop_stats.to_dict(),
        },
        worker,
    )
    _clear_scan_lock(worker)
    return {"games": stats["games_uploaded"], "offers": stats["offers_uploaded"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Tier A keyshop worker")
    parser.add_argument("--worker", choices=("laptop", "pc"), default="laptop")
    parser.add_argument("--limit", type=int, default=int(os.environ.get("TIER_A_SIZE", "5000")))
    parser.add_argument("--parallel", type=int, default=int(os.environ.get("SCAN_PARALLEL", "8")))
    parser.add_argument(
        "--shops",
        type=str,
        default=os.environ.get(
            "TIER_A_PC_SHOPS_ONLY",
            os.environ.get("TIER_A_LAPTOP_SHOPS_ONLY", os.environ.get("TIER_A_SHOPS_ONLY", "")),
        ),
        help="comma-separated shops (PC: CDKeys,Gamivo; overrides default worker shops)",
    )
    args = parser.parse_args()

    force = _manual_force_enabled()
    if not force:
        from app.parsers.tier_a_auto_scan import is_auto_scan_paused

        paused = is_auto_scan_paused()
        if not paused:
            try:
                paused = bool(low._api("GET", "admin/tier-a/status").get("auto_scan_paused"))
            except Exception:
                pass
        if paused:
            _wlog("exit: auto scan paused", args.worker)
            print("Tier A auto scan is paused — set TIER_A_FORCE_SCAN=1 for manual run")
            return 0

    if not low.ACCESS_CODE:
        print("Set PANEL3_ACCESS_CODE", file=sys.stderr)
        return 1

    try:
        remote = low._api("GET", "admin/scan-routing")
        if remote.get("routing"):
            from app.parsers.shop_scan_config import save_scan_routing

            save_scan_routing(remote["routing"])
    except Exception as exc:
        _wlog(f"Routing sync skipped: {exc}", args.worker)

    if args.worker == "laptop":
        default_shops = set(get_shops_for_worker("laptop"))
    else:
        default_shops = set(get_shops_for_worker("pc"))

    shops_override = {s.strip() for s in args.shops.split(",") if s.strip()}
    if shops_override:
        active = set(filter_active_shops(tuple(shops_override)))
        shops = active & set(EXPECTED_SHOPS)
        unknown = shops_override - set(EXPECTED_SHOPS)
        if unknown:
            _wlog(f"Ignored unknown shops: {sorted(unknown)}", args.worker)
        disabled = shops_override - shops - unknown
        if disabled:
            _wlog(f"Skipped disabled shops: {sorted(disabled)}", args.worker)
    else:
        shops = default_shops

    if not shops:
        _wlog(
            f"No active shops for {args.worker} — enable shops in SP Admin or disabled_scan_shops.json",
            args.worker,
        )
        return 1

    parallel = args.parallel
    if args.worker == "laptop" and "G2A" in shops:
        _configure_g2a_scan()
        laptop_parallel = int(os.environ.get("TIER_A_LAPTOP_PARALLEL", os.environ.get("SCAN_PARALLEL", "4")))
        parallel = min(parallel, laptop_parallel)
    if args.worker == "pc" and "Gamivo" in shops:
        _configure_gamivo_scan()

    os.environ["TIER_A_WORKER"] = args.worker
    os.environ.setdefault("ENEBA_SLUG_DELAY_SEC", "0.5")
    stats = run_tier_a_scan(
        worker=args.worker,
        shops=shops,
        limit=args.limit,
        parallel=parallel,
    )
    if stats.get("error"):
        return 1
    low._log(f"Tier A {args.worker} done: {stats}")
    _wlog(f"Tier A {args.worker} done: {stats}", args.worker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
