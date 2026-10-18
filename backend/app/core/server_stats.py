"""Host / process metrics for Panel3 real-time server stats (no psutil)."""
from __future__ import annotations

import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.core.database import BASE_DIR

_CPU_SAMPLE: dict[str, Any] | None = None
_NET_SAMPLE: dict[str, Any] | None = None

HEALTH_URL = os.environ.get("SCAN_SITEGUARD_URL", "http://127.0.0.1:8000/api/health")
DB_PATH = Path(os.environ.get("SQLITE_PATH") or (Path(BASE_DIR) / "database.db"))


def _read_loadavg() -> dict[str, float | int]:
    raw = Path("/proc/loadavg").read_text(encoding="utf-8").split()
    return {
        "load1": float(raw[0]),
        "load5": float(raw[1]),
        "load15": float(raw[2]),
        "running": int(raw[3].split("/")[0]),
        "procs": int(raw[3].split("/")[1]),
    }


def _read_mem() -> dict[str, Any]:
    info: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        key = parts[0].rstrip(":")
        try:
            info[key] = int(parts[1])  # kB
        except ValueError:
            continue
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", info.get("MemFree", 0))
    used = max(0, total - available)
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    return {
        "total_mb": round(total / 1024, 1),
        "used_mb": round(used / 1024, 1),
        "available_mb": round(available / 1024, 1),
        "used_pct": round(100.0 * used / total, 1) if total else 0.0,
        "swap_total_mb": round(swap_total / 1024, 1),
        "swap_used_mb": round((swap_total - swap_free) / 1024, 1),
    }


def _read_cpu_times() -> tuple[int, int]:
    """Return (idle+iowait, total) jiffies from /proc/stat."""
    for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
        if not line.startswith("cpu "):
            continue
        parts = [int(x) for x in line.split()[1:]]
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
        total = sum(parts)
        return idle, total
    return 0, 0


def _cpu_percent() -> float | None:
    global _CPU_SAMPLE
    idle, total = _read_cpu_times()
    now = time.monotonic()
    prev = _CPU_SAMPLE
    _CPU_SAMPLE = {"idle": idle, "total": total, "t": now}
    if not prev or total <= prev["total"]:
        return None
    d_total = total - prev["total"]
    d_idle = idle - prev["idle"]
    if d_total <= 0:
        return None
    return round(max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total))), 1)


def _read_disk(path: str = "/") -> dict[str, Any]:
    st = os.statvfs(path)
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bavail
    used = total - free
    return {
        "path": path,
        "total_gb": round(total / (1024**3), 2),
        "used_gb": round(used / (1024**3), 2),
        "free_gb": round(free / (1024**3), 2),
        "used_pct": round(100.0 * used / total, 1) if total else 0.0,
    }


def _read_uptime() -> dict[str, Any]:
    sec = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    days = int(sec // 86400)
    hours = int((sec % 86400) // 3600)
    mins = int((sec % 3600) // 60)
    return {
        "seconds": int(sec),
        "human": f"{days}д {hours}г {mins}хв" if days else f"{hours}г {mins}хв",
    }


def _read_net_rates() -> dict[str, Any]:
    """Aggregate eth/ens interface bytes; rate from previous sample."""
    global _NET_SAMPLE
    rx = tx = 0
    for line in Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]:
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        iface = name.strip()
        if iface == "lo":
            continue
        cols = rest.split()
        if len(cols) < 9:
            continue
        rx += int(cols[0])
        tx += int(cols[8])
    now = time.monotonic()
    prev = _NET_SAMPLE
    _NET_SAMPLE = {"rx": rx, "tx": tx, "t": now}
    rx_mbps = tx_mbps = None
    if prev and now > prev["t"]:
        dt = now - prev["t"]
        rx_mbps = round((rx - prev["rx"]) * 8 / dt / 1_000_000, 3)
        tx_mbps = round((tx - prev["tx"]) * 8 / dt / 1_000_000, 3)
    return {
        "rx_bytes": rx,
        "tx_bytes": tx,
        "rx_mbps": rx_mbps,
        "tx_mbps": tx_mbps,
    }


def _probe_health() -> dict[str, Any]:
    t0 = time.perf_counter()
    code = 0
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2.5) as resp:
            code = int(getattr(resp, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        code = int(exc.code)
    except Exception:
        code = 0
    return {
        "url": HEALTH_URL,
        "http_code": code,
        "ms": round((time.perf_counter() - t0) * 1000.0, 1),
        "ok": code == 200,
    }


def _db_stats() -> dict[str, Any]:
    path = DB_PATH
    if not path.is_file():
        alt = Path("/opt/kupujpl-games/backend/database.db")
        path = alt if alt.is_file() else path
    size = path.stat().st_size if path.is_file() else 0
    wal = Path(str(path) + "-wal")
    return {
        "path": str(path),
        "size_mb": round(size / (1024 * 1024), 1),
        "wal_mb": round(wal.stat().st_size / (1024 * 1024), 2) if wal.is_file() else 0.0,
    }


def _read_proc_rss_kb(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        return 0
    return 0


def _read_proc_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ")
        return raw.decode("utf-8", errors="replace").strip()[:180]
    except OSError:
        return ""


def _systemctl_show(unit: str) -> dict[str, str]:
    import subprocess

    # Non-root may read unit properties without sudo on this host.
    cmd = [
        "systemctl",
        "show",
        unit,
        "-p",
        "ActiveState",
        "-p",
        "SubState",
        "-p",
        "MainPID",
        "-p",
        "MemoryCurrent",
        "-p",
        "NRestarts",
    ]
    try:
        r = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=5)
    except Exception:
        return {}
    props: dict[str, str] = {}
    for line in (r.stdout or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    return props


def _unit_row(unit: str, label: str) -> dict[str, Any]:
    props = _systemctl_show(unit)
    pid = int(props.get("MainPID") or 0)
    mem_bytes = props.get("MemoryCurrent") or ""
    mem_mb = None
    if mem_bytes.isdigit() and int(mem_bytes) < 2**63:
        mem_mb = round(int(mem_bytes) / (1024 * 1024), 1)
    elif pid > 0:
        mem_mb = round(_read_proc_rss_kb(pid) / 1024, 1)
    return {
        "unit": unit,
        "label": label,
        "active": props.get("ActiveState") or "unknown",
        "sub": props.get("SubState") or "",
        "pid": pid,
        "mem_mb": mem_mb,
        "restarts": int(props.get("NRestarts") or 0),
        "cmdline": _read_proc_cmdline(pid) if pid else "",
    }


def _scanner_units() -> list[dict[str, Any]]:
    slugs = [
        "steam",
        "gog",
        "epic",
        "g2a",
        "gamivo",
        "kinguin",
        "fanatical",
        "cdkeys",
        "instantgaming",
    ]
    rows = []
    for slug in slugs:
        rows.append(_unit_row(f"kupujpl-scanner@{slug}.service", slug))
    return rows


def collect_server_stats() -> dict[str, Any]:
    nproc = os.cpu_count() or 1
    scanners = _scanner_units()
    scanners_active = sum(1 for r in scanners if r.get("active") == "active")
    scanners_mem = round(sum(float(r.get("mem_mb") or 0) for r in scanners), 1)
    site = _unit_row("kupujpl-games.service", "site")
    slice_props = _systemctl_show("kupujpl-scanners.slice")
    slice_mem = None
    raw_mem = slice_props.get("MemoryCurrent") or ""
    if raw_mem.isdigit() and int(raw_mem) < 2**63:
        slice_mem = round(int(raw_mem) / (1024 * 1024), 1)

    return {
        "ok": True,
        "ts": time.time(),
        "hostname": socket.gethostname(),
        "nproc": nproc,
        "uptime": _read_uptime(),
        "load": _read_loadavg(),
        "cpu_pct": _cpu_percent(),
        "memory": _read_mem(),
        "disk": _read_disk("/"),
        "network": _read_net_rates(),
        "health": _probe_health(),
        "database": _db_stats(),
        "site": site,
        "scanners_slice_mem_mb": slice_mem,
        "scanners_summary": {
            "active": scanners_active,
            "total": len(scanners),
            "mem_mb": scanners_mem,
        },
        "scanners": scanners,
    }
