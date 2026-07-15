#!/usr/bin/env python3
"""HTTP trigger for Tier A PC scan — POST /api/tier-a/trigger|stop (X-Panel3-Code)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOG = ROOT / "tmp" / "pc_scan_listener.log"
WORKER_LOG = ROOT / "tmp" / "pc_scan_worker.log"
LOCK = ROOT / "tmp" / "pc_scan.lock"
PORT = int(os.environ.get("PC_SCAN_LISTENER_PORT", "8878"))


class PcScanHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _load_token() -> str:
    token = os.environ.get("PANEL3_ACCESS_CODE", "").strip()
    if token:
        return token
    cfg = Path(__file__).resolve().parent / "scan_config.env"
    if cfg.is_file():
        for line in cfg.read_text(encoding="utf-8").splitlines():
            if line.startswith("PANEL3_ACCESS_CODE="):
                return line.split("=", 1)[1].strip()
    return "1408"


TOKEN = _load_token()
if TOKEN and not os.environ.get("PANEL3_ACCESS_CODE"):
    os.environ["PANEL3_ACCESS_CODE"] = TOKEN
if not os.environ.get("GAMES_API_URL"):
    os.environ["GAMES_API_URL"] = "https://kupujpl.pl/games"


def _scan_config_values() -> dict[str, str]:
    cfg = ROOT / "tools" / "scan_config.env"
    values: dict[str, str] = {}
    if not cfg.is_file():
        return values
    for raw in cfg.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.utcnow().isoformat()}Z {msg}\n"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line)


def _remote_auto_scan_paused() -> bool:
    import urllib.request

    api = os.environ.get("GAMES_API_URL", "https://kupujpl.pl/games").rstrip("/")
    req = urllib.request.Request(
        f"{api}/api/admin/tier-a/status",
        headers={"X-Panel3-Code": TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return bool(data.get("auto_scan_paused"))
    except Exception:
        return False


def _stop_scan() -> list[int]:
    """Kill local Tier A PC scan worker processes."""
    killed: list[int] = []
    try:
        ps = (
            "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
            "Where-Object { $_.CommandLine -like '*tier_a_scan_worker.py*' "
            "-or $_.CommandLine -like '*tier_a_pc_scan.ps1*' "
            "-or $_.CommandLine -like '*daily_tier_a_laptop.ps1*' "
            "-or $_.CommandLine -like '*run_gentle_laptop_scan.ps1*' "
            "-or $_.CommandLine -like '*start_laptop_worker*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $_.ProcessId }"
        )
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        for line in (out.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                killed.append(int(line))
    except Exception as exc:
        _log(f"stop scan error: {exc}")
    LOCK.unlink(missing_ok=True)
    _mark_workers_stopped(killed)
    return killed


def _mark_workers_stopped(killed: list[int]) -> None:
    now = datetime.utcnow().isoformat() + "Z"
    patch = {
        "phase": "stopped",
        "stopped_at": now,
        "eta_sec": None,
        "games_per_min": None,
        "current_game": None,
        "phase_error": None,
        "pause_remaining_sec": None,
        "stop_killed_pids": killed,
    }
    try:
        from app.parsers.tier_a_scan_state import save_laptop_state, save_pc_state

        pc_state = save_pc_state({"worker": "pc", **patch})
        laptop_state = save_laptop_state({"worker": "laptop", **patch})
        try:
            import local_offer_worker as low
        except Exception:
            low = None
        if low is not None:
            for endpoint, state in (
                ("admin/tier-a/pc-state", pc_state),
                ("admin/tier-a/laptop-state", laptop_state),
            ):
                try:
                    low._api("POST", endpoint, state)
                except Exception as exc:
                    _log(f"push stopped state {endpoint}: {exc}")
    except Exception as exc:
        _log(f"mark stopped state error: {exc}")


def _scan_process_running() -> bool:
    try:
        ps = (
            "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
            "Where-Object { $_.CommandLine -like '*tier_a_scan_worker.py*' "
            "-or $_.CommandLine -like '*tier_a_pc_scan.ps1*' } | "
            "Select-Object -First 1 -ExpandProperty ProcessId"
        )
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=8,
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return any(line.strip().isdigit() for line in (out.stdout or "").splitlines())
    except Exception as exc:
        _log(f"scan process check error: {exc}")
        return False


def _acquire_scan_lock() -> bool:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - LOCK.stat().st_mtime
            except OSError:
                age = 0
            if age < 6 * 3600 and _scan_process_running():
                _log("trigger skipped: scan already running")
                return False
            _log("clearing stale scan lock")
            LOCK.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(datetime.utcnow().isoformat() + "Z\n")
        return True
    return False


def _start_scan(*, force: bool = False, shops: str = "") -> bool:
    if not force:
        pause_file = ROOT / "tmp" / "tier_a_auto_scan_paused.json"
        if pause_file.is_file():
            try:
                if json.loads(pause_file.read_text(encoding="utf-8")).get("paused"):
                    _log("trigger skipped: auto scan paused (local)")
                    return False
            except (json.JSONDecodeError, OSError):
                pass
        if _remote_auto_scan_paused():
            _log("trigger skipped: auto scan paused (VPS)")
            return False
    if not _acquire_scan_lock():
        return False
    script = ROOT / "tools" / "tier_a_pc_scan.ps1"
    WORKER_LOG.parent.mkdir(parents=True, exist_ok=True)
    log_handle = WORKER_LOG.open("a", encoding="utf-8")
    log_handle.write(f"\n{datetime.utcnow().isoformat()}Z === PC scan started ===\n")
    log_handle.flush()
    env = os.environ.copy()
    if force:
        env["TIER_A_FORCE_SCAN"] = "1"
        cfg = _scan_config_values()
        # The listener may have been started from a one-game diagnostic shell.
        # Manual UI runs must use the production queue size from scan_config.env.
        if cfg.get("TIER_A_SIZE"):
            env["TIER_A_SIZE"] = cfg["TIER_A_SIZE"]
    if shops.strip():
        env["TIER_A_PC_SHOPS_ONLY"] = shops.strip()
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        cwd=str(ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        _log(fmt % args)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,X-Panel3-Code,X-Tier-A-Force,X-Tier-A-Shops")

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/api/health":
            self._json(200, {"ok": True, "service": "pc-scan-listener"})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        path = self.path.rstrip("/")
        local_request = self.client_address[0] in ("127.0.0.1", "::1")
        if self.headers.get("X-Panel3-Code") != TOKEN and not (local_request and path == "/api/tier-a/stop"):
            _log(f"rejected {self.client_address[0]}")
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        if path == "/api/tier-a/stop":
            killed = _stop_scan()
            _log(f"stop OK {self.client_address[0]} killed={killed}")
            self._json(200, {"ok": True, "message": "PC scan stopped", "killed_pids": killed})
            return
        if path != "/api/tier-a/trigger":
            self.send_error(404)
            return
        force = self.headers.get("X-Tier-A-Force", "").strip() in ("1", "true", "yes")
        shops = self.headers.get("X-Tier-A-Shops", "").strip()
        if not _start_scan(force=force, shops=shops):
            self._json(200, {"ok": True, "message": "PC scan skipped — auto scan paused", "skipped": True})
            return
        _log(f"trigger OK {self.client_address[0]} force={force} shops={shops or '(default)'}")
        self._json(200, {"ok": True, "message": "PC scan started"})


def main() -> int:
    host = os.environ.get("PC_SCAN_LISTENER_HOST", "0.0.0.0")
    server = PcScanHTTPServer((host, PORT), Handler)
    _log(f"listening {host}:{PORT}")
    print(f"PC scan listener http://{host}:{PORT}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
