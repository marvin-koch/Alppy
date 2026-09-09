"""Demo mode: a request with no cookie may answer as the demo teacher.

This is the only bypass of the session cookie in the product, and the cookie is
the one thing standing between an open URL and a roster of children's real first
and last names (`Student.first_name`, docs/privacy.md). So the tests that matter
most here are the ones asserting it is OFF — by default, and under every
neighbouring setting that might look like it should imply it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import PASSWORD, Tenant, make_app_client

from alppy.core.config import Settings


def test_demo_mode_is_off_by_default() -> None:
    """The default is what a deployment gets when nobody thought about it."""
    assert Settings(env="ci", secret_key="test-secret-key").demo_mode is False


def test_no_cookie_is_still_unauthorized_by_default(
    client: TestClient, tenant: Tenant
) -> None:
    assert client.get("/api/v1/classes").status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401


def test_debug_and_local_env_do_not_turn_demo_mode_on() -> None:
    """Deliberately not derived from any other signal.

    A flag that can switch itself on from `debug` or `env` is one that
    eventually switches itself on somewhere real.
    """
    assert Settings(env="local", debug=True, secret_key="test-secret-key").demo_mode is False
    assert Settings(env="production", secret_key="test-secret-key").demo_mode is False


def test_with_demo_mode_on_a_cookieless_request_is_the_demo_teacher(
    db: Session, storage, tenant: Tenant
) -> None:
    demo_settings = Settings(
        env="ci",
        secret_key="test-secret-key",
        max_upload_mb=1,
        demo_mode=True,
        demo_teacher_email=tenant.teacher.email,
    )
    with make_app_client(db, storage, demo_settings) as demo_client:
        response = demo_client.get("/api/v1/auth/me")
        assert response.status_code == 200
        assert response.json()["email"] == tenant.teacher.email

        # And the app is actually usable, not merely authenticated.
        assert demo_client.get("/api/v1/classes").status_code == 200


def test_demo_mode_says_so_when_the_seed_has_not_run(
    db: Session, storage, tenant: Tenant
) -> None:
    """A 401 here would send the reader hunting for a login that cannot help."""
    demo_settings = Settings(
        env="ci",
        secret_key="test-secret-key",
        max_upload_mb=1,
        demo_mode=True,
        demo_teacher_email="nobody@alppy.ch",
    )
    with make_app_client(db, storage, demo_settings) as demo_client:
        response = demo_client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert "seed" in response.text


def test_a_real_session_still_wins_over_demo_mode(
    db: Session, storage, tenant: Tenant, colleague: Tenant
) -> None:
    """Demo mode is a fallback for the *absence* of a cookie, never an override.

    A teacher who signs in on a demo instance must still be themselves, or the
    ownership rules every read depends on (D23) would silently answer for
    somebody else.
    """
    demo_settings = Settings(
        env="ci",
        secret_key="test-secret-key",
        max_upload_mb=1,
        demo_mode=True,
        demo_teacher_email=tenant.teacher.email,
    )
    with make_app_client(db, storage, demo_settings) as demo_client:
        demo_client.post(
            "/api/v1/auth/login",
            json={"email": colleague.teacher.email, "password": PASSWORD},
        )
        assert demo_client.get("/api/v1/auth/me").json()["email"] == colleague.teacher.email
