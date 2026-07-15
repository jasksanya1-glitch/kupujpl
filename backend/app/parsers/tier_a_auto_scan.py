"""Global pause for scheduled Tier A auto-scans (manual force still allowed)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.database import BASE_DIR

PAUSE_PATH = Path(BASE_DIR) / "tmp" / "tier_a_auto_scan_paused.json"


def load_auto_scan_pause() -> dict[str, Any]:
    if not PAUSE_PATH.is_file():
        return {"paused": False}
    try:
        data = json.loads(PAUSE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"paused": False}
        return data
    except (json.JSONDecodeError, OSError):
        return {"paused": False}


def is_auto_scan_paused() -> bool:
    if os.environ.get("TIER_A_AUTO_SCAN_PAUSED", "").strip().lower() in ("1", "true", "yes"):
        return True
    return bool(load_auto_scan_pause().get("paused"))


def set_auto_scan_paused(paused: bool, *, reason: str = "", by: str = "admin") -> dict[str, Any]:
    if paused:
        payload = {
            "paused": True,
            "reason": reason or "paused by admin",
            "by": by,
            "paused_at": datetime.utcnow().isoformat() + "Z",
        }
        PAUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PAUSE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    if PAUSE_PATH.is_file():
        PAUSE_PATH.unlink()
    return {"paused": False, "resumed_at": datetime.utcnow().isoformat() + "Z", "by": by}
