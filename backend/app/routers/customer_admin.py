"""Customer-admin API — team management (US-2.2 / US-2.3 / US-2.4).

Mounted at `/api/customer-admin/*`. Every handler depends on
`require_customer_admin`, which chains `get_current_user` so the RLS
tenant context is installed before any query runs. That means handlers
here can't accidentally see (or mutate) another org's rows even if a
WHERE clause is forgotten — Postgres policies enforce the boundary.

The role enum on the wire is "admin" / "member" (matches the demo and
the UI copy); internally that maps to `customer_admin` / `customer_user`.
Keeping the wire vocabulary simple means the frontend doesn't have to
know the internal role strings.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require_customer_admin
from app.models import APP_IDS, AppSubscription, User
from app.security import hash_password

# ECV is foundational — the backend forces it subscribed AND enabled for
# every customer org. Customer admins can't disable it, mirroring the
# invariant the platform-admin create/PUT flows already enforce.
_REQUIRED_APP = "ecv"

router = APIRouter(prefix="/api/customer-admin", tags=["customer-admin"])

# Wire → DB role mapping. The wire enum matches the demo UI labels
# ("admin" / "member") so the frontend stays close to the visual design;
# internally these are stored as the full role strings from USER_ROLES.
_WIRE_TO_DB_ROLE: dict[str, str] = {
    "admin": "customer_admin",
    "member": "customer_user",
}
_DB_TO_WIRE_ROLE: dict[str, str] = {v: k for k, v in _WIRE_TO_DB_ROLE.items()}


class TeamMember(BaseModel):
    """One row in the Team members list."""

    id: str
    email: str
    full_name: str
    # Wire enum — "admin" or "member". Frontend renders the same labels.
    role: Literal["admin", "member"]
    is_primary_admin: bool
    created_at: datetime


@router.get("/users", response_model=list[TeamMember])
async def list_team(
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_customer_admin)],
) -> list[TeamMember]:
    # RLS would filter to the admin's org anyway, but the explicit WHERE
    # makes the query's intent obvious and lets test fixtures that run
    # under the postgres superuser still exercise the same filter.
    stmt = select(User).where(User.org_id == admin.org_id).order_by(User.created_at.asc())
    users = (await session.execute(stmt)).scalars().all()
    return [
        TeamMember(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            role=_DB_TO_WIRE_ROLE[u.role],  # type: ignore[arg-type]
            is_primary_admin=u.is_primary_admin,
            created_at=u.created_at,
        )
        for u in users
    ]


class InviteUserRequest(BaseModel):
    """Invite payload. `temp_password` is optional — if absent the server
    generates one. Mirrors the create-account and reset-admin-password
    flows elsewhere; the admin-typed escape hatch is a demo affordance
    that should be removed when real email invites land."""

    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    role: Literal["admin", "member"] = "member"
    temp_password: str | None = Field(default=None, min_length=6, max_length=128)


class InviteUserResponse(BaseModel):
    user: TeamMember
    # Plaintext returned once — the hash is the only thing persisted.
    temp_password: str


@router.post(
    "/users",
    response_model=InviteUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_user(
    payload: InviteUserRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_customer_admin)],
) -> InviteUserResponse:
    # Cross-org uniqueness check — users.email is globally unique, so we
    # 409 on any existing row, not just ones in this admin's org. Without
    # this pre-check the DB raises a generic IntegrityError on commit; the
    # explicit query gives us a typed 409.
    existing = (await session.execute(select(User.id).where(User.email == payload.email))).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a user with that email already exists",
        )

    temp_password = payload.temp_password or secrets.token_urlsafe(9)

    new_user = User(
        email=payload.email,
        password_hash=hash_password(temp_password),
        full_name=payload.full_name,
        role=_WIRE_TO_DB_ROLE[payload.role],
        org_id=admin.org_id,
        # Only the org's founding customer_admin is primary. Invited admins
        # are regular customer_admins; they can be removed by the primary.
        is_primary_admin=False,
    )
    session.add(new_user)
    try:
        await session.commit()
    except IntegrityError as exc:
        # Race fallback — pre-check above handles the common case.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a user with that email already exists",
        ) from exc

    # Re-read so `created_at` is populated from the server default.
    await session.refresh(new_user)

    return InviteUserResponse(
        user=TeamMember(
            id=str(new_user.id),
            email=new_user.email,
            full_name=new_user.full_name,
            role=payload.role,
            is_primary_admin=False,
            created_at=new_user.created_at,
        ),
        temp_password=temp_password,
    )


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_user(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_customer_admin)],
) -> Response:
    """Remove a teammate from this admin's org.

    Three invariants:
      - The target must exist in the admin's org (RLS handles cross-org;
        we return 404 on absence to avoid leaking existence of other orgs'
        user ids to anyone prodding this endpoint).
      - The primary admin is non-removable — this is the only way to
        ensure every org always has at least one admin account.
      - Self-delete is rejected. The primary admin wouldn't pass the
        first check anyway, but for invited customer_admins this stops
        them from accidentally locking themselves out.
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot remove yourself",
        )

    target = (
        await session.execute(select(User).where(User.id == user_id, User.org_id == admin.org_id))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user not found",
        )
    if target.is_primary_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot remove the primary administrator",
        )

    await session.delete(target)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- US-2.5 / US-2.6: app access ---------------------------------------


class AppAccessRow(BaseModel):
    """One row in the customer-admin App access page.

    Every known micro-app appears in the response — `subscribed` says
    whether the platform admin has provisioned it for this org;
    `enabled` says whether the customer admin has turned it on for
    their users. Apps without a subscription return `subscribed=false,
    enabled=false`; the UI renders them as "Available to purchase".
    """

    id: str
    subscribed: bool
    enabled: bool


@router.get("/apps", response_model=list[AppAccessRow])
async def list_apps(
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_customer_admin)],
) -> list[AppAccessRow]:
    stmt = select(AppSubscription).where(AppSubscription.org_id == admin.org_id)
    subs = {row.app_id: row for row in (await session.execute(stmt)).scalars().all()}
    # Always emit a row for every known app id (in catalog order) so the
    # frontend doesn't have to cross-reference against its own list.
    return [
        AppAccessRow(
            id=app_id,
            subscribed=app_id in subs,
            enabled=subs[app_id].enabled if app_id in subs else False,
        )
        for app_id in APP_IDS
    ]


class UpdateAppAccessRequest(BaseModel):
    enabled: bool


@router.patch("/apps/{app_id}", response_model=AppAccessRow)
async def update_app_access(
    app_id: str,
    payload: UpdateAppAccessRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_customer_admin)],
) -> AppAccessRow:
    """Toggle `enabled` on an existing subscription.

    Three rejections, in order:
      - Unknown app id → 400 (before any DB touch).
      - Attempt to disable ECV → 400 (foundational; platform-level invariant).
      - App not subscribed for this org → 404 (subscriptions are
        platform-admin-controlled; customer admin has no path to create
        them here — that's what the "Contact sales" button is for).
    """
    if app_id not in APP_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown app id: {app_id}",
        )
    if app_id == _REQUIRED_APP and not payload.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ECV is required and cannot be disabled",
        )

    sub = (
        await session.execute(
            select(AppSubscription).where(
                AppSubscription.org_id == admin.org_id,
                AppSubscription.app_id == app_id,
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="app is not subscribed for this organization",
        )

    sub.enabled = payload.enabled
    await session.commit()
    return AppAccessRow(id=sub.app_id, subscribed=True, enabled=sub.enabled)
