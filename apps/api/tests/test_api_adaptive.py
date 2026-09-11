"""The adaptive batch: one sheet, a different printed page per student."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise

from alppy.models import AdaptiveProposal, Exercise


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


def test_proposing_returns_a_job_rather_than_blocking_on_the_model(
    client: TestClient, tenant: Tenant
) -> None:
    """Re-encoded when generation moved to the worker. It used to be a 200
    carrying the whole proposal, which meant every model call for the class ran
    inside the request handler — the thing CLAUDE.md forbids outright and
    `generate_feedback`'s own docstring already argued against."""
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/adaptive/propose",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "items_per_student": 4,
        },
    )
    assert response.status_code in (202, 503)
    if response.status_code == 503:
        assert response.json()["error"]["code"] == "service_unavailable"
        return
    body = response.json()
    assert body["kind"] == "propose_adaptive"
    assert body["status"] == "queued"


def test_a_second_propose_while_one_is_running_does_not_start_a_second_run(
    client: TestClient, tenant: Tenant
) -> None:
    """A double-click used to cost one rate-limit token. Queued, it would cost a
    second Job and a second set of unapproved Exercise rows for the same class —
    and the teacher would be asked to approve both."""
    login(client, tenant.teacher.email)
    body = {
        "class_id": str(tenant.school_class.id),
        "subject_id": str(tenant.subject.id),
        "items_per_student": 4,
    }
    first = client.post("/api/v1/adaptive/propose", json=body)
    if first.status_code == 503:
        pytest.skip("adaptive planning is not installed in this build")
    second = client.post("/api/v1/adaptive/propose", json=body)

    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]


def test_a_proposal_that_was_never_built_is_a_404_not_an_empty_plan(
    client: TestClient, tenant: Tenant
) -> None:
    """An empty proposal and a missing one are different facts, and the screen
    must not render "no gaps" for "the job has not finished"."""
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/adaptive/propose",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "items_per_student": 4,
        },
    )
    if response.status_code == 503:
        pytest.skip("adaptive planning is not installed in this build")
    job_id = response.json()["id"]

    assert client.get(f"/api/v1/adaptive/proposal/{job_id}").status_code == 404


def test_another_schools_proposal_is_not_readable(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    mine = client.post(
        "/api/v1/adaptive/propose",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "items_per_student": 4,
        },
    )
    if mine.status_code == 503:
        pytest.skip("adaptive planning is not installed in this build")
    job_id = mine.json()["id"]

    login(client, other_tenant.teacher.email)
    assert client.get(f"/api/v1/adaptive/proposal/{job_id}").status_code == 404


def test_a_colleagues_run_does_not_answer_my_click(
    client: TestClient, tenant: Tenant, colleague: Tenant
) -> None:
    """Two teachers, two classes, one school.

    The in-flight guard matched on the school, the kind and the status alone,
    so the second teacher to click while a colleague's proposal ran was handed
    the colleague's job id — for a class they may not even teach. The guard is
    keyed on the class, the branch and the teacher now, because the payload
    carries `items_per_student`, `group`, `n_groups` and `language`: sharing a
    run silently answers one teacher's request with another's parameters
    (audit 02, C1).
    """
    login(client, tenant.teacher.email)
    mine = client.post(
        "/api/v1/adaptive/propose",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "items_per_student": 4,
        },
    )
    if mine.status_code == 503:
        pytest.skip("adaptive planning is not installed in this build")

    login(client, colleague.teacher.email)
    theirs = client.post(
        "/api/v1/adaptive/propose",
        json={
            "class_id": str(colleague.school_class.id),
            "subject_id": str(colleague.subject.id),
            "items_per_student": 8,
        },
    )
    assert theirs.status_code == 202
    assert theirs.json()["id"] != mine.json()["id"], (
        "the colleague was handed the job running for another class"
    )


def test_a_colleague_cannot_read_my_classs_proposal(
    client: TestClient, db: Session, tenant: Tenant, colleague: Tenant
) -> None:
    """A proposal names which children are behind, on what, and what each of
    them should do next. `read_proposal` checked the school and nothing else,
    so any member of the staffroom could read any class's plan by asking for
    the job id (audit 02, C1)."""
    login(client, tenant.teacher.email)
    mine = client.post(
        "/api/v1/adaptive/propose",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "items_per_student": 4,
        },
    )
    if mine.status_code == 503:
        pytest.skip("adaptive planning is not installed in this build")
    job_id = uuid.UUID(mine.json()["id"])

    db.add(
        AdaptiveProposal(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            job_id=job_id,
            payload={
                "plans": [],
                "language": "fr",
                "grouped_by_model": False,
                "generated_count": 0,
                "needs_approval": True,
                "groups": [],
            },
        )
    )
    db.commit()

    # The teacher whose class it is reads it.
    assert client.get(f"/api/v1/adaptive/proposal/{job_id}").status_code == 200

    # The colleague down the corridor does not, and it reads as missing rather
    # than forbidden: the response must not confirm the job id exists.
    login(client, colleague.teacher.email)
    assert client.get(f"/api/v1/adaptive/proposal/{job_id}").status_code == 404


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


def test_a_batch_cannot_derive_from_a_sheet_the_caller_cannot_see(
    client: TestClient, tenant: Tenant, colleague: Tenant, db: Session
) -> None:
    """`source_sheet_id` gets the ownership check every other path gives it.

    `/adaptive/batch` performs none of its own, and the id was previously stored
    on `derived_from_id` unvalidated — `render.py` prints that sheet's title on
    the feedback page, so a colleague's (or another school's) sheet title could
    reach paper it has no business being on.
    """
    exercise = make_exercise(db, tenant, statement="pour Lea")

    # A sheet belonging to the colleague, in the same school.
    login(client, colleague.teacher.email)
    theirs = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(colleague.school_class.id),
            "subject_id": str(colleague.subject.id),
            "title": "Leur controle",
            "language": "fr",
            "items": [{"exercise_id": str(exercise.id), "position": 0}],
        },
    )
    assert theirs.status_code == 201
    foreign_sheet_id = theirs.json()["id"]

    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/adaptive/batch",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Serie differenciee",
            "language": "fr",
            "source_sheet_id": foreign_sheet_id,
            "plans": [
                {
                    "student_id": str(tenant.students[0].id),
                    "student_uid": tenant.students[0].uid,
                    "targeted_competency_ids": [str(tenant.competency.id)],
                    "retrieved": [_proposal(exercise)],
                    "generated": [],
                },
            ],
        },
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Lineage (D70) — a sheet may answer several sheets, one of them the principal
# --------------------------------------------------------------------------
def _own_sheet(client: TestClient, tenant: Tenant, exercise: Exercise, title: str) -> str:
    response = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": title,
            "language": "fr",
            "items": [{"exercise_id": str(exercise.id), "position": 0}],
        },
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _batch(client: TestClient, tenant: Tenant, exercise: Exercise, **extra: object) -> dict:
    response = client.post(
        "/api/v1/adaptive/batch",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Reprise",
            "language": "fr",
            "plans": [
                {
                    "student_id": str(tenant.students[0].id),
                    "student_uid": tenant.students[0].uid,
                    "targeted_competency_ids": [str(tenant.competency.id)],
                    "retrieved": [_proposal(exercise)],
                    "generated": [],
                }
            ],
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_a_batch_records_every_sheet_it_answers(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    exercise = make_exercise(db, tenant, statement="fractions")
    login(client, tenant.teacher.email)
    first = _own_sheet(client, tenant, exercise, "Controle")
    second = _own_sheet(client, tenant, exercise, "Fiche 2")

    batch = _batch(client, tenant, exercise, source_sheet_ids=[first, second])

    # The whole evidence set, in the order the teacher named it...
    assert batch["source_sheet_ids"] == [first, second]
    # ...and the principal is entry 0, reachable the old way too. One fact,
    # two access paths, and they must never disagree (D70).
    assert batch["derived_from_id"] == first


def test_a_batch_that_answers_one_sheet_still_reads_the_old_way(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """`source_sheet_id` alone keeps working, and lands in both places."""
    exercise = make_exercise(db, tenant, statement="fractions")
    login(client, tenant.teacher.email)
    parent = _own_sheet(client, tenant, exercise, "Controle")

    batch = _batch(client, tenant, exercise, source_sheet_id=parent)

    assert batch["derived_from_id"] == parent
    assert batch["source_sheet_ids"] == [parent]


def test_a_lineage_never_names_the_same_sheet_twice(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """A repeat is a teacher clicking twice, not a second piece of evidence."""
    exercise = make_exercise(db, tenant, statement="fractions")
    login(client, tenant.teacher.email)
    parent = _own_sheet(client, tenant, exercise, "Controle")

    batch = _batch(
        client, tenant, exercise, source_sheet_id=parent, source_sheet_ids=[parent, parent]
    )

    assert batch["source_sheet_ids"] == [parent]


def test_every_sheet_in_a_lineage_gets_the_ownership_check(
    client: TestClient, tenant: Tenant, colleague: Tenant, db: Session
) -> None:
    """Not just the principal — D61's rule applies to the whole set.

    A foreign sheet buried at position 2 would otherwise reach the lineage
    unvalidated, and the sheet detail page names every one of them.
    """
    exercise = make_exercise(db, tenant, statement="pour Lea")
    login(client, colleague.teacher.email)
    theirs = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(colleague.school_class.id),
            "subject_id": str(colleague.subject.id),
            "title": "Leur controle",
            "language": "fr",
            "items": [{"exercise_id": str(exercise.id), "position": 0}],
        },
    )
    assert theirs.status_code == 201
    foreign = str(theirs.json()["id"])

    login(client, tenant.teacher.email)
    mine = _own_sheet(client, tenant, exercise, "Mon controle")

    response = client.post(
        "/api/v1/adaptive/batch",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Reprise",
            "language": "fr",
            "source_sheet_ids": [mine, foreign],
            "plans": [
                {
                    "student_id": str(tenant.students[0].id),
                    "student_uid": tenant.students[0].uid,
                    "targeted_competency_ids": [str(tenant.competency.id)],
                    "retrieved": [_proposal(exercise)],
                    "generated": [],
                }
            ],
        },
    )
    assert response.status_code == 404


def test_the_feedback_uid_lookup_filters_on_the_school_itself(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, db: Session
) -> None:
    """The `Student` lookup in `list_feedback` carries its own `school_id`.

    It was the one scoped read in the codebase whose tenant filter was an
    inference — every id came from a note already filtered on the school, so
    the query was correct because of the query above it. This pins the
    invariant locally: a note that names a pupil of another school (which is
    what a widened filter, a bad backfill or a mistyped id would produce) must
    yield no uid, rather than reading a name out of the other school's roster.

    The note row itself is this school's, so the upstream filter passes it
    through — that is the point. Without the local predicate the endpoint
    answers with `other_tenant`'s pupil uid.
    """
    from alppy.models import MisconceptionNote

    exercise = make_exercise(db, tenant, statement="Simplifie 12/18.")
    login(client, tenant.teacher.email)
    sheet_id = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Controle commun",
            "language": "fr",
            "items": [{"exercise_id": str(exercise.id), "position": 0}],
        },
    ).json()["id"]

    mine = tenant.students[0]
    theirs = other_tenant.students[0]
    # Person ids since 0028: a note names the durable identity, and the point
    # of the test is that one of these two belongs to another school.
    for student_id in (mine.person_id, theirs.person_id):
        db.add(
            MisconceptionNote(
                id=uuid.uuid4(),
                school_id=tenant.school.id,  # this school's note ...
                person_id=student_id,  # ... naming another school's pupil
                subject_id=tenant.subject.id,
                based_on_sheet_id=uuid.UUID(sheet_id),
                language="fr",
                notes=["inverse les termes"],
            )
        )
    db.commit()

    response = client.get(f"/api/v1/adaptive/feedback?source_sheet_id={sheet_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    by_student = {n["student_id"]: n["student_uid"] for n in body}

    assert by_student[str(mine.id)] == mine.uid
    assert by_student[str(theirs.person_id)] == "", (
        "a pupil of another school has no uid to show here"
    )
    assert theirs.uid not in {n["student_uid"] for n in body}
