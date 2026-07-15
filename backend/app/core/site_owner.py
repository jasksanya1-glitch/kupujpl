"""Site owner check for panel home curation."""
from __future__ import annotations

import os

from fastapi import HTTPException

from app.models.models import User

SITE_OWNER_EMAIL = os.environ.get("SITE_OWNER_EMAIL", "").strip().lower()


def is_site_owner(user: User | None) -> bool:
    if not user or not SITE_OWNER_EMAIL:
        return False
    return (user.email or "").strip().lower() == SITE_OWNER_EMAIL


def require_site_owner(user: User) -> None:
    if not is_site_owner(user):
        raise HTTPException(status_code=403, detail="Brak uprawnień właściciela strony")
