"""``source_section`` — the book's own chapters, and on-demand extraction.

A 400-page textbook holds well over a thousand exercises, and two things in the
old shape put those out of reach:

1. Ingestion transcribed at most ``MAX_EXTRACTION_CHUNKS`` chunks *per upload*,
   so only the front of a long book ever became exercises and the teacher was
   told to split the file. That ceiling becomes per-section here: importing maps
   every section and indexes every chunk cheaply, and a section is read by the
   model the first time a teacher opens it (``extracted_at``).
2. The only grouping an exercise carried was ``chapter_id``, inferred from
   competency overlap and therefore ``NULL`` whenever the teacher has no
   chapters, the chapters carry no competency codes, or the extraction tagged
   nothing. ``source_section_id`` is a fact about the file instead, so the
   builder's primary filter can never hide a row.

``exercise_origin`` gains ``TEACHER`` for items written in the sheet builder,
and ``job_kind`` gains ``EXTRACT_SECTION``. Both enums store the member NAME
(see ``_ENUMS`` in 0001), which is why these are upper-case.

Adding a value to a Postgres enum cannot share a transaction with DDL that then
uses that value, so both ``ALTER TYPE`` statements are committed on their own
before the table work. ``IF NOT EXISTS`` keeps a re-run harmless.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # On SQLite (the unit-test database) Enum is a VARCHAR + CHECK rebuilt
        # from the model metadata, so there is nothing to alter.
        op.execute("COMMIT")
        op.execute("ALTER TYPE exercise_origin ADD VALUE IF NOT EXISTS 'TEACHER'")
        op.execute("ALTER TYPE job_kind ADD VALUE IF NOT EXISTS 'EXTRACT_SECTION'")

    op.create_table(
        "source_section",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("label", sa.String(length=20), nullable=True),
        sa.Column("page_from", sa.Integer(), nullable=False),
        sa.Column("page_to", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extraction_notice", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_section"),
        sa.ForeignKeyConstraint(
            ["school_id"], ["school.id"], name="fk_source_section_school", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["source.id"], name="fk_source_section_source", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("source_id", "position", name="uq_source_section_position"),
    )
    op.create_index("ix_source_section_source", "source_section", ["source_id", "position"])

    op.add_column(
        "exercise",
        sa.Column("source_section_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_exercise_source_section",
        "exercise",
        "source_section",
        ["source_section_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_exercise_source_section", "exercise", ["source_section_id", "source_page"]
    )


def downgrade() -> None:
    op.drop_index("ix_exercise_source_section", table_name="exercise")
    op.drop_constraint("fk_exercise_source_section", "exercise", type_="foreignkey")
    op.drop_column("exercise", "source_section_id")
    op.drop_index("ix_source_section_source", table_name="source_section")
    op.drop_table("source_section")
    # The enum values are deliberately left in place: removing one from a
    # Postgres enum means rebuilding the type, and any row still carrying
    # 'TEACHER' would have to be rewritten first. Leaving them is inert.
