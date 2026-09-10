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

from sqlalchemy import engine_from_config, pool

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


def run_migrations_online() -> None:
    """Run migrations against a live connection — the normal path."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
