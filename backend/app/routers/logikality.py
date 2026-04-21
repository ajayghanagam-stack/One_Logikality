"""Platform-admin API — customer-account management (US-1.5 onward).

Mounted under `/api/logikality/*` to mirror the reserved `/logikality/*`
route segment in the frontend. Every handler depends on
`require_platform_admin`, which chains `get_current_user` (so the RLS
tenant context is already installed) and then enforces the role — so
the queries below run under `app.current_role = 'platform_admin'` and
the policies in migration 0001 let them see every org/user row.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require_platform_admin
from app.models import ORG_TYPES, Org, User
from app.security import hash_password

router = APIRouter(prefix="/api/logikality", tags=["logikality"])

# Reserved slug — the `/logikality/*` route segment belongs to the platform
# admin portal, so no customer org can claim it. Mirrors the DB-level
# `orgs_slug_shape_check` constraint in migration 0002.
_RESERVED_SLUGS = frozenset({"logikality"})

# Same shape the DB constraint enforces: lowercase, alphanumeric + hyphen,
# must start with alphanumeric. Duplicated here so we can return a
# friendly 400 instead of letting Postgres raise a generic 23514.
_SLUG_SHAPE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class AccountRow(BaseModel):
    """One row in the customer-accounts list (US-1.5)."""

    id: str
    name: str
    slug: str
    type: str
    created_at: datetime
    # Count of users attached to this org (all roles — customer_admin +
    # customer_user). Computed via LEFT JOIN so orgs with zero users still
    # appear (useful right after platform admin creates an org).
    user_count: int
    # Count of micro-apps the platform admin has subscribed this org to.
    # Stubbed as 0 until US-2.5 lands the subscriptions table — the field
    # is in the payload now so the frontend shape doesn't churn later.
    subscription_count: int


@router.get("/accounts", response_model=list[AccountRow])
async def list_accounts(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_platform_admin)],
) -> list[AccountRow]:
    # LEFT JOIN so orgs with no users yet still return with user_count = 0.
    # Order by created_at DESC so the most recently added orgs surface first.
    stmt = (
        select(
            Org.id,
            Org.name,
            Org.slug,
            Org.type,
            Org.created_at,
            func.count(User.id).label("user_count"),
        )
        .select_from(Org)
        .outerjoin(User, User.org_id == Org.id)
        .group_by(Org.id)
        .order_by(Org.created_at.desc())
    )
    result = await session.execute(stmt)
    return [
        AccountRow(
            id=str(row.id),
            name=row.name,
            slug=row.slug,
            type=row.type,
            created_at=row.created_at,
            user_count=row.user_count,
            subscription_count=0,  # US-2.5 will wire real subscription counts
        )
        for row in result.all()
    ]


class CreateAccountRequest(BaseModel):
    """Payload for POST /accounts (US-1.6).

    Org `type` is validated against `ORG_TYPES` via pydantic's enum-ish
    `Field(pattern=...)` would be fragile for values with spaces, so we
    validate by membership check in the handler and return 400 with a
    precise message. Pydantic's `EmailStr` catches most malformed emails
    before they reach the DB's unique constraint.

    `initial_password` is a DEMO-GRADE affordance — the platform admin can
    type the customer admin's starting password, matching the behavior in
    `one-logikality-demo`. When absent the server falls back to generating
    a one-time password. Once the full app ships (real email invites /
    forced first-login password reset), delete this field and revert to
    generate-only.
    """

    name: str = Field(min_length=1, max_length=120)
    type: str
    primary_admin_full_name: str = Field(min_length=1, max_length=120)
    primary_admin_email: EmailStr
    initial_password: str | None = Field(default=None, min_length=6, max_length=128)


class CreateAccountResponse(BaseModel):
    """Success payload for POST /accounts.

    Returns the newly created account row *plus* a one-time temp password
    the platform admin will hand to the new customer admin. The hash is
    the only thing persisted; this plaintext is the caller's only chance
    to capture it — the frontend shows a copy-to-clipboard panel.
    """

    account: AccountRow
    primary_admin_email: str
    temp_password: str


@router.post(
    "/accounts",
    response_model=CreateAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_account(
    payload: CreateAccountRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_platform_admin)],
) -> CreateAccountResponse:
    # Validate org type up front — the DB CHECK would also catch this, but
    # the error would surface as IntegrityError without naming the field.
    if payload.type not in ORG_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"type must be one of: {', '.join(ORG_TYPES)}",
        )

    slug = _slugify(payload.name)
    if not slug or not _SLUG_SHAPE_RE.match(slug) or slug in _RESERVED_SLUGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "organization name must contain at least one letter or digit "
                "and cannot resolve to a reserved slug"
            ),
        )

    # Pre-check for collisions so we can return field-specific 409s instead
    # of a generic IntegrityError. The IntegrityError branch below still
    # handles the race where two admins create in parallel.
    existing_org = (
        await session.execute(select(Org.id).where((Org.name == payload.name) | (Org.slug == slug)))
    ).first()
    if existing_org is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an organization with that name or slug already exists",
        )

    existing_user = (
        await session.execute(select(User.id).where(User.email == payload.primary_admin_email))
    ).first()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a user with that email already exists",
        )

    # Admin-supplied password if provided (demo affordance — see
    # CreateAccountRequest); otherwise 12 URL-safe chars ≈ 72 bits of
    # entropy — plenty for a copy-paste-once bootstrap password. Either
    # way the customer admin is expected to change it on first login
    # (US-2.1 lands the change-password flow).
    temp_password = payload.initial_password or secrets.token_urlsafe(9)

    org = Org(name=payload.name, slug=slug, type=payload.type)
    session.add(org)
    # Flush so `org.id` is populated for the user FK without committing.
    await session.flush()

    admin_user = User(
        email=payload.primary_admin_email,
        password_hash=hash_password(temp_password),
        full_name=payload.primary_admin_full_name,
        role="customer_admin",
        org_id=org.id,
        is_primary_admin=True,
    )
    session.add(admin_user)

    try:
        await session.commit()
    except IntegrityError as exc:
        # Race fallback — pre-checks above handle the common case.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="organization name, slug, or admin email already in use",
        ) from exc

    return CreateAccountResponse(
        account=AccountRow(
            id=str(org.id),
            name=org.name,
            slug=org.slug,
            type=org.type,
            created_at=org.created_at,
            user_count=1,  # just inserted the primary admin
            subscription_count=0,
        ),
        primary_admin_email=admin_user.email,
        temp_password=temp_password,
    )


def _slugify(name: str) -> str:
    """Derive a URL-friendly slug from an org name.

    Lowercases, replaces any non-alphanumeric run with a single hyphen,
    trims leading/trailing hyphens. The result is validated against
    `_SLUG_SHAPE_RE` + `_RESERVED_SLUGS` by the caller — this helper is
    intentionally lenient so validation decisions live in one place.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
