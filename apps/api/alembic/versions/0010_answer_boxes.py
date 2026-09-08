"""Written-answer boxes, read by a vision model.

An ``open`` item used to print four ruled lines and stop there: printed, never
auto-graded. It now prints a delimited box whose size and fill the teacher
chooses per sheet item, the render job records where every box actually landed
on every student's copy, the scan job crops it, and a vision model proposes a
transcription and a verdict the teacher confirms.

* ``sheet_item.answer_box_lines`` / ``answer_box_fill`` — the teacher's choice.
* ``answer_box_placement`` — the measured rectangle, per copy and page. Written
  at render time and replaced on re-render, so an edit made after the pile was
  printed cannot move what the scanner crops.
* ``detection`` gains the crop key, the transcription and the verdict, each in
  the current/machine pair the bubbles already use, plus the model name.
* ``detection_outcome`` gains ``PENDING``: cropped, awaiting the grader.
* ``job_kind`` gains ``GRADE_OPEN_ANSWERS``, chained after ``PROCESS_SCAN``.

Enums store the member NAME (see ``_ENUMS`` in 0001). Adding a value to a
Postgres enum cannot share a transaction with DDL that then uses that value,
so the two ``ALTER TYPE`` statements are committed on their own first, as
0005 and 0006 do. ``answer_box_fill`` is a new type and is created outright.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_FILL = ("LINED", "GRID", "BLANK")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("COMMIT")
        op.execute("ALTER TYPE detection_outcome ADD VALUE IF NOT EXISTS 'PENDING'")
        op.execute("ALTER TYPE job_kind ADD VALUE IF NOT EXISTS 'GRADE_OPEN_ANSWERS'")
        postgresql.ENUM(*_FILL, name="answer_box_fill").create(bind, checkfirst=True)

    op.add_column("sheet_item", sa.Column("answer_box_lines", sa.Integer(), nullable=True))
    op.add_column(
        "sheet_item",
        sa.Column(
            "answer_box_fill",
            postgresql.ENUM(*_FILL, name="answer_box_fill", create_type=False),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_sheet_item_answer_box_lines",
        "sheet_item",
        "answer_box_lines IS NULL OR answer_box_lines IN (3, 5, 8, 12)",
    )

    op.create_table(
        "answer_box_placement",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sheet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("student_uid", sa.String(length=20), nullable=False),
        sa.Column("copy_page", sa.Integer(), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("box_lines", sa.Integer(), nullable=False),
        sa.Column(
            "box_fill",
            postgresql.ENUM(*_FILL, name="answer_box_fill", create_type=False),
            nullable=False,
        ),
        sa.Column("x_mm", sa.Float(), nullable=False),
        sa.Column("y_mm", sa.Float(), nullable=False),
        sa.Column("w_mm", sa.Float(), nullable=False),
        sa.Column("h_mm", sa.Float(), nullable=False),
        sa.Column("layout_version", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_answer_box_placement"),
        sa.ForeignKeyConstraint(
            ["school_id"], ["school.id"], name="fk_answer_box_placement_school", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sheet_id"], ["sheet.id"], name="fk_answer_box_placement_sheet", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercise.id"],
            name="fk_answer_box_placement_exercise",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "sheet_id", "student_uid", "copy_page", "item_index",
            name="uq_answer_box_placement_slot",
        ),
    )
    op.create_index("ix_answer_box_placement_school_id", "answer_box_placement", ["school_id"])
    op.create_index("ix_answer_box_placement_sheet_id", "answer_box_placement", ["sheet_id"])
    op.create_index(
        "ix_answer_box_placement_exercise_id", "answer_box_placement", ["exercise_id"]
    )

    op.add_column("detection", sa.Column("crop_key", sa.String(length=500), nullable=True))
    op.add_column("detection", sa.Column("transcription", sa.Text(), nullable=True))
    op.add_column("detection", sa.Column("machine_transcription", sa.Text(), nullable=True))
    op.add_column("detection", sa.Column("verdict_correct", sa.Boolean(), nullable=True))
    op.add_column(
        "detection", sa.Column("machine_verdict_correct", sa.Boolean(), nullable=True)
    )
    op.add_column("detection", sa.Column("vision_model", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("detection", "vision_model")
    op.drop_column("detection", "machine_verdict_correct")
    op.drop_column("detection", "verdict_correct")
    op.drop_column("detection", "machine_transcription")
    op.drop_column("detection", "transcription")
    op.drop_column("detection", "crop_key")

    op.drop_index("ix_answer_box_placement_exercise_id", table_name="answer_box_placement")
    op.drop_index("ix_answer_box_placement_sheet_id", table_name="answer_box_placement")
    op.drop_index("ix_answer_box_placement_school_id", table_name="answer_box_placement")
    op.drop_table("answer_box_placement")

    op.drop_constraint("ck_sheet_item_answer_box_lines", "sheet_item", type_="check")
    op.drop_column("sheet_item", "answer_box_fill")
    op.drop_column("sheet_item", "answer_box_lines")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name="answer_box_fill").drop(bind, checkfirst=True)
    # Postgres cannot drop an enum value; PENDING and GRADE_OPEN_ANSWERS stay.
