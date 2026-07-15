"""Password reset tokens for games accounts."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.email_service import send_reset_password_email
from app.core.security import get_password_hash
from app.models.models import User

RESET_TTL = timedelta(hours=1)


def generate_reset_code() -> str:
    return secrets.token_urlsafe(32)


def reset_code_expired(user: User, *, now: datetime | None = None) -> bool:
    if not user.reset_password_created_at:
        return True
    ts = now or datetime.utcnow()
    return user.reset_password_created_at < ts - RESET_TTL


def request_password_reset(db: Session, email: str) -> None:
    """Create reset token and send email if user exists. Always silent on missing user."""
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user:
        return

    code = generate_reset_code()
    user.reset_password_code = code
    user.reset_password_created_at = datetime.utcnow()
    db.commit()

    try:
        send_reset_password_email(user.email, code)
    except Exception:
        user.reset_password_code = None
        user.reset_password_created_at = None
        db.commit()
        raise


def reset_password_with_code(db: Session, code: str, new_password: str) -> User:
    user = db.query(User).filter(User.reset_password_code == code.strip()).first()
    if not user:
        raise ValueError("Nieprawidłowy lub wygasły link resetujący")
    if reset_code_expired(user):
        user.reset_password_code = None
        user.reset_password_created_at = None
        db.commit()
        raise ValueError("Link resetujący wygasł — poproś o nowy")

    user.hashed_password = get_password_hash(new_password)
    user.reset_password_code = None
    user.reset_password_created_at = None
    db.commit()
    db.refresh(user)
    return user
