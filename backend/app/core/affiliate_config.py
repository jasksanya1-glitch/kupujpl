"""Report which affiliate partner IDs are configured on this deployment."""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from app.core.affiliate import (
    CDKEYS_AFFILIATE_REF,
    ENEBA_PARTNER_ID,
    GOG_AFFILIATE_CODE,
    G2A_GOLDMINE_GNAME,
    HUMBLE_PARTNER_ID,
    INSTANT_GAMING_REF,
    KINGUIN_AFFILIATE_REF,
    GAMIVO_REF,
    affiliate_link_configured,
)
from app.core.database import BASE_DIR

load_dotenv(BASE_DIR / ".env")


def affiliate_env_status() -> dict[str, Any]:
    awin_key = os.environ.get("AWIN_DATAFEED_API_KEY", "").strip()
    awin_on = bool(awin_key)
    awin_aff = bool(os.environ.get("AWIN_AFFILIATE_ID", "").strip() or "2936531")
    items = [
        {
            "shop": "GOG",
            "env": "GOG_AFFILIATE_CODE",
            "configured": bool(GOG_AFFILIATE_CODE),
            "click_tracking": affiliate_link_configured("GOG"),
            "via": "direct",
        },
        {
            "shop": "CDKeys (scraper)",
            "env": "CDKEYS_AFFILIATE_REF",
            "configured": bool(CDKEYS_AFFILIATE_REF),
            "click_tracking": affiliate_link_configured("CDKeys"),
            "via": "direct",
        },
        {
            "shop": "Kinguin",
            "env": "AWIN click wrap / feed",
            "configured": affiliate_link_configured("Kinguin"),
            "click_tracking": affiliate_link_configured("Kinguin"),
            "feed_download": awin_on
            and bool(
                os.environ.get("AWIN_FEED_MERCHANT_KINGUIN", "").strip()
                or os.environ.get("AWIN_FEED_FID_KINGUIN", "").strip()
            ),
            "via": "awin",
        },
        {
            "shop": "Fanatical",
            "env": "AWIN click wrap / feed",
            "configured": affiliate_link_configured("Fanatical"),
            "click_tracking": affiliate_link_configured("Fanatical"),
            "feed_download": awin_on
            and bool(
                os.environ.get("AWIN_FEED_MERCHANT_FANATICAL", "").strip()
                or os.environ.get("AWIN_FEED_FID_FANATICAL", "").strip()
            ),
            "via": "awin",
        },
        {
            "shop": "Eneba",
            "env": "ENEBA_PARTNER_ID / AWIN",
            "configured": affiliate_link_configured("Eneba"),
            "click_tracking": affiliate_link_configured("Eneba"),
            "via": "direct+awin",
        },
        {
            "shop": "G2A Goldmine",
            "env": "G2A_GOLDMINE_GNAME",
            "configured": bool(G2A_GOLDMINE_GNAME),
            "click_tracking": affiliate_link_configured("G2A"),
            "via": "goldmine",
        },
        {
            "shop": "Gamivo",
            "env": "GAMIVO_REF",
            "configured": bool(GAMIVO_REF),
            "click_tracking": affiliate_link_configured("Gamivo"),
            "via": "direct",
        },
        {
            "shop": "Instant Gaming",
            "env": "INSTANT_GAMING_REF",
            "configured": bool(INSTANT_GAMING_REF),
            "click_tracking": affiliate_link_configured("Instant Gaming"),
            "via": "direct",
        },
    ]
    missing = [i for i in items if not i["configured"]]
    return {
        "awin_datafeed_configured": awin_on,
        "awin_click_wrap_configured": awin_aff,
        "items": items,
        "missing_count": len(missing),
        "missing_shops": [i["shop"] for i in missing],
        "note": (
            "Click tracking ≠ feed download. Kinguin/Fanatical HTML or cached offers "
            "can still wrap via Awin cread (awc=) when AWIN_AFFILIATE_ID + MID are set. "
            "GOG/CDKeys need GOG_AFFILIATE_CODE / CDKEYS_AFFILIATE_REF for params. "
            "Commission accrual is never claimed from HTTP redirects alone."
        ),
    }
