"""An answer box belongs to one render, not to a sheet.

`AnswerBoxPlacement` recorded where every written-answer box actually printed,
and every render deleted the lot and wrote them again. The model's own
docstring claimed this made it impossible for "an exercise edited after the
pile was printed" to move the rectangle the scanner crops. The delete-and-
rewrite was how it moved it:

    Tuesday    render, print 24 copies, hand them out
    Wednesday  fix a typo in item 3, re-render to run off a copy for an
               absentee — every rectangle for the sheet is deleted and
               rewritten at Wednesday's geometry
    Thursday   photograph Tuesday's 24 copies

Every crop is now cut at rows measured from a document those copies were never
printed from. A written answer cut at the wrong rows is graded on whatever ink
the crop happens to contain, and nothing anywhere records that it happened.

So a render gets a generation. `sheet.render_generation` counts up on every
render; `answer_box_placement.render_generation` says which render measured a
rectangle; `scan.render_generation` pins the one a pile was printed from, the
way `scan.layout_version` has always pinned the layout. The scan job asks for
the rectangles the paper in its hand was printed with.

**The unique constraint has to move with it.** `uq_answer_box_placement_slot`
was `(sheet_id, student_uid, copy_page, item_index)`, which is exactly what
made keeping the old rows impossible: a second render collides on every box.
The generation joins the key.

**Existing rows keep NULL, and that is the safe value.** A placement written
before this migration is matched only by a scan that also predates it, never by
a later render's crops. A pre-existing pile whose sheet is re-rendered after
this lands therefore finds no placements at all and its open items stay
`NOT_GRADEABLE` — no crop, no verdict, counted as skipped. That is the honest
direction: the pipeline already handles a missing crop, and it has no way to
handle one taken from the wrong page.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOT NULL with a server default: every existing sheet is generation 0, and
    # its next render becomes generation 1 — so no already-printed pile can
    # collide with a rectangle written after this migration.
    op.add_column(
        "sheet",
        sa.Column(
            "render_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    # Nullable on both of these, deliberately: NULL means "printed before
    # generations existed", and NULL matches NULL.
    op.add_column(
        "answer_box_placement", sa.Column("render_generation", sa.Integer(), nullable=True)
    )
    op.add_column("scan", sa.Column("render_generation", sa.Integer(), nullable=True))

    op.drop_constraint(
        "uq_answer_box_placement_slot", "answer_box_placement", type_="unique"
    )
    op.create_unique_constraint(
        "uq_answer_box_placement_slot",
        "answer_box_placement",
        ["sheet_id", "render_generation", "student_uid", "copy_page", "item_index"],
    )


def downgrade() -> None:
    # Going back means one generation's rectangles have to be the only ones,
    # and there is no way to choose which. The old constraint cannot be
    # recreated while several generations coexist, so the rows of every
    # generation but the newest are dropped — which is exactly the data loss
    # this migration exists to stop, and is why this direction is a last resort.
    op.execute(
        """
        DELETE FROM answer_box_placement a
        USING (
            SELECT sheet_id, MAX(render_generation) AS keep
            FROM answer_box_placement
            WHERE render_generation IS NOT NULL
            GROUP BY sheet_id
        ) newest
        WHERE a.sheet_id = newest.sheet_id
          AND a.render_generation IS DISTINCT FROM newest.keep
        """
    )
    op.drop_constraint(
        "uq_answer_box_placement_slot", "answer_box_placement", type_="unique"
    )
    op.create_unique_constraint(
        "uq_answer_box_placement_slot",
        "answer_box_placement",
        ["sheet_id", "student_uid", "copy_page", "item_index"],
    )
    op.drop_column("scan", "render_generation")
    op.drop_column("answer_box_placement", "render_generation")
    op.drop_column("sheet", "render_generation")
