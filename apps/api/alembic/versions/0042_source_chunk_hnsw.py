"""Retrieval stops reading the whole corpus to answer one question.

``source_chunk.embedding`` had no index. Every retrieval — and retrieval is on
the path of every sheet the teacher builds — was a sequential scan computing
``<=>`` against each row, which is correct, and gets linearly worse with each
textbook uploaded (database audit H6).

**HNSW, and ``vector_cosine_ops``, because that is the distance the query
asks for.** ``retrieval.py`` ranks with ``SourceChunk.embedding.cosine_distance``
(pgvector's ``<=>``); an index built for L2 or inner product would be ignored
by that operator and the seq scan would quietly continue, which is the failure
mode worth naming — a missing index and an index the planner cannot use look
identical from the outside.

**Plain, not tenant-scoped.** Every retrieval filters on ``school_id``, so a
composite would be the obvious thing to want — but HNSW is a single-column
access method and cannot carry a leading scalar, and the alternative,
one partial index per school, is DDL on every tenant creation. pgvector 0.8's
iterative scan is what makes the plain index behave under a selective filter,
and it is on by default. The demo corpus is ~60 chunks, which is far too small
for a benchmark to mean anything, so this ships the shape the extension is
designed for rather than a guess dressed up as a measurement.

**``CONCURRENTLY``, so it cannot lock a live corpus.** A plain ``CREATE INDEX``
takes ``ACCESS EXCLUSIVE`` for the whole build, and building HNSW over a real
textbook's chunks is not instant.

Getting there takes two steps, and the second is not decoration.
``op.execute("COMMIT")`` ends the migration's transaction, the way 0018 does
for ``ALTER TYPE`` — but SQLAlchemy opens a fresh one for the very next
statement, so the index statement would arrive inside a transaction again and
Postgres refuses it. So the build runs on a **separate connection in
AUTOCOMMIT**, opened after that commit. Doing it the other way round — a second
connection while this migration's transaction is still open — is worse than an
error: ``CREATE INDEX CONCURRENTLY`` waits for every transaction that can see
the table, which would include the one waiting for it. That is a hang, not a
failure, and it looks like a slow migration.

This is the first ``CONCURRENTLY`` in the chain, and it carries the cost 0019's
docstring names: after the commit, a failure below would leave the migration
partly applied. There is nothing below it. ``IF NOT EXISTS`` is what makes a
re-run safe, because a cancelled ``CONCURRENTLY`` build leaves an INVALID index
behind rather than nothing — see ``downgrade`` if you meet one.

Revision ID: 0042
Revises: 0041
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

INDEX = "ix_source_chunk_embedding_hnsw"


def _concurrently(statement: str) -> None:
    """Run one statement outside any transaction, this one's included.

    The ``COMMIT`` ends the migration's transaction so the index build has
    nothing of ours to wait on; the fresh AUTOCOMMIT connection is what keeps
    SQLAlchemy from opening another one underneath the statement itself.
    """
    op.execute("COMMIT")
    engine = sa.create_engine(op.get_bind().engine.url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql(statement)
    finally:
        engine.dispose()


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite has no pgvector and the suite never runs migrations against it
        # (D18); the column is spelled TEXT there by a test-only `@compiles`.
        return

    _concurrently(
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} "
        "ON source_chunk USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Dropped concurrently too, for the same reason it is built that way.

    If a build was interrupted, the index exists and is INVALID: it is ignored
    by the planner but still maintained on every write, which is the worst of
    both. ``DROP INDEX CONCURRENTLY IF EXISTS`` is also the way out of that
    state, so this is the command to run by hand before re-applying.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    _concurrently(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
