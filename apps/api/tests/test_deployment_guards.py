"""The two guards that stand between a development default and a real school.

Both exist because the dangerous configuration is the one nobody types. A
deployment that says nothing gets a published cookie-signing key, a published
bucket password, and — on every container start — two teacher logins whose
passwords are constants in this repository. Neither guard protects `local` or
`ci`: the defaults are *for* them, and a guard that fired there would be turned
off within a week.

See docs/privacy.md for what is behind the door.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from alppy.cli import _seed
from alppy.core.config import DEV_S3_SECRET_KEY, DEV_SECRET_KEY, Settings

#: A deployment that has done everything right. Each test spoils exactly one
#: field, so a failure names the field rather than the fixture.
GOOD = {
    "secret_key": "a-real-and-sufficiently-long-secret",
    "s3_secret_key": "a-real-bucket-password",
    "database_url": "postgresql+psycopg://alppy:pw@db.internal:5432/alppy",
}


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**GOOD, **overrides})  # type: ignore[arg-type]


# --- The startup validator -------------------------------------------------


@pytest.mark.parametrize("env", ["staging", "production"])
def test_a_fully_configured_deployment_boots(env: str) -> None:
    assert _settings(env=env).env == env


@pytest.mark.parametrize("env", ["local", "ci"])
def test_development_environments_keep_every_default(env: str) -> None:
    """The exemption is the point: `docker compose up` must need no arguments."""
    settings = Settings(_env_file=None, env=env)
    assert settings.secret_key == DEV_SECRET_KEY
    assert settings.s3_secret_key == DEV_S3_SECRET_KEY


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("secret_key", DEV_SECRET_KEY, "ALPPY_SECRET_KEY"),
        ("s3_secret_key", DEV_S3_SECRET_KEY, "ALPPY_S3_SECRET_KEY"),
        ("demo_mode", True, "ALPPY_DEMO_MODE"),
        (
            "database_url",
            "postgresql+psycopg://alppy:alppy@localhost:5432/alppy",
            "ALPPY_DATABASE_URL",
        ),
    ],
)
def test_each_unsafe_setting_is_refused_in_production(
    field: str, value: object, expected: str
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _settings(env="production", **{field: value})
    assert expected in str(excinfo.value)


def test_the_loopback_address_is_local_too() -> None:
    """`localhost` is the spelling people notice; 127.0.0.1 is the one they don't."""
    with pytest.raises(ValidationError, match="ALPPY_DATABASE_URL"):
        _settings(env="production", database_url="postgresql+psycopg://a:b@127.0.0.1:5432/alppy")


def test_a_failover_dsn_is_refused_when_any_host_is_local() -> None:
    """A multi-host DSN is legitimate for Postgres failover.

    Checking only the first host would let a standby on the deployer's laptop
    through — and a failover target is precisely the host nobody looks at again.
    """
    with pytest.raises(ValidationError, match="ALPPY_DATABASE_URL"):
        _settings(
            env="production",
            database_url="postgresql+psycopg://a:b@db.internal:5432,localhost:5432/alppy",
        )


def test_every_problem_is_reported_at_once() -> None:
    """A fresh deployment has several, and one restart per problem is a checklist
    that gets abandoned half-done."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, env="production", demo_mode=True)
    message = str(excinfo.value)
    for expected in ("ALPPY_SECRET_KEY", "ALPPY_S3_SECRET_KEY", "ALPPY_DEMO_MODE"):
        assert expected in message


# --- The seed guard --------------------------------------------------------


@pytest.mark.parametrize("env", ["staging", "production"])
def test_the_demo_seed_refuses_outside_development(
    env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It would plant two logins whose passwords are published in this repo.

    Asserted by watching the database session: refusing has to happen *before*
    anything opens a connection, not by rolling one back.
    """
    monkeypatch.setattr("alppy.cli.get_settings", lambda: _settings(env=env))

    def _no_session() -> None:
        raise AssertionError("the seed opened a database session in a real environment")

    monkeypatch.setattr("alppy.cli.SessionLocal", _no_session)

    assert _seed() == 0


def test_the_demo_seed_still_runs_in_development(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard must not cost `docker compose up` its demo data."""
    monkeypatch.setattr("alppy.cli.get_settings", lambda: Settings(_env_file=None, env="local"))
    ran: list[bool] = []

    class _FakeSession:
        def __enter__(self) -> _FakeSession:
            return self

        def commit(self) -> None: ...
        def rollback(self) -> None: ...
        def close(self) -> None: ...

    monkeypatch.setattr("alppy.cli.SessionLocal", _FakeSession)
    monkeypatch.setattr("alppy.seed.run_seed", lambda db: ran.append(True))

    assert _seed() == 0
    assert ran == [True]
