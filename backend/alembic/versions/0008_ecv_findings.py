"""ECV dashboard persistence — sections, line items, document inventory.

Three tables so the ECV dashboard (US-3.5 – 3.10, 3.13) can hydrate from
server state instead of hardcoded demo data:

- `ecv_sections`        — the 13 weighted validation sections per packet.
- `ecv_line_items`      — ~58 per-check rows (confidence, result text,
                          plus MISMO path + document/page refs so
                          Phase 7 primitives can land without another
                          migration).
- `ecv_documents`       — the 25 MISMO-tagged doc inventory rows (found /
                          missing, per-page issues).

All three carry `org_id` and enable RLS with the same policy shape used by
`packets` in migration 0006 — reads are org-scoped, platform_admin can
read across, customer roles can only read their own org's rows. Writes
happen from the deterministic ECV stub (background task; bypasses RLS
via the default postgres connection) so we don't need permissive INSERT
policies for customer roles.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels = None
depends_on = None


DOC_STATUSES = ("found", "missing")
PAGE_ISSUE_TYPES = ("blank_page", "low_quality", "rotated")

_OWN_ORG = "org_id::text = COALESCE(current_setting('app.current_org_id', true), '')"
_IS_PLATFORM_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'"
_IS_CUSTOMER_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'customer_admin'"


def upgrade() -> None:
    op.create_table(
        "ecv_sections",
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
        sa.Column("section_number", sa.Integer, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("weight", sa.Integer, nullable=False),
        # Numeric(5,2) gives us 0.00–999.99 which is plenty for 0–100 scores.
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "packet_id", "section_number", name="ecv_sections_packet_section_unique"
        ),
    )
    op.create_index("ix_ecv_sections_packet", "ecv_sections", ["packet_id"])
    op.create_index("ix_ecv_sections_org", "ecv_sections", ["org_id"])

    op.create_table(
        "ecv_documents",
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
        sa.Column("doc_number", sa.Integer, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("mismo_type", sa.String, nullable=False),
        # Human-facing page range, e.g. "15–16" or "—" for missing docs.
        sa.Column("pages_display", sa.String, nullable=False),
        sa.Column("page_count", sa.Integer, nullable=False),
        sa.Column("confidence", sa.Integer, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        # Page-quality issue (if any). Demo surfaces three types.
        sa.Column("page_issue_type", sa.String, nullable=True),
        sa.Column("page_issue_detail", sa.String, nullable=True),
        sa.Column("page_issue_affected_page", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in DOC_STATUSES) + ")",
            name="ecv_documents_status_check",
        ),
        sa.CheckConstraint(
            "page_issue_type IS NULL OR page_issue_type IN ("
            + ", ".join(f"'{t}'" for t in PAGE_ISSUE_TYPES)
            + ")",
            name="ecv_documents_page_issue_type_check",
        ),
        sa.UniqueConstraint("packet_id", "doc_number", name="ecv_documents_packet_doc_unique"),
    )
    op.create_index("ix_ecv_documents_packet", "ecv_documents", ["packet_id"])
    op.create_index("ix_ecv_documents_org", "ecv_documents", ["org_id"])

    op.create_table(
        "ecv_line_items",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "section_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("ecv_sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Denormalized so queries don't need to join sections to filter by
        # packet, and so RLS can scope off org_id without a join.
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
        # Human code, e.g. "1.1" — unique per packet so the UI can anchor
        # ?check=1.1 links once Phase 7 evidence panel lands.
        sa.Column("item_code", sa.String, nullable=False),
        sa.Column("check_description", sa.String, nullable=False),
        sa.Column("result_text", sa.String, nullable=False),
        sa.Column("confidence", sa.Integer, nullable=False),
        # Phase 7 extensibility — stubbed NULL today, but here so the
        # evidence panel (US-7.4) and MISMO panel (US-7.3) can hydrate
        # without a schema change.
        sa.Column("mismo_path", sa.String, nullable=True),
        sa.Column(
            "document_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("ecv_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("page_refs", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("packet_id", "item_code", name="ecv_line_items_packet_item_unique"),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="ecv_line_items_confidence_range_check",
        ),
    )
    op.create_index("ix_ecv_line_items_section", "ecv_line_items", ["section_id"])
    op.create_index("ix_ecv_line_items_packet", "ecv_line_items", ["packet_id"])
    op.create_index("ix_ecv_line_items_org", "ecv_line_items", ["org_id"])

    # RLS: same shape as packets (migration 0006). Reads are org-scoped;
    # writes only come from the server-internal ECV stub (which connects
    # as postgres superuser and bypasses RLS), so customer-role writes
    # aren't needed. We still permit customer_admin/platform_admin
    # delete/update in case a future slice needs to re-score a packet
    # under request context.
    for table in ("ecv_sections", "ecv_documents", "ecv_line_items"):
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
    for table in ("ecv_line_items", "ecv_documents", "ecv_sections"):
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_{suffix} ON {table}")

    op.drop_index("ix_ecv_line_items_org", table_name="ecv_line_items")
    op.drop_index("ix_ecv_line_items_packet", table_name="ecv_line_items")
    op.drop_index("ix_ecv_line_items_section", table_name="ecv_line_items")
    op.drop_table("ecv_line_items")

    op.drop_index("ix_ecv_documents_org", table_name="ecv_documents")
    op.drop_index("ix_ecv_documents_packet", table_name="ecv_documents")
    op.drop_table("ecv_documents")

    op.drop_index("ix_ecv_sections_org", table_name="ecv_sections")
    op.drop_index("ix_ecv_sections_packet", table_name="ecv_sections")
    op.drop_table("ecv_sections")
