"""Classes, roster paste and UID assignment, and the home summary."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_tenant


def test_create_class_normalises_the_code(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    response = client.post("/api/v1/classes", json={"code": "9a", "label": "Groupe B"})
    assert response.status_code == 201
    assert response.json()["code"] == "9A"
    assert response.json()["student_count"] == 0


def test_create_class_rejects_a_code_that_is_not_a_class_code(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.post("/api/v1/classes", json={"code": "maths"})
    assert response.status_code == 422


def test_duplicate_class_code_in_the_same_year_is_a_conflict(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    client.post("/api/v1/classes", json={"code": "9A"})
    again = client.post("/api/v1/classes", json={"code": "9A"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "conflict"


def test_a_new_school_gets_a_school_year_on_first_class(
    client: TestClient, db: Session
) -> None:
    fresh = make_tenant(db, name="Ecole neuve", email="new@ecole.ch", class_code="8C")
    login(client, fresh.teacher.email)
    assert client.post("/api/v1/classes", json={"code": "8D"}).status_code == 201


def test_roster_paste_assigns_sequential_numbers_and_uids(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    created = client.post("/api/v1/classes", json={"code": "10B"})
    class_id = created.json()["id"]

    response = client.post(
        f"/api/v1/classes/{class_id}/students",
        json={
            "students": [
                {"first_name": "Lea", "last_name": "Roth"},
                {"first_name": "Noah", "last_name": "Berger"},
                {"first_name": "Mia", "last_name": "Keller"},
            ]
        },
    )
    assert response.status_code == 201
    students = response.json()
    assert [s["number"] for s in students] == [1, 2, 3]
    assert [s["uid"] for s in students] == ["10B_01", "10B_02", "10B_03"]


def test_roster_paste_continues_after_the_existing_roster(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        f"/api/v1/classes/{tenant.school_class.id}/students",
        json={"students": [{"first_name": "Jonas", "last_name": "Weber"}]},
    )
    assert response.status_code == 201
    assert response.json()[0]["uid"] == "7B_04"


def test_an_explicit_number_is_honoured_and_a_clash_is_a_conflict(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    ok = client.post(
        f"/api/v1/classes/{tenant.school_class.id}/students",
        json={"students": [{"first_name": "Ana", "last_name": "Bianchi", "number": 12}]},
    )
    assert ok.status_code == 201
    assert ok.json()[0]["uid"] == "7B_12"

    clash = client.post(
        f"/api/v1/classes/{tenant.school_class.id}/students",
        json={"students": [{"first_name": "Zoe", "last_name": "Meier", "number": 12}]},
    )
    assert clash.status_code == 409
    assert clash.json()["error"]["details"]["number"] == 12


def test_roster_rejects_an_empty_paste(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        f"/api/v1/classes/{tenant.school_class.id}/students", json={"students": []}
    )
    assert response.status_code == 422


def test_list_students_is_ordered_by_number(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    students = client.get(f"/api/v1/classes/{tenant.school_class.id}/students").json()
    assert [s["number"] for s in students] == [1, 2, 3]
    assert [s["uid"] for s in students] == ["7B_01", "7B_02", "7B_03"]


def test_home_summarises_every_class(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    body = client.get("/api/v1/home").json()

    assert body["teacher"]["email"] == tenant.teacher.email
    assert [s["key"] for s in body["subjects"]] == ["mathematics"]
    summary = body["classes"][0]
    assert summary["code"] == "7B"
    assert summary["student_count"] == 3
    assert summary["pending_scans"] == 0
    assert summary["students_needing_attention"] == 0
    assert summary["last_sheet_title"] is None
    assert set(summary["band_counts"]) == {"solid", "ok", "weak", "fading", "none"}


def test_home_requires_a_session(client: TestClient, tenant: Tenant) -> None:
    assert client.get("/api/v1/home").status_code == 401
