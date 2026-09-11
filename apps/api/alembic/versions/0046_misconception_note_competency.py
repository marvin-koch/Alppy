"""A note's competencies become rows the database can check.

``misconception_note.competency_ids`` was a JSONB array of UUID *strings*
(database audit M3). Everything that is wrong with that follows from the type:

* **No foreign key.** A competency deleted or re-coded leaves the note pointing
  at an id that resolves to nothing, and nothing anywhere notices. The read
  path (`api/v1/adaptive.py`) parses each string back into a UUID and hands it
  to the client, dangling or not.
* **No index, and no way to ask the question backwards.** "Which notes mention
  this competency" — the question a curriculum-first view of a class asks — is
  a full scan with a JSONB containment operator, against a column no index
  covers.
* **Strings, so the type says nothing.** `["7b_15"]` is a valid value.

``misconception_note_competency`` is the same shape as ``chapter_competency``
and ``exercise_competency``, and gets the same second index that 0039 and 0043
gave those: the composite PK answers note→competency, and the reverse
direction needs its own.

**The backfill drops what the old column could hold and the new one cannot.**
Every id is joined against ``competency`` and only the ones that resolve are
carried over — because a foreign key is precisely the thing being added, and a
migration cannot invent a competency to satisfy a dangling reference. The same
join silently drops anything that is not a UUID at all, which is a value the
old column permitted. Nothing is lost that anything could read: the endpoint
already returned these ids to a client that looks each one up and finds
nothing.

That is a real deletion, so it is stated rather than implied: on the demo and
staging seeds it removes nothing (every id there comes from a seeded
competency), and on any database it removes only ids that already pointed at
no row.

The column goes. Keeping both would mean two answers to one question and a rule
about which wins, which is the state this migration exists to leave.

Reversible: the downgrade rebuilds the column and regenerates the array from the
join table. A note that lost a dangling id does not get it back — that id is
not in the join table, because it could not be.

Revision ID: 0046
Revises: 0045
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "misconception_note_competency",
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("competency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["note_id"],
            ["misconception_note.id"],
            name="fk_misconception_note_competency_note_id_misconception_note",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["competency_id"],
            ["competency.id"],
            name="fk_misconception_note_competency_competency_id_competency",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "note_id", "competency_id", name="pk_misconception_note_competency"
        ),
    )
    # The reverse direction, for the reason 0039 and 0043 added it to the other
    # two m2m tables: the composite PK leads with `note_id` and answers nothing
    # keyed on the competency.
    op.create_index(
        "ix_misconception_note_competency_competency_id",
        "misconception_note_competency",
        ["competency_id"],
    )

    # `JOIN competency` is the filter: an id that resolves to no row cannot be
    # carried across a foreign key, and one that is not a UUID cannot even be
    # compared. `ON CONFLICT DO NOTHING` so a partially applied database can be
    # re-run, matching 0016's posture.
    op.execute(
        sa.text(
            """
            INSERT INTO misconception_note_competency (note_id, competency_id)
            SELECT n.id, c.id
            FROM misconception_note n
            CROSS JOIN LATERAL jsonb_array_elements_text(n.competency_ids) AS raw(value)
            JOIN competency c
              ON raw.value ~ '^[0-9a-fA-F-]{36}$' AND c.id = raw.value::uuid
            WHERE jsonb_typeof(n.competency_ids) = 'array'
            ON CONFLICT DO NOTHING
            """
        )
    )

    op.drop_column("misconception_note", "competency_ids")


def downgrade() -> None:
    """Rebuilds the column from the join table.

    Lossy only for ids the join table could not hold — the dangling ones, which
    is the whole point of the upgrade.
    """
    op.add_column(
        "misconception_note",
        sa.Column(
            "competency_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE misconception_note n
            SET competency_ids = COALESCE(agg.ids, '[]'::jsonb)
            FROM (
                SELECT note_id, jsonb_agg(competency_id::text ORDER BY competency_id) AS ids
                FROM misconception_note_competency
                GROUP BY note_id
            ) AS agg
            WHERE agg.note_id = n.id
            """
        )
    )

    op.drop_index(
        "ix_misconception_note_competency_competency_id",
        table_name="misconception_note_competency",
    )
    op.drop_table("misconception_note_competency")
