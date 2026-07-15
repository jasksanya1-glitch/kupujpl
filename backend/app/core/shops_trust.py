"""Shop trust metadata for offer badges."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "shops_trust.json"


@lru_cache(maxsize=1)
def load_shops_trust() -> dict[str, dict]:
    if not _DATA.is_file():
        return {}
    return json.loads(_DATA.read_text(encoding="utf-8"))


def shop_trust_badge(shop_name: str, *, is_official: bool | None = None) -> dict | None:
    data = load_shops_trust().get(shop_name)
    if not data:
        if is_official:
            return {
                "label": "Oficjalny",
                "tier": "A",
                "refund_policy_url": None,
                "notes_pl": "Oficjalny sklep platformy.",
            }
        return {
            "label": "Marketplace",
            "tier": "C",
            "refund_policy_url": None,
            "notes_pl": "Marketplace kluczy — sprawdź sprzedawcę.",
        }
    tier = data.get("trust_tier", "C")
    if data.get("is_official") or is_official:
        label = "Oficjalny"
    else:
        label = f"Marketplace · tier {tier}"
    return {
        "label": label,
        "tier": tier,
        "refund_policy_url": data.get("refund_policy_url"),
        "refund_note_pl": data.get("refund_note_pl"),
        "refund_note_uk": data.get("refund_note_uk"),
        "notes_pl": data.get("notes_pl"),
        "supports_pln": data.get("supports_pln", True),
    }
