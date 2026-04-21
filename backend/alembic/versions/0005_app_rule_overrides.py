"""Add app_rule_overrides — customer-admin organization-level rule overrides.

US-4.2 lets the customer admin customize rule values per loan program;
these persist as (org_id, program_id, rule_key) → value rows. Value is
JSONB because the resolver handles str/int/float/bool uniformly; a
single column avoids an enum-of-types discriminator.

Per-command RLS policies match the split we settled on for
app_subscriptions in 0004:
  - SELECT: platform_admin OR own-org (customer roles can read — the
    `ConfigApplied` badge reads this on pages customer_user can see).
  - INSERT / UPDATE / DELETE: platform_admin OR customer_admin on own org.
    Customer users are not permitted to change configuration.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


# Source-of-truth tuple mirrored from app/rules/catalog.py::LOAN_PROGRAM_IDS.
# Duplicated here because migrations shouldn't import runtime code (that
# would make a schema change contingent on the current app's import
# graph). Changes to the program list require a new migration anyway.
PROGRAM_IDS = ("conventional", "jumbo", "fha", "va", "usda", "nonqm")

_OWN_ORG = "org_id::text = COALESCE(current_setting('app.current_org_id', true), '')"
_IS_PLATFORM_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'"
_IS_CUSTOMER_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'customer_admin'"


def upgrade() -> None:
    op.create_table(
        "app_rule_overrides",
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
        sa.Column("program_id", sa.String, nullable=False),
        # Opaque string — validated against MICRO_APP_RULES at the API layer.
        # Not constrained at the DB layer because rule keys can be added
        # without a migration (new micro-app rules ship with a code change
        # and app version bump, not a schema change).
        sa.Column("rule_key", sa.String, nullable=False),
        # JSONB lets us store str / int / float / bool under one column.
        # Resolver treats everything as RuleValue union.
        sa.Column("value", JSONB, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "org_id",
            "program_id",
            "rule_key",
            name="app_rule_overrides_org_program_rule_unique",
        ),
        sa.CheckConstraint(
            "program_id IN (" + ", ".join(f"'{p}'" for p in PROGRAM_IDS) + ")",
            name="app_rule_overrides_program_check",
        ),
    )
    op.create_index(
        "ix_app_rule_overrides_org_program",
        "app_rule_overrides",
        ["org_id", "program_id"],
    )

    op.execute("ALTER TABLE app_rule_overrides ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app_rule_overrides FORCE ROW LEVEL SECURITY")

    # SELECT: platform admin or own-org (any customer role). The
    # `ConfigApplied` badge is visible to customer_user on packet screens
    # — reading is fine; only writes are admin-gated.
    op.execute(
        f"""
        CREATE POLICY app_rule_overrides_select ON app_rule_overrides
            FOR SELECT USING ({_IS_PLATFORM_ADMIN} OR {_OWN_ORG})
        """
    )

    # INSERT/UPDATE/DELETE: platform_admin anywhere, customer_admin only
    # on own org. WITH CHECK mirrors USING so a customer_admin can't
    # pivot a row to another org by changing org_id.
    op.execute(
        f"""
        CREATE POLICY app_rule_overrides_insert ON app_rule_overrides
            FOR INSERT
            WITH CHECK ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG}))
        """
    )
    op.execute(
        f"""
        CREATE POLICY app_rule_overrides_update ON app_rule_overrides
            FOR UPDATE
            USING ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG}))
            WITH CHECK ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG}))
        """
    )
    op.execute(
        f"""
        CREATE POLICY app_rule_overrides_delete ON app_rule_overrides
            FOR DELETE
            USING ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG}))
        """
    )

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON app_rule_overrides TO app_user")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS app_rule_overrides_select ON app_rule_overrides")
    op.execute("DROP POLICY IF EXISTS app_rule_overrides_insert ON app_rule_overrides")
    op.execute("DROP POLICY IF EXISTS app_rule_overrides_update ON app_rule_overrides")
    op.execute("DROP POLICY IF EXISTS app_rule_overrides_delete ON app_rule_overrides")
    op.drop_index("ix_app_rule_overrides_org_program", table_name="app_rule_overrides")
    op.drop_table("app_rule_overrides")
