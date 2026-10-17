"""Minimal site-chat API stubs until full site_chat module is restored.

Production includes these handlers to stop /api/site-chat 404 noise from site-chat.js.
Writes are intentionally rejected (no persistence).
"""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/site-chat")
def api_site_chat_list(limit: int = 50, after_id: int | None = None):
    return {"ok": True, "messages": []}


@router.post("/api/site-chat")
async def api_site_chat_post(request: Request):
    try:
        await request.json()
    except Exception:
        pass
    return {"ok": False, "error": "chat_temporarily_unavailable"}
