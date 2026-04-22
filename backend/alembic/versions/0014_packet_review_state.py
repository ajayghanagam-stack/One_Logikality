"""Packet review state for Phase 8 send-to-manual-review + approve / reject.

Adds a single cluster of columns on `packets` that carries the
underwriter's decision on the packet:

- `review_state`        — one of `pending_manual_review` / `approved` /
                          `rejected`, or NULL if no decision has been
                          recorded yet. Drives the ECV action-bar badge
                          and gates re-submission in the UI.
- `review_notes`        — free-text rationale the underwriter enters in
                          the dialog; shown in the audit trail.
- `review_by_user_id`   — FK to users.id (SET NULL on user deletion) so
                          the "sent to manual review by Jane Smith at …"
                          line in the UI has a stable reference.
- `review_transitioned_at` — timestamp of the most recent transition.

A single state column is enough — the three values are mutually
exclusive, and any transition (including re-routing from approved → to
manual review) is captured by a fresh `_transitioned_at` timestamp. If
we later need a full history, add a `packet_review_events` child table
without migrating this shape.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels = None
depends_on = None


REVIEW_STATES = ("pending_manual_review", "approved", "rejected")


def upgrade() -> None:
    op.add_column("packets", sa.Column("review_state", sa.String, nullable=True))
    op.add_column("packets", sa.Column("review_notes", sa.Text, nullable=True))
    op.add_column(
        "packets",
        sa.Column(
            "review_by_user_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "packets",
        sa.Column("review_transitioned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "packets_review_state_check",
        "packets",
        "review_state IS NULL OR review_state IN ("
        + ", ".join(f"'{s}'" for s in REVIEW_STATES)
        + ")",
    )


def downgrade() -> None:
    op.drop_constraint("packets_review_state_check", "packets", type_="check")
    op.drop_column("packets", "review_transitioned_at")
    op.drop_column("packets", "review_by_user_id")
    op.drop_column("packets", "review_notes")
    op.drop_column("packets", "review_state")
