"""The adaptive batch: one sheet, a different printed page per student."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise

from alppy.models import Exercise


def _proposal(exercise: Exercise) -> dict[str, Any]:
    return {
        "exercise": {
            "id": str(exercise.id),
            "type": exercise.type.value,
            "origin": exercise.origin.value,
            "language": exercise.language,
            "statement": exercise.statement,
            "options": exercise.options,
            "answer_index": exercise.answer_index,
            "difficulty": exercise.difficulty,
            "competency_ids": [],
        },
        "score": 0.82,
        "provenance": {"reason": "targets a fading competency"},
    }


def test_propose_reports_the_missing_planner_or_answers(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/adaptive/propose",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "items_per_student": 4,
        },
    )
    assert response.status_code in (200, 503)
    if response.status_code == 503:
        assert response.json()["error"]["code"] == "service_unavailable"


def test_propose_rejects_a_student_from_another_class(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/adaptive/propose",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "student_ids": [str(other_tenant.students[0].id)],
        },
    )
    assert response.status_code == 404


def test_batch_gives_each_student_their_own_item_plan(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    a = make_exercise(db, tenant, statement="pour Lea")
    b = make_exercise(db, tenant, statement="pour Noah")
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/adaptive/batch",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Serie differenciee",
            "language": "fr",
            "plans": [
                {
                    "student_id": str(tenant.students[0].id),
                    "student_uid": tenant.students[0].uid,
                    "targeted_competency_ids": [str(tenant.competency.id)],
                    "retrieved": [_proposal(a)],
                    "generated": [],
                },
                {
                    "student_id": str(tenant.students[1].id),
                    "student_uid": tenant.students[1].uid,
                    "targeted_competency_ids": [str(tenant.competency.id)],
                    "retrieved": [_proposal(b)],
                    "generated": [],
                },
            ],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["target"] == "student"
    # The class-level item list is the union; the per-student plans are not.
    assert {i["exercise"]["id"] for i in body["items"]} == {str(a.id), str(b.id)}
    assert {i["student_uid"] for i in body["instances"]} == {"7B_01", "7B_02"}

    render = client.post(f"/api/v1/adaptive/batch/{body['id']}/render")
    assert render.status_code in (202, 503)


def test_batch_rejects_an_unknown_student(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    a = make_exercise(db, tenant, statement="x")
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/adaptive/batch",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Serie",
            "language": "fr",
            "plans": [
                {
                    "student_id": str(uuid.uuid4()),
                    "student_uid": "7B_99",
                    "targeted_competency_ids": [],
                    "retrieved": [_proposal(a)],
                    "generated": [],
                }
            ],
        },
    )
    assert response.status_code == 404
