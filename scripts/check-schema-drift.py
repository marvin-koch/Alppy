#!/usr/bin/env python
"""Fail when the migrations and the ORM models disagree.

Runs every migration from nothing against a real Postgres, then asks Alembic to
diff the resulting schema against ``Base.metadata``. Anything it finds is a
difference between what a fresh deployment gets and what the code believes it
has.

Why it exists
-------------
Five index drifts accumulated silently across migrations 0003-0005 (see 0008).
None of them broke anything, and that is the point: the damage was that
``alembic revision --autogenerate`` proposed the same five every run, so a real
change arrived buried in noise nobody read any more. Unit tests could not catch
it because they build the schema with ``create_all()`` from the models — which
is the very thing the migrations are supposed to reproduce.

Usage
-----
    createdb alppy_drift
    ALPPY_ENV=local \
    ALPPY_DISPOSABLE_DATABASE_URL=postgresql+psycopg://user:pw@localhost:5432/alppy_drift \
        python scripts/check-schema-drift.py

This **drops and recreates the public schema** of the database it is given, so
it refuses to run against one that is not visibly disposable — see
``alppy.db.disposable``. Exits 0 when clean, 1 with the differences listed, 2
when it would not accept the database it was pointed at.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from alppy.db.disposable import NotDisposableError, resolve_disposable_url

try:
    URL = resolve_disposable_url(os.environ)
except NotDisposableError as exc:
    print(exc)
    raise SystemExit(2) from None

# alembic/env.py reads the app's own setting rather than anything passed to it,
# by design — a migration must not be runnable against a URL hard-coded in a
# file. Pointing that setting at the database the guard just approved is how
# the two rules meet.
os.environ["ALPPY_DATABASE_URL"] = URL


def main() -> int:
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine, text

    from alppy.models import Base

    engine = create_engine(URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    config = Config(str(ROOT / "apps" / "api" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "apps" / "api" / "alembic"))
    command.upgrade(config, "head")

    with engine.connect() as conn:
        # `compare_server_default` is OFF in Alembic by default, and leaving it
        # off made this check structurally blind to the one class of drift it
        # had already been bitten by: 0025 exists because three tables reached
        # production without the `server_default` their models declared, and
        # this script watched them go (database audit H4). It compares the
        # shape a migration ends with, and a DEFAULT is not part of a column's
        # shape unless you ask.
        #
        # The comparator is the noisy one — it round-trips the rendered SQL
        # through the dialect, so a default written `now()` in one place and
        # `CURRENT_TIMESTAMP` in another reads as a difference. That noise is
        # the price: a false positive is a line in this output, and a false
        # negative is a NOT NULL violation on a live insert.
        context = MigrationContext.configure(
            conn, opts={"compare_type": True, "compare_server_default": True}
        )
        diff = compare_metadata(context, Base.metadata)

    # Alembic's own bookkeeping table is not in the models, by design.
    drift = [d for d in diff if "alembic_version" not in str(d)]
    if not drift:
        print("schema drift: none — the migrations reproduce the models exactly")
        return 0

    print(f"schema drift: {len(drift)} difference(s) between the migrations and the models\n")
    for entry in drift:
        print(f"  {entry}")
    print(
        "\nEach line is something a fresh deployment would not have, or would have "
        "and the models do not know about. Add a migration, or declare it in the model."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
