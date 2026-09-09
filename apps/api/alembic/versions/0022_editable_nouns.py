"""The teacher edits their own school's nouns.

Two columns' worth of schema for a pass that is mostly endpoints, and both
exist because a WRITE surface makes reachable what a seed never did.

**`uq_subject_key`.** Subjects have only ever arrived from the seed, so nothing
enforced one `mathematics` per school. `POST /subjects` makes a second one a
click away, and `Competency.subject_key` matches `Subject.key` **by string** —
two subjects keyed the same in one school would split the curriculum silently,
half the competencies resolving to each, with no error anywhere. The constraint
is the prerequisite for the endpoint, not a tidy-up beside it.

The backfill is deliberate about what it does NOT do: a school that somehow
already holds duplicates is left alone and the migration FAILS on the index
build. Silently merging two subjects would move sheets, chapters and exercises
between them; refusing says so and leaves a human to choose.

**`source.title`.** `Source` had only `filename` — what the teacher happened to
upload ("scan 3 (copy).pdf"), which is provenance rather than a name, and was
the only thing the shelf could show. Nullable, because every existing row has
no title and inventing one from the filename would look like data the teacher
entered.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Report duplicates as a readable error rather than as a constraint
    # violation nobody can act on. `op.get_bind()` so this runs inside the
    # migration's own transaction and rolls back with it.
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT school_id, key, count(*) AS n FROM subject "
                "GROUP BY school_id, key HAVING count(*) > 1"
            )
        )
        .all()
    )
    if duplicates:
        listed = ", ".join(f"{row.key} x{row.n} in school {row.school_id}" for row in duplicates)
        raise RuntimeError(
            "cannot add uq_subject_key: duplicate subject keys exist "
            f"({listed}). Merge them by hand first — moving sheets, chapters "
            "and exercises between two subjects is not a migration's decision."
        )

    op.create_unique_constraint("uq_subject_key", "subject", ["school_id", "key"])
    op.add_column("source", sa.Column("title", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("source", "title")
    op.drop_constraint("uq_subject_key", "subject", type_="unique")
