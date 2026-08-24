from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_access_token
from app.models.user import User, UserRole

# auto_error=False, damit wir für get_current_user_flexible selbst entscheiden
# können, ob wir stattdessen den Query-Parameter "token" akzeptieren.
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


def get_current_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    return _resolve_user(token, db)


def get_current_user_flexible(
    token: str | None = Depends(oauth2_scheme),
    token_query: str | None = Query(default=None, alias="token"),
    db: Session = Depends(get_db),
) -> User:
    """Wie `get_current_user`, akzeptiert den Token zusätzlich als Query-Parameter.

    Nötig für <img>/<iframe>-Vorschauen: Der Browser kann dort keinen
    Authorization-Header mitschicken, daher wird der Token bei der Dateivorschau
    über `?token=...` übergeben.
    """
    return _resolve_user(token or token_query, db)


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur für Administratoren")
    return user
