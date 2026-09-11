"""`POST /students/{id}/anonymise` — erasure that keeps the evidence.

The only answer to a parent's request used to be `delete_student`, which
destroys the attempts along with the child and silently changes every class
statistic they contributed to (audit 02, H8; database audit H5).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise

from alppy.models import Attempt, Person, Student


def test_the_names_go_and_the_evidence_stays(
    client: TestClient, db: Session, tenant: Tenant, reread: Callable[[], Session]
) -> None:
    """The whole point. A band already shown to somebody must not change."""
    exercise = make_exercise(db, tenant, statement="1/2 + 1/4 ?")
    student = tenant.students[0]
    db.add(
        Attempt(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            person_id=student.person_id,
            exercise_id=exercise.id,
            correct=True,
            score=1.0,
            difficulty=3,
            answered_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    db.commit()

    login(client, tenant.teacher.email)
    response = client.post(
        f"/api/v1/students/{student.id}/anonymise",
        json={"confirm": student.uid},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_name"] is None
    assert body["last_name"] is None
    assert body["anonymised_at"] is not None
    # Retained on purpose: it is what the paper carries, and what a roster
    # falls back to.
    assert body["uid"] == student.uid

    fresh = reread()
    person = fresh.get(Person, student.person_id)
    assert person is not None
    assert person.first_name is None and person.last_name is None
    assert person.anonymised_at is not None

    # The evidence is untouched.
    attempts = fresh.execute(
        select(Attempt).where(Attempt.person_id == student.person_id)
    ).scalars().all()
    assert len(attempts) == 1


def test_the_name_goes_from_every_year_not_just_this_one(
    client: TestClient, db: Session, tenant: Tenant, reread: Callable[[], Session]
) -> None:
    """A name left on last year's row is a name left."""
    student = tenant.students[0]
    login(client, tenant.teacher.email)
    assert (
        client.post(
            f"/api/v1/students/{student.id}/anonymise",
            json={"confirm": student.uid},
        ).status_code
        == 200
    )

    rows = reread().execute(
        select(Student).where(Student.person_id == student.person_id)
    ).scalars().all()
    assert rows
    assert all(r.first_name is None and r.last_name is None for r in rows)


def test_the_wrong_uid_anonymises_nobody(
    client: TestClient, tenant: Tenant, reread: Callable[[], Session]
) -> None:
    """The same confirmation deletion demands, for the same reason: a caller
    firing at the wrong row must fail rather than act on the wrong child."""
    student = tenant.students[0]
    login(client, tenant.teacher.email)
    response = client.post(
        f"/api/v1/students/{student.id}/anonymise", json={"confirm": "7B_99"}
    )
    assert response.status_code == 422
    person = reread().get(Person, student.person_id)
    assert person is not None and person.first_name is not None


def test_anonymising_twice_does_not_move_the_date(
    client: TestClient, tenant: Tenant
) -> None:
    """A second request for the same child is the same request, and the date
    may already have been shown to somebody."""
    student = tenant.students[0]
    login(client, tenant.teacher.email)
    body = {"confirm": student.uid}
    first = client.post(f"/api/v1/students/{student.id}/anonymise", json=body)
    again = client.post(f"/api/v1/students/{student.id}/anonymise", json=body)
    assert again.status_code == 200
    assert again.json()["anonymised_at"] == first.json()["anonymised_at"]


def test_a_co_teacher_cannot_anonymise_another_teachers_pupil(
    client: TestClient, tenant: Tenant, colleague: Tenant, reread: Callable[[], Session]
) -> None:
    """Reading a child and erasing their name are not the same permission —
    the same distinction `delete_student` already draws (D69, D73)."""
    student = tenant.students[0]
    login(client, colleague.teacher.email)
    response = client.post(
        f"/api/v1/students/{student.id}/anonymise",
        json={"confirm": student.uid},
    )
    assert response.status_code == 404
    person = reread().get(Person, student.person_id)
    assert person is not None and person.first_name is not None


def test_an_anonymised_pupil_still_appears_on_the_roster(
    client: TestClient, tenant: Tenant
) -> None:
    """Anonymisation is not removal. The pupil is still in the class, still
    counted, and still addressable by the identifier on their paper."""
    student = tenant.students[0]
    login(client, tenant.teacher.email)
    client.post(
        f"/api/v1/students/{student.id}/anonymise", json={"confirm": student.uid}
    )

    roster = client.get(f"/api/v1/classes/{tenant.school_class.id}/students").json()
    row = next(s for s in roster if s["uid"] == student.uid)
    assert row["first_name"] is None
    assert row["anonymised_at"] is not None
