"""Live Tier A scan progress (VPS + laptop state files)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.database import BASE_DIR

VPS_STATE_PATH = Path(BASE_DIR) / "tmp" / "tier_a_scan_state.json"
LAPTOP_STATE_PATH = Path(BASE_DIR) / "tmp" / "laptop_scan_state.json"
PC_STATE_PATH = Path(BASE_DIR) / "tmp" / "pc_scan_state.json"
VPS_CANCEL_FLAG_PATH = Path(BASE_DIR) / "tmp" / "tier_a_vps_cancel.flag"
WORKER_CANCEL_FLAG_PATHS = {
    "laptop": Path(BASE_DIR) / "tmp" / "tier_a_laptop_cancel.flag",
    "pc": Path(BASE_DIR) / "tmp" / "tier_a_pc_cancel.flag",
}


def _worker_name(worker: str | None) -> str:
    return "pc" if str(worker or "").lower() == "pc" else "laptop"


def clear_vps_cancel() -> None:
    if VPS_CANCEL_FLAG_PATH.is_file():
        VPS_CANCEL_FLAG_PATH.unlink()


def request_vps_cancel() -> None:
    VPS_CANCEL_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    VPS_CANCEL_FLAG_PATH.write_text(datetime.utcnow().isoformat() + "Z", encoding="utf-8")


def is_vps_cancel_requested() -> bool:
    return VPS_CANCEL_FLAG_PATH.is_file()


def clear_worker_cancel(worker: str | None) -> None:
    path = WORKER_CANCEL_FLAG_PATHS[_worker_name(worker)]
    if path.is_file():
        path.unlink()


def request_worker_cancel(worker: str | None) -> None:
    path = WORKER_CANCEL_FLAG_PATHS[_worker_name(worker)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.utcnow().isoformat() + "Z", encoding="utf-8")


def is_worker_cancel_requested(worker: str | None) -> bool:
    return WORKER_CANCEL_FLAG_PATHS[_worker_name(worker)].is_file()


def stop_vps_scan() -> dict[str, Any]:
    vps = load_vps_state()
    phase = str(vps.get("phase") or "idle")
    if phase not in ("rebuild_list", "scan_official"):
        return {"ok": False, "message": "VPS Tier A scan is not running", "phase": phase}
    request_vps_cancel()
    now = datetime.utcnow().isoformat() + "Z"
    done = int(vps.get("games_done") or 0)
    total = int(vps.get("games_total") or 0)
    save_vps_state(
        {
            "phase": "stopped",
            "stopped_at": now,
            "eta_sec": None,
            "games_per_min": None,
            "current_game": None,
        }
    )
    return {
        "ok": True,
        "message": f"VPS scan stop requested ({done}/{total} games)",
        "games_done": done,
        "games_total": total,
    }


def stop_worker_scan(worker: str | None) -> dict[str, Any]:
    name = _worker_name(worker)
    state = load_pc_state() if name == "pc" else load_laptop_state()
    running_phase = "scan_cdkeys" if name == "pc" else "scan_keyshops"
    phase = str(state.get("phase") or "idle")
    request_worker_cancel(name)
    now = datetime.utcnow().isoformat() + "Z"
    done = int(state.get("games_done") or 0)
    total = int(state.get("games_total") or 0)
    patch = {
        "worker": name,
        "phase": "stopped",
        "stopped_at": now,
        "eta_sec": None,
        "games_per_min": None,
        "current_game": None,
        "pause_remaining_sec": None,
    }
    if name == "pc":
        save_pc_state(patch)
    else:
        save_laptop_state(patch)
    return {
        "ok": True,
        "worker": name,
        "message": (
            f"{name} stop requested ({done}/{total} games)"
            if phase == running_phase
            else f"{name} stop requested; worker was {phase}"
        ),
        "games_done": done,
        "games_total": total,
    }


def stop_local_scans() -> dict[str, Any]:
    laptop = stop_worker_scan("laptop")
    pc = stop_worker_scan("pc")
    return {"ok": True, "message": "Local scan stop requested", "laptop": laptop, "pc": pc}


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _apply_patch(state: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if value is None:
            state.pop(key, None)
        else:
            state[key] = value


def _clear_running_stale_fields(state: dict[str, Any], patch: dict[str, Any]) -> None:
    phase = patch.get("phase")
    running_phases = {"rebuild_list", "scan_official", "scan_keyshops", "scan_cdkeys"}
    terminal_phases = {"done", "stopped", "failed", "idle"}
    if phase in running_phases:
        if "phase_error" not in patch:
            state.pop("phase_error", None)
        if "duration_sec" not in patch:
            state.pop("duration_sec", None)
        for key in ("finished_at", "stopped_at", "failed_at", "progress_pct"):
            if key not in patch:
                state.pop(key, None)
    elif phase in terminal_phases:
        for key in ("current_game", "eta_sec", "games_per_min", "pause_remaining_sec", "scan_subphase"):
            if key not in patch:
                state.pop(key, None)


def load_vps_state() -> dict[str, Any]:
    return _read(VPS_STATE_PATH)


def save_vps_state(patch: dict[str, Any]) -> dict[str, Any]:
    state = load_vps_state()
    _apply_patch(state, patch)
    _clear_running_stale_fields(state, patch)
    _write(VPS_STATE_PATH, state)
    return state


def load_laptop_state() -> dict[str, Any]:
    return _read(LAPTOP_STATE_PATH)


def save_laptop_state(patch: dict[str, Any]) -> dict[str, Any]:
    state = load_laptop_state()
    _apply_patch(state, patch)
    _clear_running_stale_fields(state, patch)
    _write(LAPTOP_STATE_PATH, state)
    return state


def load_pc_state() -> dict[str, Any]:
    return _read(PC_STATE_PATH)


def save_pc_state(patch: dict[str, Any]) -> dict[str, Any]:
    state = load_pc_state()
    _apply_patch(state, patch)
    _clear_running_stale_fields(state, patch)
    _write(PC_STATE_PATH, state)
    return state


def save_worker_state(patch: dict[str, Any]) -> dict[str, Any]:
    worker = str(patch.get("worker") or "").lower()
    if worker == "pc":
        return save_pc_state(patch)
    return save_laptop_state(patch)


def _phase_label(phase: str | None) -> str:
    labels = {
        "rebuild_list": "Оновлення списку top-5000",
        "scan_official": "Офіційні магазини (VPS)",
        "scan_keyshops": "Keyshop-и (ноутбук)",
        "scan_cdkeys": "CDKeys (ПК)",
        "done": "Завершено",
        "stopped": "Зупинено",
        "failed": "Помилка",
        "idle": "Очікування",
    }
    return labels.get(phase or "", phase or "—")


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        raw = str(ts).replace("Z", "")
        if "." in raw:
            head, tail = raw.split(".", 1)
            raw = f"{head}.{tail[:6]}"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _elapsed_sec(state: dict[str, Any]) -> int | None:
    t0 = _parse_iso(state.get("started_at"))
    if not t0:
        return None
    t1 = _parse_iso(state.get("finished_at")) or datetime.utcnow()
    return max(0, int((t1 - t0).total_seconds()))


def _duration_sec(state: dict[str, Any]) -> int | None:
    raw = state.get("duration_sec")
    if raw is not None:
        try:
            return max(0, int(round(float(raw))))
        except (TypeError, ValueError):
            pass
    elapsed = _elapsed_sec(state)
    if state.get("phase") == "done" and elapsed is not None:
        return elapsed
    return None


def _infer_worker_phase(state: dict[str, Any], worker: str) -> str:
    phase = str(state.get("phase") or "idle")
    running = "scan_cdkeys" if worker == "pc" else "scan_keyshops"
    stopped_at = _parse_iso(state.get("stopped_at"))
    done = int(state.get("games_done") or 0)
    total = int(state.get("games_total") or 0)
    if stopped_at and (not total or done < total):
        return "stopped" if (datetime.utcnow() - stopped_at).total_seconds() <= 86400 else "idle"
    if phase in (
        "rebuild_list",
        "scan_official",
        "scan_keyshops",
        "scan_cdkeys",
        "done",
        "failed",
    ):
        return phase
    if state.get("finished_at"):
        return "done"
    if state.get("current_game") or state.get("scan_subphase"):
        updated = _parse_iso(state.get("updated_at"))
        if updated and (datetime.utcnow() - updated).total_seconds() <= 300:
            return running
    if state.get("games_per_min") is not None or state.get("eta_sec") is not None:
        updated = _parse_iso(state.get("updated_at"))
        if updated and (datetime.utcnow() - updated).total_seconds() <= 300:
            return running
    if phase == "stopped":
        if stopped_at and (datetime.utcnow() - stopped_at).total_seconds() <= 180:
            return "stopped"
        return "idle"
    return phase or "idle"


def _enrich_worker(state: dict[str, Any], default_shops: list[str]) -> dict[str, Any]:
    worker = str(state.get("worker") or ("pc" if "CDKeys" in default_shops else "laptop"))
    phase = _infer_worker_phase(state, worker)
    state = {**state, "phase": phase}
    done = int(state.get("games_done") or 0)
    total = int(state.get("games_total") or 0)
    elapsed = _elapsed_sec(state)
    duration = _duration_sec(state)
    out = {
        **state,
        "progress_pct": round(done / total * 100, 1) if total else 0,
        "phase_label": _phase_label(phase),
        "cancel_requested": is_worker_cancel_requested(worker),
        "elapsed_sec": elapsed,
        "duration_sec": duration,
        "shops": state.get("shops") or default_shops,
    }
    if phase == "done" and duration is not None:
        out["phase_label"] = f"{out['phase_label']} · {_format_duration(duration)}"
    return out


def _format_duration(sec: int) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h} год {m} хв"
    if m > 0:
        return f"{m} хв {s} с"
    return f"{s} с"


def _schedule_config() -> dict[str, str]:
    hour = int(os.environ.get("TIER_A_DAILY_HOUR", "2"))
    minute = int(os.environ.get("TIER_A_DAILY_MINUTE", "30"))
    vps_local = os.environ.get("TIER_A_VPS_LOCAL_TIME", f"{hour:02d}:{minute:02d}")
    return {
        "timezone": os.environ.get("TIER_A_TZ", "Europe/Warsaw"),
        "vps_local": vps_local,
        "vps_utc": os.environ.get("TIER_A_VPS_UTC_LABEL", "00:30/01:30"),
        "pc_local": os.environ.get("TIER_A_PC_LOCAL_TIME", "06:10"),
        "laptop_local": os.environ.get("TIER_A_LAPTOP_LOCAL_TIME", "12:40"),
    }


def get_tier_a_scan_schedule_public() -> dict[str, str]:
    """Public scan schedule labels for user-facing copy."""
    return _schedule_config()


def get_tier_a_status() -> dict[str, Any]:
    from app.parsers.shop_scan_config import (
        get_disabled_scan_shops,
        get_shops_for_worker,
    )
    from app.parsers.tier_a_top5000 import load_tier_a_cache, next_tier_a_scan_at
    from app.parsers.tier_a_auto_scan import is_auto_scan_paused, load_auto_scan_pause

    cache = load_tier_a_cache()
    vps_raw = load_vps_state()
    laptop_raw = load_laptop_state()
    pc_raw = load_pc_state()

    vps_shops = list(get_shops_for_worker("vps"))
    lap_shops = list(get_shops_for_worker("laptop"))
    pc_shops = list(get_shops_for_worker("pc"))
    disabled = sorted(get_disabled_scan_shops())

    vps = _enrich_worker(vps_raw, vps_shops)
    laptop = _enrich_worker(laptop_raw, lap_shops)
    pc = _enrich_worker(pc_raw, pc_shops)

    vps_phase = vps.get("phase")
    lap_phase = laptop.get("phase")
    pc_phase = pc.get("phase")
    scan_active = (
        vps_phase in ("rebuild_list", "scan_official")
        or lap_phase == "scan_keyshops"
        or pc_phase == "scan_cdkeys"
    )

    return {
        "list_ready": bool(cache.get("list_ready")),
        "list_version": cache.get("version"),
        "list_count": cache.get("count", 0),
        "list_source": cache.get("source"),
        "list_source_label": cache.get("source_label"),
        "list_source_note": cache.get("source_note"),
        "list_fallback_count": cache.get("fallback_count", 0),
        "cache_rebuilt_at": cache.get("rebuilt_at"),
        "next_scheduled_at": vps_raw.get("next_scheduled_at") or next_tier_a_scan_at(),
        "auto_scan_paused": is_auto_scan_paused(),
        "auto_scan_pause": load_auto_scan_pause(),
        "scan_active": scan_active,
        "schedule": _schedule_config(),
        "shops": {
            "vps": vps_shops,
            "laptop": lap_shops,
            "pc": pc_shops,
            "disabled": disabled,
        },
        "vps": vps,
        "laptop": laptop,
        "pc": pc,
        "summary": {
            "list_count": int(cache.get("count") or 0),
            "vps_done": int(vps.get("games_done") or 0),
            "vps_total": int(vps.get("games_total") or 0),
            "vps_pct": float(vps.get("progress_pct") or 0),
            "vps_errors": int(vps.get("errors") or 0),
            "lap_done": int(laptop.get("games_done") or 0),
            "lap_total": int(laptop.get("games_total") or 0),
            "lap_pct": float(laptop.get("progress_pct") or 0),
            "lap_hits": int(laptop.get("games_with_hits") or 0),
            "lap_offers": int(laptop.get("offers_uploaded") or laptop.get("offers_found") or 0),
            "pc_done": int(pc.get("games_done") or 0),
            "pc_total": int(pc.get("games_total") or 0),
            "pc_pct": float(pc.get("progress_pct") or 0),
            "pc_hits": int(pc.get("games_with_hits") or 0),
            "pc_offers": int(pc.get("offers_uploaded") or pc.get("offers_found") or 0),
        },
    }
