"""Packet-level loan-program confirmation + override (US-3.11 / US-3.12).

Two clusters of columns on `packets`:

- **Confirmation** (`program_confirmation_*`) — populated by the ECV
  pipeline during the `score` stage. Tells the dashboard whether the
  documents in the packet agree with the declared program:
  `confirmed` / `conflict` / `inconclusive`. On `conflict` the pipeline
  also suggests an alternative program, and the evidence text is shown
  on the confirmation pill + override dialog preview.

- **Override** (`program_overridden_*`) — set by `POST
  /api/packets/{id}/program-override` when an underwriter/examiner
  decides the declared program is wrong. The column `program_overridden_to`
  is the program id the packet should now be treated as; the reason +
  actor + timestamp form the audit trail the dialog surfaces.

Both clusters are on the `packets` row rather than a child table because
each is 1:1 with a packet and queried alongside the rest of the packet
header — inline columns beat a join for a read that happens on every
dashboard load.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels = None
depends_on = None


CONFIRMATION_STATUSES = ("confirmed", "conflict", "inconclusive")


def upgrade() -> None:
    op.add_column(
        "packets",
        sa.Column("program_confirmation_status", sa.String, nullable=True),
    )
    op.add_column(
        "packets",
        sa.Column("program_confirmation_suggested_id", sa.String, nullable=True),
    )
    op.add_column(
        "packets",
        sa.Column("program_confirmation_evidence", sa.Text, nullable=True),
    )
    op.add_column(
        "packets",
        sa.Column("program_confirmation_documents", JSONB, nullable=True),
    )
    op.add_column(
        "packets",
        sa.Column("program_overridden_to", sa.String, nullable=True),
    )
    op.add_column(
        "packets",
        sa.Column("program_override_reason", sa.Text, nullable=True),
    )
    op.add_column(
        "packets",
        sa.Column(
            "program_overridden_by",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "packets",
        sa.Column("program_overridden_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_check_constraint(
        "packets_program_confirmation_status_check",
        "packets",
        "program_confirmation_status IS NULL OR program_confirmation_status IN ("
        + ", ".join(f"'{s}'" for s in CONFIRMATION_STATUSES)
        + ")",
    )


def downgrade() -> None:
    op.drop_constraint("packets_program_confirmation_status_check", "packets", type_="check")
    op.drop_column("packets", "program_overridden_at")
    op.drop_column("packets", "program_overridden_by")
    op.drop_column("packets", "program_override_reason")
    op.drop_column("packets", "program_overridden_to")
    op.drop_column("packets", "program_confirmation_documents")
    op.drop_column("packets", "program_confirmation_evidence")
    op.drop_column("packets", "program_confirmation_suggested_id")
    op.drop_column("packets", "program_confirmation_status")
