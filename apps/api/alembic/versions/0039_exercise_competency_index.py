"""The other direction of exercise_competency.

The composite primary key indexes ``(exercise_id, competency_id)``, which
answers "what does this exercise credit" and nothing else: a lookup keyed on
``competency_id`` alone cannot use an index whose leading column is the other
one.

Nothing asked that question until the bank did. Every read of the corpus went
through a document — ``GET /sources/{id}/exercises``, narrowed to one source
and usually one section — so the m2m was only ever traversed from an exercise
already in hand. ``GET /exercises?competency_id=`` traverses it the other way,
across the whole school's corpus, and is the query behind "every fractions
item at difficulty 2, wherever it came from".

CONCURRENTLY is deliberately not used: this table is small (one row per
exercise per competency, a handful per exercise) and the lock is measured in
milliseconds, where a concurrent build would need its own transaction and a
failure path that leaves an INVALID index behind.
"""

from __future__ import annotations

from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_exercise_competency_competency", "exercise_competency", ["competency_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_exercise_competency_competency", table_name="exercise_competency")
