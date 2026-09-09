"""Reopening a confirmed pile, and knowing which confirmation wrote a grade.

Two facts the schema could not express:

* **Which confirmation wrote an attempt.** `Attempt.detection_id` names the
  reading, but a later scan of the same copy supersedes the row in place, so
  the detection alone cannot say which pile currently owns the grade. Without
  that, reopening a pile has nothing to undo. The backfill below is exact
  rather than approximate: `confirm_scan` sets `detection_id` on both the
  create and the supersede branch, so `detection -> scan_page -> scan` recovers
  the owning scan for every row that exists today.

* **That a pile has been signed off before.** `confirmed_at`,
  `confirmation_count` and `reopened_at` carry the history. Deliberately NOT a
  fourth `ScanStatus`: `status` answers "is this pile signed off?", and a
  revised pile still answers yes. A new enum member would turn every
  `is ScanStatus.CONFIRMED` check into a two-member test and each one missed
  would silently unlock a pile. The teacher-facing label is derived (D48).

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scan", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scan", sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "scan",
        sa.Column("confirmation_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column(
        "attempt", sa.Column("confirmed_scan_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_attempt_confirmed_scan_id_scan",
        "attempt",
        "scan",
        ["confirmed_scan_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Reopening selects every attempt of one scan; without this it is a table
    # scan of the whole term's grades to undo one pile.
    op.create_index("ix_attempt_confirmed_scan_id", "attempt", ["confirmed_scan_id"])

    # The enum stores member NAMES, not values (SQLAlchemy's default for
    # `Enum(PyEnum)`), so the new kind is added as SCAN_REOPENED — and it must
    # be added at all, or the first reopen fails on an unknown label at
    # runtime rather than here. PG 12+ allows this inside a transaction as long
    # as the new value is not USED in the same transaction; it is not.
    op.execute("ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'SCAN_REOPENED'")

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE attempt SET confirmed_scan_id = sp.scan_id "
            "FROM detection d JOIN scan_page sp ON sp.id = d.scan_page_id "
            "WHERE attempt.detection_id = d.id"
        )
    )

    # The agenda records the moment a pile was confirmed, and `confirm_scan`
    # stamps the event and the attempts from the same instant — so where an
    # event exists it is the true confirmation time.
    bind.execute(
        sa.text(
            "UPDATE scan SET confirmed_at = sub.occurred_at, confirmation_count = 1 "
            "FROM (SELECT subject_id, MAX(occurred_at) AS occurred_at FROM event "
            "      WHERE kind = 'SCAN_CONFIRMED' GROUP BY subject_id) AS sub "
            "WHERE scan.id = sub.subject_id AND scan.status = 'CONFIRMED'"
        )
    )
    # A pile confirmed before the event log existed has no such row. Fall back
    # to `updated_at` so it still orders correctly against a later scan rather
    # than sorting last for want of a timestamp.
    bind.execute(
        sa.text(
            "UPDATE scan SET confirmed_at = updated_at, confirmation_count = 1 "
            "WHERE status = 'CONFIRMED' AND confirmed_at IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_attempt_confirmed_scan_id", table_name="attempt")
    op.drop_constraint("fk_attempt_confirmed_scan_id_scan", "attempt", type_="foreignkey")
    op.drop_column("attempt", "confirmed_scan_id")
    op.drop_column("scan", "confirmation_count")
    op.drop_column("scan", "reopened_at")
    op.drop_column("scan", "confirmed_at")
