"""`GET /students/{id}/export` — what the school holds about one pupil.

Before this the only route out of the product was `DELETE`, which answers
"what do you have on my child" with "nothing, now" (audit 02, H8).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise

from alppy.models import Attempt, MisconceptionNote


def _export(client: TestClient, student_id: uuid.UUID) -> dict:
    response = client.get(f"/api/v1/students/{student_id}/export")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_export_carries_the_identity_and_the_enrolment(
    client: TestClient, tenant: Tenant
) -> None:
    student = tenant.students[0]
    login(client, tenant.teacher.email)
    body = _export(client, student.id)

    assert body["person_id"] == str(student.person_id)
    assert body["first_name"] == student.first_name
    assert body["anonymised_at"] is None
    assert body["generated_at"]

    enrolment = next(e for e in body["enrolments"] if e["uid"] == student.uid)
    assert enrolment["class_code"] == tenant.school_class.code
    assert enrolment["school_year"] == "2026/27"
    assert enrolment["is_home_class"] is True


def test_the_export_carries_the_evidence_with_its_competency_codes(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """The codes, not the uuids: a document read outside Alppy cannot resolve
    an id, and `MSN.11` is what another school can look up."""
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
    body = _export(client, student.id)

    assert len(body["attempts"]) == 1
    attempt = body["attempts"][0]
    assert attempt["correct"] is True
    assert attempt["exercise_id"] == str(exercise.id)
    assert attempt["competency_codes"] == [tenant.competency.code]


def test_the_export_carries_the_notes_written_about_the_child(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """Free text a teacher or a model wrote about the pupil — the most
    sensitive thing in the record, and the reason this is more than marks."""
    student = tenant.students[0]
    db.add(
        MisconceptionNote(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            person_id=student.person_id,
            subject_id=tenant.subject.id,
            language="fr",
            notes=["confond numerateur et denominateur"],
            approved_at=datetime(2026, 9, 2, tzinfo=UTC),
        )
    )
    db.commit()

    login(client, tenant.teacher.email)
    body = _export(client, student.id)
    assert body["notes"][0]["notes"] == ["confond numerateur et denominateur"]


def test_a_discarded_note_is_not_re_surfaced_by_the_export(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """Throwing a note away has to mean something. Putting it back in a
    document the parent receives is the opposite of what it meant."""
    student = tenant.students[0]
    db.add(
        MisconceptionNote(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            person_id=student.person_id,
            subject_id=tenant.subject.id,
            language="fr",
            notes=["une note jetee"],
            discarded_at=datetime(2026, 9, 3, tzinfo=UTC),
        )
    )
    db.commit()

    login(client, tenant.teacher.email)
    assert _export(client, student.id)["notes"] == []


def test_another_schools_pupil_cannot_be_exported(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    theirs = other_tenant.students[0]
    assert client.get(f"/api/v1/students/{theirs.id}/export").status_code == 404


def test_a_colleague_who_does_not_teach_the_pupil_cannot_export_them(
    client: TestClient, tenant: Tenant, colleague: Tenant
) -> None:
    """The same gate the destructive route uses: a teacher who could erase a
    pupil may read what they would be erasing, and nobody else may do either."""
    login(client, colleague.teacher.email)
    mine = tenant.students[0]
    assert client.get(f"/api/v1/students/{mine.id}/export").status_code == 404
