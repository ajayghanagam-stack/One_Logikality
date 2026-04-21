"""Add app_subscriptions — which micro-apps each customer org has paid for.

Pulls the subscription persistence primitives from US-2.5 forward because
US-1.6 now lets the platform admin pick subscribed apps at create time
(to match the demo's onboarding form). Keeping row-existence as the
subscribed signal lets US-2.5 finish the "enablement" story by flipping
the `enabled` column without another migration.

Row-level security mirrors the pattern in 0001: platform admins can
CRUD anything, customer roles can read (and, in US-2.6, update `enabled`)
only within their own tenant. Customer roles cannot insert new rows —
subscribing is platform-admin-controlled.

Revision ID: 0003_app_subscriptions
Revises: 0002_org_slug
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


# Source of truth for known app ids — kept in lockstep with backend/app/models.py::APP_IDS
# and frontend/lib/apps.ts. The CHECK constraint rejects unknown ids at the DB layer as a
# belt-and-suspenders guard against drift.
APP_IDS = ("ecv", "title-search", "title-exam", "compliance", "income-calc")


def upgrade() -> None:
    op.create_table(
        "app_subscriptions",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("app_id", sa.String, nullable=False),
        # Customer-admin toggle — US-2.6 wires the UI. Defaults true so
        # newly created subscriptions are usable immediately.
        sa.Column(
            "enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("org_id", "app_id", name="app_subscriptions_org_app_unique"),
        sa.CheckConstraint(
            "app_id IN (" + ", ".join(f"'{a}'" for a in APP_IDS) + ")",
            name="app_subscriptions_app_id_check",
        ),
    )
    op.create_index("ix_app_subscriptions_org_id", "app_subscriptions", ["org_id"])

    # Same RLS pattern as `orgs` / `users`. Platform admin has full access;
    # customer roles see only their own org's rows. Customer INSERT is
    # blocked by the WITH CHECK (platform-admin only) — subscriptions are
    # platform-admin-controlled per the three-persona model.
    op.execute("ALTER TABLE app_subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app_subscriptions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY app_subscriptions_tenant_isolation ON app_subscriptions
            USING (
                COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'
                OR org_id::text = COALESCE(current_setting('app.current_org_id', true), '')
            )
            WITH CHECK (
                COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'
            )
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON app_subscriptions TO app_user")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS app_subscriptions_tenant_isolation ON app_subscriptions")
    op.drop_index("ix_app_subscriptions_org_id", table_name="app_subscriptions")
    op.drop_table("app_subscriptions")
