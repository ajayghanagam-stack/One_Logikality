"""FastAPI dependencies — most importantly `get_current_user`, which reads
the bearer token, applies the RLS tenant context on the request session, and
returns the authenticated `User` ORM object.

Every protected handler should declare `user: Annotated[User, Depends(get_current_user)]`.
Doing so (a) enforces auth, (b) installs the RLS session vars so subsequent
queries on the same session are automatically tenant-scoped, and (c) gives
the handler typed access to the user row without an extra query.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, set_tenant_context
from app.models import User
from app.security import InvalidTokenError, decode_token

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user(
    token: Annotated[str | None, Depends(_oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_token(token)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        user_id = uuid.UUID(claims["sub"])
        org_id = uuid.UUID(claims["org_id"]) if claims["org_id"] else None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="malformed token claims",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # Install RLS context BEFORE the user lookup — belt and suspenders: even
    # if the token is for a user who has since been deleted, the query
    # returning None still ran under tenant-scoped RLS.
    await set_tenant_context(
        session,
        user_id=user_id,
        org_id=org_id,
        role=claims["role"],
    )

    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
