"""A textbook's bibliographic facts, and a branch-level history cache.

Two unrelated additions, together because both are pure additions and neither
touches a column anything already reads.

**`source.publisher` / `isbn` / `url`.** A shelf listed books by the filename
somebody happened to upload. `title` (0022) fixed what a teacher calls a book;
these are what identifies it to a HUMAN deciding whether two shelves hold the
same one. Deliberately unvalidated beyond length: a teacher typing what is on
the cover of a cantonal workbook must not be told their ISBN is malformed, and
Alppy never redistributes the file, so nothing downstream parses these.

**`mastery_branch_snapshot`.** A cache for the history curve, and the shape
that argument had to take. A nullable `competency_id` on `mastery_snapshot`
was rejected: it would turn every `(student, competency)` key in
`latest_snapshots` into an optional and let I-mastery-07's "one row per
student, competency, day" silently admit two kinds of row.

Nothing reads it to answer "what is this child's band" — every read path
recomputes from `Attempt`s, because the score decays and a matrix opened on
Friday must not show Monday's numbers (`data-model.md` §4). It exists so a
*curve* has points to draw, which is the one question recomputation cannot
answer: history.

It stores its own coverage, `child_count` and `assessed_child_count`, because
a branch band over one assessed competency and one over three are different
claims — a cached number that dropped the denominator would be exactly the
dishonesty DC-content-07 forbids on screen.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source", sa.Column("publisher", sa.String(length=200), nullable=True))
    op.add_column("source", sa.Column("isbn", sa.String(length=20), nullable=True))
    op.add_column("source", sa.Column("url", sa.String(length=500), nullable=True))

    # `mastery_band` already exists as a type (0001); reuse it rather than
    # letting create_table try to define it a second time.
    op.create_table(
        "mastery_branch_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "band",
            postgresql.ENUM(name="mastery_band", create_type=False),
            nullable=False,
        ),
        sa.Column("child_count", sa.Integer(), nullable=False),
        sa.Column("assessed_child_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["school_id"], ["school.id"],
            name="fk_mastery_branch_snapshot_school_id_school", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["student.id"],
            name="fk_mastery_branch_snapshot_student_id_student", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subject.id"],
            name="fk_mastery_branch_snapshot_subject_id_subject", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mastery_branch_snapshot"),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="branch_score_unit_interval"),
    )
    op.create_index(
        "ix_mastery_branch_snapshot_school_id", "mastery_branch_snapshot", ["school_id"]
    )
    op.create_index(
        "ix_mastery_branch_snapshot_student_id", "mastery_branch_snapshot", ["student_id"]
    )
    op.create_index(
        "ix_mastery_branch_snapshot_subject_id", "mastery_branch_snapshot", ["subject_id"]
    )
    op.create_index(
        "ix_mastery_branch_student",
        "mastery_branch_snapshot",
        ["student_id", "subject_id", "computed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_mastery_branch_student", table_name="mastery_branch_snapshot")
    op.drop_index("ix_mastery_branch_snapshot_subject_id", table_name="mastery_branch_snapshot")
    op.drop_index("ix_mastery_branch_snapshot_student_id", table_name="mastery_branch_snapshot")
    op.drop_index("ix_mastery_branch_snapshot_school_id", table_name="mastery_branch_snapshot")
    op.drop_table("mastery_branch_snapshot")
    op.drop_column("source", "url")
    op.drop_column("source", "isbn")
    op.drop_column("source", "publisher")
