"""Shop scan configuration: active vs disabled stores per worker."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from app.core.database import BASE_DIR

# All shops shown in UI / panel3 — do not remove.
EXPECTED_SHOPS: tuple[str, ...] = (
    "Steam",
    "GOG",
    "Epic Games",
    "Instant Gaming",
    "Eneba",
    "Kinguin",
    "CDKeys",
    "G2A",
    "Gamivo",
    "Fanatical",
)

DEFAULT_DISABLED_SCAN_SHOPS: tuple[str, ...] = ("Eneba",)

# Fast official stores — Tier A on VPS only (keep TIER_A_PARALLEL low to protect SQLite).
VPS_SCAN_SHOPS: tuple[str, ...] = ("Steam", "GOG", "Epic Games")

# Keyshops never scan on VPS (remote workers bulk-upload; avoids QueuePool exhaustion).
KEYSHOP_SCAN_SHOPS: frozenset[str] = frozenset(
    {"Instant Gaming", "Eneba", "Kinguin", "CDKeys", "G2A", "Gamivo", "Fanatical"}
)

# Slow scrapers — isolated phases on home machines.
SLOW_SCAN_SHOPS: frozenset[str] = frozenset({"Gamivo", "G2A", "Eneba"})

# Fast keyshops — Dev PC (Algolia / JSON parsers).
HOME_PC_SHOPS: tuple[str, ...] = ("CDKeys", "Gamivo")
# Gamivo is slow but routed to PC for serial phase; CDKeys is fast on the same worker.

# Medium/fast keyshops + slow G2A — laptop.
HOME_LAPTOP_SHOPS: tuple[str, ...] = ("Kinguin", "G2A", "Instant Gaming", "Fanatical")

VALID_SCAN_WORKERS: frozenset[str] = frozenset({"vps", "laptop", "pc"})

_DISABLED_JSON = Path(BASE_DIR) / "tmp" / "disabled_scan_shops.json"
_ROUTING_JSON = Path(BASE_DIR) / "tmp" / "scan_routing.json"


def _default_worker_for_shop(shop_name: str) -> str:
    if shop_name in VPS_SCAN_SHOPS:
        return "vps"
    if shop_name in HOME_PC_SHOPS:
        return "pc"
    if shop_name in HOME_LAPTOP_SHOPS:
        return "laptop"
    return "laptop"


def _load_routing_overrides() -> dict[str, str]:
    data = _read_json_file(_ROUTING_JSON)
    raw = data.get("routing") if isinstance(data.get("routing"), dict) else {}
    out: dict[str, str] = {}
    for shop, worker in raw.items():
        if shop in EXPECTED_SHOPS and worker in VALID_SCAN_WORKERS:
            out[str(shop)] = str(worker)
    return out


def allowed_workers_for_shop(shop_name: str) -> tuple[str, ...]:
    if shop_name in VPS_SCAN_SHOPS:
        return ("vps",)
    if shop_name in KEYSHOP_SCAN_SHOPS:
        return ("laptop", "pc")
    return tuple(sorted(VALID_SCAN_WORKERS))


def _validate_shop_worker(shop_name: str, worker: str) -> None:
    if shop_name in KEYSHOP_SCAN_SHOPS and worker == "vps":
        raise ValueError(
            f"{shop_name} cannot scan on VPS — use pc or laptop (keyshops load the site DB)"
        )
    if shop_name in VPS_SCAN_SHOPS and worker != "vps":
        raise ValueError(
            f"{shop_name} should scan on VPS (fast official shop)"
        )


def get_shop_worker(shop_name: str) -> str:
    """Return worker (vps/laptop/pc) assigned to scan this shop."""
    overrides = _load_routing_overrides()
    worker = overrides.get(shop_name) or _default_worker_for_shop(shop_name)
    return worker if worker in VALID_SCAN_WORKERS else _default_worker_for_shop(shop_name)


def get_shops_for_worker(worker: str) -> tuple[str, ...]:
    """Active shops routed to the given worker."""
    if worker not in VALID_SCAN_WORKERS:
        return ()
    active = get_active_scan_shops()
    return tuple(s for s in active if get_shop_worker(s) == worker)


def get_scan_routing_config() -> dict:
    """Full routing map: shop -> worker, with defaults filled in."""
    overrides = _load_routing_overrides()
    routing = {shop: get_shop_worker(shop) for shop in EXPECTED_SHOPS}
    defaults = {shop: _default_worker_for_shop(shop) for shop in EXPECTED_SHOPS}
    payload = _read_json_file(_ROUTING_JSON)
    speed = {
        shop: (
            "slow" if shop in SLOW_SCAN_SHOPS
            else "fast_official" if shop in VPS_SCAN_SHOPS
            else "fast_keyshop" if shop in KEYSHOP_SCAN_SHOPS and shop not in SLOW_SCAN_SHOPS
            else "keyshop"
        )
        for shop in EXPECTED_SHOPS
    }
    return {
        "routing": routing,
        "overrides": overrides,
        "defaults": defaults,
        "speed": speed,
        "vps_shops": list(get_shops_for_worker("vps")),
        "laptop_shops": list(get_shops_for_worker("laptop")),
        "pc_shops": list(get_shops_for_worker("pc")),
        "workers": sorted(VALID_SCAN_WORKERS),
        "updated_at": payload.get("updated_at"),
    }


def save_scan_routing(routing: dict[str, str] | None = None, *, shop: str | None = None, worker: str | None = None) -> dict:
    """Persist per-shop worker routing to tmp/scan_routing.json."""
    from datetime import datetime

    allowed = set(EXPECTED_SHOPS)
    prev = _load_routing_overrides()
    new_routing = dict(prev)
    if routing:
        for name, w in routing.items():
            if name in allowed and w in VALID_SCAN_WORKERS:
                _validate_shop_worker(name, w)
                new_routing[name] = w
    if shop and worker:
        if shop not in allowed:
            raise ValueError(f"Unknown shop: {shop}")
        if worker not in VALID_SCAN_WORKERS:
            raise ValueError(f"Unknown worker: {worker}")
        _validate_shop_worker(shop, worker)
        new_routing[shop] = worker
    clean = {
        name: new_routing[name]
        for name in sorted(new_routing)
        if new_routing[name] != _default_worker_for_shop(name)
    }
    out = {
        "routing": clean,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    _ROUTING_JSON.parent.mkdir(parents=True, exist_ok=True)
    _ROUTING_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    active_shop_set.cache_clear()
    return get_scan_routing_config()


def set_shop_worker(shop_name: str, worker: str) -> dict:
    if shop_name not in EXPECTED_SHOPS:
        raise ValueError(f"Unknown shop: {shop_name}")
    if worker not in VALID_SCAN_WORKERS:
        raise ValueError(f"Unknown worker: {worker}")
    default = _default_worker_for_shop(shop_name)
    prev = _load_routing_overrides()
    if worker == default:
        prev.pop(shop_name, None)
        return save_scan_routing(prev)
    return save_scan_routing(shop=shop_name, worker=worker)


def _parse_env_disabled() -> frozenset[str]:
    raw = os.environ.get("OFFER_SCAN_DISABLED_SHOPS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(s.strip() for s in raw.split(",") if s.strip())


def _read_json_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}


def _load_json_disabled() -> frozenset[str]:
    data = _read_json_file(_DISABLED_JSON)
    return frozenset(data.get("disabled") or [])


def _load_json_payload() -> dict:
    data = _read_json_file(_DISABLED_JSON)
    return data if isinstance(data, dict) else {}


def get_disabled_scan_shops() -> frozenset[str]:
    env_extra = _parse_env_disabled()
    if _DISABLED_JSON.is_file():
        return _load_json_disabled() | env_extra
    return frozenset(DEFAULT_DISABLED_SCAN_SHOPS) | env_extra


def save_disabled_scan_shops(
    disabled: frozenset[str] | set[str] | list[str],
    *,
    reasons: dict[str, str] | None = None,
) -> dict:
    """Persist user-disabled shops to tmp/disabled_scan_shops.json."""
    from datetime import datetime

    allowed = set(EXPECTED_SHOPS)
    clean = sorted({s.strip() for s in disabled if s and s.strip() in allowed})
    payload = _load_json_payload()
    prev_reasons = payload.get("reason") if isinstance(payload.get("reason"), dict) else {}
    new_reasons = dict(prev_reasons)
    if reasons:
        for k, v in reasons.items():
            if k in allowed and v:
                new_reasons[k] = str(v)[:200]
    for name in clean:
        new_reasons.pop(name, None)
    out = {
        "disabled": clean,
        "reason": new_reasons,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    _DISABLED_JSON.parent.mkdir(parents=True, exist_ok=True)
    _DISABLED_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    active_shop_set.cache_clear()
    return out


def toggle_scan_shop(shop_name: str, *, enabled: bool) -> dict:
    if shop_name not in EXPECTED_SHOPS:
        raise ValueError(f"Unknown shop: {shop_name}")
    current = set(get_disabled_scan_shops())
    if enabled:
        current.discard(shop_name)
    else:
        current.add(shop_name)
    return save_disabled_scan_shops(current)


def get_display_shops() -> tuple[str, ...]:
    """Shops whose offers are shown on the public site (independent of scan toggles)."""
    return EXPECTED_SHOPS


def is_shop_displayed(shop_name: str) -> bool:
    return shop_name in get_display_shops()


def get_scan_shops_config() -> dict:
    disabled = sorted(get_disabled_scan_shops())
    routing_cfg = get_scan_routing_config()
    scan_active = list(get_active_scan_shops())
    display = list(get_display_shops())
    return {
        "expected_shops": list(EXPECTED_SHOPS),
        "display_shops": display,
        "active_shops": scan_active,
        "scan_shops": scan_active,
        "disabled_shops": disabled,
        "disabled_scan_shops": disabled,
        "vps_shops": list(get_shops_for_worker("vps")),
        "laptop_shops": list(get_shops_for_worker("laptop")),
        "pc_shops": list(get_shops_for_worker("pc")),
        "routing": routing_cfg["routing"],
        "routing_defaults": routing_cfg["defaults"],
        "routing_overrides": routing_cfg["overrides"],
        "speed": routing_cfg["speed"],
        "updated_at": _load_json_payload().get("updated_at"),
        "routing_updated_at": routing_cfg.get("updated_at"),
    }


def get_active_scan_shops() -> tuple[str, ...]:
    disabled = get_disabled_scan_shops()
    return tuple(s for s in EXPECTED_SHOPS if s not in disabled)


def is_shop_active(shop_name: str) -> bool:
    return shop_name in get_active_scan_shops()


def filter_active_shops(names: tuple[str, ...] | frozenset[str] | set[str]) -> tuple[str, ...]:
    active = set(get_active_scan_shops())
    return tuple(s for s in names if s in active)


def active_shops_for_worker(worker: str, phase_shops: set[str] | frozenset[str]) -> set[str]:
    """Re-read routing + disabled shops and intersect with phase shops."""
    allowed = set(get_shops_for_worker(worker))
    return allowed & set(phase_shops)


@lru_cache(maxsize=1)
def active_shop_set() -> frozenset[str]:
    return frozenset(get_active_scan_shops())


@lru_cache(maxsize=1)
def display_shop_set() -> frozenset[str]:
    return frozenset(get_display_shops())
