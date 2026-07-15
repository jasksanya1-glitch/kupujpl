#!/usr/bin/env python3
"""Netdata python.d collector — Tier A scan progress (laptop: local + VPS poll)."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.database import BASE_DIR
from app.parsers.tier_a_scan_state import load_laptop_state

VPS_STATUS_URL = os.environ.get(
    "TIER_A_VPS_STATUS_URL",
    "https://kupujpl.pl/games/api/admin/tier-a/status",
)
PANEL3_CODE = os.environ.get("PANEL3_ACCESS_CODE", os.environ.get("PANEL3_CODE", "")).strip()
LAPTOP_STATE = Path(BASE_DIR) / "tmp" / "laptop_scan_state.json"


def _poll_vps() -> dict:
    if not PANEL3_CODE:
        return {}
    req = urllib.request.Request(
        VPS_STATUS_URL,
        headers={"X-Panel3-Code": PANEL3_CODE, "User-Agent": "NetdataTierA/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def _pct(done: int, total: int) -> float:
    if not total:
        return 0.0
    return round(done / total * 100.0, 2)


def main() -> int:
    laptop = load_laptop_state()
    if LAPTOP_STATE.is_file():
        try:
            laptop = json.loads(LAPTOP_STATE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    vps_status = _poll_vps()
    vps = vps_status.get("vps") or {}

    charts = {
        "tier_a_laptop_done": laptop.get("games_done") or 0,
        "tier_a_laptop_total": laptop.get("games_total") or 0,
        "tier_a_laptop_progress_pct": _pct(
            int(laptop.get("games_done") or 0),
            int(laptop.get("games_total") or 0),
        ),
        "tier_a_vps_done": vps.get("games_done") or 0,
        "tier_a_vps_total": vps.get("games_total") or 0,
        "tier_a_vps_progress_pct": _pct(
            int(vps.get("games_done") or 0),
            int(vps.get("games_total") or 0),
        ),
        "tier_a_list_ready": 1 if vps_status.get("list_ready") else 0,
        "tier_a_vps_eta_sec": vps.get("eta_sec") or 0,
        "tier_a_laptop_eta_sec": laptop.get("eta_sec") or 0,
    }

    for key, val in charts.items():
        print(f"{key}: {val}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
