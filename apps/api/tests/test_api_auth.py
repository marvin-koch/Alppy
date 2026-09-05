"""Login, the session cookie, and the display preferences."""

from __future__ import annotations

from fastapi.testclient import TestClient

from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import PASSWORD, Tenant, login


def test_login_sets_a_session_cookie_and_returns_the_teacher(
    client: TestClient, tenant: Tenant
) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": tenant.teacher.email, "password": PASSWORD},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == tenant.teacher.email
    assert body["school_id"] == str(tenant.school.id)
    assert body["preferences"]["locale"] == "fr"
    assert "alppy_session" in response.cookies


def test_login_rejects_a_wrong_password(client: TestClient, tenant: Tenant) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": tenant.teacher.email, "password": "not-the-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_login_does_not_distinguish_an_unknown_email(client: TestClient, tenant: Tenant) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.org", "password": PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "invalid email or password"


def test_me_requires_a_session(client: TestClient, tenant: Tenant) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_the_signed_in_teacher(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["id"] == str(tenant.teacher.id)


def test_a_tampered_cookie_is_not_a_session(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    good = client.cookies["alppy_session"]
    client.cookies.set("alppy_session", good[:-3] + "xyz")
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_logout_clears_the_session(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_preferences_round_trip(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    response = client.patch(
        "/api/v1/teachers/me/preferences",
        json={"locale": "de", "theme": "dark", "contrast": "high", "motion": None, "calm": "on"},
    )
    assert response.status_code == 200
    prefs = response.json()["preferences"]
    assert prefs == {
        "locale": "de",
        "theme": "dark",
        "contrast": "high",
        "motion": None,
        "calm": "on",
    }
    # "not chosen" is a real value and must survive a round trip as null.
    assert client.get("/api/v1/auth/me").json()["preferences"]["motion"] is None


def test_password_must_be_long_enough_to_be_worth_hashing(
    client: TestClient, tenant: Tenant
) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": tenant.teacher.email, "password": "short"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
