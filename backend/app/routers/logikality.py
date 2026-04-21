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
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require_platform_admin
from app.models import APP_IDS, ORG_TYPES, AppSubscription, Org, User
from app.security import hash_password

# ECV is foundational — every customer org must subscribe to it. The
# backend enforces this regardless of what the client sends, so a
# buggy UI can't provision an org without ECV.
_REQUIRED_APP = "ecv"

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
    # Counts come from two separate aggregate queries rather than a
    # single JOIN — joining users * subscriptions would multiply rows
    # and need DISTINCT tricks. Two small queries keyed by org_id is
    # clearer and fine at customer-count scale.
    users_stmt = select(User.org_id, func.count(User.id)).group_by(User.org_id)
    subs_stmt = select(AppSubscription.org_id, func.count(AppSubscription.id)).group_by(
        AppSubscription.org_id
    )
    orgs_stmt = select(Org).order_by(Org.created_at.desc())

    users_by_org = {row[0]: row[1] for row in (await session.execute(users_stmt)).all()}
    subs_by_org = {row[0]: row[1] for row in (await session.execute(subs_stmt)).all()}
    orgs = (await session.execute(orgs_stmt)).scalars().all()

    return [
        AccountRow(
            id=str(org.id),
            name=org.name,
            slug=org.slug,
            type=org.type,
            created_at=org.created_at,
            user_count=users_by_org.get(org.id, 0),
            subscription_count=subs_by_org.get(org.id, 0),
        )
        for org in orgs
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
    # Which micro-apps the new org should be subscribed to. ECV is added
    # server-side regardless — leaving this unset gives an ECV-only org,
    # which matches the conservative default for the Mortgage BPO type.
    # Unknown ids are rejected with a 400.
    subscribed_apps: list[str] = Field(default_factory=list)


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

    # Normalize the subscribed-apps list: dedupe, always include ECV, and
    # reject unknown ids with a precise 400 before we start inserting.
    unknown = [a for a in payload.subscribed_apps if a not in APP_IDS]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown app id(s): {', '.join(sorted(set(unknown)))}",
        )
    subscribed_apps = sorted({*payload.subscribed_apps, _REQUIRED_APP})

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

    # Insert subscription rows in the same transaction so an org is never
    # left partially provisioned. `enabled` defaults to true server-side
    # (customer admin can toggle off in US-2.6).
    for app_id in subscribed_apps:
        session.add(AppSubscription(org_id=org.id, app_id=app_id))

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
            subscription_count=len(subscribed_apps),
        ),
        primary_admin_email=admin_user.email,
        temp_password=temp_password,
    )


class AccountDetail(BaseModel):
    """Single-account payload for the Manage page (US-1.7).

    Extends `AccountRow` with the primary admin (name + email) and the
    list of subscribed app ids. Kept as a distinct model so the list
    endpoint's response shape doesn't grow a big nullable admin block
    that every row would carry even when unused.
    """

    id: str
    name: str
    slug: str
    type: str
    created_at: datetime
    user_count: int
    subscription_count: int
    primary_admin_name: str | None
    primary_admin_email: str | None
    subscribed_apps: list[str]


@router.get("/accounts/{org_id}", response_model=AccountDetail)
async def get_account(
    org_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_platform_admin)],
) -> AccountDetail:
    org = (await session.execute(select(Org).where(Org.id == org_id))).scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="organization not found",
        )

    users_stmt = select(User).where(User.org_id == org_id)
    users = (await session.execute(users_stmt)).scalars().all()
    primary = next((u for u in users if u.is_primary_admin), None)

    subs_stmt = select(AppSubscription.app_id).where(AppSubscription.org_id == org_id)
    subs = [row[0] for row in (await session.execute(subs_stmt)).all()]

    return AccountDetail(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        type=org.type,
        created_at=org.created_at,
        user_count=len(users),
        subscription_count=len(subs),
        primary_admin_name=primary.full_name if primary else None,
        primary_admin_email=primary.email if primary else None,
        subscribed_apps=sorted(subs),
    )


class ResetAdminPasswordRequest(BaseModel):
    """Optional platform-admin-supplied password (demo affordance).

    Mirrors the create-account flow: if `new_password` is omitted the
    server generates a 12-char one-time password. Either way the
    plaintext is returned once and never retrievable again — the UI
    shows a copy-to-clipboard card.
    """

    new_password: str | None = Field(default=None, min_length=6, max_length=128)


class ResetAdminPasswordResponse(BaseModel):
    primary_admin_email: str
    temp_password: str


@router.post(
    "/accounts/{org_id}/reset-admin-password",
    response_model=ResetAdminPasswordResponse,
)
async def reset_admin_password(
    org_id: uuid.UUID,
    payload: ResetAdminPasswordRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_platform_admin)],
) -> ResetAdminPasswordResponse:
    # Find the org's primary admin. Every org has exactly one at create
    # time; if somehow zero we return 409 rather than silently no-op'ing.
    primary = (
        await session.execute(
            select(User).where(User.org_id == org_id, User.is_primary_admin.is_(True))
        )
    ).scalar_one_or_none()
    if primary is None:
        # 404 covers both "unknown org" and "org with no primary admin".
        # The client doesn't need to distinguish — either way, can't reset.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="primary admin not found for this organization",
        )

    temp_password = payload.new_password or secrets.token_urlsafe(9)
    primary.password_hash = hash_password(temp_password)
    await session.commit()

    return ResetAdminPasswordResponse(
        primary_admin_email=primary.email,
        temp_password=temp_password,
    )


class UpdateSubscriptionsRequest(BaseModel):
    """Replace-the-whole-set semantics: whatever arrives is the new
    subscription list, with ECV forced in and unknowns rejected.

    The `enabled` toggle per-subscription is a customer-admin concern
    (US-2.6) and lives on a separate endpoint — this one only controls
    which apps exist as subscriptions at all.
    """

    app_ids: list[str] = Field(default_factory=list)


@router.put(
    "/accounts/{org_id}/subscriptions",
    response_model=AccountDetail,
)
async def update_subscriptions(
    org_id: uuid.UUID,
    payload: UpdateSubscriptionsRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_platform_admin)],
) -> AccountDetail:
    org = (await session.execute(select(Org).where(Org.id == org_id))).scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="organization not found",
        )

    unknown = [a for a in payload.app_ids if a not in APP_IDS]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown app id(s): {', '.join(sorted(set(unknown)))}",
        )
    # Always include ECV regardless of what the client sends — mirrors
    # the create-account invariant.
    target = set(payload.app_ids) | {_REQUIRED_APP}

    existing_stmt = select(AppSubscription).where(AppSubscription.org_id == org_id)
    existing = (await session.execute(existing_stmt)).scalars().all()
    existing_ids = {s.app_id for s in existing}

    # Diff-based update — cheaper than delete-all + re-insert, and keeps
    # the `created_at` timestamp + `enabled` toggle intact on apps that
    # stay subscribed across a PUT.
    for sub in existing:
        if sub.app_id not in target:
            await session.delete(sub)
    for app_id in target - existing_ids:
        session.add(AppSubscription(org_id=org_id, app_id=app_id))

    await session.commit()

    # Re-emit the full detail payload so the client can replace its
    # local state in one go without another GET.
    return await get_account(org_id, session, _admin)


@router.delete(
    "/accounts/{org_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_account(
    org_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_platform_admin)],
) -> Response:
    """Permanently delete a customer org and everything under it.

    `users.org_id` and `app_subscriptions.org_id` are `ON DELETE CASCADE`
    (see migrations 0001/0003), so a single `DELETE FROM orgs` removes
    the users and subscription rows in the same statement. No soft-delete
    here by design — a recovery flow would need its own explicit story
    (archived flag + restore endpoint), not a quiet tombstone.

    Returns 404 (not 204) when the id doesn't exist so the platform admin
    sees a clear error if they click Delete on a row that was already
    removed in another tab.
    """
    result = await session.execute(delete(Org).where(Org.id == org_id))
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="organization not found",
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _slugify(name: str) -> str:
    """Derive a URL-friendly slug from an org name.

    Lowercases, replaces any non-alphanumeric run with a single hyphen,
    trims leading/trailing hyphens. The result is validated against
    `_SLUG_SHAPE_RE` + `_RESERVED_SLUGS` by the caller — this helper is
    intentionally lenient so validation decisions live in one place.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
