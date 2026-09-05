"""The mastery matrix and the student profile."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise

from alppy.models import Attempt, Competency, MasterySnapshot
from alppy.models.enums import CurriculumKind
from alppy.services.mastery_service import recompute_for_students


def _second_competency(db: Session) -> Competency:
    competency = Competency(
        id=uuid.uuid4(),
        curriculum=CurriculumKind.PER,
        code="MSN.13",
        parent_id=None,
        subject_key="mathematics",
        cycle=3,
        labels={"fr": "Proportionnalite"},
        description={},
    )
    db.add(competency)
    db.flush()
    return competency


def _seed_history(db: Session, tenant: Tenant) -> Competency:
    """One strong competency and one failing one, for the same student."""
    strong = make_exercise(db, tenant, statement="strong")
    weak_competency = _second_competency(db)
    weak_exercise = make_exercise(db, tenant, statement="weak", with_competency=False)
    weak_exercise.competencies = [weak_competency]
    db.flush()

    student = tenant.students[0]
    recently = datetime.now(UTC) - timedelta(hours=2)
    for _ in range(4):
        db.add(
            Attempt(
                id=uuid.uuid4(),
                school_id=tenant.school.id,
                student_id=student.id,
                exercise_id=strong.id,
                correct=True,
                score=1.0,
                difficulty=3,
                answered_at=recently,
            )
        )
        db.add(
            Attempt(
                id=uuid.uuid4(),
                school_id=tenant.school.id,
                student_id=student.id,
                exercise_id=weak_exercise.id,
                correct=False,
                score=0.0,
                difficulty=3,
                answered_at=recently,
            )
        )
    db.commit()
    recompute_for_students(db, tenant.school.id, [student.id])
    db.commit()
    return weak_competency


def test_matrix_has_a_cell_for_every_student_and_competency(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    _seed_history(db, tenant)
    login(client, tenant.teacher.email)

    matrix = client.get(f"/api/v1/classes/{tenant.school_class.id}/mastery").json()
    assert len(matrix["students"]) == 3
    assert len(matrix["competencies"]) == 2
    assert len(matrix["cells"]) == 6

    student_id = str(tenant.students[0].id)
    bands = {
        c["competency_id"]: c["band"] for c in matrix["cells"] if c["student_id"] == student_id
    }
    assert sorted(bands.values()) == ["fading", "solid"]

    # A student who has sat nothing is "none", never a zero score.
    untouched = [c for c in matrix["cells"] if c["student_id"] == str(tenant.students[1].id)]
    assert {c["band"] for c in untouched} == {"none"}
    assert all(c["attempts_count"] == 0 for c in untouched)


def test_matrix_can_be_narrowed_to_one_subject(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    _seed_history(db, tenant)
    login(client, tenant.teacher.email)
    matrix = client.get(
        f"/api/v1/classes/{tenant.school_class.id}/mastery?subject_id={tenant.subject.id}"
    ).json()
    assert len(matrix["competencies"]) == 2

    other = client.get(
        f"/api/v1/classes/{tenant.school_class.id}/mastery?subject_id={uuid.uuid4()}"
    ).json()
    assert other["competencies"] == []
    assert other["cells"] == []


def test_student_profile_separates_strengths_from_gaps(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    weak_competency = _seed_history(db, tenant)
    login(client, tenant.teacher.email)

    profile = client.get(f"/api/v1/students/{tenant.students[0].id}/mastery").json()
    assert profile["student"]["uid"] == "7B_01"
    assert [s["band"] for s in profile["strengths"]] == ["solid"]
    assert [g["competency"]["code"] for g in profile["gaps"]] == [weak_competency.code]
    assert len(profile["all_competencies"]) == 2
    assert 0.0 < profile["overall_score"] < 1.0

    history = profile["all_competencies"][0]["history"]
    assert len(history) == 1
    assert history[0]["band"] in {"solid", "fading"}


def test_recompute_is_idempotent_within_a_day(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    _seed_history(db, tenant)
    before = db.execute(select(MasterySnapshot)).scalars().all()
    recompute_for_students(db, tenant.school.id, [tenant.students[0].id])
    db.commit()
    after = db.execute(select(MasterySnapshot)).scalars().all()
    assert len(after) == len(before) == 2


def test_profile_of_a_student_with_no_attempts_is_empty_not_an_error(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    profile = client.get(f"/api/v1/students/{tenant.students[2].id}/mastery").json()
    assert profile["overall_score"] == 0.0
    assert profile["strengths"] == []
    assert profile["gaps"] == []
    assert profile["sheets_taken"] == 0


def test_home_reports_students_needing_attention(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    _seed_history(db, tenant)
    login(client, tenant.teacher.email)
    summary = client.get("/api/v1/home").json()["classes"][0]
    assert summary["students_needing_attention"] == 1
    assert summary["band_counts"]["solid"] == 1
    assert summary["band_counts"]["fading"] == 1
