"""Access-code gate for /panel3 admin (games)."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

PANEL3_COOKIE_NAME = "panel3_gate"
PANEL3_ACCESS_CODE = os.environ.get("PANEL3_ACCESS_CODE", os.environ.get("PANEL2_ACCESS_CODE", "1408"))
PANEL3_COOKIE_SECRET = os.environ.get(
    "PANEL3_COOKIE_SECRET",
    os.environ.get("PANEL2_COOKIE_SECRET", "panel3-cookie-dev-change-me"),
)
PANEL3_COOKIE_DOMAIN = os.environ.get("PANEL3_COOKIE_DOMAIN", os.environ.get("PANEL2_COOKIE_DOMAIN", ""))
PANEL3_COOKIE_SECURE = os.environ.get("PANEL3_COOKIE_SECURE", os.environ.get("PANEL2_COOKIE_SECURE_MODE", "auto"))


def _norm_code(value: str) -> str:
    t = (value or "").strip().lstrip("\ufeff")
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        t = t[1:-1].strip()
    return t


def _unlock_code_ok(submitted: str) -> bool:
    code = _norm_code(PANEL3_ACCESS_CODE or "") or "1408"
    a = _norm_code(submitted).encode("utf-8")
    b = code.encode("utf-8")
    if len(a) != len(b):
        return False
    return secrets.compare_digest(a, b)


def _cookie_secret_bytes() -> bytes:
    return str(PANEL3_COOKIE_SECRET or "panel3-cookie-dev-change-me").encode("utf-8")


def panel3_cookie_value() -> str:
    return hmac.new(_cookie_secret_bytes(), b"panel3-unlock-v1", hashlib.sha256).hexdigest()


def panel3_gate_ok(request: Request) -> bool:
    try:
        got = request.cookies.get(PANEL3_COOKIE_NAME, "")
        if len(got) != 64:
            return False
        return hmac.compare_digest(got, panel3_cookie_value())
    except Exception:
        return False


def panel3_cookie_kwargs(request: Request) -> dict:
    secure = PANEL3_COOKIE_SECURE.lower() == "on"
    if PANEL3_COOKIE_SECURE.lower() == "auto":
        secure = request.url.scheme == "https"
    kwargs = {
        "httponly": True,
        "samesite": "lax",
        "max_age": 30 * 24 * 3600,
        "secure": secure,
        "path": "/games/",
    }
    if PANEL3_COOKIE_DOMAIN:
        kwargs["domain"] = PANEL3_COOKIE_DOMAIN
    return kwargs


def redirect_to_panel3_gate(next_path: str = "/panel3") -> RedirectResponse:
    q = f"?next={quote(next_path, safe='')}" if next_path.startswith("/") else ""
    return RedirectResponse(url=f"/games/panel3{q}", status_code=303)


def require_panel3_gate(request: Request) -> None:
    if not panel3_gate_ok(request):
        raise HTTPException(status_code=401, detail="Panel3 gate required")


def panel3_admin_ok(request: Request) -> bool:
    """Cookie gate or X-Panel3-Code header (for CLI worker on home PC)."""
    if panel3_gate_ok(request):
        return True
    header = request.headers.get("X-Panel3-Code") or request.headers.get("x-panel3-code") or ""
    return _unlock_code_ok(header)


def require_panel3_admin(request: Request) -> None:
    if not panel3_admin_ok(request):
        raise HTTPException(status_code=401, detail="Panel3 admin required")
