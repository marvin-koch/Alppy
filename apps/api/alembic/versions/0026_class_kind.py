"""A homeroom and a niveau group are both classes, and the product cannot tell.

``Class`` has always been able to *hold* a Vaud niveau-2 maths group: its own
code, its own head teacher, ``class_subject = {mathematics}``, and pupils
enrolled from several homerooms whose ``home_class_id`` stays their homeroom.
The docstring says so — *"A teaching group"* — and ``class_student`` has been a
many-to-many since 0019.

What is missing is a **discriminator**. Nothing marks which rows are homerooms
and which are course groups, so the nav, the tree and every roster read treat
them identically, and a pupil in three groups has three equally-weighted
"classes" with no way to say which one is *theirs*.

One nullable column, and nothing reads it yet. That is the whole migration.

**NULL is a real value here and means "not declared".** It is not a synonym for
``homeroom``: every row that exists today predates the question, and back-
filling them all as homerooms would invent an answer for the niveau groups the
demo seed already contains. A school that never answers keeps today's
behaviour, which is the behaviour NULL has to mean for this to be additive.

Deliberately NOT the full ``class`` / ``teaching_group`` split (the audit's
delta 6). That split changes which table grows the validity columns 0027 adds,
so it would have to land *before* 0027 rather than beside it — and it is worth
doing once, with a pilot school's real roster in hand, rather than twice.

Revision ID: 0026
Revises: 0025
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

_CLASS_KIND = ("homeroom", "course")


def upgrade() -> None:
    bind = op.get_bind()
    # A brand-new type, so it is created outright — no `ALTER TYPE ... ADD
    # VALUE`, and therefore none of 0018's early-`COMMIT` dance, which would
    # end this migration's transaction for no reason. `checkfirst` so a
    # partially-applied database can be re-run, matching 0016's posture.
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(*_CLASS_KIND, name="class_kind").create(bind, checkfirst=True)

    op.add_column(
        "class",
        sa.Column(
            "kind",
            postgresql.ENUM(*_CLASS_KIND, name="class_kind", create_type=False),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Lossy only for schools that answered the question.

    A declared ``homeroom``/``course`` is dropped with the column. Nothing
    reads it, so nothing else changes shape.
    """
    op.drop_column("class", "kind")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name="class_kind").drop(bind, checkfirst=True)
