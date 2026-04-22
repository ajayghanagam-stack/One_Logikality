"""Title Search & Abstraction micro-app persistence — flags + property.

Two tables so the Title Search page (US-6.1) can hydrate from server
state:

- `title_flags`         — one row per risk finding (7 in the canned
                          seed). Carries severity, flag type, AI
                          recommendation, MISMO extractions, source
                          evidence, and optional cross-app reference.
- `title_properties`    — singleton per packet. Carries the entire
                          PROPERTY_SUMMARY shape (property ID, physical
                          attributes, chain of title, mortgages, liens,
                          easements, taxes, title insurance) as JSONB
                          because the UI consumes it as a nested
                          document — over-normalizing would just push
                          joins onto the API.

Both carry `org_id` and enable RLS with the same policy shape used by
the ECV / Compliance / Income tables.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels = None
depends_on = None


SEVERITIES = ("critical", "high", "medium", "low")
AI_DECISIONS = ("approve", "reject", "escalate")

_OWN_ORG = "org_id::text = COALESCE(current_setting('app.current_org_id', true), '')"
_IS_PLATFORM_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'"
_IS_CUSTOMER_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'customer_admin'"


def upgrade() -> None:
    op.create_table(
        "title_flags",
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
        # Stable per-packet ordinal (1..N). The demo keys flags by
        # integer id; we keep that as `flag_number` so deep links
        # (?flag=1) remain portable.
        sa.Column("flag_number", sa.Integer, nullable=False),
        sa.Column("severity", sa.String, nullable=False),
        # e.g. "Unreleased Mortgage", "Chain of Title Gap".
        sa.Column("flag_type", sa.String, nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        # Page reference as-shown, e.g. "p. 42, 78".
        sa.Column("page_ref", sa.String, nullable=False),
        sa.Column("ai_note", sa.Text, nullable=True),
        # AI recommendation (Phase 7 primitive surface).
        sa.Column("ai_rec_decision", sa.String, nullable=True),
        sa.Column("ai_rec_confidence", sa.Integer, nullable=True),
        sa.Column("ai_rec_reasoning", sa.Text, nullable=True),
        # MISMO 3.6 extractions: [{"entity", "field", "value", "confidence"}, ...]
        sa.Column("mismo_fields", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        # Source doc metadata: {"doc_type", "pages": [..]}.
        sa.Column("source", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        # Optional cross-app reference: {"app", "section", "note"} or NULL.
        sa.Column("cross_app", JSONB, nullable=True),
        # Evidence snippets: [{"page", "snippet"}, ...]
        sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN (" + ", ".join(f"'{s}'" for s in SEVERITIES) + ")",
            name="title_flags_severity_check",
        ),
        sa.CheckConstraint(
            "ai_rec_decision IS NULL OR ai_rec_decision IN ("
            + ", ".join(f"'{d}'" for d in AI_DECISIONS)
            + ")",
            name="title_flags_ai_decision_check",
        ),
        sa.CheckConstraint(
            "ai_rec_confidence IS NULL OR (ai_rec_confidence BETWEEN 0 AND 100)",
            name="title_flags_ai_confidence_range_check",
        ),
        sa.UniqueConstraint("packet_id", "flag_number", name="title_flags_packet_number_unique"),
    )
    op.create_index("ix_title_flags_packet", "title_flags", ["packet_id"])
    op.create_index("ix_title_flags_org", "title_flags", ["org_id"])

    op.create_table(
        "title_properties",
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
        # Full PROPERTY_SUMMARY shape as JSONB. Keys mirror the demo so
        # the frontend can render the Results / Property tabs without
        # translation: property_identification, physical_attributes,
        # lot_and_land, current_ownership, chain_of_title[],
        # mortgages[], liens[], easements[], restrictions[], taxes,
        # title_insurance.
        sa.Column("summary", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # One summary per packet — re-running the stub would otherwise
        # insert duplicates.
        sa.UniqueConstraint("packet_id", name="title_properties_packet_unique"),
    )
    op.create_index("ix_title_properties_packet", "title_properties", ["packet_id"])
    op.create_index("ix_title_properties_org", "title_properties", ["org_id"])

    for table in ("title_flags", "title_properties"):
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
    for table in ("title_properties", "title_flags"):
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_{suffix} ON {table}")

    op.drop_index("ix_title_properties_org", table_name="title_properties")
    op.drop_index("ix_title_properties_packet", table_name="title_properties")
    op.drop_table("title_properties")

    op.drop_index("ix_title_flags_org", table_name="title_flags")
    op.drop_index("ix_title_flags_packet", table_name="title_flags")
    op.drop_table("title_flags")
