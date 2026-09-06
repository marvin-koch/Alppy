"""Source.notice — a truthful caveat on a successful ingest.

``Source.error`` explains a failure. It has no room for the case that actually
misled a teacher: an ingest that *succeeded* but did less than it appears to —
extraction skipped because no grounded model is configured, or only the first
``MAX_EXTRACTION_CHUNKS`` of a 300-page book scanned for exercises. Those used
to render as a green tick and a silent zero.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source", sa.Column("notice", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("source", "notice")
