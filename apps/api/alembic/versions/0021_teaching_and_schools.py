"""A teacher is assigned a branch in a class, and may work at several schools.

Two renames and two join tables, in one migration because they are the same
shape twice and because ``teacher`` must not be migrated again in a later
release, after every read site has already been reviewed once.

**Who teaches what.** ``class.teacher_id`` carried two facts that only looked
like one while a class had a single teacher: *who may read this class* and
*who is its maître de classe*. Mme Martin takes French AND maths in 5A while
M. Lambert takes history in the same 5A, and none of that was expressible: the
schema could say "Martin owns 5A" and, separately, "5A studies French and
maths" — indistinguishable from "Martin owns 5A and teaches everything in it".

Split the way D56 split ``Chapter`` and D69 split ``Student``: where a row
*sits* is a column, what it *belongs to* is a join table.

* ``class.head_teacher_id`` — the maître de classe. Still NOT NULL, still
  RESTRICT, still exactly one.
* ``class_teacher_subject`` — who teaches which branch here.

``class_subject`` stays and is untouched. It is what the class STUDIES, and it
carries the Branch nav order; the new table is who TEACHES it. Deriving the
branch list from staffing instead would re-create the circularity D57 removed,
in a new costume: a Branch would vanish from the navigation the moment its
teacher was unassigned, taking its Themes, its sheets and its bands with it.
The composite FK is what makes ``class_subject`` provably the superset.

**Who works where.** ``teacher.school_id`` was the tenant boundary every query
filters on. A teacher who splits their load between two establishments belongs
to both, so the fact moves to ``teacher_school`` and the column that stays
answers a different question — where the account is based, and which school
``login`` mints the first cookie for. Tenancy for a request now comes from the
SESSION (``deps.get_membership``), which is where it was already carried: the
cookie has serialised ``{"t": teacher_id, "s": school_id}`` since 0001.

**Both columns are renamed rather than kept**, on D69's reasoning. There were
five read sites to judge one at a time as "ownership" or "the class's own
teacher", and five more as "the session's school" or "the account's home".
Under the old names every site nobody reviewed would have gone on compiling
with the old meaning. ``mastery_service._owned_student`` is this migration's
``scan_processing.wrong_class``: left reading a column renamed in meaning only,
a co-taught child's profile would 404 for the teacher who teaches them.

**This release is provably behaviour-preserving, and that is the point of
shipping it alone.** After the backfill, every class's assignment set is
exactly {head teacher} × {declared branches}, so ``owned_class_ids`` — head
teacher OR any assignment — selects a class for a teacher if and only if the
old single predicate did, *including for a class with no declared branches at
all*, which is why the head-teacher arm of that union is not optional. And
every teacher is a member of exactly the one school their cookie already
names, so ``session.school_id`` still resolves to what ``teacher.school_id``
used to return and **no live session is logged out by this deploy**. Nothing
here can create a second assignment or a second membership: the endpoints that
do ship separately. D69's "shipped in two parts", twice.

``SESSION_SALT`` is deliberately NOT bumped for the same reason — the payload
is byte-identical and its meaning is a strict widening.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1 · The column says which of the two facts it holds.
    #
    # A rename keeps the OLD constraint and index names, so both are respelled
    # explicitly. The drift gate compares names, not just shapes, and would
    # fail on those alone.
    op.alter_column("class", "teacher_id", new_column_name="head_teacher_id")
    op.drop_constraint("fk_class_teacher_id_teacher", "class", type_="foreignkey")
    op.create_foreign_key(
        "fk_class_head_teacher_id_teacher",
        "class",
        "teacher",
        ["head_teacher_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_index("ix_class_teacher_id", table_name="class")
    op.create_index("ix_class_head_teacher_id", "class", ["head_teacher_id"])

    # --- 2 · Who teaches which branch here.
    #
    # No `school_id`, like `class_subject` and `class_student`: every read
    # joins through a `class` already filtered on the session's school, so
    # tenancy holds transitively (I-platform-02). Unlike those two, this table
    # has an end — the teacher — that CAN belong to another school, so
    # `class_service.assign_branch` asserts the membership the column does not
    # (I-platform-12).
    #
    # `teacher_id` is RESTRICT, not the module's usual CASCADE: ownership is
    # assignment-based from here on, so cascading would let deleting an account
    # strip a class of its last owner — a roster of named children nobody can
    # open, with no error anywhere.
    #
    # The composite FK to `class_subject` makes "you cannot be assigned a
    # branch this class does not study" a constraint rather than a convention.
    op.create_table(
        "class_teacher_subject",
        sa.Column("class_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("teacher_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["class_id", "subject_id"],
            ["class_subject.class_id", "class_subject.subject_id"],
            name="fk_class_teacher_subject_class_subject",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id"],
            ["teacher.id"],
            name="fk_class_teacher_subject_teacher_id_teacher",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "class_id", "teacher_id", "subject_id", name="pk_class_teacher_subject"
        ),
    )
    # The PK's btree only answers class-first lookups. "Which classes does this
    # teacher hold a branch in" is the TENANCY query (`owned_class_ids`) and
    # runs on nearly every request, so it gets its own index — one column wider
    # than `ix_class_student_student_id` because the projection is `class_id`.
    op.create_index(
        "ix_class_teacher_subject_teacher",
        "class_teacher_subject",
        ["teacher_id", "class_id"],
    )

    # --- 3 · Backfill: one assignment per branch the class already declares,
    # held by the teacher who already owned it.
    #
    # `class.created_at`, not now(): a backfilled row carries the date of the
    # thing it describes, not the date the backfill ran — the same rule 0019
    # followed for `class_student.enrolled_at`. ON CONFLICT DO NOTHING so a
    # partially-applied database can be re-run, matching 0016's posture.
    op.execute(
        sa.text(
            """
            INSERT INTO class_teacher_subject (class_id, teacher_id, subject_id, assigned_at)
            SELECT cs.class_id, c.head_teacher_id, cs.subject_id, c.created_at
            FROM class_subject cs
            JOIN class c ON c.id = cs.class_id
            ON CONFLICT DO NOTHING
            """
        )
    )

    # --- 4 · Where this account is based, vs. where it may work.
    op.alter_column("teacher", "school_id", new_column_name="home_school_id")
    op.drop_constraint("fk_teacher_school_id_school", "teacher", type_="foreignkey")
    op.create_foreign_key(
        "fk_teacher_home_school_id_school",
        "teacher",
        "school",
        ["home_school_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("ix_teacher_school_id", table_name="teacher")
    op.create_index("ix_teacher_home_school_id", "teacher", ["home_school_id"])

    op.create_table(
        "teacher_school",
        sa.Column("teacher_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id"],
            ["teacher.id"],
            name="fk_teacher_school_teacher_id_teacher",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["school.id"],
            name="fk_teacher_school_school_id_school",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("teacher_id", "school_id", name="pk_teacher_school"),
    )
    # "Who is in this staffroom" — the reverse of the PK's btree, and the
    # direction a colleague picker reads.
    op.create_index(
        "ix_teacher_school_school", "teacher_school", ["school_id", "teacher_id"]
    )

    # Every teacher keeps exactly the school they already had, which is what
    # makes every cookie in flight still validate.
    op.execute(
        sa.text(
            """
            INSERT INTO teacher_school (teacher_id, school_id, joined_at)
            SELECT id, home_school_id, created_at FROM teacher
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    """Lossy beyond one assignment per branch and one school per teacher.

    Both of those are the pre-change state, and both are still readable from
    the columns that stayed — which is the other reason the columns stayed.
    """
    op.drop_index("ix_teacher_school_school", table_name="teacher_school")
    op.drop_table("teacher_school")
    op.drop_index("ix_teacher_home_school_id", table_name="teacher")
    op.drop_constraint("fk_teacher_home_school_id_school", "teacher", type_="foreignkey")
    op.alter_column("teacher", "home_school_id", new_column_name="school_id")
    op.create_foreign_key(
        "fk_teacher_school_id_school",
        "teacher",
        "school",
        ["school_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_teacher_school_id", "teacher", ["school_id"])

    op.drop_index("ix_class_teacher_subject_teacher", table_name="class_teacher_subject")
    op.drop_table("class_teacher_subject")
    op.drop_index("ix_class_head_teacher_id", table_name="class")
    op.drop_constraint("fk_class_head_teacher_id_teacher", "class", type_="foreignkey")
    op.alter_column("class", "head_teacher_id", new_column_name="teacher_id")
    op.create_foreign_key(
        "fk_class_teacher_id_teacher",
        "class",
        "teacher",
        ["teacher_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_class_teacher_id", "class", ["teacher_id"])
