"""Site Chat API — honest unavailable until app.core.site_chat is restored.

Do not persist messages. Do not return ok:true on writes.
Frontend must show unavailable state (see site-chat.js).
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

_UNAVAILABLE = {
    "ok": False,
    "available": False,
    "error": "chat_unavailable",
    "messages": [],
    "detail": "Site chat is temporarily unavailable. Messages are not accepted or stored.",
}


@router.get("/api/site-chat")
def api_site_chat_list(limit: int = 50, after_id: int | None = None):
    return JSONResponse(status_code=503, content=_UNAVAILABLE)


@router.post("/api/site-chat")
async def api_site_chat_post(request: Request):
    try:
        await request.json()
    except Exception:
        pass
    return JSONResponse(status_code=503, content=_UNAVAILABLE)
