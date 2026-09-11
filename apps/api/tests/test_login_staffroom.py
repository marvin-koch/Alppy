"""The staffroom list in a login response.

Row-level security is keyed on `app.current_school_id` and an unbound session
sees nothing (D84). Login was the one entry point that never bound, so on
Postgres `schools` came back `[]` on every login in every deployment — while
this suite, which runs on SQLite and has no policies, saw it full and passed.

That asymmetry is why these tests assert the BINDING rather than only the list:
the list is what SQLite can check, and the bind is what Postgres needs.
`scripts/check-rls.py` is the other half, against a real Postgres.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import PASSWORD, Tenant

from alppy.db.validity import today
from alppy.models import teacher_school


def test_login_reports_the_staffrooms(client: TestClient, tenant: Tenant) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": tenant.teacher.email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    names = [s["name"] for s in response.json()["schools"]]
    assert tenant.school.name in names


def test_login_binds_the_tenant_so_the_read_can_see_anything(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """The claim SQLite cannot make on its own.

    Asserted by observing the session the handler used: without the bind the
    read is answered by a policy that matches nothing, and the symptom on
    Postgres is an empty list rather than an error.
    """
    bound: list[object] = []
    from alppy.db import tenancy

    original = tenancy.bind

    def _record(session: Session, **kwargs: object) -> None:
        bound.append(kwargs.get("school_id"))
        original(session, **kwargs)  # type: ignore[arg-type]

    tenancy.bind = _record  # type: ignore[assignment]
    try:
        client.post(
            "/api/v1/auth/login",
            json={"email": tenant.teacher.email, "password": PASSWORD},
        )
    finally:
        tenancy.bind = original  # type: ignore[assignment]

    assert tenant.school.id in bound


def test_a_teacher_who_left_their_home_school_binds_nothing(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """The entitlement check comes with the bind, and it is the same predicate
    `get_membership` uses.

    Their cookie is minted for a school they no longer work at, so every
    subsequent request is refused anyway — an empty staffroom list is the
    honest report of the state they are in, not a failure to look.
    """
    db.execute(
        teacher_school.update()
        .where(teacher_school.c.teacher_id == tenant.teacher.id)
        .where(teacher_school.c.school_id == tenant.school.id)
        .values(valid_to=today())
    )
    db.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": tenant.teacher.email, "password": PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["schools"] == []


def test_a_second_staffroom_is_reported_too(
    client: TestClient, db: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    """What the `school` policy's second arm exists for (D74): a teacher sees
    the OTHER schools they work at, so the rail can offer the switch."""
    from alppy.services import class_service

    class_service.join_school(db, tenant.teacher.id, other_tenant.school.id)
    db.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": tenant.teacher.email, "password": PASSWORD},
    )
    names = {s["name"] for s in response.json()["schools"]}
    assert {tenant.school.name, other_tenant.school.name} <= names
