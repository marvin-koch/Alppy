"""``exercise.discarded_at`` — a generated item the teacher threw away.

F4 asks that a teacher be able to discard a generated exercise and never be
offered it again. That needs a durable mark: deleting the row is wrong because
an `Attempt` may already point at it if an earlier version of the sheet was
printed, and "unapproved" is not the same thing as "rejected" — an unapproved
item is simply waiting for a decision, and the next run should still be free to
propose it.

Partial index rather than a plain one: almost every row is `NULL` here, and the
only query that reads the column asks for the handful that are not.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exercise",
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_exercise_discarded",
        "exercise",
        ["subject_id"],
        unique=False,
        postgresql_where=sa.text("discarded_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_exercise_discarded", table_name="exercise")
    op.drop_column("exercise", "discarded_at")
