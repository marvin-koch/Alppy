"""A student sits in many classes, and exactly one of them minted their UID.

``student.class_id`` carried two facts that only looked like one for as long as
a child belonged to a single class: **which class is this pupil's**, and **which
classes does this pupil attend**. A teacher who takes 7B for maths and also
takes a support group cannot express the second, and every roster, matrix, tree
and printed pile read the first as though it were.

Splitting them is the shape D56 already established for `Chapter`: where a row
*sits* is one column, what it *belongs to* is a join table.

* ``student.home_class_id`` — the class that minted ``uid`` (``7B_15``) and
  ``number``. Still NOT NULL, still exactly one. This is what keeps the print
  and scan path untouched by this migration: the UID on paper is a fact about
  the pupil's home, unique per (school, school_year), and the detector goes on
  decoding it exactly as before.
* ``class_student`` — who actually sits where.

**The column is renamed rather than kept.** There were a dozen read sites to
judge one at a time as "enrolled" or "home", and under the old name every site
nobody reviewed would have kept compiling with the old meaning. The worst of
them, ``scan_processing``'s ``wrong_class`` test, *discards every detection on
the page*: a co-enrolled pupil's answers would have vanished with no error
anywhere. Renaming turns each unreviewed site into an AttributeError the suite
catches instead.

``home_class_id`` also becomes **RESTRICT** where ``class_id`` was CASCADE.
Deleting a class currently deletes its students, and `attempt`, `mastery_snapshot`
and `sheet_instance` all cascade from there — a term of evidence, gone, for a
child who may also have been sitting in another class. There is no class-delete
endpoint today, so RESTRICT costs nothing now and refuses the destructive case
later. Note this is the same topology `class.teacher_id` has carried since 0001,
which means `DELETE FROM school` is already not a supported operation: Postgres
checks RESTRICT without knowing the referencing row is itself about to go.

Deliberately NOT copied from 0018: its ``op.execute("COMMIT")``. That exists
only because ``ALTER TYPE ... ADD VALUE`` cannot share a transaction with DDL
that uses the new value. This migration adds no enum member, and committing
early here would end the transaction before the backfill and leave 0019 half
applied if anything below raised.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

#: **This migration cannot be rolled back** (docs/runbook/rollback.md).
#: Renames a column in place, so the previous application version and this one
#: cannot share the schema: a rolling deploy serves 500s from whichever half
#: is behind. Nothing is lost, and it still cannot be rolled back.
#:
#: Checked by scripts/check-migration-safety.py, so the rule is a gate
#: rather than something a reviewer has to remember on a Friday.
DESTRUCTIVE = True

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1 · The column says which of the two facts it holds.
    op.alter_column("student", "class_id", new_column_name="home_class_id")

    # The FK has to be recreated anyway to carry the new name, so the ondelete
    # change rides along rather than becoming a second migration.
    op.drop_constraint("fk_student_class_id_class", "student", type_="foreignkey")
    op.create_foreign_key(
        "fk_student_home_class_id_class",
        "student",
        "class",
        ["home_class_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_index("ix_student_class_id", table_name="student")
    op.create_index("ix_student_home_class_id", "student", ["home_class_id"])

    # --- 2 · Who sits where.
    #
    # No `school_id`, like `class_subject` and `chapter_competency`: both ends
    # are school-scoped and every read joins through a `class` already filtered
    # on the session's school, so tenancy holds transitively (I-platform-02).
    #
    # The composite PK IS the uniqueness guarantee — a separate UniqueConstraint
    # over the same two columns would leave autogenerate reporting a duplicate
    # index on every run forever.
    op.create_table(
        "class_student",
        sa.Column("class_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["class.id"],
            name="fk_class_student_class_id_class",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["student.id"],
            name="fk_class_student_student_id_student",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("class_id", "student_id", name="pk_class_student"),
    )
    # The PK's btree only answers class-first lookups. "Which classes is this
    # student in" is the tenancy query (`mastery_service._owned_student`) and
    # runs on every student-profile request, so it gets its own index.
    op.create_index("ix_class_student_student_id", "class_student", ["student_id"])

    # --- 3 · Backfill: one enrollment per student, equal to their home.
    #
    # `created_at`, not now(): the honest answer to "when did this pupil join
    # this class" is the moment the roster paste created the row, and it is
    # sitting right there. ON CONFLICT DO NOTHING so a partially-applied
    # database can be re-run, matching 0016's posture.
    #
    # After this every student has exactly one enrollment, so every read this
    # release rewrites returns precisely what it returned before. Nothing can
    # create a second enrollment until the enroll endpoint ships.
    op.execute(
        sa.text(
            """
            INSERT INTO class_student (class_id, student_id, enrolled_at)
            SELECT home_class_id, id, created_at FROM student
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    """Lossy, and there is no honest way around it.

    A pupil enrolled in three classes goes back to holding one, their home.
    The other two enrollments are dropped with the table.
    """
    op.drop_index("ix_class_student_student_id", table_name="class_student")
    op.drop_table("class_student")

    op.drop_index("ix_student_home_class_id", table_name="student")
    op.drop_constraint("fk_student_home_class_id_class", "student", type_="foreignkey")
    op.alter_column("student", "home_class_id", new_column_name="class_id")
    op.create_foreign_key(
        "fk_student_class_id_class",
        "student",
        "class",
        ["class_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_student_class_id", "student", ["class_id"])
