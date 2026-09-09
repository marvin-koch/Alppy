"""Class -> Branch -> Competence -> Theme -> Sheet, as facts rather than joins.

Three things the schema could not express, each of which the product was
inferring at read time instead:

* **Which Branches a class studies.** There was no `Class -> Subject` relation
  at all: `class_service.subject_ids_for_class` answered the question with
  `SELECT DISTINCT sheet.subject_id`. That is circular — a brand-new class had
  no Branch level to navigate until somebody had already built it a sheet in
  one. `class_subject` declares it, backfilled below from the same query it
  replaces, ordered by when the class first met each subject rather than
  alphabetically (D57).

* **Where a Theme sits in the curriculum.** `chapter_competency` is a
  many-to-many on purpose and stays one: it is what lets `Pythagore` carry a
  PER code and an LP21 code at once so two language regions can share a
  chapter (docs/curriculum.md §3). But a many-to-many cannot say which single
  node a chapter HANGS FROM in a tree. `chapter.primary_competency_id` is that
  one node, and because `chapter` is school-scoped each school resolves its own
  from `School.default_curriculum` — so "per school, per curriculum" needs one
  nullable FK, not two columns (D56). This migration only adds the column; the
  seed loader fills it, because the migration has no business deciding which
  competency is pedagogically primary.

* **Which Theme a sheet is filed under.** `sheet` knew its class and its
  subject and stopped there. `sheet.chapter_id` is NOT NULL: every sheet has a
  home, even when that home is honestly "nobody has filed this yet".

That last one is why `unfiled` exists. Existing sheets have nothing to
backfill from, and the tempting source — a majority vote over
`sheet_item -> exercise.chapter_id` — is itself an inference that the
`SourceSection` docstring says fails on a large minority of rows of a real
textbook. Promoting a second-hand guess into a teacher-facing filing the
teacher never confirmed is exactly what `Exercise.approved_at` exists to
prevent elsewhere. So every existing sheet moves to a per-subject `unfiled`
chapter, which says the true thing, and the teacher re-files it when they care.
`unfiled` is marked by `primary_competency_id IS NULL`, not by its `key`: one
nullable FK carries both meanings ("no canonical parent" *is* "not in the
tree"), so a school that renames the bucket cannot readmit it to the roll-up.

Note `sheet.chapter_id` takes no `server_default`, unlike 0014's
`default_points_correct`. The rule is the same, the situation is not: 0014
added a NOT NULL column straight onto a populated table, so Postgres itself
had to have a value for the existing rows. Here the column is added nullable,
filled by the backfill below, and only then tightened — by which point there
is nothing left for a default to do.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

# The bucket every unfiled sheet lands in. Position is a fixed sentinel past
# every seeded chapter's 0..6 so a plain `ORDER BY position` puts it last
# without a second query to filter it out.
UNFILED_KEY = "unfiled"
UNFILED_POSITION = 999
UNFILED_LABELS = '{"fr":"Non classé","de":"Nicht zugeordnet","en":"Unfiled"}'


def upgrade() -> None:
    # --- 1 · Chapter gains its canonical parent. Nullable, unfilled here: the
    # seed loader knows the school's curriculum, this migration does not.
    op.add_column(
        "chapter",
        sa.Column("primary_competency_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_chapter_primary_competency_id_competency",
        "chapter",
        "competency",
        ["primary_competency_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_chapter_primary_competency_id", "chapter", ["primary_competency_id"])

    # `POST /chapters` never checked for a duplicate key, so existing data may
    # violate the constraint below. Rename the later rows rather than deleting
    # them: a teacher's chapter — and whatever `Exercise.chapter_id` points at
    # it — is not this migration's to throw away. `key` is String(80), so the
    # suffix is made to fit.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id,
                       key,
                       ROW_NUMBER() OVER (
                           PARTITION BY school_id, subject_id, key
                           ORDER BY created_at, id
                       ) AS n
                FROM chapter
            )
            UPDATE chapter c
            SET key = left(r.key, 74) || '-' || r.n
            FROM ranked r
            WHERE c.id = r.id AND r.n > 1
            """
        )
    )

    # One chapter per key per subject — and in particular one `unfiled` bucket.
    # `chapter_service.ensure_unfiled_chapter` relies on this to make its
    # ON CONFLICT DO NOTHING meaningful; without it two concurrent first-ever
    # sheets in a subject each create a bucket and the subject's unfiled sheets
    # split silently between them.
    op.create_unique_constraint(
        "uq_chapter_key", "chapter", ["school_id", "subject_id", "key"]
    )

    # --- 2 · The Branches a class studies, declared.
    op.create_table(
        "class_subject",
        sa.Column("class_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["class_id"], ["class.id"], name="fk_class_subject_class_id_class", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subject.id"],
            name="fk_class_subject_subject_id_subject",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("class_id", "subject_id", name="pk_class_subject"),
    )

    # --- 3 · Backfill it from the derived query it replaces. `position` is
    # first-use order, which is what the column means; ROW_NUMBER over
    # MIN(created_at) reproduces it deterministically.
    op.execute(
        sa.text(
            """
            INSERT INTO class_subject (class_id, subject_id, position)
            SELECT class_id,
                   subject_id,
                   (ROW_NUMBER() OVER (PARTITION BY class_id ORDER BY first_seen) - 1)::int
            FROM (
                SELECT class_id, subject_id, MIN(created_at) AS first_seen
                FROM sheet
                GROUP BY class_id, subject_id
            ) AS first_use
            ON CONFLICT DO NOTHING
            """
        )
    )

    # --- 4 · One `unfiled` chapter per subject, per school. Must exist before
    # step 5 has anywhere to point.
    op.execute(
        sa.text(
            f"""
            INSERT INTO chapter (
                id, school_id, subject_id, primary_competency_id,
                key, labels, position, created_at, updated_at
            )
            SELECT gen_random_uuid(), s.school_id, s.id, NULL,
                   '{UNFILED_KEY}', '{UNFILED_LABELS}'::jsonb, {UNFILED_POSITION},
                   now(), now()
            FROM subject s
            WHERE NOT EXISTS (
                SELECT 1 FROM chapter c
                WHERE c.subject_id = s.id AND c.key = '{UNFILED_KEY}'
            )
            """
        )
    )

    # --- 5 · Sheet gains its home. Nullable, backfilled, then tightened.
    op.add_column(
        "sheet", sa.Column("chapter_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.execute(
        sa.text(
            f"""
            UPDATE sheet
            SET chapter_id = c.id
            FROM chapter c
            WHERE c.school_id = sheet.school_id
              AND c.subject_id = sheet.subject_id
              AND c.key = '{UNFILED_KEY}'
              AND sheet.chapter_id IS NULL
            """
        )
    )
    op.alter_column("sheet", "chapter_id", nullable=False)
    op.create_foreign_key(
        "fk_sheet_chapter_id_chapter",
        "sheet",
        "chapter",
        ["chapter_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_sheet_chapter_id", "sheet", ["chapter_id"])


def downgrade() -> None:
    # Symmetric in reverse for the SCHEMA. The `unfiled` chapter rows and the
    # class_subject backfill are deliberately left where they are, the same way
    # 0015's downgrade leaves the `confirmed_at` values it derived: once the
    # column above them is gone the rows are inert, and re-deriving "was this
    # row inserted by this migration" is not worth the complexity or the risk
    # of deleting a chapter a teacher has since filed real sheets under.
    op.drop_index("ix_sheet_chapter_id", table_name="sheet")
    op.drop_constraint("fk_sheet_chapter_id_chapter", "sheet", type_="foreignkey")
    op.drop_column("sheet", "chapter_id")

    op.drop_table("class_subject")

    op.drop_constraint("uq_chapter_key", "chapter", type_="unique")
    op.drop_index("ix_chapter_primary_competency_id", table_name="chapter")
    op.drop_constraint(
        "fk_chapter_primary_competency_id_competency", "chapter", type_="foreignkey"
    )
    op.drop_column("chapter", "primary_competency_id")
