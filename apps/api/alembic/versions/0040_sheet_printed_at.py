"""When a sheet went to the photocopier, as a column.

The fact existed — `POST /sheets/{id}/printed` has recorded a `SHEET_PRINTED`
event since it was written — but only in the event log. So "has this sheet been
printed", which is the question a teacher's list of sheets is really asking,
could only be answered by paging `/timeline` and reading an audit trail
sideways (audit 02, M13).

Not `rendered_at`, which is when the PDF was built and is often days earlier: a
teacher renders on Sunday and prints on Tuesday morning.

A column rather than a lookup in the serialiser because `sheet_out` is pure by
design — it takes what it needs as arguments and never queries — and a queried
field would fan out one event query per row of `GET /sheets`.

The backfill is exact rather than approximate. `event_backfill.py` is explicit
that no `SHEET_PRINTED` event is ever manufactured from timestamps, so every
row in the log is a real printing that really happened, and the earliest one
per sheet is when that sheet was first printed. Sheets never printed keep NULL,
which is the honest answer and not a guess at one.

The enum literals are the member NAMES, not their values. `Enum(EventKind)` is
declared without `values_callable`, so SQLAlchemy stores `SHEET_PRINTED` and
not `sheet_printed` — 0015 compares them the same way. Written the other way
round this backfill matches zero rows and reports success, which is worse than
failing.

`occurred_at` rather than `created_at`: the first is when the printing
happened, the second when the row was written, and `record()` takes the former
as an argument precisely so the two can differ.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sheet", sa.Column("printed_at", sa.DateTime(timezone=True), nullable=True))
    # The FIRST printing, not the latest: the column answers "when did this go
    # to the photocopier", and a sheet reprinted in March was still printed in
    # November. Every occurrence stays in the timeline.
    op.execute(
        """
        UPDATE sheet
           SET printed_at = first_print.at
          FROM (
                SELECT subject_id AS sheet_id, MIN(occurred_at) AS at
                  FROM event
                 WHERE kind = 'SHEET_PRINTED'
                   AND subject_type = 'SHEET'
              GROUP BY subject_id
               ) AS first_print
         WHERE sheet.id = first_print.sheet_id
        """
    )


def downgrade() -> None:
    op.drop_column("sheet", "printed_at")
