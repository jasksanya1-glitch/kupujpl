"""Feature flags for price engine (avoids import cycles)."""
from __future__ import annotations

import os


def price_engine_v2_enabled() -> bool:
    return os.environ.get("PRICE_ENGINE_V2", "0").strip() in {"1", "true", "yes", "on"}
