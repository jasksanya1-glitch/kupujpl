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


def inter_font_head(static_base: str) -> str:
    """Self-hosted Inter (Price Radar) вЂ” avoids Google Fonts."""
    base = static_base.rstrip("/")
    if not base.startswith("http"):
        base = f"{SITE_ORIGIN}/{base.lstrip('/')}"
    return (
        "<style>"
        "@font-face{font-family:'Inter';font-style:normal;font-weight:100 900;font-display:swap;"
        f"src:url({base}/fonts/inter-latin.woff2) format('woff2');"
        "unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,"
        "U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}"
        "@font-face{font-family:'Inter';font-style:normal;font-weight:100 900;font-display:swap;"
        f"src:url({base}/fonts/inter-latin-ext-pl.woff2) format('woff2');"
        "unicode-range:U+0104-0107,U+0118-0119,U+0141-0144,U+015A-015B,U+0179-017C}"
        "@font-face{font-family:'Inter Fallback';src:local('Arial');size-adjust:107.4%;"
        "ascent-override:90.2%;descent-override:22.5%;line-gap-override:0%}"
        "</style>"
    )
