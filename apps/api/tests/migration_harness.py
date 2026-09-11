"""A disposable database per test, migrated to a chosen revision.

``test_migration_0021.py`` built this first and its docstrings carry the
reasoning; this module is the same machinery factored out so that 0027 and 0028
do not each grow a third and fourth copy. 0021 is deliberately left alone —
it works, it is well documented, and rewriting a passing test to share a helper
is a change with risk and no benefit.

Why a migration test needs a database of its own, rather than the one the unit
suite uses: the unit suite never runs a migration at all. It builds its schema
with ``create_all()`` from the models (D18), which is the very thing the
migrations are supposed to reproduce, so a backfill that moved no rows — or the
wrong ones — leaves every one of those tests green. ``check-schema-drift.py``
runs the migrations but compares only the *shape* they end with, and a wrong
backfill ends with a perfect shape.

Needs a Postgres with **pgvector**: migration 0001 creates the extension for
``SourceChunk.embedding``, so a plain local Postgres cannot replay the chain.
"""

from __future__ import annotations

import getpass
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic.config import Config

from alppy.core.config import get_settings

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CANDIDATES = [
    os.environ.get("ALPPY_TEST_DATABASE_URL"),
    "postgresql+psycopg://alppy:alppy@localhost:5432/postgres",
    f"postgresql+psycopg://{getpass.getuser()}@127.0.0.1:5432/postgres",
]


def _has_pgvector(url: str | None) -> bool:
    if not url:
        return False
    engine = None
    try:
        engine = sa.create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            found = conn.execute(
                sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
            ).scalar_one_or_none()
            return found is not None
    except Exception:
        return False
    finally:
        if engine is not None:
            engine.dispose()


SERVER_URL = next((u for u in _CANDIDATES if _has_pgvector(u)), None)


def require_or_skip(what: str) -> None:
    """Make an unreachable server a collection error where CI says so.

    A skip is the right answer on a laptop with no Postgres and the wrong one
    in CI, where it reads as a pass. ``ALPPY_REQUIRE_PG_TESTS=1`` is how CI
    says it expects these to run; without this call a credentials change would
    retire the module in silence, green.
    """
    if SERVER_URL is not None or os.environ.get("ALPPY_REQUIRE_PG_TESTS") != "1":
        return
    raise RuntimeError(
        f"ALPPY_REQUIRE_PG_TESTS=1 but no Postgres with pgvector was reachable, "
        f"so {what} cannot run. Set ALPPY_TEST_DATABASE_URL to a server (not a "
        f"database — one is created per run), or unset ALPPY_REQUIRE_PG_TESTS "
        f"to allow the skip."
    )


SKIP_REASON = (
    "needs a Postgres with pgvector (migration 0001 creates the extension). "
    "Run `docker compose up postgres`, or set ALPPY_TEST_DATABASE_URL."
)


def disposable_database() -> Iterator[str]:
    """A database of this test's own, dropped afterwards.

    A plain generator rather than a fixture, wrapped by a one-line ``db_url``
    fixture in each module that wants it. Importing a fixture by name and then
    naming it as a test argument shadows the import, which ruff reports as
    F811 — and it is right to: the import would be doing nothing a reader can
    see.

    Never the developer's. These tests run ``downgrade`` as well as
    ``upgrade``, and ``alppy.db.disposable`` exists because pointing a
    destructive check at a database in use is an accident this project has
    already had.
    """
    assert SERVER_URL is not None
    name = f"alppy_mig_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(SERVER_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = SERVER_URL.rsplit("/", 1)[0] + f"/{name}"
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"
                ),
                {"n": name},
            )
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


@contextmanager
def alembic_at(url: str) -> Iterator[Config]:
    """An Alembic config pointed at ``url``.

    ``alembic/env.py`` deliberately ignores ``sqlalchemy.url`` and always reads
    ``get_settings().database_url``, so that a migration can never be run
    against a URL hard-coded in a file. That is the right rule and this does
    not weaken it — it sets the environment the rule reads, and puts it back
    afterwards, so nothing later in the session inherits a throwaway database.
    """
    previous = os.environ.get("ALPPY_DATABASE_URL")
    os.environ["ALPPY_DATABASE_URL"] = url
    get_settings.cache_clear()
    cfg = Config(os.path.join(_HERE, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_HERE, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    try:
        yield cfg
    finally:
        if previous is None:
            os.environ.pop("ALPPY_DATABASE_URL", None)
        else:
            os.environ["ALPPY_DATABASE_URL"] = previous
        get_settings.cache_clear()
