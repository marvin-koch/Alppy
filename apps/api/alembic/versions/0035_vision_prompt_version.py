"""A verdict records which prompt produced it.

`Detection.vision_model` said which model read a written answer. That does not
identify the judgement on its own: the same model under `grade_open_answer.v2`
and `.v3` is told different things about what counts, and — since B8 — about
what an instruction written inside the answer box means.

A grade contested months later has to be traceable to the exact pair that
produced it, and the prompt version is precisely the thing that moves between
the mark being given and the appeal being heard.

NULL on every existing row, which is honest: those verdicts were written before
anything recorded it, and inventing the current version for them would be a
claim about a call nobody logged.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "detection", sa.Column("vision_prompt_version", sa.String(length=20), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("detection", "vision_prompt_version")
