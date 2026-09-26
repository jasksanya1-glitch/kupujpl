"""Soft-consent UI for editorial / deal push categories (separate from price alerts)."""
from __future__ import annotations

# Categories for future push topics — stored client-side until user opts in.
PUSH_TOPIC_FREE = "free_games"
PUSH_TOPIC_BIG_DEALS = "deals_70"
PUSH_TOPIC_WISHLIST = "wishlist"

SOFT_CONSENT_COPY_PL = {
    "title": "Chcesz otrzymywać informacje o darmowych grach i dużych promocjach?",
    "enable": "Włącz powiadomienia",
    "later": "Nie teraz",
    "topics": [
        {"id": PUSH_TOPIC_FREE, "label": "Darmowe gry"},
        {"id": PUSH_TOPIC_BIG_DEALS, "label": "Promocje 70%+"},
        {"id": PUSH_TOPIC_WISHLIST, "label": "Wybrane gry / wishlist"},
    ],
}


def soft_consent_config() -> dict:
    return {
        "enabled": True,
        "storage_key": "kupujpl-push-soft-consent",
        "utm_source": "web_push",
        "utm_medium": "notification",
        "copy": SOFT_CONSENT_COPY_PL,
    }
