"""ORM models for the auth / multi-tenant spine.

Two tables — `orgs` and `users` — plus their check constraints. Every
tenant-scoped table added later MUST carry `org_id UUID NOT NULL REFERENCES
orgs(id) ON DELETE CASCADE` and enable RLS with the same policy shape used
in the initial migration. Platform admins are modeled as users with
`role = 'platform_admin'` and `org_id = NULL` — they aren't scoped to a
customer organization.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base

# Kept as tuples of literals so the same values are used by the migration,
# the model-level CHECK constraints, and any Python-side validation.
ORG_TYPES: tuple[str, ...] = (
    "Mortgage Lender",
    "Loan Servicer",
    "Title Agency",
    "Mortgage BPO",
)

USER_ROLES: tuple[str, ...] = (
    "platform_admin",
    "customer_admin",
    "customer_user",
)

# Known micro-app ids — in lockstep with migration 0003's CHECK constraint
# and frontend/lib/apps.ts. ECV is foundational (every org must subscribe);
# the others are à la carte. The demo uses the same ids so reference
# material stays directly comparable.
APP_IDS: tuple[str, ...] = (
    "ecv",
    "title-search",
    "title-exam",
    "compliance",
    "income-calc",
)


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # URL-friendly identifier used by the customer portal at /{slug}/*.
    # Uniqueness + shape + the reserved `logikality` exclusion are enforced
    # in the 0002 migration (constraint `orgs_slug_shape_check`).
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    users: Mapped[list[User]] = relationship(back_populates="org")

    __table_args__ = (
        CheckConstraint(
            "type IN (" + ", ".join(f"'{t}'" for t in ORG_TYPES) + ")",
            name="orgs_type_check",
        ),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    # NULL for platform_admin users; enforced by users_role_org_consistency below.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    is_primary_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    org: Mapped[Org | None] = relationship(back_populates="users")

    __table_args__ = (
        CheckConstraint(
            "role IN (" + ", ".join(f"'{r}'" for r in USER_ROLES) + ")",
            name="users_role_check",
        ),
        # Platform admins aren't scoped to an org; customer roles always are.
        CheckConstraint(
            "(role = 'platform_admin' AND org_id IS NULL) "
            "OR (role IN ('customer_admin', 'customer_user') AND org_id IS NOT NULL)",
            name="users_role_org_consistency",
        ),
    )


class AppSubscription(Base):
    """Which micro-apps a customer org has been subscribed to.

    Row-existence = subscribed. The `enabled` column is the customer-admin
    toggle (US-2.6) — subscriptions the org has paid for but temporarily
    disabled still exist as rows with `enabled = false`. Unique
    `(org_id, app_id)` prevents duplicate subscriptions.
    """

    __tablename__ = "app_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    app_id: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("org_id", "app_id", name="app_subscriptions_org_app_unique"),
        CheckConstraint(
            "app_id IN (" + ", ".join(f"'{a}'" for a in APP_IDS) + ")",
            name="app_subscriptions_app_id_check",
        ),
    )
