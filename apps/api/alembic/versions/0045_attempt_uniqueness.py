"""The anti-double-count backstop stops having a hole, and gains a partition key.

Two findings on one constraint, and they pull in opposite directions, so both
are spelled out.

**M4 · the NULL hole.** ``uq_attempt_person_exercise_sheet`` covers
``(person_id, exercise_id, sheet_id)``, and ``sheet_id`` is NULLABLE — an
attempt whose sheet was deleted keeps the mark and loses the reference. In
Postgres two NULLs are distinct inside a unique index, so the constraint
stopped covering exactly the rows that most needed it: every sheetless attempt
for one pupil and one exercise was unique against every other one, and the
backstop was silently off for them. ``NULLS NOT DISTINCT`` (Postgres 15+, and
we run 16) closes it: NULL equals NULL for the purposes of this constraint,
which is what "one attempt per pupil per exercise per sheet, and no sheet is a
sheet" has to mean.

**M7 · ``answered_at`` joins the key.** Postgres requires the partition key in
every unique constraint on a partitioned table, so a later decision to
partition ``attempt`` by time would have to change this constraint — and
changing a uniqueness rule on a table holding a term of marking is a different
proposition from changing one on a table holding a demo seed. This is the
cheap moment, and it was taken deliberately.

**It costs something, and the cost is written down here rather than discovered
later.** ``Attempt.answered_at`` is ``scan.created_at``
(``scan_service._answered_at``), so re-uploading the same pile as a NEW scan
produces a DIFFERENT ``answered_at`` — and with that column in the key the two
rows no longer collide. The database therefore stops being able to guarantee
what its own comment claims: that re-scanning corrects the record rather than
doubling it.

Nothing changes today, because ``confirm_scan`` looks its row up on
``(person_id, exercise_id, sheet_id, school_id)`` — without ``answered_at`` —
and UPDATEs what it finds. The guarantee moves from the schema to that lookup,
which is a worse place for it, so the suite now pins it directly:
``test_a_rescan_on_another_day_still_supersedes`` fails if a future path ever
inserts where it should supersede. That test is the replacement backstop; do
not delete it without restoring the constraint.

**The better fix, deliberately not taken here.** If ``answered_at`` were the
date the sheet was *printed* (``Sheet.printed_at``, since 0040) rather than the
moment its pile was uploaded, it would be stable across re-scans — the tuple
would be identical, uniqueness would still collapse duplicates, and a pile
scanned three weeks late would stop dating every attempt in it to the scan,
which the decay model reads as recency. That is a change to what the mastery
model is fed, and it belongs to its own decision with its own review, not to a
migration about a constraint.

Reversible: the downgrade restores the three-column, NULLS-DISTINCT form. It
can fail, and honestly should, if rows have accumulated that the old constraint
forbids — two attempts for one pupil, exercise and sheet at different times.
That is data the old shape cannot hold, and a migration must not choose which
of them to delete.

Revision ID: 0045
Revises: 0044
"""

from __future__ import annotations

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

NAME = "uq_attempt_person_exercise_sheet"


def upgrade() -> None:
    op.drop_constraint(NAME, "attempt", type_="unique")
    # Written as raw DDL because `create_unique_constraint` has no argument for
    # NULLS NOT DISTINCT; the model carries `postgresql_nulls_not_distinct`, so
    # `check-schema-drift.py` still compares the two.
    op.execute(
        f"ALTER TABLE attempt ADD CONSTRAINT {NAME} "
        "UNIQUE NULLS NOT DISTINCT (person_id, exercise_id, sheet_id, answered_at)"
    )


def downgrade() -> None:
    op.drop_constraint(NAME, "attempt", type_="unique")
    op.create_unique_constraint(NAME, "attempt", ["person_id", "exercise_id", "sheet_id"])
