"""Platform-admin API — customer-account management (US-1.5 onward).

Mounted under `/api/logikality/*` to mirror the reserved `/logikality/*`
route segment in the frontend. Every handler depends on
`require_platform_admin`, which chains `get_current_user` (so the RLS
tenant context is already installed) and then enforces the role — so
the queries below run under `app.current_role = 'platform_admin'` and
the policies in migration 0001 let them see every org/user row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require_platform_admin
from app.models import Org, User

router = APIRouter(prefix="/api/logikality", tags=["logikality"])


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
