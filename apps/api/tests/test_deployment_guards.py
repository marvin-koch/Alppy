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
    "database_url": "postgresql+psycopg://alppy_app:pw@db.internal:5432/alppy",
    "admin_database_url": "postgresql+psycopg://alppy:pw@db.internal:5432/alppy",
    "cors_origins": ("https://app.alppy.ch",),
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
        # Unset means migrations run as the API's own role, which means the API
        # IS the schema owner — and row-level security does not apply to a
        # table's owner. Every policy is present and none of them fire (D84).
        ("admin_database_url", None, "ALPPY_ADMIN_DATABASE_URL"),
        # `allow_credentials=True` is what makes this list a trust boundary: a
        # wildcard is reflected back per-origin, so the session cookie travels
        # and any page on the internet reads the roster the teacher can see.
        ("cors_origins", ("*",), "ALPPY_CORS_ORIGINS"),
        ("cors_origins", ("https://app.alppy.ch", "*"), "ALPPY_CORS_ORIGINS"),
        ("cors_origins", ("https://*.alppy.ch",), "ALPPY_CORS_ORIGINS"),
        # The default. Nothing has to be typed wrong for this one to reach a
        # server — it is what the deployment gets by saying nothing.
        ("cors_origins", ("http://localhost:3000",), "ALPPY_CORS_ORIGINS"),
        ("cors_origins", ("https://app.alppy.ch", "http://127.0.0.1:3000"), "ALPPY_CORS_ORIGINS"),
        ("cors_origins", (), "ALPPY_CORS_ORIGINS"),
    ],
)
def test_each_unsafe_setting_is_refused_in_production(
    field: str, value: object, expected: str
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _settings(env="production", **{field: value})
    assert expected in str(excinfo.value)


def test_a_production_deployment_may_name_several_real_origins() -> None:
    """The guard rejects a shape, not a length: a school on its own domain and
    the app's own host are two legitimate entries, and neither is local."""
    settings = _settings(
        env="production",
        cors_origins=("https://app.alppy.ch", "https://sion.alppy.ch"),
    )
    assert settings.cors_origins == ("https://app.alppy.ch", "https://sion.alppy.ch")


def test_a_developer_keeps_localhost_in_the_environments_it_is_for() -> None:
    """`pnpm dev` serves the web app from `http://localhost:3000`, so the
    default has to keep working — the guard is about `env`, not about the
    string."""
    settings = Settings(_env_file=None, env="local")
    assert settings.cors_origins == ("http://localhost:3000",)


def test_the_cors_refusal_says_what_a_wildcard_costs() -> None:
    """The message is the whole value of a startup guard: whoever hits it is
    mid-deployment and looking for the shortest way past. "Not allowed" invites
    a wildcard on a different line; naming the cookie does not."""
    with pytest.raises(ValidationError) as excinfo:
        _settings(env="production", cors_origins=("*",))
    message = str(excinfo.value)
    assert "cookie" in message and "cross-origin" in message


def test_the_api_may_not_connect_as_the_schema_owner() -> None:
    """Two DSNs naming one role is the same mistake as having only one.

    It is worth its own test because it is the version that LOOKS configured:
    `ALPPY_ADMIN_DATABASE_URL` is set, so the guard above is satisfied, and
    every row-level security policy is in place and inert — Postgres does not
    apply them to the role that owns the table (D84).
    """
    with pytest.raises(ValidationError) as excinfo:
        _settings(
            env="production",
            database_url="postgresql+psycopg://alppy:pw@db.internal:5432/alppy",
        )
    assert "ALPPY_ADMIN_DATABASE_URL" in str(excinfo.value)


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

    monkeypatch.setattr("alppy.cli.admin_session", _no_session)

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

    monkeypatch.setattr("alppy.cli.admin_session", _FakeSession)
    monkeypatch.setattr("alppy.seed.run_seed", lambda db: ran.append(True))

    assert _seed() == 0
    assert ran == [True]
