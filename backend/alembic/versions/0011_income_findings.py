"""Income Calculation micro-app persistence — sources + DTI items.

Two tables so the Income Calculation page (US-6.4) can hydrate from
server state:

- `income_sources`      — one row per income source (base / overtime /
                          bonus / rental). Carries monthly + annual
                          amounts, trend, confidence, supporting docs,
                          optional AI note, and MISMO extractions.
- `income_dti_items`    — one row per monthly obligation feeding the
                          debt-to-income ratio (PITIA + each debt).

Both carry `org_id` and enable RLS with the same policy shape used by
the ECV + Compliance tables — reads are org-scoped, writes happen from
the server-internal pipeline stub.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels = None
depends_on = None


TRENDS = ("stable", "increasing", "decreasing")

_OWN_ORG = "org_id::text = COALESCE(current_setting('app.current_org_id', true), '')"
_IS_PLATFORM_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'"
_IS_CUSTOMER_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'customer_admin'"


def upgrade() -> None:
    op.create_table(
        "income_sources",
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
        # Human-facing code, e.g. "I-01". Unique per packet.
        sa.Column("source_code", sa.String, nullable=False),
        sa.Column("source_name", sa.String, nullable=False),
        # Employer is NULL for non-employment income (rental, etc.).
        sa.Column("employer", sa.String, nullable=True),
        sa.Column("position", sa.String, nullable=True),
        sa.Column("income_type", sa.String, nullable=False),  # "W-2", "1040 Sch E", etc.
        # Currency as NUMERIC so aggregation (total monthly, total annual)
        # stays exact on the server side; the frontend formats with commas.
        sa.Column("monthly_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("annual_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("trend", sa.String, nullable=False),
        # Years of documented history (e.g., 6.2 years on base).
        sa.Column("years_history", sa.Numeric(4, 1), nullable=False),
        sa.Column("confidence", sa.Integer, nullable=False),
        sa.Column("ai_note", sa.Text, nullable=True),
        # MISMO 3.6 extractions — list of
        # {"entity": ..., "field": ..., "value": ..., "confidence": int}.
        sa.Column("mismo_fields", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        # Supporting docs: array of strings (display names used by the
        # expanded row "Docs" column).
        sa.Column("docs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        # Display order so the sources tab renders deterministically.
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "trend IN (" + ", ".join(f"'{t}'" for t in TRENDS) + ")",
            name="income_sources_trend_check",
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="income_sources_confidence_range_check",
        ),
        sa.UniqueConstraint("packet_id", "source_code", name="income_sources_packet_code_unique"),
    )
    op.create_index("ix_income_sources_packet", "income_sources", ["packet_id"])
    op.create_index("ix_income_sources_org", "income_sources", ["org_id"])

    op.create_table(
        "income_dti_items",
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
        sa.Column("description", sa.String, nullable=False),
        sa.Column("monthly_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_income_dti_items_packet", "income_dti_items", ["packet_id"])
    op.create_index("ix_income_dti_items_org", "income_dti_items", ["org_id"])

    for table in ("income_sources", "income_dti_items"):
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
    for table in ("income_dti_items", "income_sources"):
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_{suffix} ON {table}")

    op.drop_index("ix_income_dti_items_org", table_name="income_dti_items")
    op.drop_index("ix_income_dti_items_packet", table_name="income_dti_items")
    op.drop_table("income_dti_items")

    op.drop_index("ix_income_sources_org", table_name="income_sources")
    op.drop_index("ix_income_sources_packet", table_name="income_sources")
    op.drop_table("income_sources")
