"""Cross-tenant isolation.

A teacher signed into one school must not be able to read another school's
rows, and the API must not confirm that the id exists at all — every one of
these is a 404, never a 403.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise


def test_another_schools_class_reads_as_missing(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    foreign = other_tenant.school_class.id

    for path in (
        f"/api/v1/classes/{foreign}",
        f"/api/v1/classes/{foreign}/students",
        f"/api/v1/classes/{foreign}/mastery",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "not_found"


def test_another_schools_student_profile_reads_as_missing(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    foreign = other_tenant.students[0].id
    assert client.get(f"/api/v1/students/{foreign}/mastery").status_code == 404


def test_a_roster_cannot_be_written_into_another_school(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, db: Session
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        f"/api/v1/classes/{other_tenant.school_class.id}/students",
        json={"students": [{"first_name": "Eve", "last_name": "Attacker"}]},
    )
    assert response.status_code == 404
    assert len(other_tenant.school_class.students) == 1


def test_listings_never_cross_the_tenant_boundary(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    codes = {c["code"] for c in client.get("/api/v1/classes").json()}
    assert codes == {tenant.school_class.code}

    subjects = client.get("/api/v1/subjects").json()
    assert {s["id"] for s in subjects} == {str(tenant.subject.id)}

    home = client.get("/api/v1/home").json()
    assert {c["code"] for c in home["classes"]} == {tenant.school_class.code}


def test_a_sheet_cannot_reference_another_schools_exercise(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, db: Session
) -> None:
    foreign_exercise = make_exercise(db, other_tenant, statement="2/3 + 1/3 ?")
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Fractions",
            "language": "fr",
            "items": [{"exercise_id": str(foreign_exercise.id), "position": 0}],
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["details"]["ids"] == [str(foreign_exercise.id)]


def test_a_foreign_sheet_and_job_are_invisible(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, db: Session
) -> None:
    exercise = make_exercise(db, other_tenant, statement="foreign")
    login(client, other_tenant.teacher.email)
    created = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(other_tenant.school_class.id),
            "subject_id": str(other_tenant.subject.id),
            "title": "Leur feuille",
            "language": "fr",
            "items": [{"exercise_id": str(exercise.id), "position": 0}],
        },
    )
    assert created.status_code == 201
    foreign_sheet_id = created.json()["id"]

    client.post("/api/v1/auth/logout")
    login(client, tenant.teacher.email)
    assert client.get(f"/api/v1/sheets/{foreign_sheet_id}").status_code == 404
    assert client.get("/api/v1/sheets").json() == []
    assert client.get(f"/api/v1/jobs/{uuid.uuid4()}").status_code == 404
