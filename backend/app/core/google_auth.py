"""Google Sign-In (GIS id_token) — login / register."""
from __future__ import annotations

import logging
import os
import secrets
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_password_hash
from app.models.models import User

logger = logging.getLogger("google_auth")


def google_client_id() -> str | None:
    cid = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    return cid or None


def google_auth_enabled() -> bool:
    return bool(google_client_id())


def verify_google_credential(credential: str) -> dict[str, Any]:
    client_id = google_client_id()
    if not client_id:
        raise HTTPException(status_code=503, detail="Logowanie Google nie jest skonfigurowane.")
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError as exc:
        logger.error("google-auth package missing: %s", exc)
        raise HTTPException(status_code=503, detail="Logowanie Google tymczasowo niedostępne.") from exc

    try:
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            client_id,
        )
    except Exception as exc:
        logger.warning("Google token verify failed: %s", exc)
        raise HTTPException(status_code=401, detail="Nieprawidłowy token Google.") from exc

    iss = idinfo.get("iss")
    if iss not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(status_code=401, detail="Nieprawidłowy wydawca tokenu Google.")

    if not idinfo.get("email_verified"):
        raise HTTPException(status_code=401, detail="E-mail Google nie jest zweryfikowany.")

    email = (idinfo.get("email") or "").strip().lower()
    sub = (idinfo.get("sub") or "").strip()
    if not email or not sub:
        raise HTTPException(status_code=401, detail="Brak e-maila w koncie Google.")

    return {"email": email, "sub": sub, "name": idinfo.get("name")}


def authenticate_google_user(db: Session, idinfo: dict[str, Any]) -> tuple[User, bool]:
    """Return (user, is_new). Links Google to existing local account with same e-mail."""
    email = idinfo["email"]
    sub = idinfo["sub"]

    by_sub = db.query(User).filter(User.google_sub == sub).first()
    if by_sub:
        return by_sub, False

    by_email = db.query(User).filter(User.email == email).first()
    if by_email:
        if by_email.google_sub and by_email.google_sub != sub:
            raise HTTPException(
                status_code=409,
                detail="Ten e-mail jest powiązany z innym kontem Google.",
            )
        by_email.google_sub = sub
        db.commit()
        db.refresh(by_email)
        return by_email, False

    user = User(
        email=email,
        hashed_password=get_password_hash(secrets.token_urlsafe(48)),
        auth_provider="google",
        google_sub=sub,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, True


def issue_token_for_user(db: Session, user: User):
    from datetime import datetime

    user.last_seen_at = datetime.utcnow()
    db.commit()
    token = create_access_token(user.id)
    return token
