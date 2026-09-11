"""Approving an exercise, and editing an answer key, become events.

The staffroom is flat on purpose (D85): there is no admin tier, and anyone in
the school can approve an AI-generated exercise for print or edit a sheet
item's expected answer. That model is fine — and it is only fine if both acts
are legible afterwards.

Approval is the gate `Exercise.approved_at` exists to be: it is what stands
between something a model wrote and something a child is handed. Editing an
expected answer after a pile has been printed changes what the grader judges
against, on a paper the class has already sat.

Neither had an author or a date beyond a column being set. This changes no
permission; it makes the two acts answerable.
"""

from __future__ import annotations

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

_KINDS = ("EXERCISE_APPROVED", "EXERCISE_EDITED")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for name in _KINDS:
        op.execute(f"ALTER TYPE event_kind ADD VALUE IF NOT EXISTS '{name}'")
    op.execute("ALTER TYPE event_subject ADD VALUE IF NOT EXISTS 'EXERCISE'")


def downgrade() -> None:
    # Postgres cannot drop an enum value; see 0032 for the argument.
    pass
