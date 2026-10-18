"""Thread-local requests.Session pools for official/API scanners (keep-alive).

Does not change RPS — only reuses TCP connections within a worker thread.
"""
from __future__ import annotations

import threading
from typing import Any

import requests

_LOCAL = threading.local()


def session_for(name: str, *, headers: dict[str, str] | None = None) -> requests.Session:
    bag: dict[str, Any] = getattr(_LOCAL, "sessions", None) or {}
    sess = bag.get(name)
    if sess is None:
        sess = requests.Session()
        if headers:
            sess.headers.update(headers)
        bag[name] = sess
        _LOCAL.sessions = bag
    return sess


def reset_sessions() -> None:
    """Test helper — drop thread-local sessions."""
    _LOCAL.sessions = {}
