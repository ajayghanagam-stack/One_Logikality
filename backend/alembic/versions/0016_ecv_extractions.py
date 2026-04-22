"""M3 — persist real MISMO 3.6 field extractions with evidence.

Adds `ecv_extractions`: one row per (document, MISMO path) pair. Populated
by the Vertex AI Gemini Pro extraction stage per M3 of the ECV pipeline
build-out. Each row carries the value the model read out of the page plus
the evidence snippet + page number so the MISMO panel (US-7.3) and
evidence panel (US-7.4) can render real data instead of canned strings.

Shape chosen so future-us can:
- Re-run extraction on a packet without managing an upsert — we DELETE
  all extractions for the packet first, then bulk INSERT.
- Feed downstream micro-apps (compliance, income, title) from a single
  source of truth rather than splitting real data across each app's
  JSONB columns.

RLS policies match the same shape used for `ecv_documents` / `ecv_line_items`
in migration 0008 — platform_admin reads across, customer roles read their
own org only. Writes come from the server-internal ECV pipeline connecting
as postgres superuser (bypassing RLS by design).

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels = None
depends_on = None


_OWN_ORG = "org_id::text = COALESCE(current_setting('app.current_org_id', true), '')"
_IS_PLATFORM_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'"
_IS_CUSTOMER_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'customer_admin'"


def upgrade() -> None:
    op.create_table(
        "ecv_extractions",
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
        # SET NULL rather than CASCADE so re-classifying a packet (which
        # rewrites `ecv_documents` rows) doesn't silently delete the
        # extractions; callers decide whether to keep or re-extract.
        sa.Column(
            "document_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("ecv_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Full dotted MISMO 3.6 path, e.g.
        # "DEAL.LOANS.LOAN[1].TERMS_OF_LOAN.LoanAmount". Kept as a plain
        # string rather than split into parts so the path is preserved
        # exactly as Gemini emits it.
        sa.Column("mismo_path", sa.String, nullable=False),
        # Convenience splits — the UI groups extractions by entity and
        # shows entity.field. Denormalized to avoid string-slicing in the
        # frontend.
        sa.Column("entity", sa.String, nullable=False),
        sa.Column("field", sa.String, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("confidence", sa.Integer, nullable=False),
        sa.Column("page_number", sa.Integer, nullable=True),
        sa.Column("snippet", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="ecv_extractions_confidence_range_check",
        ),
    )
    op.create_index("ix_ecv_extractions_packet", "ecv_extractions", ["packet_id"])
    op.create_index("ix_ecv_extractions_org", "ecv_extractions", ["org_id"])
    op.create_index("ix_ecv_extractions_document", "ecv_extractions", ["document_id"])

    op.execute("ALTER TABLE ecv_extractions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ecv_extractions FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY ecv_extractions_select ON ecv_extractions
            FOR SELECT USING ({_IS_PLATFORM_ADMIN} OR {_OWN_ORG})
        """
    )
    op.execute(
        f"""
        CREATE POLICY ecv_extractions_insert ON ecv_extractions
            FOR INSERT
            WITH CHECK ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG}))
        """
    )
    op.execute(
        f"""
        CREATE POLICY ecv_extractions_update ON ecv_extractions
            FOR UPDATE
            USING ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG}))
            WITH CHECK ({_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG}))
        """
    )
    op.execute(
        """
        CREATE POLICY ecv_extractions_delete ON ecv_extractions
            FOR DELETE
            USING ("""
        + f"{_IS_PLATFORM_ADMIN} OR ({_IS_CUSTOMER_ADMIN} AND {_OWN_ORG})"
        + ")"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ecv_extractions TO app_user")


def downgrade() -> None:
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS ecv_extractions_{suffix} ON ecv_extractions")
    op.drop_index("ix_ecv_extractions_document", table_name="ecv_extractions")
    op.drop_index("ix_ecv_extractions_org", table_name="ecv_extractions")
    op.drop_index("ix_ecv_extractions_packet", table_name="ecv_extractions")
    op.drop_table("ecv_extractions")
