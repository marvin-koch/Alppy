"""A sheet may answer several sheets, and one of them is the principal.

``sheet.derived_from_id`` records the common sheet a differentiated batch
answers, and D61 made it ownership-checked. But it holds exactly one row, and a
reprise legitimately answers more than one thing: the test whose results
triggered it, and the two earlier worksheets whose gaps it revisits. There was
nowhere to say so, and "which sheets is this one about" had no answer beyond a
single parent.

``sheet_source`` is that answer. The column stays, because the two facts are
different: ``derived_from_id`` is where the sheet HANGS — what the feedback page
prints, what the tree draws, what D61 validates — and the table is what it is
ABOUT. Position 0 is the principal and is the same sheet as the column, written
together and asserted equal in ``sheet_service.set_sources``; a lineage where
the feedback page names one sheet and the tree draws another would be worse than
no lineage at all.

This is D56's shape a third time, after ``chapter.primary_competency_id`` and
``student.home_class_id``: where a row sits is a column, what it belongs to is a
join table.

``source_sheet_id`` cascades rather than SET NULL — a composite primary key
cannot hold a null. Deleting a source sheet shortens the chain; it never leaves
a lineage row pointing at a sheet that is gone.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sheet_source",
        sa.Column("sheet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_sheet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["sheet_id"],
            ["sheet.id"],
            name="fk_sheet_source_sheet_id_sheet",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_sheet_id"],
            ["sheet.id"],
            name="fk_sheet_source_source_sheet_id_sheet",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("sheet_id", "source_sheet_id", name="pk_sheet_source"),
    )
    # "Which sheets answered this one" — the reverse direction, which is what a
    # sheet detail page asks to draw the rest of the teaching unit.
    op.create_index(
        "ix_sheet_source_source_sheet_id", "sheet_source", ["source_sheet_id"]
    )

    # Backfill: every existing lineage is a single principal, so it becomes
    # position 0 and the column and the table agree from the first row.
    op.execute(
        sa.text(
            """
            INSERT INTO sheet_source (sheet_id, source_sheet_id, position)
            SELECT id, derived_from_id, 0 FROM sheet WHERE derived_from_id IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    """Lossy beyond the principal, which `derived_from_id` already holds."""
    op.drop_index("ix_sheet_source_source_sheet_id", table_name="sheet_source")
    op.drop_table("sheet_source")
