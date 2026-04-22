"""Compliance micro-app persistence — checks + fee tolerance buckets.

Two tables so the Compliance page (US-6.3) can hydrate from server state
instead of hardcoded demo data:

- `compliance_checks`           — one row per regulatory check run against
                                  the packet (C-01 through C-10 in the
                                  canned seed). Carries status (pass /
                                  fail / warn / n/a), category, rule
                                  citation, detail narrative, optional AI
                                  note, and a JSONB bag of MISMO
                                  extractions feeding Phase 7 primitives.
- `compliance_fee_tolerances`   — one row per TRID tolerance bucket (Zero
                                  / 10% / Unlimited) with LE vs CD
                                  numbers and the computed variance.

Both carry `org_id` and enable RLS with the same policy shape used by the
ECV tables (migration 0008) — reads are org-scoped, writes happen from
the server-internal pipeline stub (bypasses RLS via the default postgres
connection).

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels = None
depends_on = None


CHECK_STATUSES = ("pass", "fail", "warn", "n/a")
TOLERANCE_STATUSES = ("pass", "fail", "warn")

_OWN_ORG = "org_id::text = COALESCE(current_setting('app.current_org_id', true), '')"
_IS_PLATFORM_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'"
_IS_CUSTOMER_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'customer_admin'"


def upgrade() -> None:
    op.create_table(
        "compliance_checks",
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
        sa.Column(
            "org_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Human-facing code, e.g. "C-01". Unique per packet so the UI can
        # anchor ?check=C-01 links when the review dialog lands.
        sa.Column("check_code", sa.String, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("rule", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
        # AI compliance-officer note (Phase 7 primitive). NULL when the
        # check passes cleanly with nothing interesting to call out.
        sa.Column("ai_note", sa.Text, nullable=True),
        # MISMO 3.6 extractions supporting the check. Shape:
        # [{"entity": ..., "field": ..., "value": ..., "confidence": int}, ...]
        sa.Column("mismo_fields", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in CHECK_STATUSES) + ")",
            name="compliance_checks_status_check",
        ),
        sa.UniqueConstraint("packet_id", "check_code", name="compliance_checks_packet_code_unique"),
    )
    op.create_index("ix_compliance_checks_packet", "compliance_checks", ["packet_id"])
    op.create_index("ix_compliance_checks_org", "compliance_checks", ["org_id"])

    op.create_table(
        "compliance_fee_tolerances",
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
        sa.Column(
            "org_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Bucket label as it appears in the demo: "Zero tolerance (0%)",
        # "10% tolerance", "Unlimited tolerance". Unique per packet.
        sa.Column("bucket", sa.String, nullable=False),
        # Currency strings preserved as the demo shows them ("$4,200.00").
        # Keeping strings avoids repeated format roundtrips and matches
        # the wire shape the frontend renders directly.
        sa.Column("le_amount", sa.String, nullable=False),
        sa.Column("cd_amount", sa.String, nullable=False),
        sa.Column("diff_amount", sa.String, nullable=False),
        sa.Column("variance_pct", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        # Display order so the table renders deterministically regardless
        # of insertion timing. Matches demo: Zero → 10% → Unlimited.
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in TOLERANCE_STATUSES) + ")",
            name="compliance_fee_tolerances_status_check",
        ),
        sa.UniqueConstraint(
            "packet_id", "bucket", name="compliance_fee_tolerances_packet_bucket_unique"
        ),
    )
    op.create_index(
        "ix_compliance_fee_tolerances_packet", "compliance_fee_tolerances", ["packet_id"]
    )
    op.create_index("ix_compliance_fee_tolerances_org", "compliance_fee_tolerances", ["org_id"])

    for table in ("compliance_checks", "compliance_fee_tolerances"):
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
                WITH CHECK ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG}))
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
    for table in ("compliance_fee_tolerances", "compliance_checks"):
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_{suffix} ON {table}")

    op.drop_index("ix_compliance_fee_tolerances_org", table_name="compliance_fee_tolerances")
    op.drop_index("ix_compliance_fee_tolerances_packet", table_name="compliance_fee_tolerances")
    op.drop_table("compliance_fee_tolerances")

    op.drop_index("ix_compliance_checks_org", table_name="compliance_checks")
    op.drop_index("ix_compliance_checks_packet", table_name="compliance_checks")
    op.drop_table("compliance_checks")
