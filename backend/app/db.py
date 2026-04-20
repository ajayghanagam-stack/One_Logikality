"""Async SQLAlchemy engine, session factory, and RLS context helper.

Postgres row-level security is keyed on three session-scoped settings:

    app.current_user_id  — UUID of the authenticated user
    app.current_org_id   — UUID of that user's org (empty for platform_admin)
    app.current_role     — 'platform_admin' | 'customer_admin' | 'customer_user'

Request handlers should `set_tenant_context(...)` once inside the transaction
that wraps the handler; the settings unset automatically at commit/rollback
because they're set with `is_local=true` (equivalent to SET LOCAL). See
docs/TechStack.md §4 — "Postgres RLS keyed on org_id, enforced from day one".
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Project-wide declarative base; all ORM models inherit from this."""


engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def set_tenant_context(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    role: str | None = None,
) -> None:
    """Install RLS session variables for the current transaction and switch
    to the non-superuser `app_user` role so policies actually apply.

    Superusers bypass RLS regardless of FORCE RLS, so the app connects as
    postgres (which keeps migrations and seeding simple) and then each
    request-scoped transaction drops to app_user via `SET LOCAL ROLE`.

    Uses `set_config(key, value, is_local=true)` so values are scoped to the
    current transaction and cleared on commit/rollback — matches SET LOCAL
    semantics without breaking when asyncpg prepares the statement.
    """
    await session.execute(text("SET LOCAL ROLE app_user"))
    await session.execute(
        text("SELECT set_config('app.current_user_id', :v, true)"),
        {"v": str(user_id) if user_id is not None else ""},
    )
    await session.execute(
        text("SELECT set_config('app.current_org_id', :v, true)"),
        {"v": str(org_id) if org_id is not None else ""},
    )
    await session.execute(
        text("SELECT set_config('app.current_role', :v, true)"),
        {"v": role or ""},
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a per-request AsyncSession."""
    async with SessionLocal() as session:
        yield session
