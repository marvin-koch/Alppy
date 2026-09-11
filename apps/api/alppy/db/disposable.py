"""Refuse to hand a destructive check a database somebody still wants.

``check-schema-drift.py`` and ``check-rls.py`` both open with ``DROP SCHEMA
public CASCADE``. That is correct — each one has to migrate from nothing to
mean anything — and for a long time the only thing standing between that
statement and a real database was::

    if "postgresql" not in URL:
        raise SystemExit(2)

which passes for every Postgres in the world, including the one serving the
application. The variable both scripts read is ``ALPPY_DATABASE_URL``: the
*app's own*. This repository's ``.env`` points it at the running demo
database, ``.env.example`` ships an ``ALPPY_ADMIN_DATABASE_URL`` that is the
owner of that same database, and CLAUDE.md documents the RLS check as taking
the owner's DSN. So the failure did not need anyone to make a mistake — a
developer who exported the environment the repository gives them and ran the
command the repository documents lost the database, and the guard said nothing
because the URL did indeed contain "postgresql".

``test_migration_0021.py``'s fixture already had this right, and says so in its
own docstring: it creates a database per run and drops it afterwards, "never
the developer's ... exactly the accident worth designing out". This module is
that fixture's rule, made available to the two scripts that most need it.

Three conditions, and **all** of them must hold:

1. **The database is named like a throwaway.** One of the last two
   underscore-separated segments is a disposable marker, so ``alppy_drift``,
   ``alppy_rls`` and ``alppy_mig_9f2c`` pass and ``alppy`` does not. This is
   the load-bearing one: the database a deployment actually serves is the one
   that will not be named after a test.
2. **``ALPPY_ENV`` is ``ci`` or ``local``.** Staging and production hold data
   whose loss is somebody's afternoon or somebody's year.
3. **The host is loopback, or the DSN came from ``ALPPY_DISPOSABLE_DATABASE_URL``
   rather than the app's own variable.** Naming a separate variable is how a
   developer says "I meant this one" — and it is the only way to point a check
   at a remote host, which is deliberate.

Condition 3 is the weakest of the three and is not trusted alone: on a
developer machine loopback frequently reaches a personal Postgres full of
unrelated work. It narrows the blast radius; condition 1 is what stops the
accident.

Every failure is collected and reported together. Whoever hits this guard is
mid-command and looking for the shortest way past it, so the message names the
shortest *safe* way rather than the shortest.
"""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

#: The app's own DSN. Reading this one is what made the accident possible, so
#: it is the fallback, never the first choice.
APP_URL_VAR = "ALPPY_DATABASE_URL"

#: Say "I meant this database" out loud. Checked first, and the only way to
#: aim a destructive check at a host that is not loopback.
DISPOSABLE_URL_VAR = "ALPPY_DISPOSABLE_DATABASE_URL"

#: A segment that marks a database as somebody's scratch space. Matched against
#: the last two underscore-separated segments of the database name, which is
#: what lets a per-run suffix through (``alppy_mig_9f2c``) without letting a
#: prefix through (``test_alppy_production`` does not pass).
DISPOSABLE_MARKERS = frozenset(
    {
        "ci",
        "disposable",
        "drift",
        "mig",
        "probe",
        "rls",
        "scratch",
        "temp",
        "test",
        "tests",
        "throwaway",
        "tmp",
    }
)

#: ``ALPPY_ENV`` values in which losing the database costs a re-run.
DISPOSABLE_ENVS = frozenset({"ci", "local"})

#: An empty host is a unix socket, which is as local as it gets.
LOOPBACK_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1", "[::1]"})


class NotDisposableError(RuntimeError):
    """The named database is not one this process may destroy."""


def is_disposable_name(database: str) -> bool:
    """Is ``database`` named like something nobody will miss?

    One of the **last two** segments must be a marker. Anchoring at the end is
    the point: a per-run suffix is normal (``alppy_mig_9f2c``) and a reassuring
    prefix is not evidence of anything (``test_alppy`` is how a production
    database ends up named after the environment it was cloned from).
    """
    segments = database.lower().split("_")
    return any(segment in DISPOSABLE_MARKERS for segment in segments[-2:])


def resolve_disposable_url(env: Mapping[str, str]) -> str:
    """Return a DSN it is safe to drop the public schema of.

    Raises ``NotDisposableError`` with every reason at once, or ``KeyError``-shaped
    ``NotDisposableError`` when neither variable is set.
    """
    source = DISPOSABLE_URL_VAR if env.get(DISPOSABLE_URL_VAR) else APP_URL_VAR
    raw = env.get(source)
    if not raw:
        raise NotDisposableError(
            f"neither {DISPOSABLE_URL_VAR} nor {APP_URL_VAR} is set. This check "
            f"migrates a database from nothing, so it needs one it may destroy:\n\n"
            f"    {DISPOSABLE_URL_VAR}=postgresql+psycopg://user:pw@localhost:5432/alppy_drift\n"
        )

    try:
        url = make_url(raw)
    except ArgumentError as exc:  # a typo in a DSN, not a database we may drop
        raise NotDisposableError(f"{source} is not a database URL: {exc}") from exc

    if not url.drivername.startswith("postgresql"):
        raise NotDisposableError(
            f"this check needs Postgres, not {url.drivername.split('+')[0]}: "
            f"SQLite has neither the roles nor the policies it looks for."
        )

    database = url.database or ""
    host = (url.host or "").lower()
    app_env = env.get("ALPPY_ENV", "")

    refusals: list[str] = []
    if not is_disposable_name(database):
        refusals.append(
            f"the database is named {database!r}, which is not a throwaway name. "
            f"One of its last two underscore-separated segments must be one of: "
            f"{', '.join(sorted(DISPOSABLE_MARKERS))}. "
            f"{database!r} is much more likely to be a database someone is using."
        )
    if app_env not in DISPOSABLE_ENVS:
        refusals.append(
            f"ALPPY_ENV is {app_env or 'unset'!r}, not one of "
            f"{', '.join(sorted(DISPOSABLE_ENVS))}. A check that drops the public "
            f"schema does not run against an environment holding anyone's data."
        )
    if host not in LOOPBACK_HOSTS and source != DISPOSABLE_URL_VAR:
        refusals.append(
            f"the host is {host!r}, which is not loopback, and the DSN came from "
            f"{APP_URL_VAR} — the variable the application itself reads. To aim "
            f"this check at a remote database, name it in {DISPOSABLE_URL_VAR} "
            f"instead, which is how you say you meant it."
        )

    if refusals:
        raise NotDisposableError(
            f"refusing to drop the public schema of {_redact(raw)}, read from "
            f"{source}.\n\n"
            + "\n\n".join(f"  - {reason}" for reason in refusals)
            + f"\n\nThis check destroys the database it runs against. The safe way "
            f"is a database of its own:\n\n"
            f"    createdb alppy_drift\n"
            f"    ALPPY_ENV=local {DISPOSABLE_URL_VAR}=postgresql+psycopg://"
            f"user:pw@localhost:5432/alppy_drift \\\n"
            f"        python scripts/check-schema-drift.py\n"
        )

    return raw


def _redact(raw: str) -> str:
    """A DSN without its password — this string goes to a terminal and a CI log."""
    try:
        return make_url(raw).render_as_string(hide_password=True)
    except ArgumentError:
        return "<unparseable DSN>"
