"""Thread-safe per-shop counters for Tier A / local offer scans."""
from __future__ import annotations

import threading
from typing import Any


class ShopScanStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._shops: dict[str, dict[str, Any]] = {}

    def _entry(self, shop: str) -> dict[str, Any]:
        return self._shops.setdefault(
            shop,
            {
                "queries": 0,
                "hits": 0,
                "misses": 0,
                "errors": {},
                "last_error": None,
            },
        )

    def record(self, shop: str, status: str, *, error: str | None = None) -> None:
        with self._lock:
            row = self._entry(shop)
            row["queries"] += 1
            if status == "hit":
                row["hits"] += 1
            elif status == "miss":
                row["misses"] += 1
            else:
                errors = row["errors"]
                errors[status] = int(errors.get(status) or 0) + 1
                if error:
                    row["last_error"] = error[:160]

    def to_dict(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            out: dict[str, dict[str, Any]] = {}
            for shop, row in self._shops.items():
                queries = int(row.get("queries") or 0)
                hits = int(row.get("hits") or 0)
                out[shop] = {
                    "queries": queries,
                    "hits": hits,
                    "misses": int(row.get("misses") or 0),
                    "errors": dict(row.get("errors") or {}),
                    "last_error": row.get("last_error"),
                    "hit_rate": round(hits / queries * 100, 1) if queries else 0.0,
                }
            return out
