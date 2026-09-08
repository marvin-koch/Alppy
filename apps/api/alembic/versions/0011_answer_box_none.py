"""A written-answer box may be switched off: 0 lines.

A textbook exercise is often worked in the notebook, as the book intends, and
a teacher who wants that keeps the picture and drops the box. 0 joins the four
presets in the check constraint; nothing else changes.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_NAME = "ck_sheet_item_answer_box_lines"


def upgrade() -> None:
    op.drop_constraint(_NAME, "sheet_item", type_="check")
    op.create_check_constraint(
        _NAME, "sheet_item", "answer_box_lines IS NULL OR answer_box_lines IN (0, 3, 5, 8, 12)"
    )


def downgrade() -> None:
    op.drop_constraint(_NAME, "sheet_item", type_="check")
    op.create_check_constraint(
        _NAME, "sheet_item", "answer_box_lines IS NULL OR answer_box_lines IN (3, 5, 8, 12)"
    )
