"""Income + Compliance TI-parity superset (US-6.3 / US-6.4).

Extends the income and compliance tables so every field in the target
`IncomeCalculationOutput` / `ComplianceOutput` TypeScript interfaces has
somewhere to land. Every new column is nullable so existing rows
(written by migrations 0010 / 0011) stay valid until the seed repopulates.

Shape summary:

- `income_sources`                        — add borrower scoping, employment
                                            breakdown, VOE, MISMO paths, and
                                            stated/verified monthly columns.
- `income_findings`                       — new: per-packet income findings
                                            (missing_doc, variance, etc).
- `income_packet_metadata`                — new: singleton per packet holding
                                            appliedRules, residualIncome,
                                            evidence trace, confidence.
- `compliance_checks`                     — add check_type, rule_id, citation,
                                            severity, details JSONB.
- `compliance_fee_tolerances`             — add rule_id, citation, fee_name,
                                            fee_category, dates, severity,
                                            cure_amount, numeric amounts.
- `compliance_findings`                   — new: consolidated compliance
                                            findings with curative payloads.
- `compliance_packet_metadata`            — new: singleton per packet holding
                                            appliedFramework, appliedRules,
                                            evidence, confidence.

RLS follows the same pattern the rest of the tenant-scoped tables use —
select within own org, mutate via platform / customer admin roles.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels = None
depends_on = None


INCOME_CATEGORIES = ("employment", "non_employment")
INCOME_EMPLOYMENT_TYPES = ("w2", "self_employed", "1099", "military")
INCOME_FINDING_SEVERITIES = ("critical", "review", "info")
INCOME_FINDING_CATEGORIES = (
    "missing_doc",
    "variance",
    "trending_concern",
    "dti_exceeded",
    "incomplete_verification",
)

COMPLIANCE_CHECK_TYPES = (
    "disclosure_timing",
    "fee_tolerance",
    "required_disclosure",
    "program_specific",
    "fair_lending",
    "state_specific",
)
COMPLIANCE_SEVERITIES = ("critical", "warning", "info")
COMPLIANCE_FEE_CATEGORIES = ("zero_tolerance", "ten_percent", "no_tolerance")

_NEW_TABLES = (
    "income_findings",
    "income_packet_metadata",
    "compliance_findings",
    "compliance_packet_metadata",
)

_OWN_ORG = "org_id::text = COALESCE(current_setting('app.current_org_id', true), '')"
_IS_PLATFORM_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'platform_admin'"
_IS_CUSTOMER_ADMIN = "COALESCE(current_setting('app.current_role', true), '') = 'customer_admin'"


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # --- income_sources: per-source TI-parity columns -------------------
    with op.batch_alter_table("income_sources") as batch:
        batch.add_column(sa.Column("borrower_id", sa.String, nullable=True))
        batch.add_column(sa.Column("borrower_name", sa.String, nullable=True))
        batch.add_column(sa.Column("category", sa.String, nullable=True))
        batch.add_column(sa.Column("employment_type", sa.String, nullable=True))
        batch.add_column(sa.Column("start_date", sa.Date, nullable=True))
        batch.add_column(sa.Column("tenure_years", sa.Integer, nullable=True))
        batch.add_column(sa.Column("tenure_months", sa.Integer, nullable=True))
        batch.add_column(sa.Column("base_salary", sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column("overtime", JSONB, nullable=True))
        batch.add_column(sa.Column("bonus", JSONB, nullable=True))
        batch.add_column(sa.Column("commission", JSONB, nullable=True))
        batch.add_column(sa.Column("total_qualifying", sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column("voe", JSONB, nullable=True))
        batch.add_column(sa.Column("mismo_paths", JSONB, nullable=True))
        batch.add_column(sa.Column("stated_monthly", sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column("verified_monthly", sa.Numeric(12, 2), nullable=True))
        batch.create_check_constraint(
            "income_sources_category_check",
            f"category IS NULL OR category IN ({_in_list(INCOME_CATEGORIES)})",
        )
        batch.create_check_constraint(
            "income_sources_employment_type_check",
            "employment_type IS NULL OR employment_type IN ("
            + _in_list(INCOME_EMPLOYMENT_TYPES)
            + ")",
        )

    # --- income_findings ------------------------------------------------
    op.create_table(
        "income_findings",
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
        sa.Column("finding_id", sa.String, nullable=False),
        sa.Column("severity", sa.String, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("recommendation", sa.Text, nullable=False),
        sa.Column("affected_sources", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("mismo_refs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"severity IN ({_in_list(INCOME_FINDING_SEVERITIES)})",
            name="income_findings_severity_check",
        ),
        sa.CheckConstraint(
            f"category IN ({_in_list(INCOME_FINDING_CATEGORIES)})",
            name="income_findings_category_check",
        ),
        sa.UniqueConstraint(
            "packet_id", "finding_id", name="income_findings_packet_finding_unique"
        ),
    )
    op.create_index("ix_income_findings_packet", "income_findings", ["packet_id"])
    op.create_index("ix_income_findings_org", "income_findings", ["org_id"])

    # --- income_packet_metadata ----------------------------------------
    op.create_table(
        "income_packet_metadata",
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
            unique=True,
        ),
        sa.Column(
            "org_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("applied_rules", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("residual_income", JSONB, nullable=True),
        sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("confidence", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="income_packet_metadata_confidence_range_check",
        ),
    )
    op.create_index("ix_income_packet_metadata_org", "income_packet_metadata", ["org_id"])

    # --- compliance_checks: extended structured columns -----------------
    with op.batch_alter_table("compliance_checks") as batch:
        batch.add_column(sa.Column("check_type", sa.String, nullable=True))
        batch.add_column(sa.Column("rule_id", sa.String, nullable=True))
        batch.add_column(sa.Column("citation", sa.String, nullable=True))
        batch.add_column(sa.Column("severity", sa.String, nullable=True))
        batch.add_column(sa.Column("details", JSONB, nullable=True))
        batch.create_check_constraint(
            "compliance_checks_check_type_check",
            f"check_type IS NULL OR check_type IN ({_in_list(COMPLIANCE_CHECK_TYPES)})",
        )
        batch.create_check_constraint(
            "compliance_checks_severity_check",
            f"severity IS NULL OR severity IN ({_in_list(COMPLIANCE_SEVERITIES)})",
        )

    # --- compliance_fee_tolerances: extended columns --------------------
    with op.batch_alter_table("compliance_fee_tolerances") as batch:
        batch.add_column(sa.Column("rule_id", sa.String, nullable=True))
        batch.add_column(sa.Column("citation", sa.String, nullable=True))
        batch.add_column(sa.Column("fee_name", sa.String, nullable=True))
        batch.add_column(sa.Column("fee_category", sa.String, nullable=True))
        batch.add_column(sa.Column("le_date", sa.Date, nullable=True))
        batch.add_column(sa.Column("cd_date", sa.Date, nullable=True))
        batch.add_column(sa.Column("severity", sa.String, nullable=True))
        batch.add_column(sa.Column("cure_amount", sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column("le_amount_num", sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column("cd_amount_num", sa.Numeric(12, 2), nullable=True))
        batch.create_check_constraint(
            "compliance_fee_tolerances_fee_category_check",
            "fee_category IS NULL OR fee_category IN (" + _in_list(COMPLIANCE_FEE_CATEGORIES) + ")",
        )
        batch.create_check_constraint(
            "compliance_fee_tolerances_severity_check",
            f"severity IS NULL OR severity IN ({_in_list(COMPLIANCE_SEVERITIES)})",
        )

    # --- compliance_findings -------------------------------------------
    op.create_table(
        "compliance_findings",
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
        sa.Column("finding_id", sa.String, nullable=False),
        sa.Column("severity", sa.String, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("rule_id", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("impact", sa.Text, nullable=False),
        sa.Column("recommendation", sa.Text, nullable=False),
        sa.Column("curative", JSONB, nullable=True),
        sa.Column("regulatory_citation", sa.String, nullable=False),
        sa.Column(
            "affected_parties",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "mismo_refs",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"severity IN ({_in_list(COMPLIANCE_SEVERITIES)})",
            name="compliance_findings_severity_check",
        ),
        sa.UniqueConstraint(
            "packet_id", "finding_id", name="compliance_findings_packet_finding_unique"
        ),
    )
    op.create_index("ix_compliance_findings_packet", "compliance_findings", ["packet_id"])
    op.create_index("ix_compliance_findings_org", "compliance_findings", ["org_id"])

    # --- compliance_packet_metadata ------------------------------------
    op.create_table(
        "compliance_packet_metadata",
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
            unique=True,
        ),
        sa.Column(
            "org_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "applied_framework",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "applied_rules",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("confidence", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="compliance_packet_metadata_confidence_range_check",
        ),
    )
    op.create_index("ix_compliance_packet_metadata_org", "compliance_packet_metadata", ["org_id"])

    # --- RLS on the four new tables ------------------------------------
    for table in _NEW_TABLES:
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
    # Drop policies + new tables first (tolerant in case partial apply).
    for table in _NEW_TABLES:
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_{suffix} ON {table}")

    op.execute("DROP INDEX IF EXISTS ix_compliance_packet_metadata_org")
    op.execute("DROP TABLE IF EXISTS compliance_packet_metadata")

    op.execute("DROP INDEX IF EXISTS ix_compliance_findings_org")
    op.execute("DROP INDEX IF EXISTS ix_compliance_findings_packet")
    op.execute("DROP TABLE IF EXISTS compliance_findings")

    op.execute("DROP INDEX IF EXISTS ix_income_packet_metadata_org")
    op.execute("DROP TABLE IF EXISTS income_packet_metadata")

    op.execute("DROP INDEX IF EXISTS ix_income_findings_org")
    op.execute("DROP INDEX IF EXISTS ix_income_findings_packet")
    op.execute("DROP TABLE IF EXISTS income_findings")

    # Revert column additions.
    with op.batch_alter_table("compliance_fee_tolerances") as batch:
        for c in (
            "compliance_fee_tolerances_fee_category_check",
            "compliance_fee_tolerances_severity_check",
        ):
            batch.drop_constraint(c, type_="check")
        for col in (
            "cd_amount_num",
            "le_amount_num",
            "cure_amount",
            "severity",
            "cd_date",
            "le_date",
            "fee_category",
            "fee_name",
            "citation",
            "rule_id",
        ):
            batch.drop_column(col)

    with op.batch_alter_table("compliance_checks") as batch:
        for c in ("compliance_checks_check_type_check", "compliance_checks_severity_check"):
            batch.drop_constraint(c, type_="check")
        for col in ("details", "severity", "citation", "rule_id", "check_type"):
            batch.drop_column(col)

    with op.batch_alter_table("income_sources") as batch:
        for c in ("income_sources_category_check", "income_sources_employment_type_check"):
            batch.drop_constraint(c, type_="check")
        for col in (
            "verified_monthly",
            "stated_monthly",
            "mismo_paths",
            "voe",
            "total_qualifying",
            "commission",
            "bonus",
            "overtime",
            "base_salary",
            "tenure_months",
            "tenure_years",
            "start_date",
            "employment_type",
            "category",
            "borrower_name",
            "borrower_id",
        ):
            batch.drop_column(col)
