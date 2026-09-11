"""Projector mode, as a preference that follows the teacher.

Alppy's screens are projected. A teacher opens the class matrix to show the
class what the week looked like, or leaves the roster up while the room fills,
and every name is on the wall beside a band that says how that child is doing.
The product was careful about this in one direction — no name ever reaches a
model provider — and had nothing at all in the other, where the audience is the
class itself.

`discreet` collapses names to UIDs wherever pupils are listed, with a
deliberate reveal. Stored on the teacher rather than only in the browser, for
the same reason the other four switches are: the classroom machine and the
laptop at home are the same person, and this is the setting they would be most
annoyed to have to find twice — usually while thirty pupils watch them find it.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable with no default: NULL is "not chosen", which is the same third
    # state the other switches use and is not a synonym for "off".
    op.add_column("teacher", sa.Column("discreet", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("teacher", "discreet")
