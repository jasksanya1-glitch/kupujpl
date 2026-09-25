"""Generation counter for public catalog caches (home, games list, sitemap)."""
from __future__ import annotations

import threading
from collections.abc import Callable

_lock = threading.Lock()
_generation = 0
_listeners: list[Callable[[], None]] = []


def catalog_generation() -> int:
    with _lock:
        return _generation


def on_catalog_change(fn: Callable[[], None]) -> None:
    with _lock:
        _listeners.append(fn)


def bump_catalog_generation() -> int:
    """Invalidate caches after offer/catalog writes. Does not write to the database."""
    global _generation
    with _lock:
        _generation += 1
        listeners = list(_listeners)
        gen = _generation
    for fn in listeners:
        fn()
    return gen
