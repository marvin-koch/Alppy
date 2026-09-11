"""Alembic environment.

The database URL always comes from ``alppy.core.config.get_settings()`` (which
reads the environment / ``.env``) — never from a URL hard-coded in
``alembic.ini`` — so the same migrations run unchanged in local dev, CI and
production.

It reads ``ALPPY_ADMIN_DATABASE_URL``, not ``ALPPY_DATABASE_URL``: since D84
the API connects as a role with no DDL and no ``BYPASSRLS``, and migrations
need both. It falls back to ``ALPPY_DATABASE_URL`` so a single-role development
database still migrates with no extra configuration.

Target metadata is ``alppy.models.Base.metadata``, so
``alembic revision --autogenerate`` has something real to diff against for
every migration after this hand-written initial one.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context
from alppy.core.config import get_settings
from alppy.models import Base

# Alembic Config object, giving access to values in alembic.ini.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The single source of truth for schema: every model in alppy.models is
# imported transitively via alppy.models.Base, so autogenerate sees every
# table.
target_metadata = Base.metadata

# Override whatever placeholder is in alembic.ini with the real settings URL.
# psycopg's driver uses '%' for parameter placeholders, which ConfigParser's
# interpolation also uses -- escape any literal '%' before handing it to
# set_main_option.
_settings = get_settings()
_db_url = str(_settings.admin_database_url or _settings.database_url).replace(
    "%", "%%"
)
config.set_main_option("sqlalchemy.url", _db_url)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection (``--sql``)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


#: Advisory-lock key for "somebody is migrating this database" (D13).
#:
#: Any stable 64-bit integer; this one is arbitrary and only has to stay the
#: same forever, so every process asking for it is asking for the same lock.
#: Changing it silently reopens the race it closes.
MIGRATION_LOCK_KEY = 0x41_4C_50_50_59_00_01  # b"ALPPY" + a counter


def run_migrations_online() -> None:
    """Run migrations against a live connection — the normal path.

    Serialized on a Postgres advisory lock. The API container runs
    ``alembic upgrade head`` on start (``infra/api/entrypoint.sh``), so two
    instances starting together — a rolling deploy, a crash-loop, a scale-up —
    both ran it at once against the same database. Alembic's own protection is
    a transaction per migration, which stops a *half-applied* revision and does
    nothing about two processes applying the same one: one of them fails on a
    duplicate object, the container exits, and the orchestrator restarts it
    into the same race.

    ``pg_advisory_lock`` is session-scoped, so it is held for the whole upgrade
    and released in ``finally`` — not ``pg_advisory_xact_lock``, because a
    migration is free to commit and that would drop the lock mid-run. The
    second instance blocks until the first is done and then finds nothing to
    do, which is the intended outcome: it starts, a few seconds later.

    This is the small half of D13. Migrating from inside the serving
    container's start at all is the larger question, and it belongs with the
    deploy pipeline (audit 07, Phase 3).
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Postgres only. SQLite has no advisory locks and no concurrent
        # migrator to protect against — the suite builds its schema with
        # `create_all` and never comes through here.
        locked = connection.dialect.name == "postgresql"
        if locked:
            connection.execute(
                text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
            )
            # COMMIT, and this line is load-bearing. SQLAlchemy 2.0 begins a
            # transaction implicitly on the first `execute`, so without this the
            # lock statement leaves one open — and alembic's own
            # `begin_transaction()` then nests inside it rather than owning it.
            # Every migration runs, every migration logs "Running upgrade", and
            # the whole thing is ROLLED BACK when the connection closes: a
            # database left at whatever revision it started from, with an
            # entrypoint that reported success. Found by running
            # `docker compose up` rather than by any test, because the suite
            # builds its schema with `create_all` on SQLite and never comes
            # through here.
            #
            # Committing does not release the lock: `pg_advisory_lock` is
            # SESSION-scoped, which is the reason this file uses it rather than
            # the transaction-scoped variant.
            connection.commit()
        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )

            with context.begin_transaction():
                context.run_migrations()
        finally:
            if locked:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": MIGRATION_LOCK_KEY},
                )
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
