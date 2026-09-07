"""Scan correction integrity — the columns F2 needed and did not have.

Five separate holes, one migration, because they are all the same story: the
scan pipeline could not say what it had actually read.

* ``scan.storage_keys`` — a phone upload is one file per copy. The teacher
  selects 28 photos and expects one review session, not 28 scans.
* ``scan.layout_version`` — a page must be registered against the layout it was
  *printed* with, so the version travels with the pile rather than being
  whatever the code happens to implement today.
* ``scan_page.wrong_class`` / ``discarded`` / ``page_in_copy`` — a page can be
  last week's pile, or a cover sheet, and one of those must not be able to hold
  a whole class set hostage.
* ``detection.exercise_id`` / ``printed_number`` — a differentiated copy prints
  its own item list, so "item 3 of the sheet" is not "item 3 of this paper". The
  pairing is now recorded rather than re-derived from a position, along with the
  number the student actually sees beside the question.
* ``detection.machine_*`` — the teacher's override used to be written over the
  machine's reading. Both are kept now; the disagreement is the audit trail.
* ``uq_attempt_student_exercise_sheet`` — re-scanning a pile corrects the
  record instead of doubling it.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# The type already exists (created by 0001 for detection.outcome); the new
# machine_outcome column reuses it and must not try to create it again.
_OUTCOME = postgresql.ENUM(name="detection_outcome", create_type=False)


def upgrade() -> None:
    op.add_column("scan", sa.Column("storage_keys", postgresql.JSONB(), nullable=True))
    op.add_column("scan", sa.Column("layout_version", sa.String(length=10), nullable=True))

    op.add_column(
        "scan_page",
        sa.Column("wrong_class", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "scan_page",
        sa.Column("discarded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("scan_page", sa.Column("page_in_copy", sa.Integer(), nullable=True))

    op.add_column(
        "detection",
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_detection_exercise_id_exercise",
        "detection",
        "exercise",
        ["exercise_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("detection", sa.Column("printed_number", sa.Integer(), nullable=True))
    op.add_column("detection", sa.Column("machine_index", sa.Integer(), nullable=True))
    op.add_column("detection", sa.Column("machine_outcome", _OUTCOME, nullable=True))
    op.add_column("detection", sa.Column("machine_confidence", sa.Float(), nullable=True))

    # Existing rows: whatever is in the row is the machine's reading unless a
    # teacher already corrected it, in which case the original is genuinely
    # gone and NULL is the honest answer.
    op.execute(
        """
        UPDATE detection
           SET machine_index = detected_index,
               machine_outcome = outcome,
               machine_confidence = confidence
         WHERE corrected_at IS NULL
        """
    )

    # Collapse any duplicates the old code already wrote, keeping the most
    # recent, so the constraint can be created on existing databases.
    op.execute(
        """
        DELETE FROM attempt a
         USING attempt b
         WHERE a.student_id = b.student_id
           AND a.exercise_id = b.exercise_id
           AND a.sheet_id IS NOT DISTINCT FROM b.sheet_id
           AND (a.created_at, a.id) < (b.created_at, b.id)
        """
    )
    op.create_unique_constraint(
        "uq_attempt_student_exercise_sheet",
        "attempt",
        ["student_id", "exercise_id", "sheet_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_attempt_student_exercise_sheet", "attempt", type_="unique")
    op.drop_column("detection", "machine_confidence")
    op.drop_column("detection", "machine_outcome")
    op.drop_column("detection", "machine_index")
    op.drop_column("detection", "printed_number")
    op.drop_constraint("fk_detection_exercise_id_exercise", "detection", type_="foreignkey")
    op.drop_column("detection", "exercise_id")
    op.drop_column("scan_page", "page_in_copy")
    op.drop_column("scan_page", "discarded")
    op.drop_column("scan_page", "wrong_class")
    op.drop_column("scan", "layout_version")
    op.drop_column("scan", "storage_keys")
