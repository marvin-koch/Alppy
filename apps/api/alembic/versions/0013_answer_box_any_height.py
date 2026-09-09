"""A written-answer box may be any height up to the page's ceiling.

The four presets (3, 5, 8, 12 lines) were the only values the check allowed.
They stay as shortcuts in the builder; the constraint now admits any height
from 0 (no box) to 14 lines, the tallest box that still fits the statement
region on its own once carried to the next page.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_NAME = "ck_sheet_item_answer_box_lines"


def upgrade() -> None:
    op.drop_constraint(_NAME, "sheet_item", type_="check")
    op.create_check_constraint(
        _NAME, "sheet_item", "answer_box_lines IS NULL OR answer_box_lines BETWEEN 0 AND 14"
    )


def downgrade() -> None:
    # Rows with a non-preset height would violate the old constraint.
    op.execute(
        "UPDATE sheet_item SET answer_box_lines = NULL "
        "WHERE answer_box_lines IS NOT NULL AND answer_box_lines NOT IN (0, 3, 5, 8, 12)"
    )
    op.drop_constraint(_NAME, "sheet_item", type_="check")
    op.create_check_constraint(
        _NAME, "sheet_item", "answer_box_lines IS NULL OR answer_box_lines IN (0, 3, 5, 8, 12)"
    )
