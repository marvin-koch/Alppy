"""Proposing an adaptive batch becomes a job.

``POST /adaptive/propose`` ran targeting, retrieval and every generation call
inside the request handler. CLAUDE.md forbids exactly that — "nothing blocks a
request handler on a model call" — and the codebase already argued the case
against itself: ``generate_feedback``'s own docstring says a class of twenty
model calls inside a handler "is a timeout with a half-written batch behind it".
Propose was doing the same thing, one call per child, and only escaped notice
because it predates the rule being written down.

``JobKind.GENERATE_ADAPTIVE`` could not be reused. Despite the name it *renders*
an approved batch to PDF (``worker/tasks.py``), and ``TASK_NAMES`` maps each kind
to exactly one worker function, so branching on payload keys would make one kind
mean two unrelated things. Hence a new value, and the old one keeps its job and
its misleading name — renaming an enum value in the same change that adds one is
how a migration ends up half-applied.

Postgres stores the member NAME (see ``_ENUMS`` in 0001), and adding a value to
an enum cannot share a transaction with DDL that then uses it — so the
``ALTER TYPE`` is committed on its own first, exactly as 0005, 0006 and 0010 do.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("COMMIT")
        op.execute("ALTER TYPE job_kind ADD VALUE IF NOT EXISTS 'PROPOSE_ADAPTIVE'")

    # Where the built proposal waits to be read. Deliberately not `job.result`:
    # the review screen polls the job every 900 ms while it runs, and a class of
    # 24 with 8 items each is close to a megabyte of statements and provenance.
    # A status row must stay cheap to ask about.
    op.create_table(
        "adaptive_proposal",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_adaptive_proposal"),
        sa.UniqueConstraint("job_id", name="uq_adaptive_proposal_job"),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["school.id"],
            name="fk_adaptive_proposal_school_id_school",
            ondelete="CASCADE",
        ),
        # Cascade from the job: the proposal is the shape of one screen and has
        # no meaning once the run that produced it is gone.
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name="fk_adaptive_proposal_job_id_job",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_adaptive_proposal_school_id", "adaptive_proposal", ["school_id"])
    op.create_index("ix_adaptive_proposal_job_id", "adaptive_proposal", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_adaptive_proposal_job_id", table_name="adaptive_proposal")
    op.drop_index("ix_adaptive_proposal_school_id", table_name="adaptive_proposal")
    op.drop_table("adaptive_proposal")

    # Postgres cannot drop an enum value, and rebuilding the type would have to
    # rewrite every `job` row that uses it. 0005 and 0010 set the precedent:
    # the value stays, and a downgraded schema simply never writes it.
