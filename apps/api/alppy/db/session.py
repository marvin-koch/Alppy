"""Engines and session factories.

Two of each, because there are two privilege levels (D84):

``SessionLocal``   the API and the worker. Connects as ``alppy_app``, a role
                   with no DDL and no ``BYPASSRLS``, so every read it makes is
                   filtered by the tenant bound in :mod:`alppy.db.tenancy`.

``admin_session``  alembic and the cross-school CLI (``seed``,
                   ``backfill-events``, ``purge-prompt-logs``). Connects as the
                   schema owner, which carries ``BYPASSRLS`` — those three
                   commands sweep every school by definition, and no GUC can
                   name "all of them". It is a deliberate hole, which is why it
                   is a separate factory with a separate DSN rather than a flag
                   on the normal one: reaching for it is a visible act.

``ALPPY_ADMIN_DATABASE_URL`` falls back to ``ALPPY_DATABASE_URL`` so a
single-role development database keeps working with no configuration at all;
``Settings._refuse_unsafe_deployment`` is what stops that fallback reaching a
real school.
"""

from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from alppy.core.config import get_settings
from alppy.db.tenancy import TenantSession

_settings = get_settings()


def _connect_args(url: str, statement_timeout_ms: int) -> dict[str, str]:
    """A ceiling on any single statement, applied per connection.

    The role carries one too (``infra/postgres/init.sql``) and that is the one
    that cannot be forgotten. This is the per-process override on top of it:
    the worker runs a scan pipeline and an embedding write, which are
    legitimately slower than anything a request handler may do, and it raises
    its own ceiling through ``ALPPY_DB_STATEMENT_TIMEOUT_MS`` rather than the
    API lowering its guard to accommodate it.
    """
    if not url.startswith("postgresql") or statement_timeout_ms <= 0:
        return {}
    return {"options": f"-c statement_timeout={statement_timeout_ms}"}


engine = create_engine(
    str(_settings.database_url),
    pool_pre_ping=True,
    future=True,
    echo=False,
    connect_args=_connect_args(
        str(_settings.database_url), _settings.db_statement_timeout_ms
    ),
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=TenantSession,
    autoflush=False,
    expire_on_commit=False,
)


@lru_cache
def admin_engine() -> Engine:
    """The schema owner's engine. Built on first use, never at import."""
    settings = get_settings()
    url = str(settings.admin_database_url or settings.database_url)
    # No statement_timeout: a migration rewriting a large table is meant to
    # take as long as it takes.
    return create_engine(url, pool_pre_ping=True, future=True, echo=False)


@lru_cache
def _admin_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(
        bind=admin_engine(), class_=Session, autoflush=False, expire_on_commit=False
    )


def admin_session() -> Session:
    """A session that sees every school. Callers: alembic and the CLI, only."""
    return _admin_sessionmaker()()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
