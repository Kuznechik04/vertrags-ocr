from fastapi import Cookie, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import decode_access_token, decode_preview_token
from app.models.user import User, UserRole

# auto_error=False, damit sowohl der Authorization-Header (für API-Clients wie
# training/prepare_dataset.py) als auch das httpOnly-Session-Cookie (fürs
# Frontend) akzeptiert werden können - siehe get_current_user unten.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Ungültige oder abgelaufene Anmeldung",
    headers={"WWW-Authenticate": "Bearer"},
)


def _resolve_user(token: str | None, db: Session) -> User:
    if not token:
        raise CREDENTIALS_ERROR
    try:
        payload = decode_access_token(token)
    except Exception:  # noqa: BLE001 - jede Art von Decodierfehler (abgelaufen, falsche Signatur, kaputtes Token, ...)
        raise CREDENTIALS_ERROR

    user_id = payload.get("sub")
    if not user_id:
        raise CREDENTIALS_ERROR

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise CREDENTIALS_ERROR
    return user


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    session_cookie: str | None = Cookie(default=None, alias=settings.session_cookie_name),
    db: Session = Depends(get_db),
) -> User:
    """Akzeptiert den Session-Token entweder als Authorization-Header (API-
    Clients wie training/prepare_dataset.py) oder als httpOnly-Cookie (Browser-
    Frontend, siehe app.api.auth)."""
    return _resolve_user(token or session_cookie, db)


def get_current_user_flexible(
    document_id: str,
    token: str | None = Depends(oauth2_scheme),
    session_cookie: str | None = Cookie(default=None, alias=settings.session_cookie_name),
    preview_token: str | None = Query(default=None, alias="preview_token"),
    db: Session = Depends(get_db),
) -> User:
    """Wie `get_current_user`, akzeptiert zusätzlich einen kurzlebigen,
    auf `document_id` beschränkten Preview-Token als Query-Parameter.

    Nötig für <img>/<iframe>-Vorschauen: Der Browser kann dort keinen
    Authorization-Header mitschicken, und das reguläre Session-Cookie soll
    nicht in einer URL landen (Logs/Historie/Referer) - daher wird für die
    Dateivorschau ein separater, kurzlebiger Token über `?preview_token=...`
    übergeben (siehe POST .../preview-token in app.api.documents)."""
    if preview_token:
        try:
            payload = decode_preview_token(preview_token, document_id)
        except Exception:  # noqa: BLE001 - jede Art von Decodierfehler
            raise CREDENTIALS_ERROR
        user_id = payload.get("sub")
        user = db.get(User, user_id) if user_id else None
        if not user or not user.is_active:
            raise CREDENTIALS_ERROR
        return user
    return _resolve_user(token or session_cookie, db)


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur für Administratoren")
    return user
