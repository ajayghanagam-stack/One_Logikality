"""Add packet-level app scope (`packets.scoped_app_ids`) + line-item tag.

ECV today runs all 13 sections / ~54 checks regardless of what the
packet is actually for. A packet uploaded just for title examination
lights up every income-calc / compliance check as red because those
documents legitimately aren't there — not because the packet is bad.

We fix the false-red by making "what apps is this packet scoped to"
a first-class attribute of the upload:

  - `packets.scoped_app_ids` — the set of app ids the uploader declared
    this packet should be scored against. ECV is always implicitly in
    scope (foundational); the column is NOT NULL with a server default
    of `{ecv}` so existing rows become valid without a backfill step.

  - `ecv_line_items.app_ids` — which downstream apps each validation
    check is relevant to. Populated from `_CHECK_DEFS` at write time.
    NULL / empty means "core ECV check, applies to every packet" so
    the dashboard never needs special-casing — the filter rule is
    just `app_ids empty OR app_ids intersects packet.scoped_app_ids`.

Both columns use TEXT[] (Postgres native array) rather than JSONB
because they're small, enumerated, and need cheap `&&` (array overlap)
membership checks.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "packets",
        sa.Column(
            "scoped_app_ids",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            # Existing demo packets are ECV-only scoped retroactively —
            # they predate this feature. New uploads override via the
            # upload form.
            server_default=sa.text("ARRAY['ecv']::text[]"),
        ),
    )
    op.add_column(
        "ecv_line_items",
        sa.Column(
            "app_ids",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("ecv_line_items", "app_ids")
    op.drop_column("packets", "scoped_app_ids")
