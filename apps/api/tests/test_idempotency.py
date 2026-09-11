"""A retry does the work once (audit 03, B17).

Nothing in the product was idempotent. A phone on a staffroom connection
retries a POST whose answer never arrived; a teacher taps "print" again because
the screen has not moved. Both used to produce a second render job, a second
batch of unapproved exercises, a second pile of twenty-eight copies.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise

from alppy.api import errors
from alppy.models import IdempotencyKey, Job
from alppy.models.enums import JobKind, JobStatus
from alppy.schemas import JobOut
from alppy.services import idempotency


def _payload(tenant: Tenant, exercise_ids: list[str]) -> dict:
    return {
        "class_id": str(tenant.school_class.id),
        "subject_id": str(tenant.subject.id),
        "title": "Contrôle",
        "language": "fr",
        "items": [
            {"exercise_id": eid, "position": index}
            for index, eid in enumerate(exercise_ids)
        ],
    }


def _job_out() -> JobOut:
    """A minimal valid JobOut, for the tests that exercise the helper directly."""
    return JobOut(
        id=uuid.uuid4(),
        kind=JobKind.RENDER_SHEET,
        status=JobStatus.QUEUED,
        progress=0.0,
        created_at=datetime.now(UTC),
    )


def test_the_same_key_renders_once_and_replays_the_answer(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Two taps on "print", one render.

    The second render is not merely wasteful: since B7 each one opens a new
    answer-box generation, so two renders of one sheet leave two sets of
    rectangles and a pile printed between them pinned to whichever it caught.
    """
    exercise = make_exercise(db, tenant, statement="3 + 4 x 2 = ?")
    login(client, tenant.teacher.email)
    sheet_id = client.post("/api/v1/sheets", json=_payload(tenant, [str(exercise.id)])).json()["id"]

    headers = {"Idempotency-Key": "print-once-please"}
    first = client.post(f"/api/v1/sheets/{sheet_id}/render", headers=headers)
    second = client.post(f"/api/v1/sheets/{sheet_id}/render", headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json() == second.json(), "the retry got a different answer"
    assert db.query(Job).count() == 1, "the retry queued a second render"


def test_without_a_key_nothing_changes(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Opt-in per request.

    Every existing client keeps working unchanged; a caller that wants the
    guarantee asks for it. Without this the feature would be a silent behaviour
    change for every caller that never sent a header.
    """
    exercise = make_exercise(db, tenant, statement="3 + 4 x 2 = ?")
    login(client, tenant.teacher.email)
    sheet_id = client.post("/api/v1/sheets", json=_payload(tenant, [str(exercise.id)])).json()["id"]

    client.post(f"/api/v1/sheets/{sheet_id}/render")
    client.post(f"/api/v1/sheets/{sheet_id}/render")
    assert db.query(Job).count() == 2


def test_a_different_key_is_a_different_request(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The boundary: this must not collapse every render into one."""
    exercise = make_exercise(db, tenant, statement="3 + 4 x 2 = ?")
    login(client, tenant.teacher.email)
    sheet_id = client.post("/api/v1/sheets", json=_payload(tenant, [str(exercise.id)])).json()["id"]

    client.post(f"/api/v1/sheets/{sheet_id}/render", headers={"Idempotency-Key": "a"})
    client.post(f"/api/v1/sheets/{sheet_id}/render", headers={"Idempotency-Key": "b"})
    assert db.query(Job).count() == 2


def test_a_claim_is_visible_before_the_work_finishes(
    db: Session, tenant: Tenant
) -> None:
    """The ordering that makes this work at all.

    The key is claimed and COMMITTED before `work` runs, so a concurrent retry
    collides on the unique constraint instead of running the work a second
    time. A row written afterwards would let both attempts through and remember
    only whichever finished last — which is the bug, not the fix.
    """
    seen: list[bool] = []

    def _work() -> JobOut:
        row = db.execute(
            select(IdempotencyKey).where(IdempotencyKey.key == "claimed-first")
        ).scalar_one_or_none()
        seen.append(row is not None)
        return _job_out()

    idempotency.run(
        db, school_id=tenant.school.id, endpoint="t", key="claimed-first",
        model=JobOut, work=_work,
    )
    assert seen == [True], "the work ran before its key was claimed"


def test_a_second_attempt_while_the_first_is_in_flight_is_refused(
    db: Session, tenant: Tenant
) -> None:
    """The loser of the race is told, not run.

    Reached by claiming the key and never finishing it, which is exactly the
    state a concurrent request sees.
    """
    def _never_finishes() -> JobOut:
        raise RuntimeError("stop here, leaving the claim held")

    db.add(
        IdempotencyKey(
            id=uuid.uuid4(), school_id=tenant.school.id, endpoint="t",
            key="in-flight", response=None,
        )
    )
    db.commit()

    with pytest.raises(errors.ApiError) as refused:
        idempotency.run(
            db, school_id=tenant.school.id, endpoint="t", key="in-flight",
            model=JobOut, work=_never_finishes,
        )
    assert refused.value.code == "idempotency_in_flight"


def test_a_failed_attempt_releases_its_key(db: Session, tenant: Tenant) -> None:
    """Otherwise the first 500 poisons that key forever.

    And the teacher's retry — the one thing they will certainly do — is refused
    with a conflict about a request that never succeeded.
    """
    calls: list[int] = []

    def _fails() -> JobOut:
        calls.append(1)
        raise RuntimeError("provider fell over")

    with pytest.raises(RuntimeError):
        idempotency.run(
            db, school_id=tenant.school.id, endpoint="t", key="retry-me",
            model=JobOut, work=_fails,
        )
    # The claim is gone, so the same key can be tried again.
    with pytest.raises(RuntimeError):
        idempotency.run(
            db, school_id=tenant.school.id, endpoint="t", key="retry-me",
            model=JobOut, work=_fails,
        )
    assert len(calls) == 2, "a failed attempt kept its key and blocked the retry"


def test_one_schools_key_is_not_anothers(
    db: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    """Keyed per tenant.

    `(endpoint, key)` alone would let one school probe another's keyspace by
    guessing, and learn from a 409 that a particular request had been made.
    """
    def _work() -> JobOut:
        return _job_out()

    a = idempotency.run(
        db, school_id=tenant.school.id, endpoint="t", key="same", model=JobOut, work=_work
    )
    b = idempotency.run(
        db, school_id=other_tenant.school.id, endpoint="t", key="same",
        model=JobOut, work=_work,
    )
    assert a.id != b.id, "a colleague's key replayed another school's answer"
