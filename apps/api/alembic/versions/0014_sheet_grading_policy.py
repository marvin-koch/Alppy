"""The teacher's barème: points for a correct answer, a penalty for a wrong one.

A sheet-level default plus an optional per-item override, the same shape as
`answer_box_lines` and `expected_answer` before it (0010, 0012). The item
columns are nullable and NULL means "use the sheet's default"; the sheet
columns are NOT NULL because they are what everything falls back to.

The penalty is stored as a magnitude, never as a negative number — the sign is
applied once, in `scan.grading.score_for`. That is why the check is a plain
`BETWEEN 0 AND 20` on both columns rather than a signed range.

A blank answer is not represented here at all: it is a graded zero (D5) and
`grading.py` settles it before the barème is ever consulted, so no value in
these columns can turn an unanswered item into a penalised one.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default is required on the sheet columns and only on those: the
    # table already has rows, and a NOT NULL column added without one fails on
    # them. The item columns are nullable, so they need none.
    op.add_column(
        "sheet",
        sa.Column("default_points_correct", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.add_column(
        "sheet",
        sa.Column("default_points_penalty", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.create_check_constraint(
        "ck_sheet_default_points_correct", "sheet", "default_points_correct BETWEEN 0 AND 20"
    )
    op.create_check_constraint(
        "ck_sheet_default_points_penalty", "sheet", "default_points_penalty BETWEEN 0 AND 20"
    )

    op.add_column("sheet_item", sa.Column("points_correct", sa.Float(), nullable=True))
    op.add_column("sheet_item", sa.Column("points_penalty", sa.Float(), nullable=True))
    op.create_check_constraint(
        "ck_sheet_item_points_correct",
        "sheet_item",
        "points_correct IS NULL OR points_correct BETWEEN 0 AND 20",
    )
    op.create_check_constraint(
        "ck_sheet_item_points_penalty",
        "sheet_item",
        "points_penalty IS NULL OR points_penalty BETWEEN 0 AND 20",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sheet_item_points_penalty", "sheet_item", type_="check")
    op.drop_constraint("ck_sheet_item_points_correct", "sheet_item", type_="check")
    op.drop_column("sheet_item", "points_penalty")
    op.drop_column("sheet_item", "points_correct")
    op.drop_constraint("ck_sheet_default_points_penalty", "sheet", type_="check")
    op.drop_constraint("ck_sheet_default_points_correct", "sheet", type_="check")
    op.drop_column("sheet", "default_points_penalty")
    op.drop_column("sheet", "default_points_correct")
