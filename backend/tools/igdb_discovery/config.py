"""Config for IGDB discovery prototype — local .env only."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

TOOLS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TOOLS_DIR.parents[1]
REPO_ROOT = BACKEND_DIR.parent
REPORTS_DIR = TOOLS_DIR / "reports"
STAGING_DIR = TOOLS_DIR / "staging"
STAGING_DB = STAGING_DIR / "discovery_staging.sqlite3"
# Disposable DB for simulation / unit approval tests — never human_approved lane.
TEST_STAGING_DB = STAGING_DIR / "discovery_test.sqlite3"
RANKINGS_DB = STAGING_DIR / "game_rankings.sqlite3"
CATALOG_DB = BACKEND_DIR / "database.db"
TOKEN_CACHE = STAGING_DIR / "igdb_token_cache.json"

# Load backend/.env then optional local override (never commit secrets).
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(TOOLS_DIR / ".env")

IGDB_CLIENT_ID = (os.environ.get("IGDB_CLIENT_ID") or "").strip()
IGDB_CLIENT_SECRET = (os.environ.get("IGDB_CLIENT_SECRET") or "").strip()

TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
IGDB_API_BASE = "https://api.igdb.com/v4"

# Safety switches — production write/scan enqueue stay OFF for prototype.
DRY_RUN = os.environ.get("IGDB_DISCOVERY_DRY_RUN", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
WRITE_PRODUCTION = os.environ.get("IGDB_DISCOVERY_WRITE_PRODUCTION", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}
ENQUEUE_SCANNERS = os.environ.get("IGDB_DISCOVERY_ENQUEUE_SCANNERS", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}
PROTOTYPE_LIMIT = max(1, int(os.environ.get("IGDB_DISCOVERY_LIMIT", "50")))

# IGDB platform id 6 = PC (Windows). game_type 0 = main game (legacy category 0).
PC_PLATFORM_ID = 6
MAIN_GAME_TYPE_IDS = frozenset({0})  # main_game
# Steam external source (legacy category / external_game_source).
STEAM_EXTERNAL_SOURCE = 1

# PopScore primitive IDs (from /popularity_types).
POPULARITY_TYPE_VISITS = 1
POPULARITY_TYPE_WANT_TO_PLAY = 2
POPULARITY_TYPE_GLOBAL_TOP_SELLERS = 9
POPULARITY_TYPE_WISHLISTED_UPCOMING = 10

REQUEST_PAUSE_SEC = float(os.environ.get("IGDB_REQUEST_PAUSE_SEC", "0.28"))
USER_AGENT = "QuenlyIGDBDiscoveryPrototype/0.2 (local; non-production)"


def require_credentials() -> tuple[str, str]:
    if not IGDB_CLIENT_ID or not IGDB_CLIENT_SECRET:
        raise RuntimeError(
            "Missing IGDB_CLIENT_ID / IGDB_CLIENT_SECRET. "
            "Copy backend/.env.igdb.example → backend/.env"
        )
    return IGDB_CLIENT_ID, IGDB_CLIENT_SECRET


def assert_prototype_safety() -> None:
    if WRITE_PRODUCTION or ENQUEUE_SCANNERS:
        raise RuntimeError(
            "Prototype refuses WRITE_PRODUCTION/ENQUEUE_SCANNERS=1. "
            "Promote only after commercial IGDB approval + GO decision."
        )
