"""Classes, roster paste and UID assignment, and the home summary."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_colleague, make_tenant

from alppy.api.errors import ApiError
from alppy.models import Class
from alppy.services import class_service


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


# --------------------------------------------------------------------------
# Enrollment (D69) — a student sits in many classes, one of which minted the uid
# --------------------------------------------------------------------------
def _visiting_class(db: Session, tenant: Tenant, code: str = "9A") -> Class:
    school_class = Class(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        school_year_id=tenant.school_class.school_year_id,
        teacher_id=tenant.teacher.id,
        code=code,
        label="Soutien",
    )
    db.add(school_class)
    db.flush()
    return school_class


def test_a_co_enrolled_student_keeps_the_uid_their_home_class_minted(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    support = _visiting_class(db, tenant)
    visitor = tenant.students[0]
    class_service.enroll(db, support, visitor)
    db.commit()

    login(client, tenant.teacher.email)
    listed = client.get(f"/api/v1/classes/{support.id}/students").json()

    # In both rosters, under one identity. The uid is printed on paper and
    # decoded by the detector; it belongs to the home class, not to wherever
    # the child happens to be sitting (I-platform-09).
    assert [s["uid"] for s in listed] == [visitor.uid]
    assert visitor.uid.startswith(tenant.school_class.code)

    home = client.get(f"/api/v1/classes/{tenant.school_class.id}/students").json()
    assert visitor.uid in {s["uid"] for s in home}


def test_a_roster_paste_numbers_around_a_visiting_student(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """A visitor's number belongs to their own class, and blocks nothing here."""
    support = _visiting_class(db, tenant)
    visitor = tenant.students[0]  # 7B_01, number 1
    class_service.enroll(db, support, visitor)
    db.commit()
    assert visitor.number == 1

    login(client, tenant.teacher.email)
    response = client.post(
        f"/api/v1/classes/{support.id}/students",
        json={"students": [{"first_name": "Tim", "last_name": "Frei"}]},
    )

    # Number 1 is free in 9A even though a visitor carrying number 1 sits in
    # it: `taken` is computed over the class's OWN pupils, not its roster.
    assert response.status_code == 201
    assert response.json()[0]["uid"] == "9A_01"


def test_a_student_cannot_leave_the_class_that_minted_their_uid(
    db: Session, tenant: Tenant
) -> None:
    with pytest.raises(ApiError):
        class_service.unenroll(db, tenant.school_class, tenant.students[0])


def test_unenrolling_removes_a_visitor_without_touching_their_record(
    db: Session, tenant: Tenant
) -> None:
    support = _visiting_class(db, tenant)
    visitor = tenant.students[0]
    class_service.enroll(db, support, visitor)
    db.commit()

    class_service.unenroll(db, support, visitor)
    db.commit()

    assert class_service.list_students(db, tenant.scope, support.id) == []
    # The pupil, their uid and their home are all untouched: unenrolling is
    # not a delete, and only a delete is allowed to destroy evidence.
    still = class_service.list_students(db, tenant.scope, tenant.school_class.id)
    assert visitor.uid in {s.uid for s in still}


def test_enrolling_seats_a_pupil_without_touching_their_identifier(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    support = _visiting_class(db, tenant)
    visitor = tenant.students[0]
    db.commit()
    login(client, tenant.teacher.email)

    response = client.post(
        f"/api/v1/classes/{support.id}/students/{visitor.id}/enrollment"
    )
    assert response.status_code == 201
    assert [s["uid"] for s in response.json()] == [visitor.uid]

    # The uid is printed on paper and decoded by the scanner. Moving a pupil
    # between classes must never move it.
    db.refresh(visitor)
    assert visitor.uid.startswith(tenant.school_class.code)
    assert visitor.home_class_id == tenant.school_class.id


def test_enrolling_twice_is_not_an_error(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    support = _visiting_class(db, tenant)
    db.commit()
    login(client, tenant.teacher.email)
    path = f"/api/v1/classes/{support.id}/students/{tenant.students[0].id}/enrollment"

    assert client.post(path).status_code == 201
    second = client.post(path)
    assert second.status_code == 201
    assert len(second.json()) == 1


def test_unenrolling_keeps_the_pupil_and_their_evidence(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    support = _visiting_class(db, tenant)
    visitor = tenant.students[0]
    db.commit()
    login(client, tenant.teacher.email)
    path = f"/api/v1/classes/{support.id}/students/{visitor.id}/enrollment"
    client.post(path)

    response = client.delete(path)
    assert response.status_code == 200
    assert response.json() == []

    # Still in their own class, still themselves.
    home = client.get(f"/api/v1/classes/{tenant.school_class.id}/students").json()
    assert visitor.uid in {s["uid"] for s in home}


def test_a_pupil_cannot_be_unenrolled_from_their_home_class(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.delete(
        f"/api/v1/classes/{tenant.school_class.id}"
        f"/students/{tenant.students[0].id}/enrollment"
    )
    assert response.status_code == 409


def test_a_colleagues_pupil_cannot_be_enrolled(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """Enrollment widens who a teacher may read; it is not a way in."""
    colleague = make_colleague(db, tenant, email="bea2@alpes.ch", class_code="8B")
    support = _visiting_class(db, tenant, code="9C")
    db.commit()
    login(client, tenant.teacher.email)

    response = client.post(
        f"/api/v1/classes/{support.id}/students/{colleague.students[0].id}/enrollment"
    )
    assert response.status_code == 404
