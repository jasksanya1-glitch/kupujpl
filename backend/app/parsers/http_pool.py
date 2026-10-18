"""Thread-local requests.Session pools for official/API scanners (keep-alive).

Reuses TCP connections within a worker thread. Every get/post also respects the
shared per-shop RPS limiter when a scanner shop HTTP context is active, so
ThreadPool workers + retries cannot multiply request rate.
"""
from __future__ import annotations

import threading
from typing import Any

import requests

_LOCAL = threading.local()


class _RateLimitedSession:
    """Thin wrapper: wait on shared shop limiter before each outbound call."""

    def __init__(self, session: requests.Session, shop_key: str) -> None:
        self._session = session
        self._shop_key = shop_key

    def _wait(self) -> None:
        try:
            from app.parsers.shop_scan_queue import shop_http_wait

            shop_http_wait(self._shop_key)
        except Exception:
            pass

    def get(self, *args: Any, **kwargs: Any):
        self._wait()
        return self._session.get(*args, **kwargs)

    def post(self, *args: Any, **kwargs: Any):
        self._wait()
        return self._session.post(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


def session_for(name: str, *, headers: dict[str, str] | None = None) -> requests.Session:
    bag: dict[str, Any] = getattr(_LOCAL, "sessions", None) or {}
    sess = bag.get(name)
    if sess is None:
        raw = requests.Session()
        if headers:
            raw.headers.update(headers)
        # Map pool name → shop display name for budget lookup.
        shop = {"gog": "GOG", "epic": "Epic Games", "steam": "Steam"}.get(name, name)
        sess = _RateLimitedSession(raw, shop)
        bag[name] = sess
        _LOCAL.sessions = bag
    return sess  # type: ignore[return-value]


def reset_sessions() -> None:
    """Test helper — drop thread-local sessions."""
    _LOCAL.sessions = {}
