"""Deleting a Branch stops depending on whether anyone printed a sheet.

``chapter.subject_id`` was CASCADE while ``sheet.chapter_id`` is RESTRICT
(database audit M10), and the two rules contradict each other in a way that
only shows up sometimes.

Deleting a ``Subject`` removed its ``Chapter`` rows; the RESTRICT on
``Sheet.chapter_id`` then refused — from inside a cascade, about a row the
caller never named. So the same operation either quietly deleted a school's
Themes or failed with an error about a table nobody asked about, and which of
the two happened depended on whether a sheet existed.

RESTRICT on both makes it one rule: a Branch that still holds Themes is not
deletable, refused at the level the question was asked, where a service can
say so in a sentence a teacher can act on.

Nothing calls this today — there is no subject-delete endpoint, only
``undeclare_subject``, which removes a Branch from one class and already
refuses while sheets hang off it. That is exactly why now is the moment: the
rule is free to fix while no caller depends on the old behaviour.

Reversible, and the downgrade restores a contradiction rather than a
capability.

Revision ID: 0048
Revises: 0047
"""

from __future__ import annotations

from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

NAME = "fk_chapter_subject_id_subject"


def upgrade() -> None:
    op.drop_constraint(NAME, "chapter", type_="foreignkey")
    op.create_foreign_key(
        NAME, "chapter", "subject", ["subject_id"], ["id"], ondelete="RESTRICT"
    )


def downgrade() -> None:
    op.drop_constraint(NAME, "chapter", type_="foreignkey")
    op.create_foreign_key(
        NAME, "chapter", "subject", ["subject_id"], ["id"], ondelete="CASCADE"
    )
