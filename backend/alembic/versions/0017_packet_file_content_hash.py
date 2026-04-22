"""Add content_hash to packet_files for deterministic dedupe.

Real LLM pipelines (Gemini Flash for classify, Gemini Pro for extract,
Claude Sonnet for validate) drift across calls even at temperature=0, so
re-uploading identical bytes produces different ECV scores. That's
inconsistent with user expectation AND wastes paid tokens.

Storing the SHA256 hex digest per file lets the upload handler compare
file-hash sets against prior completed packets in the same org +
declared_program_id and return the existing packet rather than running
the pipeline again.

All packets were truncated during the demo reset, so we add the column
as NOT NULL from the start — no backfill needed.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "packet_files",
        sa.Column("content_hash", sa.String(length=64), nullable=False),
    )
    # Compound index on (org_id, content_hash) — that's the lookup the
    # upload handler runs: "does any file I already own have this hash?".
    op.create_index(
        "ix_packet_files_org_hash",
        "packet_files",
        ["org_id", "content_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_packet_files_org_hash", table_name="packet_files")
    op.drop_column("packet_files", "content_hash")
