"""Shop trust metadata for offer badges."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.core.store_classification import (
    StoreClass,
    classify_store,
    store_class_label_pl,
    store_class_label_short_pl,
)

_DATA = Path(__file__).resolve().parent.parent / "data" / "shops_trust.json"


@lru_cache(maxsize=1)
def load_shops_trust() -> dict[str, dict]:
    if not _DATA.is_file():
        return {}
    return json.loads(_DATA.read_text(encoding="utf-8"))


def shop_trust_badge(shop_name: str, *, is_official: bool | None = None) -> dict | None:
    data = load_shops_trust().get(shop_name) or {}
    store_class = classify_store(shop_name)
    # Legacy callers may pass is_official=True for platform stores missing from JSON.
    if is_official and store_class is StoreClass.UNREVIEWED:
        store_class = StoreClass.OFFICIAL_STORE
    tier = data.get("trust_tier") or (
        "A"
        if store_class is StoreClass.OFFICIAL_STORE
        else "B"
        if store_class is StoreClass.AUTHORIZED_RESELLER
        else "C"
    )
    return {
        "label": store_class_label_short_pl(store_class),
        "label_full": store_class_label_pl(store_class),
        "store_class": store_class.value,
        "tier": tier,
        "refund_policy_url": data.get("refund_policy_url"),
        "refund_note_pl": data.get("refund_note_pl"),
        "refund_note_uk": data.get("refund_note_uk"),
        "notes_pl": data.get("notes_pl")
        or (
            "Oficjalny sklep platformy."
            if store_class is StoreClass.OFFICIAL_STORE
            else "Autoryzowany sprzedawca — sprawdź region klucza."
            if store_class is StoreClass.AUTHORIZED_RESELLER
            else "Marketplace kluczy — sprawdź sprzedawcę."
            if store_class is StoreClass.MARKETPLACE
            else "Sklep — sprawdź warunki u sprzedawcy."
        ),
        "supports_pln": data.get("supports_pln", True),
    }
