"""Let customer admins UPDATE their own org's app_subscriptions rows.

Migration 0003 encoded "subscriptions are platform-admin-controlled" as a
single RLS policy: SELECT filtered by org, every write gated on
`platform_admin`. That was too coarse — US-2.6 asks the customer admin
to flip `enabled` on their own subscriptions, which the single-policy
encoding blocks with an `InsufficientPrivilegeError`.

Fix: replace the combined policy with per-command policies. SELECT + UPDATE
let customer admins act on their own org; INSERT + DELETE remain
platform-admin-only so customer admins can't provision themselves new
subscriptions or delete paid rows. Customer users aren't mentioned on
UPDATE — only customer_admin can flip the enablement flag.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None

_OWN_ORG = "org_id::text = COALESCE(current_setting('app.current_org_id', true), '')"
_IS_PLATFORM_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'"
_IS_CUSTOMER_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'customer_admin'"


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS app_subscriptions_tenant_isolation ON app_subscriptions")

    # SELECT: platform admin sees all; customer roles see their org's rows.
    # Matches the tenant-visibility story used for `orgs` / `users`.
    op.execute(
        f"""
        CREATE POLICY app_subscriptions_select ON app_subscriptions
            FOR SELECT USING ({_IS_PLATFORM_ADMIN} OR {_OWN_ORG})
        """
    )

    # INSERT/DELETE: platform admin only. Customer admins contact sales to
    # add/remove subscriptions; they don't mint rows themselves.
    op.execute(
        f"""
        CREATE POLICY app_subscriptions_insert ON app_subscriptions
            FOR INSERT WITH CHECK ({_IS_PLATFORM_ADMIN})
        """
    )
    op.execute(
        f"""
        CREATE POLICY app_subscriptions_delete ON app_subscriptions
            FOR DELETE USING ({_IS_PLATFORM_ADMIN})
        """
    )

    # UPDATE: platform admin can update anything; customer_admin can update
    # rows in their own org (the only thing the app changes on UPDATE is
    # `enabled`). WITH CHECK mirrors USING so an admin can't pivot a row
    # onto another org by changing `org_id`.
    op.execute(
        f"""
        CREATE POLICY app_subscriptions_update ON app_subscriptions
            FOR UPDATE
            USING ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG}))
            WITH CHECK ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG}))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS app_subscriptions_select ON app_subscriptions")
    op.execute("DROP POLICY IF EXISTS app_subscriptions_insert ON app_subscriptions")
    op.execute("DROP POLICY IF EXISTS app_subscriptions_delete ON app_subscriptions")
    op.execute("DROP POLICY IF EXISTS app_subscriptions_update ON app_subscriptions")
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
