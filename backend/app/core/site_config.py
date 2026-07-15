"""Public site contact / donate settings (env)."""
from __future__ import annotations

import os

CONTACT_EMAIL = os.environ.get("GAMES_CONTACT_EMAIL", "kupujpl.pl@gmail.com").strip()
CONTACT_TELEGRAM_URL = os.environ.get("GAMES_TELEGRAM_URL", "https://t.me/KupujPl_bot").strip()
CONTACT_TELEGRAM_LABEL = os.environ.get("GAMES_TELEGRAM_LABEL", "Napisz na Telegramie").strip()
TELEGRAM_CHANNEL_URL = os.environ.get(
    "GAMES_TELEGRAM_CHANNEL_URL", "https://t.me/kupujpl_okazje"
).strip()
TELEGRAM_CHANNEL_LABEL = os.environ.get(
    "GAMES_TELEGRAM_CHANNEL_LABEL", "Okazje na Telegramie"
).strip()
INSTAGRAM_URL = os.environ.get("GAMES_INSTAGRAM_URL", "https://www.instagram.com/kupujpl.pl/").strip()
INSTAGRAM_LABEL = os.environ.get("GAMES_INSTAGRAM_LABEL", "Profil na Instagramie").strip()
DONATE_URL = os.environ.get("GAMES_DONATE_URL", "https://buymeacoffee.com/echoplay").strip()
DONATE_LABEL = os.environ.get("GAMES_DONATE_LABEL", "Buy Me a Coffee").strip()
SITE_ORIGIN = os.environ.get("GAMES_BASE_URL", "https://kupujpl.pl/games").rstrip("/")


def public_site_info() -> dict[str, str]:
    return {
        "contact_email": CONTACT_EMAIL,
        "telegram_url": CONTACT_TELEGRAM_URL,
        "telegram_label": CONTACT_TELEGRAM_LABEL,
        "telegram_channel_url": TELEGRAM_CHANNEL_URL,
        "telegram_channel_label": TELEGRAM_CHANNEL_LABEL,
        "instagram_url": INSTAGRAM_URL,
        "instagram_label": INSTAGRAM_LABEL,
        "donate_url": DONATE_URL,
        "donate_label": DONATE_LABEL,
        "site_origin": SITE_ORIGIN,
    }
