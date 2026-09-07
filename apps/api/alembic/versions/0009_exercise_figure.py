"""An exercise can carry the book's own code, title and a crop of the page.

Until now an extracted exercise was a transcription: whatever a model made of
the chunk of text the PDF's text layer offered. On a real textbook that layer
loses the figure, the table, the fractions and the reading order — exactly the
part a student is meant to look at. The region detector
(``alppy.ingest.regions``) now finds each coded exercise on the page and cuts it
out as an image, and the sheet prints that image in place of the statement.

* ``label`` / ``title`` — "NO64", "Les quatre multiplications": the book's own
  identity for the exercise, which is what a teacher recognises.
* ``figure_key`` — the crop, in object storage.
* ``figure_width_mm`` / ``figure_height_mm`` — its physical size at 1:1, kept
  here so pagination can reserve the right height without opening the image.

All nullable: an exercise a model or a teacher wrote has none of them.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("exercise", sa.Column("label", sa.String(length=16), nullable=True))
    op.add_column("exercise", sa.Column("title", sa.String(length=200), nullable=True))
    op.add_column("exercise", sa.Column("figure_key", sa.String(length=500), nullable=True))
    op.add_column("exercise", sa.Column("figure_width_mm", sa.Float(), nullable=True))
    op.add_column("exercise", sa.Column("figure_height_mm", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("exercise", "figure_height_mm")
    op.drop_column("exercise", "figure_width_mm")
    op.drop_column("exercise", "figure_key")
    op.drop_column("exercise", "title")
    op.drop_column("exercise", "label")
