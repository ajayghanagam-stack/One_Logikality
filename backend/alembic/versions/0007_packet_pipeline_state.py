"""Add pipeline-state columns to packets (US-3.4).

Three columns so the UI's processing animation can sync to real server
state: `current_stage` tells the stepper which node to highlight;
`started_processing_at` and `completed_at` bracket the run for duration
display + polling exit.

Stage identifiers match the demo's `PIPELINE_STAGES` exactly — ingest /
classify / extract / validate / score / route — so the UI can port the
labels/icons without translation.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels = None
depends_on = None


PIPELINE_STAGES = ("ingest", "classify", "extract", "validate", "score", "route")


def upgrade() -> None:
    op.add_column(
        "packets",
        sa.Column("current_stage", sa.String, nullable=True),
    )
    op.add_column(
        "packets",
        sa.Column("started_processing_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "packets",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "packets_current_stage_check",
        "packets",
        "current_stage IS NULL OR current_stage IN ("
        + ", ".join(f"'{s}'" for s in PIPELINE_STAGES)
        + ")",
    )


def downgrade() -> None:
    op.drop_constraint("packets_current_stage_check", "packets", type_="check")
    op.drop_column("packets", "completed_at")
    op.drop_column("packets", "started_processing_at")
    op.drop_column("packets", "current_stage")
