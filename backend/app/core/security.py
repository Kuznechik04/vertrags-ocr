"""Passwort-Hashing und JWT-Handling.

Bewusst ohne `passlib`/`bcrypt`, da diese nativen C-Erweiterungen auf sehr neuen
Python-Versionen (z.B. 3.14) mangels vorgebauter Wheels manchmal nicht installierbar
sind. Stattdessen wird PBKDF2-HMAC-SHA256 aus der Python-Standardbibliothek genutzt,
was ohne zusätzliche native Abhängigkeiten funktioniert und für diesen Zweck sicher
genug ist.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

PBKDF2_ITERATIONS = 260_000
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        salt, digest_hex = hashed.split("$", 1)
    except ValueError:
        return False
    expected = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return hmac.compare_digest(expected.hex(), digest_hex)


PREVIEW_TOKEN_AUDIENCE = "preview"


def _create_token(subject: str, expires_minutes: float, extra_claims: dict | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {"sub": subject, "exp": expire, **(extra_claims or {})}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(subject: str, extra_claims: dict | None = None) -> str:
    return _create_token(subject, settings.access_token_expire_minutes, extra_claims)


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    if "aud" in payload:
        # Session-Tokens haben nie eine "aud"-Claim - ein Token, das eine
        # mitbringt (z.B. ein Preview-Token), darf nicht als vollwertiger
        # Session-Token akzeptiert werden.
        raise jwt.InvalidTokenError("Token ist für einen anderen Zweck ausgestellt")
    return payload


def create_preview_token(subject: str, document_id: str) -> str:
    """Kurzlebiger Token für <img>/<iframe>-Dateivorschauen, auf ein
    einzelnes Dokument beschränkt (siehe app.core.deps.get_current_user_flexible)."""
    return _create_token(
        subject,
        settings.preview_token_expire_minutes,
        {"aud": PREVIEW_TOKEN_AUDIENCE, "document_id": document_id},
    )


def decode_preview_token(token: str, document_id: str) -> dict:
    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM], audience=PREVIEW_TOKEN_AUDIENCE)
    if payload.get("document_id") != document_id:
        raise jwt.InvalidTokenError("Preview-Token gilt für ein anderes Dokument")
    return payload
