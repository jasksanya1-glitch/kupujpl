import logging
import os
from urllib.parse import (
    parse_qsl,
    unquote,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

import requests

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

_log = logging.getLogger("affiliate")

# Ad blockers commonly block awin1.com / awstrack.me. Resolve the hop on our
# server and send the browser straight to the merchant URL (with awc=).
_AWIN_UNWRAP_TIMEOUT = float(os.environ.get("AWIN_UNWRAP_TIMEOUT_SEC", "5") or "5")
_AWIN_UNWRAP_UA = (
    "Mozilla/5.0 (compatible; KupujPL/1.0; +https://kupujpl.pl) "
    "AppleWebKit/537.36 (KHTML, like Gecko)"
)


_AWIN_AFFILIATE_ID = os.environ.get("AWIN_AFFILIATE_ID", "2936531").strip()
_AWIN_MID_BY_SHOP = {
    "kinguin": os.environ.get("AWIN_MID_KINGUIN", "125776").strip(),
    "fanatical": os.environ.get("AWIN_MID_FANATICAL", "118821").strip(),
    "g2a": os.environ.get("AWIN_MID_G2A", "11280").strip(),
    "eneba": os.environ.get("AWIN_MID_ENEBA", "19520").strip(),
}


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


def _strip_url_fragment(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((
        parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, "",
    ))


def merchant_fallback_from_url(url: str) -> str | None:
    """Shop deep link stored alongside an Awin click URL (fragment kp_dest or ued=)."""
    try:
        parsed = urlparse(url or "")
    except Exception:
        return None
    for source in (parsed.fragment, parsed.query):
        params = dict(parse_qsl(source, keep_blank_values=False))
        for key in ("kp_dest", "ued", "url", "desturl", "destination", "redirect"):
            raw = unquote(params.get(key, "") or "").strip()
            if raw.startswith(("http://", "https://")) and not _is_awin_tracking_url(raw):
                return raw
    return None


def attach_merchant_fallback(awin_url: str, merchant_url: str) -> str:
    """Keep Awin click URL as primary; stash shop URL in fragment for unwrap fallback."""
    if not merchant_url or not merchant_url.startswith(("http://", "https://")):
        return awin_url
    if _is_awin_tracking_url(merchant_url):
        return awin_url
    parsed = urlparse(awin_url)
    fragment_params = dict(parse_qsl(parsed.fragment))
    fragment_params["kp_dest"] = merchant_url
    return urlunparse((
        parsed.scheme, parsed.netloc, parsed.path, parsed.params,
        parsed.query, urlencode(fragment_params),
    ))


def unwrap_awin_click_url(url: str, *, timeout: float | None = None) -> str | None:
    """Server-side resolve Awin → merchant Location (includes awc= for attribution).

    Browser never loads awin1.com, so ad blockers do not break the buy click.
    """
    if not _is_awin_tracking_url(url):
        return None
    wait = _AWIN_UNWRAP_TIMEOUT if timeout is None else timeout
    current = _strip_url_fragment(url)
    headers = {"User-Agent": _AWIN_UNWRAP_UA, "Accept": "text/html,application/xhtml+xml"}
    try:
        with requests.Session() as session:
            for _ in range(5):
                resp = session.get(
                    current,
                    allow_redirects=False,
                    timeout=wait,
                    headers=headers,
                )
                loc = (resp.headers.get("Location") or "").strip()
                if not loc:
                    break
                nxt = urljoin(current, loc)
                if not nxt.startswith(("http://", "https://")):
                    break
                if not _is_awin_tracking_url(nxt):
                    return nxt
                current = _strip_url_fragment(nxt)
    except Exception as exc:
        _log.warning("awin unwrap failed for %s: %s", url[:96], exc)
        return None
    return None


def _shop_key_for_awin_wrap(url: str, shop_name: str) -> str | None:
    shop = (shop_name or "").strip().lower()
    if shop in _AWIN_MID_BY_SHOP:
        return shop
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return None
    if "kinguin.net" in host:
        return "kinguin"
    if "fanatical.com" in host:
        return "fanatical"
    if "g2a.com" in host:
        return "g2a"
    if "eneba.com" in host:
        return "eneba"
    return None


def _wrap_direct_url_with_awin(url: str, shop_name: str) -> str | None:
    """Create AWIN deeplink for direct merchant URLs (when shop MID is known)."""
    if not url.startswith(("http://", "https://")):
        return None
    if _is_awin_tracking_url(url):
        return url
    parsed = urlparse(url)
    if "awc=" in (parsed.query or ""):
        return url
    if not _AWIN_AFFILIATE_ID:
        return None
    shop_key = _shop_key_for_awin_wrap(url, shop_name)
    if not shop_key:
        return None
    awin_mid = (_AWIN_MID_BY_SHOP.get(shop_key) or "").strip()
    if not awin_mid:
        return None
    query = urlencode(
        {
            "awinmid": awin_mid,
            "awinaffid": _AWIN_AFFILIATE_ID,
            "ued": url,
        }
    )
    return f"https://www.awin1.com/cread.php?{query}"


def resolve_outbound_url(url: str, shop_name: str) -> str:
    """Build the final browser redirect target for /api/go.

    Prefer merchant deep link (with Awin awc= when unwrapped server-side) over
    sending the user through blocked awin1.com / awstrack.me.
    """
    raw = (url or "").strip()
    if not raw:
        return raw

    source = raw
    wrapped_direct_fallback: str | None = None
    if not _is_awin_tracking_url(source):
        wrapped = _wrap_direct_url_with_awin(source, shop_name)
        if wrapped and wrapped != source:
            source = wrapped
            wrapped_direct_fallback = raw

    destination = source
    if _is_awin_tracking_url(source):
        unwrapped = unwrap_awin_click_url(source)
        if unwrapped:
            destination = unwrapped
        else:
            fallback = merchant_fallback_from_url(source)
            if fallback:
                _log.info(
                    "awin unwrap miss; using kp_dest fallback for %s",
                    (shop_name or "?"),
                )
                destination = fallback
            elif wrapped_direct_fallback:
                _log.info(
                    "awin unwrap miss; falling back to direct merchant URL for %s",
                    (shop_name or "?"),
                )
                destination = wrapped_direct_fallback
            else:
                _log.warning(
                    "awin unwrap miss and no merchant fallback; user may hit adblock (%s)",
                    (shop_name or "?"),
                )

    return make_affiliate_link(destination, shop_name)


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
        # Prefer existing Awin awc= attribution; only add direct referral when
        # env is set and awc is absent (e.g. plain merchant deep link).
        if KINGUIN_AFFILIATE_REF and "awc" not in query_params:
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
