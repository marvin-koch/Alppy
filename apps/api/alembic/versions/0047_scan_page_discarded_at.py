"""Discarding a page records who did it and when.

``scan_page.discarded`` was a bare boolean (database audit M6). Throwing a
page out of a pile is a **teacher's decision** that removes a copy — and with
it a pupil's marks — from everything downstream: grading skips it, the results
screen omits it, and the mastery recompute never sees it. The row recorded that
it had happened and nothing else. Asked in June why a pupil has no mark for the
February sheet, there was no answer in the database.

``discarded_at`` / ``discarded_by_id``, which is the shape this codebase
already uses for every other reversible human act — ``approved_at``,
``corrected_at`` / ``corrected_by_id``, ``confirmed_at``, ``anonymised_at``.

**Only this one of the three booleans.** ``registered`` and ``wrong_class``
stay exactly as they are, and that is a decision rather than an omission. They
are not events: ``registered`` is whether fiducial registration succeeded, and
``wrong_class`` is a *classification* the pipeline recomputes — a property of
the page, re-derived every time it is processed. A timestamp on a derived
property invites the reader to believe it marks the moment something happened,
when re-running the pipeline would move it. The audit grouped all three; the
thing they have in common is the column type, not the meaning.

**The backfill cannot know who, and does not guess.** ``discarded_at`` takes
``updated_at`` — the moment the row last changed, which for a discarded page is
the discard itself or later, and is the honest answer sitting right there, the
same reasoning 0019 and 0021 used. ``discarded_by_id`` stays NULL: nothing
recorded the actor, and inventing one — the scan's uploader, the class's head
teacher — would put a name against an act that person may not have performed.
NULL means "before this column existed", and every row written from now on has
a real one.

The API contract does not move. ``ScanPageOut.discarded`` stays a boolean,
derived from whether the timestamp is set, so no client changes.

Revision ID: 0047
Revises: 0046
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

#: **This migration cannot be rolled back** (docs/runbook/rollback.md).
#: Drops the boolean this replaces with a timestamp-and-actor. The timestamp
#: can be recomputed into a boolean; the actor and the moment cannot.
#:
#: Checked by scripts/check-migration-safety.py, so the rule is a gate
#: rather than something a reviewer has to remember on a Friday.
DESTRUCTIVE = True

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scan_page",
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scan_page",
        sa.Column("discarded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_scan_page_discarded_by_id_teacher",
        "scan_page",
        "teacher",
        ["discarded_by_id"],
        ["id"],
        # SET NULL, like every other actor column: deleting an account must not
        # delete the fact that a page was discarded, only who is on record for
        # it. The same rule `Detection.corrected_by_id` follows.
        ondelete="SET NULL",
    )

    op.execute(
        sa.text("UPDATE scan_page SET discarded_at = updated_at WHERE discarded")
    )
    op.drop_column("scan_page", "discarded")


def downgrade() -> None:
    """Lossy in exactly one direction: the actor and the moment are dropped.

    Whether a page was discarded survives; who discarded it does not, because
    the boolean has nowhere to put it.
    """
    op.add_column(
        "scan_page",
        sa.Column(
            "discarded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute(
        sa.text("UPDATE scan_page SET discarded = true WHERE discarded_at IS NOT NULL")
    )
    op.drop_constraint("fk_scan_page_discarded_by_id_teacher", "scan_page", type_="foreignkey")
    op.drop_column("scan_page", "discarded_by_id")
    op.drop_column("scan_page", "discarded_at")
