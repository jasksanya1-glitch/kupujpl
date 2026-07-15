#!/usr/bin/env python3
"""Download partner product feeds (Awin CSV) into tmp/affiliate_feeds/."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.parsers.affiliate_feeds import affiliate_feed_status, refresh_affiliate_feeds  # noqa: E402


def main() -> int:
    counts = refresh_affiliate_feeds(force=True)
    print(json.dumps({"ok": True, "rows": counts, "status": affiliate_feed_status()}, indent=2))
    return 0 if counts else 1


if __name__ == "__main__":
    raise SystemExit(main())
