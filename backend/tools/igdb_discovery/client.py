"""Twitch OAuth + IGDB HTTP client (rate-limited)."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from . import config

logger = logging.getLogger("igdb_discovery.client")


@dataclass
class TokenInfo:
    access_token: str
    expires_at: float  # unix ts

    @property
    def valid(self) -> bool:
        return bool(self.access_token) and time.time() < (self.expires_at - 60)


class IgdbClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": config.USER_AGENT, "Accept": "application/json"})
        self._token: TokenInfo | None = None
        self._last_request_at = 0.0
        config.STAGING_DIR.mkdir(parents=True, exist_ok=True)

    def _load_cached_token(self) -> TokenInfo | None:
        path = config.TOKEN_CACHE
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            tok = TokenInfo(access_token=data["access_token"], expires_at=float(data["expires_at"]))
            return tok if tok.valid else None
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return None

    def _save_token(self, tok: TokenInfo) -> None:
        config.TOKEN_CACHE.write_text(
            json.dumps(
                {
                    "access_token": tok.access_token,
                    "expires_at": tok.expires_at,
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def ensure_token(self) -> str:
        if self._token and self._token.valid:
            return self._token.access_token
        cached = self._load_cached_token()
        if cached:
            self._token = cached
            return cached.access_token

        client_id, client_secret = config.require_credentials()
        url = config.TWITCH_TOKEN_URL
        # Use form body (not query string) so secrets are not echoed in urllib3 URL logs.
        resp = self._session.post(
            url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        expires_in = int(payload.get("expires_in", 3600))
        tok = TokenInfo(
            access_token=str(payload["access_token"]),
            expires_at=time.time() + expires_in,
        )
        self._token = tok
        self._save_token(tok)
        logger.info("IGDB Twitch token acquired (expires_in=%ss)", expires_in)
        return tok.access_token

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_at
        if elapsed < config.REQUEST_PAUSE_SEC:
            time.sleep(config.REQUEST_PAUSE_SEC - elapsed)

    def query(self, endpoint: str, body: str, *, retries: int = 3) -> list[dict[str, Any]]:
        """POST Apicalypse body to /v4/{endpoint}."""
        client_id, _ = config.require_credentials()
        token = self.ensure_token()
        url = f"{config.IGDB_API_BASE}/{endpoint.lstrip('/')}"
        headers = {
            "Client-ID": client_id,
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/plain",
        }
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            self._throttle()
            try:
                resp = self._session.post(url, data=body.encode("utf-8"), headers=headers, timeout=60)
                self._last_request_at = time.time()
                if resp.status_code == 401 and attempt < retries:
                    self._token = None
                    if config.TOKEN_CACHE.is_file():
                        config.TOKEN_CACHE.unlink(missing_ok=True)
                    token = self.ensure_token()
                    headers["Authorization"] = f"Bearer {token}"
                    continue
                if resp.status_code == 429:
                    wait = min(2.0 * attempt, 8.0)
                    logger.warning("IGDB 429 — sleep %.1fs", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    raise RuntimeError(f"Unexpected IGDB payload type: {type(data)}")
                return data
            except Exception as exc:  # noqa: BLE001 — retry then raise
                last_err = exc
                logger.warning("IGDB %s attempt %s failed: %s", endpoint, attempt, exc)
                time.sleep(0.5 * attempt)
        raise RuntimeError(f"IGDB query failed for {endpoint}: {last_err}")
