"""Site Chat must advertise unavailability — never fake success."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.site_chat_routes import router


def test_site_chat_get_returns_unavailable():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    res = client.get("/api/site-chat")
    assert res.status_code == 503
    body = res.json()
    assert body.get("ok") is False
    assert body.get("available") is False
    assert body.get("error") == "chat_unavailable"
    assert body.get("messages") == []


def test_site_chat_post_rejects_without_fake_success():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    res = client.post("/api/site-chat", json={"body": "hello", "author_name": "Test"})
    assert res.status_code == 503
    body = res.json()
    assert body.get("ok") is False
    assert body.get("available") is False
    assert "message" not in body or body.get("message") is None
