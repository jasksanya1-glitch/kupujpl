from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import PyJWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import ALGORITHM, SECRET_KEY, SESSION_COOKIE_NAME
from app.models.models import User
import jwt

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    # Prefer cookie; keep Bearer for JS localStorage and workers.
    if not token and credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wymagane logowanie",
        )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Nieprawidłowy token")
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Nieprawidłowy lub wygasły token")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="Użytkownik nie istnieje")
    return user


def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None and not request.cookies.get(SESSION_COOKIE_NAME):
        return None
    try:
        return get_current_user(request, credentials, db)
    except HTTPException:
        return None
