"""A remplaçant is not a titulaire, and the staffing row could not say so.

`class_teacher_subject` records who teaches which branch in which class, and
since 0027 for how long. What it could never say is **in what capacity**
(database audit L2) — and the four capacities are not interchangeable to
anybody in the building. A staff list showed two names against one branch with
no way to say that one of them is covering the other's maternity leave, or
that one is there for three named pupils.

`titulaire` | `appui` | `remplacant` | `co_enseignant`, kept in French because
these are the words on a timetable and in a décision d'attribution; translating
them would make a different claim. Rendering is the UI's job, through the
message catalogues.

**NULL is a third state and the default, not a synonym for `titulaire`.** Every
existing row predates the question. Backfilling them all as `titulaire` would
be inventing an answer, and inventing the *wrong* one for exactly the rows that
matter: a cover teacher put on record as holding the branch. This is the same
reasoning 0026 used for `class.kind`, and it is the reason this migration has
no backfill at all.

`valid_to` is what makes the role worth having. A remplaçant covering March to
May is now one row with two dates and a capacity, rather than a row that
appeared and vanished (0027, D87).

Nothing branches on it yet.

Revision ID: 0049
Revises: 0048
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

_ROLES = ("titulaire", "appui", "remplacant", "co_enseignant")


def upgrade() -> None:
    bind = op.get_bind()
    # A brand-new type, so it is created outright — no `ALTER TYPE ... ADD
    # VALUE`, and therefore none of 0018's early-`COMMIT`, which would end this
    # migration's transaction for nothing.
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(*_ROLES, name="staffing_role").create(bind, checkfirst=True)

    op.add_column(
        "class_teacher_subject",
        sa.Column(
            "role",
            postgresql.ENUM(*_ROLES, name="staffing_role", create_type=False),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Lossy only for the schools that answered the question."""
    op.drop_column("class_teacher_subject", "role")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name="staffing_role").drop(bind, checkfirst=True)
