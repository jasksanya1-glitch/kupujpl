#!/usr/bin/env python3
"""IGDB Game Discovery — local dry-run or stage (never production).

Usage (from backend/):
  python tools/igdb_discovery/run_prototype.py --mode dry-run --limit 50
  python tools/igdb_discovery/run_prototype.py --mode stage --limit 50

dry-run  → reports only (JSON/HTML/MD), no staging DB writes
stage    → reports + isolated staging SQLite only
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from tools.igdb_discovery import config  # noqa: E402
from tools.igdb_discovery.pipeline import run_discovery  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IGDB discovery dry-run / stage")
    parser.add_argument("--mode", choices=("dry-run", "stage"), default="dry-run")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--per-category", type=int, default=None)
    parser.add_argument("--skip-steam-verify", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        report = run_discovery(
            mode=args.mode,
            limit=args.limit,
            per_category=args.per_category,
            verify_steam=not args.skip_steam_verify,
        )
    except Exception as exc:  # noqa: BLE001
        logging.exception("Discovery failed: %s", exc)
        return 1

    summary = {
        "mode": report.get("mode"),
        "wrote_staging": report.get("wrote_staging"),
        "bucket_counts": report.get("bucket_counts"),
        "verification_30_counts": report.get("verification_30_counts"),
        "approvable": len(report.get("approvable_games") or []),
        "approvable_games": report.get("approvable_games"),
        "go_nogo": report.get("go_nogo"),
        "html": str(config.REPORTS_DIR / "discovery_report.html"),
        "json": str(config.REPORTS_DIR / "discovery_latest.json"),
        "md": str(config.REPORTS_DIR / "DISCOVERY_V2_GO_NOGO.md"),
    }
    sys.stdout.buffer.write((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
