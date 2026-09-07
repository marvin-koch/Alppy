"""The foreign-key indexes the migrations and the models disagreed about.

``models._fk`` declares ``index=True`` on every foreign key, so SQLAlchemy's
metadata has an index for each one. Four of them were never created by the
migration that added the column, and one index exists in the database that the
models do not declare:

* ``detection.exercise_id``          — added in 0003, index missing
* ``exercise.source_section_id``     — added in 0005, index missing
* ``source_section.school_id``       — added in 0005, index missing
* ``source_section.source_id``       — added in 0005, index missing
* ``ix_exercise_discarded``          — created in 0004 on ``subject_id``,
  declared nowhere in the models

Harmless at today's row counts, and that is exactly why it survived: the cost
is not a slow query, it is that ``alembic revision --autogenerate`` proposed
these five on every run, so a real change arrived buried in noise nobody read.
Found by diffing a freshly migrated database against ``Base.metadata``; the
same comparison now runs in CI (``scripts/check-schema-drift.py``), which is
what stops this recurring.

``ix_exercise_discarded`` is **kept**, and declared in the model instead. It is
a partial index — ``subject_id`` where ``discarded_at IS NOT NULL`` — added
deliberately in 0004 for the one query that wants the discarded tail: "what has
this teacher already rejected for this subject", which the next generation run
asks so it does not offer the same item twice. Dropping a working index to
satisfy a diff would be the wrong direction; declaring it is the fix.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

#: (index name, table, columns) — every one SQLAlchemy's `index=True` implies.
_MISSING = (
    ("ix_detection_exercise_id", "detection", ["exercise_id"]),
    ("ix_exercise_source_section_id", "exercise", ["source_section_id"]),
    ("ix_source_section_school_id", "source_section", ["school_id"]),
    ("ix_source_section_source_id", "source_section", ["source_id"]),
)


def upgrade() -> None:
    for name, table, columns in _MISSING:
        op.create_index(name, table, columns, if_not_exists=True)


def downgrade() -> None:
    for name, table, _columns in reversed(_MISSING):
        op.drop_index(name, table_name=table, if_exists=True)
