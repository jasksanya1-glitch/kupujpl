#!/usr/bin/env python3
"""Refresh IGDB ranking lists and enqueue games for independent scanners (VPS/cron)."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

_BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND / ".env")
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.core.igdb_scan_lists import refresh_igdb_scan_lists  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    init_db()
    db = SessionLocal()
    try:
        out = refresh_igdb_scan_lists(db)
    finally:
        db.close()
    sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    return 0 if not out.get("skipped") else 2


if __name__ == "__main__":
    raise SystemExit(main())
