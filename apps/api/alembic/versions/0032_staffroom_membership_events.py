"""Joining and leaving a staffroom become events.

`teacher_school` has carried a `valid_to` since 0027, and `get_membership` has
respected it since the same day — so a membership has been revocable for two
migrations and there was no way to revoke one. `add_teacher_to_school`'s own
docstring said so: "no route removes a membership, so a colleague added by a
mistyped uuid comes out in SQL."

The staffroom is flat by design (D85): membership *is* the permission model,
and there is no admin tier above it. That makes the two moments where it
changes the two most worth recording — a colleague gaining or losing sight of
every class in the school, previously a change with no author and no date.
"""

from __future__ import annotations

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

# SQLAlchemy stores enum NAMES, not values — the same spelling 0005 and 0010
# used when they widened `job_kind`.
_KINDS = ("TEACHER_JOINED", "TEACHER_LEFT")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for name in _KINDS:
        op.execute(f"ALTER TYPE event_kind ADD VALUE IF NOT EXISTS '{name}'")
    op.execute("ALTER TYPE event_subject ADD VALUE IF NOT EXISTS 'TEACHER'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum type. Removing these would mean
    # rewriting the type and every column that uses it, to delete two labels
    # that cost nothing to leave in place — and any row already written with one
    # would have to be destroyed to do it. Left, deliberately.
    pass
