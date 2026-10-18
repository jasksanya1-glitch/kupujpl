"""Control plane for independent per-shop scanners (systemd template units)."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.database import BASE_DIR

logger = logging.getLogger("scanner_control")

CONTROL_DIR = Path(BASE_DIR) / "tmp" / "scanner_control"
PAUSE_ALL = CONTROL_DIR / "PAUSE_ALL"
SITE_THROTTLE = CONTROL_DIR / "SITE_THROTTLE"

# systemd instance name -> Offer.shop_name
SHOP_SLUGS: dict[str, str] = {
    "steam": "Steam",
    "gog": "GOG",
    "epic": "Epic Games",
    "g2a": "G2A",
    "gamivo": "Gamivo",
    "kinguin": "Kinguin",
    "fanatical": "Fanatical",
    "cdkeys": "CDKeys",
    "instantgaming": "Instant Gaming",
}

SHOP_TO_SLUG: dict[str, str] = {v: k for k, v in SHOP_SLUGS.items()}

UNIT_TEMPLATE = "kupujpl-scanner@{slug}.service"
SLICE_NAME = "kupujpl-scanners.slice"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_control_dir() -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)


def pause_path(slug: str) -> Path:
    return CONTROL_DIR / f"PAUSE_{slug}"


def is_paused(slug: str | None = None) -> bool:
    ensure_control_dir()
    if PAUSE_ALL.is_file() or SITE_THROTTLE.is_file():
        return True
    if slug and pause_path(slug).is_file():
        return True
    return False


def pause_reason(slug: str | None = None) -> str | None:
    ensure_control_dir()
    if SITE_THROTTLE.is_file():
        return "site_throttle"
    if PAUSE_ALL.is_file():
        return "pause_all"
    if slug and pause_path(slug).is_file():
        return f"pause_{slug}"
    return None


def set_paused(slug: str | None, paused: bool, *, reason: str = "") -> dict[str, Any]:
    ensure_control_dir()
    path = PAUSE_ALL if slug is None or slug == "all" else pause_path(slug)
    if paused:
        path.write_text(
            json.dumps(
                {
                    "paused_at": _utcnow().isoformat() + "Z",
                    "reason": reason or "manual",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    else:
        path.unlink(missing_ok=True)
        if slug in (None, "all"):
            SITE_THROTTLE.unlink(missing_ok=True)
    return {"slug": slug or "all", "paused": paused, "path": str(path)}


def set_site_throttle(active: bool, *, detail: str = "") -> None:
    ensure_control_dir()
    if active:
        SITE_THROTTLE.write_text(
            json.dumps(
                {"at": _utcnow().isoformat() + "Z", "detail": detail[:300]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    else:
        SITE_THROTTLE.unlink(missing_ok=True)


def slug_to_shop(slug: str) -> str:
    key = (slug or "").strip().lower()
    if key not in SHOP_SLUGS:
        raise ValueError(f"Unknown scanner slug: {slug}")
    return SHOP_SLUGS[key]


def shop_to_slug(shop: str) -> str:
    if shop not in SHOP_TO_SLUG:
        raise ValueError(f"Unknown shop: {shop}")
    return SHOP_TO_SLUG[shop]


def unit_name(slug: str) -> str:
    return UNIT_TEMPLATE.format(slug=slug.lower())


_READ_SYSTEMCTL = frozenset({"is-active", "is-enabled", "show", "list-units", "status"})


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    """Run systemctl.

    Read-only verbs work as www-data without sudo. Mutating verbs need
    passwordless sudo — but kupujpl-games.service sets NoNewPrivileges=yes,
    which blocks sudo elevation. Prefer bare systemctl for reads so Panel3
    status never goes blank; use sudo only for start/stop/restart.
    """
    verb = (args[0] if args else "").strip().lower()
    cmd = ["systemctl", *args]
    needs_root = verb not in _READ_SYSTEMCTL
    if needs_root and os.geteuid() != 0:
        cmd = ["sudo", "-n", *cmd]
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def scanner_unit_status(slug: str) -> dict[str, Any]:
    unit = unit_name(slug)
    active = _systemctl("is-active", unit)
    enabled = _systemctl("is-enabled", unit)
    show = _systemctl(
        "show",
        unit,
        "-p",
        "ActiveState",
        "-p",
        "SubState",
        "-p",
        "MainPID",
        "-p",
        "NRestarts",
        "-p",
        "ActiveEnterTimestamp",
    )
    props: dict[str, str] = {}
    for line in (show.stdout or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    return {
        "slug": slug,
        "shop": SHOP_SLUGS.get(slug),
        "unit": unit,
        "is_active": (active.stdout or "").strip(),
        "is_enabled": (enabled.stdout or "").strip(),
        "paused": is_paused(slug),
        "pause_reason": pause_reason(slug),
        "main_pid": int(props.get("MainPID") or 0),
        "n_restarts": int(props.get("NRestarts") or 0),
        "active_enter": props.get("ActiveEnterTimestamp") or "",
        "sub_state": props.get("SubState") or "",
    }


def list_scanner_statuses() -> list[dict[str, Any]]:
    return [scanner_unit_status(slug) for slug in SHOP_SLUGS]


def restart_scanner(slug: str) -> dict[str, Any]:
    unit = unit_name(slug)
    r = _systemctl("restart", unit)
    return {
        "slug": slug,
        "unit": unit,
        "ok": r.returncode == 0,
        "stderr": (r.stderr or "")[:300],
    }


def stop_scanner(slug: str) -> dict[str, Any]:
    unit = unit_name(slug)
    r = _systemctl("stop", unit)
    return {"slug": slug, "unit": unit, "ok": r.returncode == 0, "stderr": (r.stderr or "")[:300]}


def start_scanner(slug: str) -> dict[str, Any]:
    unit = unit_name(slug)
    r = _systemctl("start", unit)
    return {"slug": slug, "unit": unit, "ok": r.returncode == 0, "stderr": (r.stderr or "")[:300]}


def independent_mode_enabled() -> bool:
    return os.environ.get("SCAN_INDEPENDENT_MODE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
