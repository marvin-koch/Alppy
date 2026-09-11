"""One year per label, and one current year per school.

`school_year` carried neither constraint (database audit H8), and both matter
for the same reason 0036 pinned the label's *format*: `current_school_year`
resolves a year BY LABEL when no row is marked current, and `Student.uid` is
unique per `(school_id, school_year_id)`. Two rows that a human would read as
the same year are two rosters and two sets of UIDs, and a class created in the
wrong one is not visibly wrong from any screen.

**`uq_school_year_label` — UNIQUE (school_id, label).** 0036 made "2026/2027"
unwritable; this makes a *second* "2026/27" unwritable. The pair is the point:
a format check stops one way of spelling the same year differently, and a
uniqueness constraint stops the same spelling twice.

**`uq_school_year_current` — UNIQUE (school_id) WHERE is_current.** A school has
one current year or none. Nothing enforced it, and the read that depends on it
(`current_school_year`) papers over the ambiguity with `ORDER BY starts_on DESC
LIMIT 1` — so a second current row would not raise anywhere, it would just make
"the current year" mean whichever row sorted first that day.

Note the existing write path cannot produce that state on its own: it flips
`is_current` only on the branch where the first query found no current row at
all. The constraint is there for the paths that do not exist yet — a rollover,
an import, a psql session — which is the moment it is cheapest to add.

**The backfill is a repair, and only for `is_current`.** Any school carrying
more than one current year keeps the latest by `starts_on` and loses the flag
on the rest; the rows themselves are untouched, and `is_current` is a cache of
something `starts_on`/`ends_on` already say, so nothing is lost that cannot be
recomputed. Ordering is `starts_on DESC, id` so the choice is deterministic
rather than whatever the heap returns.

Duplicate *labels* are deliberately NOT repaired. Merging two years would mean
choosing which roster, which UIDs and which attempts survive, and a migration
is the wrong place to decide that: if any exist this migration fails on the
constraint, loudly, with the school and label in the error. Nothing in the
seeds or the current write paths can create one.

Revision ID: 0044
Revises: 0043
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

LABEL_UNIQUE = "uq_school_year_label"
CURRENT_UNIQUE = "uq_school_year_current"


def upgrade() -> None:
    # Keep the latest current year per school; clear the flag on the rest.
    # `starts_on DESC, id` so two years starting the same day resolve the same
    # way on every database this runs against.
    op.execute(
        sa.text(
            """
            UPDATE school_year SET is_current = false
            WHERE is_current AND id NOT IN (
                SELECT DISTINCT ON (school_id) id
                FROM school_year
                WHERE is_current
                ORDER BY school_id, starts_on DESC, id
            )
            """
        )
    )

    op.create_unique_constraint(LABEL_UNIQUE, "school_year", ["school_id", "label"])
    op.create_index(
        CURRENT_UNIQUE,
        "school_year",
        ["school_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )


def downgrade() -> None:
    """Not lossy: the repair above is not undone, and does not need to be.

    A school that had two current years ends with one, and going back does not
    restore the second — but "two current years" was never a state the product
    could read, only one it could hold.
    """
    op.drop_index(CURRENT_UNIQUE, table_name="school_year")
    op.drop_constraint(LABEL_UNIQUE, "school_year", type_="unique")
