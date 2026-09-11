"""A retry stops doing the work twice.

Nothing in the product was idempotent (audit 03, B17). A phone on a staffroom
connection retries a POST whose answer never arrived; a teacher taps "print"
again because the screen has not moved. Both produced a second render job, a
second batch of unapproved exercises, a second pile of scans — and the few
endpoints that guarded against it each invented their own in-flight query and
their own idea of what "the same request" was.

The key is **claimed before the work runs**. Two simultaneous retries race on
the unique constraint, exactly one wins, and the loser is told the work is
already in flight rather than repeating it. A row written after the work would
let both through and remember only whichever finished last.

Keyed per tenant. `(endpoint, key)` alone would let one school probe another's
keyspace and learn from a 409 that a given request had been made.

RLS from the first migration that creates the table, never bolted on: it is a
`SchoolScopedMixin` table, and `scripts/check-rls.py` fails the build for a
scoped table without a FORCED policy — which is the point of that script.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

CURRENT_SCHOOL = "nullif(current_setting('app.current_school_id', true), '')::uuid"
POLICY = "tenant_isolation"


def upgrade() -> None:
    op.create_table(
        "idempotency_key",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.String(length=80), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["school_id"], ["school.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("school_id", "endpoint", "key", name="uq_idempotency_key"),
    )
    op.create_index("ix_idempotency_key_created", "idempotency_key", ["created_at"])
    op.create_index("ix_idempotency_key_school_id", "idempotency_key", ["school_id"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE idempotency_key ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE idempotency_key FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON idempotency_key "
            f"USING (school_id = {CURRENT_SCHOOL}) "
            f"WITH CHECK (school_id = {CURRENT_SCHOOL})"
        )


def downgrade() -> None:
    op.drop_index("ix_idempotency_key_school_id", table_name="idempotency_key")
    op.drop_index("ix_idempotency_key_created", table_name="idempotency_key")
    op.drop_table("idempotency_key")
