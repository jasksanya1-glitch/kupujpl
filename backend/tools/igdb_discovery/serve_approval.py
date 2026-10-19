"""Local HTTP server for discovery approval (staging only, loopback only).

Usage (from backend/):
  python -m tools.igdb_discovery.serve_approval

Security:
  - Bound to 127.0.0.1 only
  - Rejects any peer that is not loopback
  - State changes ONLY via POST /api/decision (GET never mutates)
  - Never writes production games/offers
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from . import config
from .approval import LANE_STAGING, ApprovalStore
from .staging import StagingStore

logger = logging.getLogger("igdb_discovery.serve_approval")
HOST = "127.0.0.1"
PORT = 8766
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


class Handler(BaseHTTPRequestHandler):
    store = ApprovalStore(lane=LANE_STAGING)

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _peer_ok(self) -> bool:
        host = (self.client_address[0] or "").strip()
        if host in LOOPBACK:
            return True
        # IPv4-mapped IPv6
        if host.startswith("::ffff:") and host.split("::ffff:")[-1] in {"127.0.0.1"}:
            return True
        return False

    def _cors(self) -> None:
        # Local file:// / loopback UI only — never open to WAN origins.
        origin = self.headers.get("Origin") or ""
        if origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost"):
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, content_type: str) -> None:  # noqa: ANN001
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self._cors()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _deny_nonlocal(self) -> bool:
        if self._peer_ok():
            return False
        self._json(
            403,
            {
                "ok": False,
                "error": "loopback_only",
                "message": "Approval UI accepts connections from 127.0.0.1 only.",
            },
        )
        return True

    def do_OPTIONS(self) -> None:  # noqa: N802
        if self._deny_nonlocal():
            return
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self._deny_nonlocal():
            return
        path = urlparse(self.path).path
        # GET is read-only — never mutate state here (no approve via query string).
        if path.startswith("/api/decision"):
            self._json(
                405,
                {
                    "ok": False,
                    "error": "method_not_allowed",
                    "message": "Mutations require POST /api/decision",
                },
            )
            return
        if path in {"/", "/report", "/discovery_report.html"}:
            html = config.REPORTS_DIR / "discovery_report.html"
            if not html.is_file():
                self._json(404, {"ok": False, "error": "report_missing"})
                return
            self._file(html, "text/html; charset=utf-8")
            return
        if path in {"/rankings", "/rankings_report.html"}:
            html = config.REPORTS_DIR / "rankings_report.html"
            if not html.is_file():
                self._json(404, {"ok": False, "error": "rankings_report_missing"})
                return
            self._file(html, "text/html; charset=utf-8")
            return
        if path == "/api/summary":
            self._json(
                200,
                {
                    "ok": True,
                    "staging": StagingStore().summary(),
                    "approval": self.store.summary(),
                    "production_publish": False,
                    "bind": f"{HOST}:{PORT}",
                    "mutations": "POST /api/decision only",
                },
            )
            return
        if path == "/api/log":
            self._json(200, {"ok": True, "log": self.store.recent_log(100)})
            return
        self._json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self._deny_nonlocal():
            return
        path = urlparse(self.path).path
        if path != "/api/decision":
            self._json(404, {"ok": False, "error": "not_found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "invalid_json"})
            return
        igdb_id = data.get("igdb_id")
        action = data.get("action")
        note = data.get("note")
        force = bool(data.get("force"))
        actor = (data.get("actor") or "local_reviewer").strip()
        if igdb_id is None or action not in {"approve", "reject", "defer", "revoke"}:
            self._json(400, {"ok": False, "error": "need_igdb_id_and_action"})
            return
        result = self.store.decide(
            int(igdb_id), action, note=note, force=force, actor=actor
        )
        self._json(200 if result.get("ok") else 409, result)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config.assert_prototype_safety()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Discovery approval UI: http://{HOST}:{PORT}/ (loopback only)")
    print(f"Staging DB: {config.STAGING_DB}")
    print("Mutations: POST /api/decision only. APPROVE never writes production.")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
