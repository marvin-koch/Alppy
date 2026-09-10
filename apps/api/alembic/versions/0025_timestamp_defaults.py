"""The three tables whose timestamps the database never learned to fill.

``TimestampMixin`` declares both columns with ``server_default=func.now()``,
and "every table has created_at and updated_at, no exceptions" is the comment
above it. Twenty-six tables carry ``DEFAULT now()``; three do not —
`prompt_log` (0017), `adaptive_proposal` (0018) and `mastery_branch_snapshot`
(0023) each spell the columns ``nullable=False`` and stop there.

A ``server_default`` is not cosmetic to SQLAlchemy: it is what tells the ORM to
leave the column out of the INSERT and read it back through RETURNING. So the
statement these three tables receive is

    INSERT INTO adaptive_proposal (id, job_id, payload, school_id) VALUES (...)
        RETURNING created_at, updated_at

— no timestamp on the way in, no default on the way down, and a
``NotNullViolation`` on the first row anyone tries to write. Every
``PROPOSE_ADAPTIVE`` job reached "proposal built" at 0.9 and then died there;
the same fault was waiting under `ALPPY_AI_PROMPT_LOG_RETENTION_DAYS` and under
the branch-level history cache, neither of which had been written to yet.

This is the drift CLAUDE.md names in the check-schema-drift entry, and it is
worth being precise about why it survived: the unit tests build their schema
with ``create_all()`` *from the models*, so the column they test against always
has the default the mixin declares. The migration is the only artefact that
disagreed, and no test in the suite reads it. `scripts/check-schema-drift.py`
against a disposable Postgres is what catches this class, and it is the thing
to run before believing a migration reproduces the models.

Written as a forward ALTER rather than a correction to 0017/0018/0023: those
have run in every environment that exists, and editing an applied migration
fixes nobody's database. ``ALTER COLUMN SET DEFAULT`` is metadata only — it
takes an ACCESS EXCLUSIVE lock for the moment it runs, rewrites no rows, and
touches no existing value. The columns are already NOT NULL, so there are no
nulls to backfill.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

#: The three that 0017, 0018 and 0023 created without the mixin's default.
_TABLES = ("prompt_log", "adaptive_proposal", "mastery_branch_snapshot")
_COLUMNS = ("created_at", "updated_at")


def upgrade() -> None:
    for table in _TABLES:
        for column in _COLUMNS:
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
                server_default=sa.func.now(),
            )


def downgrade() -> None:
    for table in _TABLES:
        for column in _COLUMNS:
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
                server_default=None,
            )
