"""The curriculum gains its real levels, an edition, and a word for streaming.

Three findings, one shape, because they are three ways of saying that
`competency` was a flat pair of levels with no provenance (audit H1, H2, H3).

**H3 · an edition, and a flag for what we invented.** `uq_competency_code` was
`(curriculum, code)`, so two editions of the PER could not coexist: updating
the curriculum meant overwriting the very rows every past band was computed
from, and every historical mastery number would silently start meaning
something else. `curriculum_edition` plus `competency.edition_id`, and the key
widens to `(curriculum, edition_id, code)`.

`is_official` and `source_ref` are the other half. The seed carried invented
codes — `MSN 31.2` is not a CIIP code — written in CIIP's own notation, so a
teacher reading one off a printed sheet had no way to know their inspector
would not recognise it. Now a row either cites where it came from or admits it
has nowhere to cite.

**H1 · `kind` and `year`.** The tree was two levels where the PER is five:
domaine, objectif, composante, progression (per year), attente fondamentale.
`kind` says which a row is and `year` dates the progressions, which is what
makes "every progression for 10H maths" a query rather than an impossibility.

**H2 · `stream`, and `class.stream_id`.** Cycle 3 is streamed and every canton
streams differently — VD's VG/VP with niveaux inside VG, GE's R1/R2/R3, VS's
niveau I and II. A niveau-2 maths group was a `Class` whose code happened to
contain a "2". A LOOKUP TABLE, not an enum, and that is the finding's own test:
a canton must be addable without a migration.

**The backfill is honest about what it is looking at.** Every existing row is
attached to a "2010" PER / "2014" LP21 edition and marked `is_official = false`
with no `source_ref` — including the five real objectif codes, because this
migration cannot tell which of the rows in front of it came from a publisher.
0052 re-seeds from the CIIP API and marks what it can prove. Claiming
officialdom here, for rows this migration did not fetch, would be exactly the
lie `is_official` exists to prevent.

`kind` defaults to `objectif` for the same reason: it is what the existing
two-level tree was, and the invented sub-level was being used as one.

Revision ID: 0051
Revises: 0050
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

#: Member names, like every enum since 0001 — that is what SQLAlchemy sends
#: for an `Enum(PyEnum)` column. The values (`domaine`, `9H`) are what the
#: API and the seed files speak in.
_KINDS = ("DOMAINE", "OBJECTIF", "COMPOSANTE", "PROGRESSION", "ATTENTE")
_YEARS = ("H9", "H10", "H11")

#: curriculum -> the edition its existing rows are treated as belonging to.
_EDITIONS = {"PER": "2010", "LP21": "2014"}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(*_KINDS, name="competency_kind").create(bind, checkfirst=True)
        postgresql.ENUM(*_YEARS, name="curriculum_year").create(bind, checkfirst=True)

    op.create_table(
        "curriculum_edition",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "curriculum",
            postgresql.ENUM("LP21", "PER", name="curriculum_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("edition", sa.String(length=20), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_curriculum_edition"),
        sa.UniqueConstraint("curriculum", "edition", name="uq_curriculum_edition"),
    )

    op.create_table(
        "stream",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canton", sa.String(length=2), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stream"),
        sa.UniqueConstraint("canton", "code", name="uq_stream_code"),
    )
    op.create_index("ix_stream_canton_position", "stream", ["canton", "position"])

    op.add_column(
        "class",
        sa.Column("stream_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_class_stream_id_stream", "class", "stream", ["stream_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_class_stream_id", "class", ["stream_id"])

    op.add_column(
        "competency",
        sa.Column("edition_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "competency",
        sa.Column(
            "kind",
            postgresql.ENUM(*_KINDS, name="competency_kind", create_type=False),
            nullable=False,
            server_default=sa.text("'OBJECTIF'"),
        ),
    )
    op.add_column(
        "competency",
        sa.Column(
            "year",
            postgresql.ENUM(*_YEARS, name="curriculum_year", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "competency",
        sa.Column(
            "is_official", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column("competency", sa.Column("source_ref", sa.String(length=200), nullable=True))

    # One edition row per curriculum that has rows, then point them at it.
    for curriculum, edition in _EDITIONS.items():
        op.execute(
            sa.text(
                """
                INSERT INTO curriculum_edition (id, curriculum, edition)
                SELECT gen_random_uuid(), CAST(:curriculum AS curriculum_kind), :edition
                WHERE EXISTS (
                    SELECT 1 FROM competency WHERE curriculum::text = :curriculum
                )
                  AND NOT EXISTS (
                      SELECT 1 FROM curriculum_edition
                      WHERE curriculum::text = :curriculum AND edition = :edition
                  )
                """
            ).bindparams(
                sa.bindparam("curriculum", value=curriculum, type_=sa.String()),
                sa.bindparam("edition", value=edition, type_=sa.String()),
            )
        )
    op.execute(
        sa.text(
            """
            UPDATE competency c
            SET edition_id = e.id
            FROM curriculum_edition e
            WHERE e.curriculum::text = c.curriculum::text AND c.edition_id IS NULL
            """
        )
    )

    # NOT NULL once every row has one. Nullable was only ever a way to add the
    # column before the backfill — and leaving it nullable would have put a
    # NULL hole straight into the widened unique key, since two NULLs are
    # distinct: `(PER, NULL, 'MSN 31')` twice would both be allowed, which is
    # the very duplication the constraint exists to refuse (the shape 0045 had
    # to close on `attempt`).
    op.alter_column("competency", "edition_id", nullable=False)
    op.create_foreign_key(
        "fk_competency_edition_id_curriculum_edition",
        "competency",
        "curriculum_edition",
        ["edition_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_competency_edition_id", "competency", ["edition_id"])
    op.create_index("ix_competency_kind_year", "competency", ["kind", "year"])

    op.drop_constraint("uq_competency_code", "competency", type_="unique")
    op.create_unique_constraint(
        "uq_competency_code", "competency", ["curriculum", "edition_id", "code"]
    )


def downgrade() -> None:
    """Reversible, and the uniqueness constraint is why it can fail.

    Going back to `(curriculum, code)` is refused if two editions hold the same
    code — which is the state this migration exists to make possible. Nothing
    here chooses which edition to delete.
    """
    # Refuse legibly rather than fail on the index build six frames down. Going
    # back to `(curriculum, code)` is impossible the moment two editions hold
    # one code — which is the state this migration exists to make possible, so
    # it is an expected refusal and not a bug. Deleting one of the two is a
    # decision about which curriculum a school marks against, and a downgrade
    # is the wrong place to take it.
    clashes = op.get_bind().execute(
        sa.text(
            """
            SELECT curriculum::text, code, count(*) AS editions
            FROM competency
            GROUP BY 1, 2 HAVING count(*) > 1
            ORDER BY 1, 2 LIMIT 5
            """
        )
    ).all()
    if clashes:
        listed = ", ".join(f"{c}/{code} in {n} editions" for c, code, n in clashes)
        raise RuntimeError(
            "cannot downgrade 0051: `uq_competency_code` would collapse codes that "
            f"exist in more than one edition ({listed}). Delete the edition you do "
            "not want first — this migration will not choose for you."
        )

    op.drop_constraint("uq_competency_code", "competency", type_="unique")
    op.create_unique_constraint("uq_competency_code", "competency", ["curriculum", "code"])

    op.alter_column("competency", "edition_id", nullable=True)
    op.drop_index("ix_competency_kind_year", table_name="competency")
    op.drop_index("ix_competency_edition_id", table_name="competency")
    op.drop_constraint(
        "fk_competency_edition_id_curriculum_edition", "competency", type_="foreignkey"
    )
    for column in ("source_ref", "is_official", "year", "kind", "edition_id"):
        op.drop_column("competency", column)

    op.drop_index("ix_class_stream_id", table_name="class")
    op.drop_constraint("fk_class_stream_id_stream", "class", type_="foreignkey")
    op.drop_column("class", "stream_id")

    op.drop_index("ix_stream_canton_position", table_name="stream")
    op.drop_table("stream")
    op.drop_table("curriculum_edition")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name="curriculum_year").drop(bind, checkfirst=True)
        postgresql.ENUM(name="competency_kind").drop(bind, checkfirst=True)
