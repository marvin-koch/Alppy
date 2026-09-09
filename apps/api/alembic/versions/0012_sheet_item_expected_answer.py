"""The teacher's expected answer, per sheet item.

An open item's answer used to come only from the exercise: extracted from the
book, or typed when the teacher wrote the exercise. A textbook exercise picked
in the builder had no place to write one, and the grader was handed the words
"no expected answer was recorded" and told to judge against them.

``sheet_item.expected_answer`` is where the builder writes it now: per sheet
item, like the wording, because a reworded statement wants a different answer
and the corpus keeps the book's own. NULL falls back to the exercise's
``answer_text``; when both are NULL the grader works the answer out itself.

``detection.reference_answer`` keeps what the grader judged against — the
teacher's answer, or the model's own — so a verdict reached without a key is
reviewable rather than a bare tick.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sheet_item", sa.Column("expected_answer", sa.Text(), nullable=True))
    op.add_column("detection", sa.Column("reference_answer", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("detection", "reference_answer")
    op.drop_column("sheet_item", "expected_answer")
