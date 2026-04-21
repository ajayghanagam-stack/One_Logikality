"""Add packets + packet_files — document packets uploaded for ECV processing.

One `packets` row per user-initiated upload, with its declared loan
program baked in so rule resolution at processing time is stable even
if the org's config changes mid-flight. One `packet_files` row per
uploaded document — the storage layer holds the actual bytes; this
table just keeps the filename/size/content-type + a storage key so the
pipeline knows where to fetch from.

Any authenticated customer role can upload; reads are org-scoped.
Deletes are restricted to the uploader's own admin (and platform
admin) so a customer_user can't walk away with another user's upload.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None


# Mirrored from app/rules/catalog.py::LOAN_PROGRAM_IDS. Migrations
# shouldn't import runtime code (schema changes shouldn't depend on the
# current app's import graph), and changes to this list require a new
# migration anyway.
PROGRAM_IDS = ("conventional", "jumbo", "fha", "va", "usda", "nonqm")

PACKET_STATUSES = ("uploaded", "processing", "completed", "failed")

_OWN_ORG = "org_id::text = COALESCE(current_setting('app.current_org_id', true), '')"
_IS_PLATFORM_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'"
_IS_CUSTOMER_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'customer_admin'"
_IS_CUSTOMER_ROLE = (
    "COALESCE(current_setting('app.current_role', true), '') IN ('customer_admin', 'customer_user')"
)


def upgrade() -> None:
    op.create_table(
        "packets",
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
        sa.Column("declared_program_id", sa.String, nullable=False),
        sa.Column(
            "status",
            sa.String,
            nullable=False,
            server_default=sa.text("'uploaded'"),
        ),
        sa.Column(
            "created_by",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "declared_program_id IN (" + ", ".join(f"'{p}'" for p in PROGRAM_IDS) + ")",
            name="packets_program_check",
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in PACKET_STATUSES) + ")",
            name="packets_status_check",
        ),
    )
    op.create_index("ix_packets_org_created", "packets", ["org_id", "created_at"])

    op.create_table(
        "packet_files",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "packet_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("packets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Denormalized so the RLS policy can scope without joining packets.
        sa.Column(
            "org_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("content_type", sa.String, nullable=False),
        # Storage key relative to the storage adapter's base path — e.g.
        # `packets/<org_id>/<packet_id>/<file_id>__filename.pdf`. Unique
        # because the packet_id + file_id suffix keeps them from colliding.
        sa.Column("storage_key", sa.String, nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_packet_files_packet", "packet_files", ["packet_id"])
    op.create_index("ix_packet_files_org", "packet_files", ["org_id"])

    # RLS: reads are org-scoped for any role; platform_admin reads anywhere.
    # Writes: customer roles can insert on own org (customer_user uploads
    # packets too, per demo). Updates/deletes restricted to customer_admin
    # or platform_admin so a customer_user can't walk away with their own
    # upload after submission.
    for table in ("packets", "packet_files"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

        op.execute(
            f"""
            CREATE POLICY {table}_select ON {table}
                FOR SELECT USING ({_IS_PLATFORM_ADMIN} OR {_OWN_ORG})
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_insert ON {table}
                FOR INSERT
                WITH CHECK ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ROLE} AND {_OWN_ORG}))
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_update ON {table}
                FOR UPDATE
                USING ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG}))
                WITH CHECK ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG}))
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_delete ON {table}
                FOR DELETE
                USING ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG}))
            """
        )

        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_user")


def downgrade() -> None:
    for table in ("packet_files", "packets"):
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_{suffix} ON {table}")
    op.drop_index("ix_packet_files_org", table_name="packet_files")
    op.drop_index("ix_packet_files_packet", table_name="packet_files")
    op.drop_table("packet_files")
    op.drop_index("ix_packets_org_created", table_name="packets")
    op.drop_table("packets")
