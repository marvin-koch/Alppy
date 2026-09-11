"""The guard between `DROP SCHEMA public CASCADE` and a database in use.

``check-schema-drift.py`` and ``check-rls.py`` each have to migrate a database
from nothing, so each one opens by dropping the public schema. For a long time
the only thing between that statement and a real database was a test that the
URL contained "postgresql", which every Postgres in the world passes.

What makes it worth a module of tests rather than a warning in a docstring is
that nobody had to make a mistake for it to fire. Both scripts read
``ALPPY_DATABASE_URL`` — the *application's* variable. This repository's
``.env`` points that at the running demo database; ``.env.example`` ships an
``ALPPY_ADMIN_DATABASE_URL`` that is the owner of the same database; and
CLAUDE.md documents the RLS check as taking an owner DSN. Exporting the
environment the repository provides and running the command the repository
documents was the failure path.

So the case that matters most here is `test_the_repositorys_own_env_is_refused`:
not a malformed DSN, not a typo, but the exact configuration a developer gets
by following instructions.
"""

from __future__ import annotations

import pytest

from alppy.db.disposable import (
    APP_URL_VAR,
    DISPOSABLE_URL_VAR,
    NotDisposableError,
    is_disposable_name,
    resolve_disposable_url,
)

#: An environment that should be allowed through, so each test can spoil
#: exactly one thing and have the failure name that thing.
GOOD = {
    "ALPPY_ENV": "local",
    DISPOSABLE_URL_VAR: "postgresql+psycopg://alppy:pw@localhost:5432/alppy_drift",
}


def _resolve(**overrides: str) -> str:
    env = {**GOOD, **overrides}
    return resolve_disposable_url({k: v for k, v in env.items() if v})


# --- The case the guard exists for -----------------------------------------


def test_the_repositorys_own_env_is_refused() -> None:
    """`.env` as committed, plus the command CLAUDE.md documents.

    This is the whole point. `alppy` is a perfectly ordinary database name, the
    host is loopback, and ALPPY_ENV is `local` — two of the three conditions
    hold, which is exactly why the name has to be the load-bearing one.
    """
    with pytest.raises(NotDisposableError) as excinfo:
        resolve_disposable_url(
            {
                "ALPPY_ENV": "local",
                APP_URL_VAR: "postgresql+psycopg://alppy:alppy@localhost:5432/alppy",
            }
        )
    message = str(excinfo.value)
    assert "'alppy'" in message
    assert "not a throwaway name" in message


def test_the_admin_dsn_from_env_example_is_refused() -> None:
    """`check-rls.py` asks for an owner DSN, and the owner DSN a developer has
    to hand owns the database the application is serving."""
    with pytest.raises(NotDisposableError):
        resolve_disposable_url(
            {
                "ALPPY_ENV": "local",
                APP_URL_VAR: "postgresql+psycopg://alppy:alppy@localhost:5432/alppy",
            }
        )


# --- Each condition, spoiled one at a time ---------------------------------


def test_a_disposable_database_is_allowed() -> None:
    assert _resolve() == GOOD[DISPOSABLE_URL_VAR]


@pytest.mark.parametrize(
    "database",
    ["alppy", "postgres", "alppy_production", "alppy_staging", "sion", "alppy_demo"],
)
def test_a_database_nobody_called_a_throwaway_is_refused(database: str) -> None:
    with pytest.raises(NotDisposableError, match="not a throwaway name"):
        _resolve(
            **{DISPOSABLE_URL_VAR: f"postgresql+psycopg://alppy:pw@localhost:5432/{database}"}
        )


@pytest.mark.parametrize(
    "database",
    [
        "alppy_drift",  # the schema-drift CI job
        "alppy_rls",  # the row-level-security CI job
        "alppy_test",  # the API job's server
        "alppy_mig_9f2c1d",  # test_migration_0021.py's per-run fixture
        "scratch",
        "alppy_ci",
    ],
)
def test_the_names_the_project_actually_uses_are_allowed(database: str) -> None:
    assert _resolve(
        **{DISPOSABLE_URL_VAR: f"postgresql+psycopg://alppy:pw@localhost:5432/{database}"}
    )


@pytest.mark.parametrize("env", ["staging", "production", "", "prod"])
def test_an_environment_holding_someones_data_is_refused(env: str) -> None:
    with pytest.raises(NotDisposableError, match="ALPPY_ENV"):
        _resolve(ALPPY_ENV=env)


def test_a_remote_host_is_refused_through_the_apps_own_variable() -> None:
    """The third condition. Naming the dedicated variable is how a developer
    says they meant it; the app's variable is what a shell inherits by
    accident."""
    with pytest.raises(NotDisposableError, match="not loopback"):
        resolve_disposable_url(
            {
                "ALPPY_ENV": "local",
                APP_URL_VAR: "postgresql+psycopg://alppy:pw@db.internal:5432/alppy_drift",
            }
        )


def test_a_remote_host_is_allowed_when_it_was_named_deliberately() -> None:
    """A disposable database on a remote CI server is legitimate — but only
    via the variable nothing else sets."""
    url = "postgresql+psycopg://alppy:pw@db.internal:5432/alppy_drift"
    assert resolve_disposable_url({"ALPPY_ENV": "ci", DISPOSABLE_URL_VAR: url}) == url


def test_the_dedicated_variable_wins_over_the_apps_own() -> None:
    """Both set — which is the normal case, since `.env` sets the app's — must
    resolve to the one that was named on purpose."""
    disposable = "postgresql+psycopg://alppy:pw@localhost:5432/alppy_drift"
    assert (
        resolve_disposable_url(
            {
                "ALPPY_ENV": "local",
                APP_URL_VAR: "postgresql+psycopg://alppy:alppy@localhost:5432/alppy",
                DISPOSABLE_URL_VAR: disposable,
            }
        )
        == disposable
    )


# --- Shapes that are not a database at all ---------------------------------


def test_nothing_set_names_the_variable_to_set() -> None:
    with pytest.raises(NotDisposableError, match=DISPOSABLE_URL_VAR):
        resolve_disposable_url({"ALPPY_ENV": "local"})


def test_sqlite_is_refused_for_what_it_cannot_show() -> None:
    with pytest.raises(NotDisposableError, match="needs Postgres"):
        _resolve(**{DISPOSABLE_URL_VAR: "sqlite:///./alppy_test.db"})


def test_the_refusal_does_not_print_the_password() -> None:
    """This message goes to a terminal and to a CI log."""
    with pytest.raises(NotDisposableError) as excinfo:
        resolve_disposable_url(
            {
                "ALPPY_ENV": "production",
                DISPOSABLE_URL_VAR: "postgresql+psycopg://alppy:hunter2@localhost:5432/alppy_drift",
            }
        )
    assert "hunter2" not in str(excinfo.value)


def test_the_refusal_says_the_shortest_safe_way_past_it() -> None:
    """Whoever hits this is mid-command and looking for the shortest way on.
    "Not allowed" invites `|| true`; a working command does not."""
    with pytest.raises(NotDisposableError) as excinfo:
        resolve_disposable_url(
            {
                "ALPPY_ENV": "local",
                APP_URL_VAR: "postgresql+psycopg://alppy:alppy@localhost:5432/alppy",
            }
        )
    message = str(excinfo.value)
    assert "createdb alppy_drift" in message
    assert DISPOSABLE_URL_VAR in message


# --- The name rule on its own ----------------------------------------------


def test_a_reassuring_prefix_is_not_evidence() -> None:
    """A marker has to be in the last two segments. `test_alppy_production` is
    how a real database ends up named after what it was cloned from."""
    assert not is_disposable_name("test_alppy_production")
    assert is_disposable_name("alppy_production_test")
