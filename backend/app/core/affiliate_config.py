"""Report which affiliate partner IDs are configured on this deployment."""
from __future__ import annotations

import os
from typing import Any

from app.core.affiliate import (
    CDKEYS_AFFILIATE_REF,
    ENEBA_PARTNER_ID,
    GOG_AFFILIATE_CODE,
    G2A_GOLDMINE_GNAME,
    HUMBLE_PARTNER_ID,
    INSTANT_GAMING_REF,
    KINGUIN_AFFILIATE_REF,
    GAMIVO_REF,
)


def affiliate_env_status() -> dict[str, Any]:
    awin_key = os.environ.get("AWIN_DATAFEED_API_KEY", "").strip()
    awin_on = bool(awin_key)
    items = [
        {
            "shop": "GOG",
            "env": "GOG_AFFILIATE_CODE",
            "configured": bool(GOG_AFFILIATE_CODE),
            "via": "direct",
        },
        {
            "shop": "CDKeys (scraper)",
            "env": "CDKEYS_AFFILIATE_REF",
            "configured": bool(CDKEYS_AFFILIATE_REF),
            "via": "direct",
        },
        {
            "shop": "Kinguin",
            "env": "AWIN feed",
            "configured": awin_on and bool(os.environ.get("AWIN_FEED_MERCHANT_KINGUIN", "").strip()),
            "via": "awin",
        },
        {
            "shop": "Fanatical",
            "env": "AWIN feed",
            "configured": awin_on and bool(os.environ.get("AWIN_FEED_MERCHANT_FANATICAL", "").strip()),
            "via": "awin",
        },
        {
            "shop": "Eneba",
            "env": "ENEBA_PARTNER_ID",
            "configured": bool(ENEBA_PARTNER_ID),
            "via": "direct",
        },
        {
            "shop": "G2A Goldmine",
            "env": "G2A_GOLDMINE_GNAME",
            "configured": bool(G2A_GOLDMINE_GNAME),
            "via": "goldmine",
        },
        {
            "shop": "Gamivo",
            "env": "GAMIVO_REF",
            "configured": bool(GAMIVO_REF),
            "via": "direct",
        },
        {
            "shop": "Instant Gaming",
            "env": "INSTANT_GAMING_REF",
            "configured": bool(INSTANT_GAMING_REF),
            "via": "direct",
        },
    ]
    missing = [i for i in items if not i["configured"]]
    return {
        "awin_datafeed_configured": awin_on,
        "items": items,
        "missing_count": len(missing),
        "missing_shops": [i["shop"] for i in missing],
        "note": (
            "Рефералки з чату: G2A reflink-1c4032615f, Instant Gaming gamer-c353127, "
            "Gamivo 5oq0ouor. Kinguin/Fanatical/G2A feed — через Awin pclick. "
            "GOG/CDKeys scraper потребують окремих ID з партнерського кабінету."
        ),
    }
