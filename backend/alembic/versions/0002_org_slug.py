"""Add orgs.slug — URL-friendly identifier used in customer portal paths.

Every customer-scoped route is `/{org_slug}/*`; platform-admin routes live
under the reserved literal segment `/logikality/*`. The `logikality` slug
must never be assigned to a customer org — Phase 1.6's create-customer
flow enforces this, and the app-level reservation check should go there.

Migration strategy (safe if rows already exist):
  1. ADD COLUMN slug VARCHAR NULL
  2. Backfill the seeded "Acme Mortgage Holdings" org with slug='acme'
  3. ALTER COLUMN slug SET NOT NULL + add UNIQUE constraint + CHECK shape

Revision ID: 0002_org_slug
Revises: 0001_auth_multitenant_spine
"""

from __future__ import annotations

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add nullable column so existing rows are valid during backfill.
    op.execute("ALTER TABLE orgs ADD COLUMN slug VARCHAR")

    # 2. Backfill the seeded Acme org. New orgs created by Phase 1.6 will
    #    supply their own slug, so no generic fallback is needed.
    op.execute("UPDATE orgs SET slug = 'acme' WHERE name = 'Acme Mortgage Holdings'")

    # 3. Lock down shape. NOT NULL + UNIQUE enforces "every org has exactly
    #    one routable slug". The CHECK keeps slugs URL-safe and rejects the
    #    reserved `logikality` literal (which routes platform admin).
    op.execute("ALTER TABLE orgs ALTER COLUMN slug SET NOT NULL")
    op.execute("CREATE UNIQUE INDEX ix_orgs_slug ON orgs (slug)")
    op.execute(
        "ALTER TABLE orgs ADD CONSTRAINT orgs_slug_shape_check "
        "CHECK (slug ~ '^[a-z0-9][a-z0-9-]*$' AND slug <> 'logikality')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE orgs DROP CONSTRAINT IF EXISTS orgs_slug_shape_check")
    op.execute("DROP INDEX IF EXISTS ix_orgs_slug")
    op.execute("ALTER TABLE orgs DROP COLUMN IF EXISTS slug")
