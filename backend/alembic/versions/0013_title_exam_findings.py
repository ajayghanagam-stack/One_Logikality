"""Title Examination micro-app persistence — ALTA schedules + curative checklist.

Four tables so the Title Examination page (US-6.2) can hydrate from
server state and support the curative workflow:

- `title_exam_exceptions`       — Schedule B items (standard + specific),
                                  discriminated by `schedule` column.
- `title_exam_requirements`     — Schedule C items with status + priority.
- `title_exam_warnings`         — examiner notes with severity.
- `title_exam_checklist_items`  — curative checklist with a per-item
                                  `checked` flag so underwriters can
                                  mark items complete. This is the state
                                  primitive the Phase 6 "curative
                                  workflow" rides on.

All carry `org_id` with RLS matching the ECV / Compliance / Income /
Title Search tables. The checklist `checked` column is the only field
on these tables that customers can UPDATE — everything else is
seeded by the stub and read-only in the demo.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels = None
depends_on = None


SEVERITIES = ("critical", "high", "medium", "low")
SCHEDULES = ("standard", "specific")
# Schedule C — "must close" / "should close" / "recommended" maps the
# ALTA closing-urgency tiers the demo uses.
PRIORITIES = ("must_close", "should_close", "recommended")
# Small, stable set of Schedule C statuses. Checklist priorities reuse
# the severity tuple (critical / high / medium / low / recommended) —
# keep as free-text to avoid two half-overlapping enums.
REQUIREMENT_STATUSES = ("open", "requested", "provided", "not_ordered")

# Flag taxonomy — superset of TI Hub's ExaminerFlag.flag_type so the
# structured output is a strict superset of TI Hub's.
FLAG_TYPES = (
    "missing_endorsement",
    "unacceptable_exception",
    "unresolved_lien",
    "unreleased_mortgage",
    "cross_section_mismatch",
    "requirement_missing_proof",
    "name_discrepancy",
    "marital_status_issue",
    "incomplete_document",
    "regulatory_compliance",
    "chain_of_title_gap",
    "document_defect",
    "mineral_rights",
    "trust_issue",
    "estate_issue",
    "vesting_issue",
    "tax_issue",
)
FLAG_STATUSES = ("open", "reviewed", "closed")
REVIEW_DECISIONS = ("approve", "reject", "escalate")
FLAG_KINDS = ("exception", "warning")

_OWN_ORG = "org_id::text = COALESCE(current_setting('app.current_org_id', true), '')"
_IS_PLATFORM_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'"
_IS_CUSTOMER_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'customer_admin'"


def upgrade() -> None:
    op.create_table(
        "title_exam_exceptions",
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
        sa.Column("schedule", sa.String, nullable=False),
        sa.Column("exception_number", sa.Integer, nullable=False),
        sa.Column("severity", sa.String, nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("page_ref", sa.String, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        # TI Hub superset: flag taxonomy + AI explanation + structured
        # evidence + per-flag lifecycle.
        sa.Column("flag_type", sa.String, nullable=True),
        sa.Column("ai_explanation", sa.Text, nullable=True),
        sa.Column("evidence_refs", JSONB, nullable=True),
        sa.Column(
            "status",
            sa.String,
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schedule IN (" + ", ".join(f"'{s}'" for s in SCHEDULES) + ")",
            name="title_exam_exceptions_schedule_check",
        ),
        sa.CheckConstraint(
            "severity IN (" + ", ".join(f"'{s}'" for s in SEVERITIES) + ")",
            name="title_exam_exceptions_severity_check",
        ),
        sa.CheckConstraint(
            "flag_type IS NULL OR flag_type IN (" + ", ".join(f"'{t}'" for t in FLAG_TYPES) + ")",
            name="title_exam_exceptions_flag_type_check",
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in FLAG_STATUSES) + ")",
            name="title_exam_exceptions_status_check",
        ),
        sa.UniqueConstraint(
            "packet_id",
            "schedule",
            "exception_number",
            name="title_exam_exceptions_packet_schedule_number_unique",
        ),
    )
    op.create_index("ix_title_exam_exceptions_packet", "title_exam_exceptions", ["packet_id"])
    op.create_index("ix_title_exam_exceptions_org", "title_exam_exceptions", ["org_id"])

    op.create_table(
        "title_exam_requirements",
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
        sa.Column("requirement_number", sa.Integer, nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("priority", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("page_ref", sa.String, nullable=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        # TI Hub-parity transparency fields on requirements too.
        sa.Column("ai_explanation", sa.Text, nullable=True),
        sa.Column("evidence_refs", JSONB, nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "priority IN (" + ", ".join(f"'{p}'" for p in PRIORITIES) + ")",
            name="title_exam_requirements_priority_check",
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in REQUIREMENT_STATUSES) + ")",
            name="title_exam_requirements_status_check",
        ),
        sa.UniqueConstraint(
            "packet_id",
            "requirement_number",
            name="title_exam_requirements_packet_number_unique",
        ),
    )
    op.create_index("ix_title_exam_requirements_packet", "title_exam_requirements", ["packet_id"])
    op.create_index("ix_title_exam_requirements_org", "title_exam_requirements", ["org_id"])

    op.create_table(
        "title_exam_warnings",
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
        sa.Column("severity", sa.String, nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        # TI Hub superset: warnings carry the same shape as exceptions.
        sa.Column("flag_type", sa.String, nullable=True),
        sa.Column("ai_explanation", sa.Text, nullable=True),
        sa.Column("evidence_refs", JSONB, nullable=True),
        sa.Column(
            "status",
            sa.String,
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN (" + ", ".join(f"'{s}'" for s in SEVERITIES) + ")",
            name="title_exam_warnings_severity_check",
        ),
        sa.CheckConstraint(
            "flag_type IS NULL OR flag_type IN (" + ", ".join(f"'{t}'" for t in FLAG_TYPES) + ")",
            name="title_exam_warnings_flag_type_check",
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in FLAG_STATUSES) + ")",
            name="title_exam_warnings_status_check",
        ),
    )
    op.create_index("ix_title_exam_warnings_packet", "title_exam_warnings", ["packet_id"])
    op.create_index("ix_title_exam_warnings_org", "title_exam_warnings", ["org_id"])

    op.create_table(
        "title_exam_checklist_items",
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
        sa.Column("item_number", sa.Integer, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        # Free-text: Critical / High / Medium / Recommended in the demo.
        sa.Column("priority", sa.String, nullable=False),
        sa.Column("checked", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "packet_id",
            "item_number",
            name="title_exam_checklist_items_packet_number_unique",
        ),
    )
    op.create_index(
        "ix_title_exam_checklist_items_packet",
        "title_exam_checklist_items",
        ["packet_id"],
    )
    op.create_index("ix_title_exam_checklist_items_org", "title_exam_checklist_items", ["org_id"])

    # Per-flag review workflow — polymorphic across exceptions + warnings
    # so both can participate in TI Hub's approve/reject/escalate flow.
    op.create_table(
        "title_exam_reviews",
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
        sa.Column("flag_kind", sa.String, nullable=False),
        sa.Column("flag_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "reviewer_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String, nullable=False),
        sa.Column("reason_code", sa.String, nullable=False, server_default=sa.text("''")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "flag_kind IN (" + ", ".join(f"'{k}'" for k in FLAG_KINDS) + ")",
            name="title_exam_reviews_flag_kind_check",
        ),
        sa.CheckConstraint(
            "decision IN (" + ", ".join(f"'{d}'" for d in REVIEW_DECISIONS) + ")",
            name="title_exam_reviews_decision_check",
        ),
    )
    op.create_index("ix_title_exam_reviews_packet", "title_exam_reviews", ["packet_id"])
    op.create_index("ix_title_exam_reviews_org", "title_exam_reviews", ["org_id"])
    op.create_index(
        "ix_title_exam_reviews_flag",
        "title_exam_reviews",
        ["flag_kind", "flag_id"],
    )

    tables = (
        "title_exam_exceptions",
        "title_exam_requirements",
        "title_exam_warnings",
        "title_exam_checklist_items",
        "title_exam_reviews",
    )
    for table in tables:
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
    tables = (
        "title_exam_reviews",
        "title_exam_checklist_items",
        "title_exam_warnings",
        "title_exam_requirements",
        "title_exam_exceptions",
    )
    for table in tables:
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_{suffix} ON {table}")

    # `IF EXISTS` tolerates a downgrade from a DB that was upgraded under
    # an older version of this migration (before the reviews table existed).
    op.execute("DROP INDEX IF EXISTS ix_title_exam_reviews_flag")
    op.execute("DROP INDEX IF EXISTS ix_title_exam_reviews_org")
    op.execute("DROP INDEX IF EXISTS ix_title_exam_reviews_packet")
    op.execute("DROP TABLE IF EXISTS title_exam_reviews")

    op.drop_index("ix_title_exam_checklist_items_org", table_name="title_exam_checklist_items")
    op.drop_index("ix_title_exam_checklist_items_packet", table_name="title_exam_checklist_items")
    op.drop_table("title_exam_checklist_items")

    op.drop_index("ix_title_exam_warnings_org", table_name="title_exam_warnings")
    op.drop_index("ix_title_exam_warnings_packet", table_name="title_exam_warnings")
    op.drop_table("title_exam_warnings")

    op.drop_index("ix_title_exam_requirements_org", table_name="title_exam_requirements")
    op.drop_index("ix_title_exam_requirements_packet", table_name="title_exam_requirements")
    op.drop_table("title_exam_requirements")

    op.drop_index("ix_title_exam_exceptions_org", table_name="title_exam_exceptions")
    op.drop_index("ix_title_exam_exceptions_packet", table_name="title_exam_exceptions")
    op.drop_table("title_exam_exceptions")
