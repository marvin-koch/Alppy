"""A membership ends, and the fact that it existed outlives it.

Three join tables carried a start and no end — ``class_student.enrolled_at``,
``class_teacher_subject.assigned_at``, ``teacher_school.joined_at`` — and
leaving was a ``DELETE``. The models say so, and give the reason:

    Provenance, not a state machine — there is deliberately no `left_at`: the
    moment one exists every roster read grows a temporal predicate and every
    test needs an injectable clock. Leaving a class is a deleted row.

That cost is real and this migration pays it. The trade was the wrong one for
Cycle 3, where pupils are streamed into maths niveaux *across* homerooms and
move between them mid-year, so the composition of a teaching group is a
snapshot that overwrites itself:

Léa is in the niveau-2 maths group and sits three worksheets there in October.
In February she moves to niveau 3, which is one ``DELETE``. From that moment
``mastery_service.class_matrix`` builds its roster from current enrolment, so
she vanishes from the niveau-2 matrix *including the October columns she sat*;
``_owned_student`` gates her profile on a current enrolment, so M. Rossier —
who taught her for six months and marked those three sheets — gets a 404; and
nothing anywhere records that she was ever in niveau 2. Her ``attempt`` rows
survive and are correctly attributed. They are simply unreachable through
every class-grained read the product has.

**Three columns, and the third is the one the audit did not ask for.**

* ``valid_from date NOT NULL`` / ``valid_to date NULL`` on all three tables.
* The primary key widens to include ``valid_from``, so re-enrolment after a
  gap is representable — Léa returning to niveau 2 in May is a second row, not
  a conflict.
* **A partial unique index on the open row.** Widening the PK alone would
  admit *two open memberships* for the same pair with different
  ``valid_from``, which double-counts that pupil in every roster join and
  every matrix. ``uq_class_student_open`` and its two siblings are what keep
  "at most one current membership" true, and they are also what ``enroll``'s
  ``ON CONFLICT DO NOTHING`` re-targets onto: keyed on the widened PK it would
  no longer see a second enrolment as a conflict at all.

**Why the backfill is behaviour-preserving.** ``valid_from`` takes the start
column already on the row — the honest answer to "when did this membership
begin" is sitting right there, the same reasoning 0019 and 0021 used for
``created_at`` — and ``valid_to`` is NULL for every existing row. After the
backfill **every row is open**, so ``valid_to IS NULL`` selects exactly the
rows an unqualified read selected before, and ``valid_from <= today`` is true
of all of them. No membership changes, no session is invalidated, and no
roster, matrix, tree or printed pile changes by one pupil. Nothing can create a
closed row until the ``UPDATE``-instead-of-``DELETE`` paths in this release
ship.

The cast is ``(enrolled_at AT TIME ZONE 'UTC')::date`` rather than a bare
``::date``, which would resolve through the session's ``TimeZone`` and give a
different answer for a membership created late in the evening depending on who
ran the migration.

**One policy moves.** ``school``'s RLS policy asks whether the current teacher
is a member of a school, which is an *entitlement* question, so it has to
respect validity or a teacher who left keeps seeing the staffroom they left.
The two association policies deliberately do NOT change: they ask whether a
row belongs to this tenant, and an ended membership belongs to that school
exactly as much as an open one — filtering them there would hide the history
this migration exists to keep.

Deliberately NOT renamed to ``group_membership``/``group_staffing`` (the
audit's deltas 3 and 4). Those names presuppose a ``teaching_group`` entity;
0026 chose ``class.kind`` over that split, so the names would be a promise the
schema does not keep. The "unreviewed read sites fail loudly" property those
renames buy is bought instead by making ``on`` a **required** keyword argument
on every subquery in ``services/enrollment.py`` — no existing call site
compiles until someone states which grain it wants.

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

#: table -> (start column, primary-key name, the key columns before widening)
_MEMBERSHIPS = {
    "class_student": (
        "enrolled_at",
        "pk_class_student",
        ("class_id", "student_id"),
    ),
    "class_teacher_subject": (
        "assigned_at",
        "pk_class_teacher_subject",
        ("class_id", "teacher_id", "subject_id"),
    ),
    "teacher_school": (
        "joined_at",
        "pk_teacher_school",
        ("teacher_id", "school_id"),
    ),
}

CURRENT_SCHOOL = "nullif(current_setting('app.current_school_id', true), '')::uuid"
CURRENT_TEACHER = "nullif(current_setting('app.current_teacher_id', true), '')::uuid"


def _open_index(table: str) -> str:
    return f"uq_{table}_open"


def upgrade() -> None:
    for table, (started, pk_name, key_columns) in _MEMBERSHIPS.items():
        # --- 1 · Added nullable, so the existing rows survive the ALTER; the
        # NOT NULL goes on in step 3 once every one of them has a value.
        op.add_column(table, sa.Column("valid_from", sa.Date(), nullable=True))
        op.add_column(table, sa.Column("valid_to", sa.Date(), nullable=True))

        # --- 2 · Backfill from the start column already on the row.
        op.execute(
            sa.text(
                # The table name is one of this module's own literals.
                f"UPDATE {table} "
                f"SET valid_from = ({started} AT TIME ZONE 'UTC')::date "
                "WHERE valid_from IS NULL"
            )
        )

        # --- 3 · Now it can be NOT NULL, and carry a default for the same
        # reason `enrolled_at` carries one: a write that does not name it (a
        # seed, a psql console, a fixture) should get the honest answer rather
        # than a constraint violation. 0025 is the migration that exists
        # because three tables were missing exactly this.
        op.alter_column(
            table,
            "valid_from",
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        )

        # --- 4 · The key widens so a gap-then-return is a second row.
        op.drop_constraint(pk_name, table, type_="primary")
        op.create_primary_key(pk_name, table, [*key_columns, "valid_from"])

        # --- 5 · ...and the partial unique index keeps "at most one CURRENT
        # membership" true, which the widened key on its own does not. This is
        # also the index `enroll`/`assign_branch` now name in ON CONFLICT.
        op.create_index(
            _open_index(table),
            table,
            list(key_columns),
            unique=True,
            postgresql_where=sa.text("valid_to IS NULL"),
        )

    # --- 6 · Entitlement respects validity; tenancy does not.
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON school")
    op.execute(
        "CREATE POLICY tenant_isolation ON school "
        f"USING (id = {CURRENT_SCHOOL} OR EXISTS ("
        "  SELECT 1 FROM teacher_school ts"
        f"  WHERE ts.school_id = school.id AND ts.teacher_id = {CURRENT_TEACHER}"
        "  AND ts.valid_to IS NULL"
        ")) "
        f"WITH CHECK (id = {CURRENT_SCHOOL} OR {CURRENT_SCHOOL} IS NULL)"
    )


def downgrade() -> None:
    """Lossy exactly where this migration is the point.

    An ended membership goes back to being unrepresentable, so every row
    carrying a ``valid_to`` is dropped rather than silently reappearing as a
    current one — a pupil who left niveau 2 must not come back onto that
    roster because the schema forgot how to say they had gone. A pair with two
    historical rows and no open one loses both, which is the pre-change state:
    before 0027 that pupil was a deleted row too.
    """
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON school")
    op.execute(
        "CREATE POLICY tenant_isolation ON school "
        f"USING (id = {CURRENT_SCHOOL} OR EXISTS ("
        "  SELECT 1 FROM teacher_school ts"
        f"  WHERE ts.school_id = school.id AND ts.teacher_id = {CURRENT_TEACHER}"
        ")) "
        f"WITH CHECK (id = {CURRENT_SCHOOL} OR {CURRENT_SCHOOL} IS NULL)"
    )

    for table, (_started, pk_name, key_columns) in _MEMBERSHIPS.items():
        op.execute(f"DELETE FROM {table} WHERE valid_to IS NOT NULL")

        op.drop_index(_open_index(table), table_name=table)
        op.drop_constraint(pk_name, table, type_="primary")
        op.create_primary_key(pk_name, table, list(key_columns))

        op.drop_column(table, "valid_to")
        op.drop_column(table, "valid_from")
