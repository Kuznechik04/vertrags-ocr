import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.rate_limit import enforce_ip_rate_limit
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User, UserRole
from app.schemas.auth import Token, UserCreate, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Grobe Brute-Force-/Spam-Bremse pro Client-IP. Bewusst grob (in-memory,
# einzelner Prozess) - Details siehe app.core.rate_limit.
REGISTER_RATE_LIMIT = {"max_attempts": 10, "window_seconds": 60}
LOGIN_RATE_LIMIT = {"max_attempts": 10, "window_seconds": 60}


def _set_auth_cookies(response: Response, access_token: str) -> None:
    """Setzt Session- und CSRF-Cookie fürs Browser-Frontend (Double-Submit-
    Cookie-Pattern: das CSRF-Cookie ist absichtlich NICHT httpOnly, das
    Frontend liest es per JS und schickt es als `X-CSRF-Token`-Header bei
    verändernden Requests zurück, siehe app.main.CSRFMiddleware). API-Clients
    (z.B. training/prepare_dataset.py) nutzen weiterhin den `access_token`
    aus dem Response-Body als Authorization-Bearer-Header - beide Wege
    funktionieren nebeneinander."""
    max_age = settings.access_token_expire_minutes * 60
    response.set_cookie(
        key=settings.session_cookie_name,
        value=access_token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=secrets.token_urlsafe(32),
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


@router.post("/register", response_model=Token, status_code=201)
def register(request: Request, response: Response, payload: UserCreate, db: Session = Depends(get_db)):
    enforce_ip_rate_limit(request, key_prefix="register", **REGISTER_RATE_LIMIT)

    existing = db.query(User).filter(User.email == payload.email.lower()).first()
    if existing:
        raise HTTPException(400, "Diese E-Mail-Adresse ist bereits registriert")

    # Bootstrap: der allererste registrierte Nutzer wird automatisch Admin,
    # damit nach dem Erststart nicht manuell in der DB herumgepfuscht werden muss.
    is_first_user = db.query(User).count() == 0

    user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        role=UserRole.ADMIN if is_first_user else UserRole.USER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(subject=user.id, extra_claims={"role": user.role.value})
    _set_auth_cookies(response, token)
    return Token(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=Token)
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    enforce_ip_rate_limit(request, key_prefix="login", **LOGIN_RATE_LIMIT)

    # OAuth2PasswordRequestForm nutzt das Feld "username" für die E-Mail-Adresse
    user = db.query(User).filter(User.email == form_data.username.lower()).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(401, "E-Mail oder Passwort ist falsch")
    if not user.is_active:
        raise HTTPException(403, "Konto ist deaktiviert")

    token = create_access_token(subject=user.id, extra_claims={"role": user.role.value})
    _set_auth_cookies(response, token)
    return Token(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout", status_code=204)
def logout(response: Response):
    """Löscht Session-/CSRF-Cookie. Für das Bearer-Token-basierte API-Clients
    (training/prepare_dataset.py) ist das nicht relevant - deren Token laufen
    einfach nach `access_token_expire_minutes` ab."""
    _clear_auth_cookies(response)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
