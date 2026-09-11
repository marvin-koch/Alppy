"""A returned paper's total stops moving.

`points_earned` on a returned paper is the sum of `Attempt.score`, frozen when
the pile was confirmed. `points_possible` was recomputed live from
`SheetItem.points_correct` and `Sheet.default_points_correct` every time the
report was opened.

So the two halves of one fraction came from different moments. Editing the
barème after confirming rewrote the denominator of every paper already handed
back: 14/20 became 14/25, silently, on a sheet the class had taken home and a
parent may have signed.

Frozen **per copy**, not per attempt. An item the grader could not read produces
no `Attempt` at all — it is counted as skipped — so a sum over attempts would
leave those items out of what the paper was worth, which is a different number
from the one printed on the page.

NULL means the copy has never been confirmed, and the live computation still
applies to it: a sheet being previewed or edited must show the barème as it
stands now. Existing rows therefore keep behaving exactly as they do today, and
freeze the first time they are confirmed.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sheet_instance", sa.Column("points_possible", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sheet_instance", "points_possible")
