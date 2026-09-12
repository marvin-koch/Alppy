"""A pupil outlives the school year; the row that carried them did not.

``student`` is a year-bound row, not a person. ``school_year_id`` is NOT NULL
and ``uq_student_uid`` is keyed on it, so 2027/28 needs a *new* ``student`` row
with a new UUID — and ``attempt``, ``mastery_snapshot``,
``mastery_branch_snapshot`` and ``misconception_note`` all hang off
``student.id``.

For a product whose mastery model is explicitly about decay, that resets the
longitudinal record every August, over the one interval where decay matters
most. Noah repeats his 10e année: in 2026/27 he is a ``student`` with uid
``10VG3_07``, in 2027/28 a different ``student`` with uid ``10VG2_11``, and
Alppy proposes him adaptive work as though he had never seen the material he
failed. Nothing joins the two rows — not the uid (it changes with the class),
not the name (homonyms, spelling, a roster pasted differently).

So the durable identity moves up one level:

* ``person`` — school-scoped, holds the names and **nothing else**. Plus
  ``anonymised_at``, which is where a parent's erasure request lands: names
  nulled, the pedagogical record kept.
* ``student`` — demoted to what it already was, a year-bound *enrolment
  record*: ``uid``, ``number``, ``home_class_id``, ``school_year_id``, and now
  ``person_id``.

This is the third instance of a split the codebase has already named twice —
D56 for ``Chapter``, D69 for ``Student``: *where a row sits is a column, what
it belongs to is a join*. Applied here to time rather than to hierarchy.

**What moves and what stays.** The four longitudinal tables move to
``person_id``. The print and scan path does **not**: ``sheet_instance``,
``answer_box_placement.student_uid``, ``scan_page.student_id`` and
``exercise_variant.student_id`` stay on the year-bound row, because a UID is a
fact about one year's paper and must not change meaning. (``exercise_variant``
is a fifth FK to ``student.id`` that the audit's list omits; it is an adaptive
artefact for one year's sheet, so it stays with the others.)

**The columns are renamed, not repointed in place.** ``attempt.student_id``
means something different afterwards — a durable person rather than one year's
enrolment — and there are about twenty read sites across ``mastery_service``,
``results_service``, ``feedback_service``, ``adaptive_service``,
``performance_summary`` and four API modules. Under the old name every site
nobody reviewed would go on compiling with the old meaning. This is 0019's
argument, and 0019 was right.

**The new ids are deliberately fresh, not copied from ``student.id``.** Reusing
the uuid would make this migration free — no rewrite of the highest-volume
table — and would be a trap: every place that confused a ``student_id`` with a
``person_id`` would keep resolving, silently and correctly, until the first
pupil had two ``student`` rows. Fresh uuids make that same confusion a foreign
key violation on the day it is written. The tables are small now, which is the
whole reason the audit says to do this now.

**Why the backfill is behaviour-preserving.** Exactly one ``person`` per
existing ``student``, created from that student's own names and timestamps. The
mapping is total and injective, so after the rewrite every row in the four
tables points at the person of precisely the student it pointed at before, and
every query returns what it returned before. ``uq_attempt_person_exercise_sheet``
is equally exact: a sheet belongs to one class in one school year, and a person
has at most one ``student`` row per year, so per-person and per-student
uniqueness select the same rows. Nothing can create a second ``student`` for a
person until a rollover path ships, and there is none in this release.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

#: **This migration cannot be rolled back** (docs/runbook/rollback.md).
#: Renames in place while splitting `Student` into `Person` + one year's
#: enrolment. Old and new app versions cannot share the schema.
#:
#: Checked by scripts/check-migration-safety.py, so the rule is a gate
#: rather than something a reviewer has to remember on a Friday.
DESTRUCTIVE = True

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

CURRENT_SCHOOL = "nullif(current_setting('app.current_school_id', true), '')::uuid"

#: table -> the indexes whose names carry the old meaning.
#: (old name, new name, the columns, so downgrade can rebuild them.)
_RENAMED_INDEXES = {
    "attempt": (
        ("ix_attempt_student_id", "ix_attempt_person_id"),
        ("ix_attempt_student_answered", "ix_attempt_person_answered"),
    ),
    "mastery_snapshot": (
        ("ix_mastery_snapshot_student_id", "ix_mastery_snapshot_person_id"),
        ("ix_mastery_student_competency", "ix_mastery_person_competency"),
    ),
    "mastery_branch_snapshot": (
        ("ix_mastery_branch_snapshot_student_id", "ix_mastery_branch_snapshot_person_id"),
        ("ix_mastery_branch_student", "ix_mastery_branch_person"),
    ),
    "misconception_note": (
        ("ix_misconception_note_student_id", "ix_misconception_note_person_id"),
        ("ix_misconception_note_student_sheet", "ix_misconception_note_person_sheet"),
    ),
}

#: table -> the FK constraint that pointed at `student`, as it is named today.
#: `misconception_note`'s was hand-named in 0006 and does not follow the
#: convention; the replacements all do.
_OLD_FKS = {
    "attempt": "fk_attempt_student_id_student",
    "mastery_snapshot": "fk_mastery_snapshot_student_id_student",
    "mastery_branch_snapshot": "fk_mastery_branch_snapshot_student_id_student",
    "misconception_note": "fk_misconception_note_student",
}


def upgrade() -> None:
    # --- 1 · The durable identity.
    op.create_table(
        "person",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        # Where a parent's erasure request lands. Names nulled, the uid and the
        # pedagogical record kept — so a class statistic does not silently
        # change shape and a band already shown to a parent still reconciles.
        # Nothing writes it in this release; the endpoint is H5's, in Phase 4.
        sa.Column("anonymised_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["school.id"],
            name="fk_person_school_id_school",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_person"),
    )
    op.create_index("ix_person_school_id", "person", ["school_id"])

    # `person` is SchoolScopedMixin, so it needs its own policy written here.
    # 0024's table list is a frozen snapshot on purpose and does not grow; what
    # keeps a new scoped table from being forgotten is `scripts/check-rls.py`,
    # which derives its expectation from the models and fails CI on a table
    # with RLS on and no policy.
    op.execute('ALTER TABLE "person" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "person" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation ON "person" '
        f"USING (school_id = {CURRENT_SCHOOL}) "
        f"WITH CHECK (school_id = {CURRENT_SCHOOL})"
    )

    # --- 2 · One person per existing student, 1:1.
    #
    # The uuid is minted on `student` first and the `person` row inserted from
    # it, because `INSERT ... RETURNING` cannot hand back the source row it was
    # built from. Names and timestamps come from the student: the honest answer
    # to "when did this person appear in this school" is the moment the roster
    # paste created their row, and it is sitting right there — the same
    # reasoning 0019 and 0021 used.
    op.add_column(
        "student", sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.execute(
        sa.text("UPDATE student SET person_id = gen_random_uuid() WHERE person_id IS NULL")
    )
    op.execute(
        sa.text(
            """
            INSERT INTO person (id, school_id, first_name, last_name, created_at, updated_at)
            SELECT s.person_id, s.school_id, s.first_name, s.last_name,
                   s.created_at, s.updated_at
            FROM student s
            ON CONFLICT DO NOTHING
            """
        )
    )
    op.create_foreign_key(
        "fk_student_person_id_person",
        "student",
        "person",
        ["person_id"],
        ["id"],
        # A person's every year goes with them. `student` is the year-bound
        # record; deleting the identity deletes the enrolments, and through
        # them the evidence — which is what makes `delete_student` still able
        # to destroy a pupil's record once it deletes the person too.
        ondelete="CASCADE",
    )
    op.alter_column("student", "person_id", nullable=False)
    op.create_index("ix_student_person_id", "student", ["person_id"])

    # --- 3 · The longitudinal tables follow the person.
    for table, old_fk in _OLD_FKS.items():
        op.drop_constraint(old_fk, table, type_="foreignkey")
        op.alter_column(table, "student_id", new_column_name="person_id")
        # The column now holds a `student.id`, which is not a `person.id` any
        # more. Rewriting it through the mapping created in step 2 is what
        # makes every existing row point at the person of exactly the student
        # it pointed at before.
        op.execute(
            sa.text(
                f"UPDATE {table} t SET person_id = s.person_id "
                "FROM student s WHERE t.person_id = s.id"
            )
        )
        op.create_foreign_key(
            f"fk_{table}_person_id_person",
            table,
            "person",
            ["person_id"],
            ["id"],
            ondelete="CASCADE",
        )
        for old_name, new_name in _RENAMED_INDEXES[table]:
            op.execute(f"ALTER INDEX {old_name} RENAME TO {new_name}")

    # The anti-double-count backstop keeps its shape and changes its noun. A
    # sheet belongs to one class in one school year and a person has at most
    # one `student` row per year, so per-person uniqueness selects exactly the
    # rows per-student uniqueness selected.
    op.execute(
        "ALTER TABLE attempt RENAME CONSTRAINT uq_attempt_student_exercise_sheet "
        "TO uq_attempt_person_exercise_sheet"
    )


def downgrade() -> None:
    """Lossy for anything the split made possible, and only for that.

    A pupil with two years of ``student`` rows loses the link between them and
    every attempt collapses onto whichever row the mapping resolves first —
    which is the pre-change state, where the two rows were strangers anyway.
    With one student per person, the state this migration was applied to, the
    reversal is exact.
    """
    op.execute(
        "ALTER TABLE attempt RENAME CONSTRAINT uq_attempt_person_exercise_sheet "
        "TO uq_attempt_student_exercise_sheet"
    )

    for table, old_fk in _OLD_FKS.items():
        for old_name, new_name in _RENAMED_INDEXES[table]:
            op.execute(f"ALTER INDEX {new_name} RENAME TO {old_name}")
        op.drop_constraint(f"fk_{table}_person_id_person", table, type_="foreignkey")
        # Back through the mapping, the other way. `DISTINCT ON` because a
        # person may by then own several student rows and the old column can
        # hold only one; the earliest year is the one that carried the record
        # before the split.
        op.execute(
            sa.text(
                f"UPDATE {table} t SET person_id = s.id "
                "FROM (SELECT DISTINCT ON (person_id) person_id, id FROM student "
                "ORDER BY person_id, created_at) s "
                "WHERE t.person_id = s.person_id"
            )
        )
        op.alter_column(table, "person_id", new_column_name="student_id")
        op.create_foreign_key(
            old_fk, table, "student", ["student_id"], ["id"], ondelete="CASCADE"
        )

    op.drop_index("ix_student_person_id", table_name="student")
    op.drop_constraint("fk_student_person_id_person", "student", type_="foreignkey")
    op.drop_column("student", "person_id")

    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "person"')
    op.drop_index("ix_person_school_id", table_name="person")
    op.drop_table("person")
