"""A pupil's names can be removed without removing the pupil.

Until now the only answer to a parent's erasure request was `delete_student`,
which destroys the attempts, the snapshots and the notes along with the child.
That silently changes every class statistic they contributed to — a band a
teacher showed a parent in March stops matching itself in April — and it is a
heavier answer than most requests actually ask for.

Anonymisation is the default answer instead (database audit H5, delta 3): the
names go, the uid and the whole pedagogical record stay. Hard delete remains
for the cases that genuinely need it.

Four columns, not two. 0028 moved the durable identity to `person` but left a
copy of the names on each year's `student` row, so nulling only `person` would
leave the name on every roster, every printed sheet's instance list, and every
`StudentOut` the API serves. Both tables or neither.

NULL rather than a placeholder. A placeholder is a value in a name column that
every reader — a query, an export, a teacher scanning a list — has to be told
the meaning of, and one that is indistinguishable from a real name to anything
that has not been told. NULL says "there is no name here" in the only way a
database can, and `person.anonymised_at` carries the intent.

Nothing is backfilled: no pupil has been anonymised, because until this
migration there was no way to.

**Not reversible in substance.** `downgrade()` restores the constraint, but it
cannot restore a name that was nulled — it will fail against any row that has
been anonymised, which is correct. Erasing an erasure is not a schema
operation.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

_COLUMNS = (("person", "first_name"), ("person", "last_name"),
            ("student", "first_name"), ("student", "last_name"))


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(table, column, existing_type=sa.String(100), nullable=True)


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(table, column, existing_type=sa.String(100), nullable=False)
