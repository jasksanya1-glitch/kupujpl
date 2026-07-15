#!/usr/bin/env python3
"""Bootstrap Tier A: enable timer + run first VPS pipeline immediately."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy Tier A bootstrap on VPS")
    parser.add_argument("--skip-systemd", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    venv_python = Path("/opt/kupujpl-games/backend/venv/bin/python")
    if not venv_python.is_file():
        venv_python = ROOT / "venv" / "Scripts" / "python.exe"
        if not venv_python.is_file():
            venv_python = Path(sys.executable)

    cmds: list[list[str]] = []
    if not args.skip_systemd:
        deploy = ROOT / "deploy" / "systemd"
        for unit in ("kupujpl-games-tier-a-daily.service", "kupujpl-games-tier-a-daily.timer"):
            src = deploy / unit
            if src.is_file():
                cmds.append(["sudo", "cp", str(src), f"/etc/systemd/system/{unit}"])
        cmds.append(["sudo", "systemctl", "daemon-reload"])
        cmds.append(["sudo", "systemctl", "enable", "--now", "kupujpl-games-tier-a-daily.timer"])

    cmds.append([str(venv_python), "-m", "app.parsers.daily_tier_a_pipeline", "--bootstrap"])

    for cmd in cmds:
        print("+", " ".join(cmd))
        if args.dry_run:
            continue
        subprocess.run(cmd, cwd=str(ROOT), check=False)

    print("\nNext: on laptop run:")
    print(r"  .\tools\daily_tier_a_laptop.ps1 -Bootstrap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
