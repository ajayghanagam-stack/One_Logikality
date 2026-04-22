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
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters.llm import LLMAdapter
from app.adapters.llm_anthropic import AnthropicLLMAdapter
from app.adapters.llm_gemini import GeminiLLMAdapter
from app.adapters.llm_vertex import VertexLLMAdapter
from app.config import settings
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

    # Eager-load Org so handlers (and UserOut.from_orm) can read the slug
    # without triggering a lazy load on an async session.
    user = (
        await session.execute(
            select(User).options(selectinload(User.org)).where(User.id == user_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_platform_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Dependency for platform-admin-only routes. Chains off `get_current_user`
    so the tenant context and user lookup already ran; this layer just
    enforces the role. Returns 403 (not 401) for authenticated-but-wrong-role
    so callers can distinguish "log in" from "you're in the wrong portal"."""
    if user.role != "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="platform admin only",
        )
    return user


async def require_customer_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Dependency for routes a customer admin owns (user management, app
    enablement, org configuration). Platform admins are NOT allowed through
    this gate — they have their own surfaces under `/api/logikality/*` and
    shouldn't be quietly substituting themselves into a tenant's admin
    plane. Returns 403 for authenticated-but-wrong-role."""
    if user.role != "customer_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="customer admin only",
        )
    return user


async def require_customer_role(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Either customer role — admin or user. Use for tenant-plane actions
    both roles perform (uploading packets, viewing ECV results). Keeps
    platform admins out: they shouldn't be silently dropping packets
    into customer orgs without a deliberate impersonation flow."""
    if user.role not in ("customer_admin", "customer_user"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="customer role required",
        )
    return user


# --- LLM adapters ------------------------------------------------------------
# Singletons: one client per process. `lru_cache` gives us lazy instantiation
# plus idempotent reuse across requests. Call-site injects via FastAPI Depends.


@lru_cache(maxsize=1)
def get_vertex_adapter() -> LLMAdapter:
    # Prefer Gemini Developer API key (AI Studio) — works without a service
    # account or gcloud auth, making it suitable for Replit and CI environments.
    if settings.gemini_api_key:
        return GeminiLLMAdapter(api_key=settings.gemini_api_key)
    # Fall back to Vertex AI via Application Default Credentials.
    if not settings.google_cloud_project:
        raise RuntimeError(
            "No Gemini credentials configured. Set GEMINI_API_KEY (from "
            "https://aistudio.google.com) or set GOOGLE_CLOUD_PROJECT with "
            "Application Default Credentials."
        )
    return VertexLLMAdapter(
        project=settings.google_cloud_project,
        location=settings.google_cloud_region,
    )


@lru_cache(maxsize=1)
def get_anthropic_adapter() -> LLMAdapter:
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set — configure it in .env before using Claude models."
        )
    return AnthropicLLMAdapter(api_key=settings.anthropic_api_key)
