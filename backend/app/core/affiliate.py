import os
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

ENEBA_PARTNER_ID = os.environ.get("ENEBA_PARTNER_ID", "").strip()
GOG_AFFILIATE_CODE = os.environ.get("GOG_AFFILIATE_CODE", "").strip()
KINGUIN_AFFILIATE_REF = os.environ.get("KINGUIN_AFFILIATE_REF", "").strip()
CDKEYS_AFFILIATE_REF = os.environ.get("CDKEYS_AFFILIATE_REF", "").strip()
# Goldmine reflink slug, e.g. reflink-1c4032615f from https://www.g2a.com/n/reflink-1c4032615f
G2A_GOLDMINE_GNAME = os.environ.get("G2A_GOLDMINE_GNAME", "reflink-1c4032615f")
G2A_AFFILIATE_ADID = os.environ.get("G2A_AFFILIATE_ADID", "")
HUMBLE_PARTNER_ID = os.environ.get("HUMBLE_PARTNER_ID", "").strip()
INSTANT_GAMING_REF = os.environ.get("INSTANT_GAMING_REF", "gamer-c353127")
GAMIVO_REF = os.environ.get("GAMIVO_REF", "5oq0ouor")

_G2A_TRACKING_KEYS = frozenset({
    "gname",
    "adid",
    "utm_campaign",
    "utm_medium",
    "utm_source",
})


def _is_awin_tracking_url(url: str) -> bool:
    """Awin feed / pclick links already carry publisher attribution — do not rewrite."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return "awin1.com" in host or "awstrack.me" in host


def affiliate_link_configured(shop_name: str) -> bool:
    """Return True when we have a real (non-empty) partner id for direct shop links."""
    shop = (shop_name or "").lower()
    if shop == "eneba":
        return bool(ENEBA_PARTNER_ID)
    if shop == "gog":
        return bool(GOG_AFFILIATE_CODE)
    if shop == "kinguin":
        return bool(KINGUIN_AFFILIATE_REF)
    if shop == "cdkeys":
        return bool(CDKEYS_AFFILIATE_REF)
    if shop == "humble store":
        return bool(HUMBLE_PARTNER_ID)
    if shop == "g2a":
        return bool(G2A_GOLDMINE_GNAME or G2A_AFFILIATE_ADID)
    if shop == "instant gaming":
        return bool(INSTANT_GAMING_REF)
    if shop == "gamivo":
        return bool(GAMIVO_REF)
    return False


_LEGACY_PLACEHOLDER = "kupujpl"


def _strip_legacy_placeholders(query_params: dict) -> None:
    """Remove bogus kupujpl params baked into DB URLs before real IDs were configured."""
    mapping = {
        "pp": GOG_AFFILIATE_CODE,
        "ref": CDKEYS_AFFILIATE_REF,
        "referral": KINGUIN_AFFILIATE_REF,
        "af_id": ENEBA_PARTNER_ID,
        "partner": HUMBLE_PARTNER_ID,
    }
    for key, real in mapping.items():
        if query_params.get(key) == _LEGACY_PLACEHOLDER and not real:
            del query_params[key]


def make_affiliate_link(url: str, shop_name: str) -> str:
    """Append affiliate tracking parameters to store URLs."""
    if _is_awin_tracking_url(url):
        parsed = urlparse(url)
        params = dict(parse_qsl(parsed.query))
        if "referral" in params:
            params.pop("referral", None)
            return urlunparse((
                parsed.scheme, parsed.netloc, parsed.path, parsed.params,
                urlencode(params), parsed.fragment,
            ))
        return url

    parsed = urlparse(url)
    query_params = dict(parse_qsl(parsed.query))
    _strip_legacy_placeholders(query_params)
    host = parsed.netloc.lower()
    shop = (shop_name or "").lower()

    if "eneba.com" in host or shop == "eneba":
        if ENEBA_PARTNER_ID:
            query_params["af_id"] = ENEBA_PARTNER_ID

    elif "gog.com" in host or shop == "gog":
        if GOG_AFFILIATE_CODE:
            query_params["pp"] = GOG_AFFILIATE_CODE

    elif "kinguin.net" in host or shop == "kinguin":
        if KINGUIN_AFFILIATE_REF:
            query_params["referral"] = KINGUIN_AFFILIATE_REF

    elif "cdkeys.com" in host or "loaded.com" in host or shop == "cdkeys":
        if CDKEYS_AFFILIATE_REF:
            query_params["ref"] = CDKEYS_AFFILIATE_REF

    elif "epicgames.com" in host or shop in ("epic", "epic games"):
        pass

    elif "humblebundle.com" in host or shop == "humble store":
        if HUMBLE_PARTNER_ID:
            query_params["partner"] = HUMBLE_PARTNER_ID

    elif "instant-gaming.com" in host or shop == "instant gaming":
        if INSTANT_GAMING_REF:
            query_params["igr"] = INSTANT_GAMING_REF

    elif "gamivo.com" in host or shop == "gamivo":
        if GAMIVO_REF:
            query_params["glv"] = GAMIVO_REF

    elif "g2a.com" in host or shop == "g2a":
        for key in list(query_params):
            if key in _G2A_TRACKING_KEYS:
                del query_params[key]
        if G2A_GOLDMINE_GNAME:
            query_params["gname"] = G2A_GOLDMINE_GNAME
            query_params["utm_campaign"] = "goldmine"
            query_params["utm_medium"] = "goldmine"
        elif G2A_AFFILIATE_ADID:
            query_params["adid"] = G2A_AFFILIATE_ADID

    new_query = urlencode(query_params)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment,
    ))
