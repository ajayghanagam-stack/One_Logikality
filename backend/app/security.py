"""Password hashing and JWT encode/decode.

Isolated here so handlers never import passlib or jwt directly — easier to
swap out later (e.g. for argon2 or a managed auth provider) without touching
business code. See docs/TechStack.md §6.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TypedDict

import jwt
from passlib.context import CryptContext

from app.config import settings

_JWT_ALGORITHM = "HS256"

# `deprecated="auto"` auto-upgrades hashes when users successfully log in,
# so if we later change rounds or algorithms older hashes migrate on touch.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plaintext: str) -> str:
    return _pwd_context.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    return _pwd_context.verify(plaintext, hashed)


class JWTClaims(TypedDict):
    sub: str  # user id (UUID string)
    role: str  # 'platform_admin' | 'customer_admin' | 'customer_user'
    org_id: str | None  # UUID string; None for platform admins
    exp: int  # unix seconds


def issue_token(
    *,
    user_id: uuid.UUID,
    role: str,
    org_id: uuid.UUID | None,
) -> tuple[str, datetime]:
    """Encode a short-lived bearer token for the given user.

    Returns (token, expires_at). The caller may want the expiry to return in
    the login response so clients can schedule refresh.
    """
    expires_at = datetime.now(tz=UTC) + timedelta(minutes=settings.jwt_expiration_minutes)
    claims: JWTClaims = {
        "sub": str(user_id),
        "role": role,
        "org_id": str(org_id) if org_id is not None else None,
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm=_JWT_ALGORITHM)
    return token, expires_at


class InvalidTokenError(Exception):
    """Raised when a token fails to decode / validate. Kept distinct from
    jwt's own exceptions so handlers can catch a single app-level type."""


def decode_token(token: str) -> JWTClaims:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
    except jwt.InvalidTokenError as exc:  # covers expired, bad signature, malformed
        raise InvalidTokenError(str(exc)) from exc

    # Narrow to our expected shape; anything missing means the token wasn't
    # issued by us (or was issued by an older code version we no longer trust).
    if not all(k in payload for k in ("sub", "role", "exp")) or "org_id" not in payload:
        raise InvalidTokenError("token missing required claims")
    return payload  # type: ignore[return-value]
