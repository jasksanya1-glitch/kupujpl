"""Central store classification for UI badges / SEO copy.

Preferred taxonomy (single source — do not re-derive in templates):
- OFFICIAL_STORE: first-party storefronts
- AUTHORIZED_RESELLER: authorized digital retailers
- MARKETPLACE: multi-seller key marketplaces
- UNREVIEWED: present in data but not confidently classified

Mapping is based on app/data/shops_trust.json notes + explicit project overrides.
Do not guess business models for unknown shops.
"""
from __future__ import annotations

from enum import Enum


class StoreClass(str, Enum):
    OFFICIAL_STORE = "OFFICIAL_STORE"
    AUTHORIZED_RESELLER = "AUTHORIZED_RESELLER"
    MARKETPLACE = "MARKETPLACE"
    UNREVIEWED = "UNREVIEWED"


# Explicit, documented mappings for shops we actively compare.
_OFFICIAL = frozenset(
    {
        "Steam",
        "Steam US",
        "GOG",
        "Epic Games",
        "PlayStation Store",
        "Xbox Store",
        "EA App",
    }
)
_AUTHORIZED_RESELLERS = frozenset(
    {
        "Instant Gaming",  # shops_trust: „Autoryzowany reseller”
        "Fanatical",  # shops_trust: „Oficjalny retailer cyfrowy (Fanatical Global)”
        "Green Man Gaming",  # shops_trust: „Autoryzowany partner wydawców”
        "Humble",
        "Humble Bundle",
    }
)
_MARKETPLACE = frozenset(
    {
        "G2A",
        "Kinguin",
        "Gamivo",
        "Eneba",
        "CDKeys",
    }
)

# Shops seen in DB/offers that need human review before labeling.
_NEEDS_REVIEW: frozenset[str] = frozenset()


def classify_store(shop_name: str | None) -> StoreClass:
    name = (shop_name or "").strip()
    if not name:
        return StoreClass.UNREVIEWED
    if name in _OFFICIAL:
        return StoreClass.OFFICIAL_STORE
    if name in _AUTHORIZED_RESELLERS:
        return StoreClass.AUTHORIZED_RESELLER
    if name in _MARKETPLACE:
        return StoreClass.MARKETPLACE
    if name in _NEEDS_REVIEW:
        return StoreClass.UNREVIEWED

    # Lazy import avoids circular dependency with shops_trust badges.
    from app.core.shops_trust import load_shops_trust

    trust = load_shops_trust().get(name) or {}
    if trust.get("is_official"):
        return StoreClass.OFFICIAL_STORE
    notes = str(trust.get("notes_pl") or "").lower()
    if "marketplace" in notes:
        return StoreClass.MARKETPLACE
    if "autoryzowan" in notes or "partner wydawc" in notes or "retailer cyfrowy" in notes:
        return StoreClass.AUTHORIZED_RESELLER
    if trust:
        # Known in trust JSON but ambiguous → do not invent a class.
        return StoreClass.UNREVIEWED
    return StoreClass.UNREVIEWED


def store_class_label_pl(store_class: StoreClass) -> str:
    if store_class is StoreClass.OFFICIAL_STORE:
        return "Oficjalny sklep"
    if store_class is StoreClass.AUTHORIZED_RESELLER:
        return "Autoryzowany sprzedawca"
    if store_class is StoreClass.MARKETPLACE:
        return "Marketplace"
    if store_class is StoreClass.UNREVIEWED:
        return "Sklep"
    raise ValueError(f"Unhandled store class: {store_class!r}")


def store_class_label_short_pl(store_class: StoreClass) -> str:
    """Compact labels for mobile badges."""
    if store_class is StoreClass.OFFICIAL_STORE:
        return "Oficjalny"
    if store_class is StoreClass.AUTHORIZED_RESELLER:
        return "Autoryzowany"
    if store_class is StoreClass.MARKETPLACE:
        return "Marketplace"
    if store_class is StoreClass.UNREVIEWED:
        return "Sklep"
    raise ValueError(f"Unhandled store class: {store_class!r}")


def audit_store_classification(shop_names: list[str] | None = None) -> list[dict]:
    """Return classification rows for known + provided shop names."""
    from app.core.shops_trust import load_shops_trust

    trust = load_shops_trust()
    names = set(shop_names or [])
    names.update(_OFFICIAL)
    names.update(_AUTHORIZED_RESELLERS)
    names.update(_MARKETPLACE)
    names.update(trust.keys())
    rows = []
    for name in sorted(names):
        sc = classify_store(name)
        rows.append(
            {
                "shop": name,
                "class": sc.value,
                "label_pl": store_class_label_pl(sc),
                "in_trust_json": name in trust,
            }
        )
    return rows
