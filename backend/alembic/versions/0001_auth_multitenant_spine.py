"""auth + multi-tenant spine

Creates the `orgs` and `users` tables, the three-role check constraint, and
enables Postgres RLS keyed on `app.current_org_id` / `app.current_user_id` /
`app.current_role`. See docs/Plan.md Step 1 and app/db.py for how handlers
set these session variables.

Revision ID: 0001
Revises:
Create Date: 2026-04-20
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


# Kept in sync with app/models.py::ORG_TYPES / USER_ROLES.
ORG_TYPES = ("Mortgage Lender", "Loan Servicer", "Title Agency", "Mortgage BPO")
USER_ROLES = ("platform_admin", "customer_admin", "customer_user")


def _in_list(col: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{col} IN ({quoted})"


def upgrade() -> None:
    # pgcrypto provides gen_random_uuid(); available on stock postgres:16.
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # A non-superuser role so RLS is actually enforced. Superusers always
    # bypass RLS, so the runtime must connect as postgres and then
    # `SET LOCAL ROLE app_user` in each request-scoped transaction (see
    # app/db.py::set_tenant_context). Migrations and the seed script stay
    # as postgres so they can create/seed unrestricted.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
                CREATE ROLE app_user NOINHERIT NOBYPASSRLS;
            END IF;
        END
        $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO app_user")

    op.create_table(
        "orgs",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="orgs_name_unique"),
        sa.CheckConstraint(_in_list("type", ORG_TYPES), name="orgs_type_check"),
    )

    op.create_table(
        "users",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String, nullable=False),
        sa.Column("password_hash", sa.String, nullable=False),
        sa.Column("full_name", sa.String, nullable=False),
        sa.Column("role", sa.String, nullable=False),
        sa.Column(
            "org_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "is_primary_admin",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="users_email_unique"),
        sa.CheckConstraint(_in_list("role", USER_ROLES), name="users_role_check"),
        sa.CheckConstraint(
            "(role = 'platform_admin' AND org_id IS NULL) "
            "OR (role IN ('customer_admin', 'customer_user') AND org_id IS NOT NULL)",
            name="users_role_org_consistency",
        ),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])

    # ---- Row-Level Security ----
    # FORCE RLS applies the policies even to the table owner (the postgres role
    # we connect as locally). Migrations themselves are DDL-only so they are
    # unaffected; DML in the seed script and at runtime must either be run as
    # a session with `app.current_role = 'platform_admin'` or match the tenant
    # policy.
    _enable_rls("orgs")
    op.execute(
        """
        CREATE POLICY orgs_tenant_isolation ON orgs
            USING (
                COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'
                OR id::text = COALESCE(current_setting('app.current_org_id', true), '')
            )
            WITH CHECK (
                COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'
            )
        """
    )

    _enable_rls("users")
    op.execute(
        """
        CREATE POLICY users_tenant_isolation ON users
            USING (
                COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'
                OR id::text = COALESCE(current_setting('app.current_user_id', true), '')
                OR org_id::text = COALESCE(current_setting('app.current_org_id', true), '')
            )
            WITH CHECK (
                COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'
                OR org_id::text = COALESCE(current_setting('app.current_org_id', true), '')
            )
        """
    )

    # Grant DML to app_user on every table created above. Future migrations
    # that add tenant-scoped tables must repeat this grant.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON orgs, users TO app_user")


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_tenant_isolation ON users")
    op.execute("DROP POLICY IF EXISTS orgs_tenant_isolation ON orgs")
    op.drop_index("ix_users_org_id", table_name="users")
    op.drop_table("users")
    op.drop_table("orgs")
    # Leave the app_user role in place; dropping it across re-runs of
    # upgrade/downgrade is noisy and it can be reused by future migrations.
