"""The four handlers the suite reached through no HTTP request at all (T8).

`POST /adaptive/feedback/generate` had **zero** covered lines. That matters
more than the number: the handler body contains the in-flight dedup keyed on
`(class, source sheet, teacher)`, which is the same fix an earlier audit
required for `/adaptive/propose` — and `propose` got a test for it while this
one did not. The two were written from the same argument, and only one of them
is defended.

`/adaptive/regenerate`, `/scans/{id}/reopen` and `/detections/{id}/revert` are
well covered at the service layer. What was missing is the layer above: whether
the handler maps a conflict to the right status, whether it refuses what the
service would refuse, and whether it exists at the address the client calls.
The last one is not hypothetical — the audit records a route called at the
wrong address for two milestones.

Tenancy and the no-session case for all four are covered by the route sweep in
`test_route_sweep.py`, which sweeps every route rather than a chosen subset.
This module is the behaviour on top of that: what happens on the second POST,
what happens to a colleague, and what the rate limiter does.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_colleague, make_exercise, make_paper_trail

from alppy.api.deps import get_ai_limiter
from alppy.models import Sheet, SheetItem
from alppy.models.enums import DetectionOutcome, ScanStatus, SheetTarget


def _common_sheet(db: Session, tenant: Tenant) -> Sheet:
    """A corrected common sheet — what feedback is written from."""
    exercise = make_exercise(db, tenant, statement="2/3 + 1/3 ?")
    sheet = Sheet(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        class_id=tenant.school_class.id,
        subject_id=tenant.subject.id,
        chapter_id=tenant.unfiled_chapter_id,
        title="Fractions, controle 1",
        target=SheetTarget.CLASS,
        language="fr",
        layout_version="v1",
    )
    db.add(sheet)
    db.flush()
    db.add(
        SheetItem(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            sheet_id=sheet.id,
            exercise_id=exercise.id,
            position=0,
        )
    )
    db.flush()
    db.commit()
    return sheet


def _generate_body(tenant: Tenant, sheet: Sheet) -> dict[str, str]:
    return {
        "class_id": str(tenant.school_class.id),
        "subject_id": str(tenant.subject.id),
        "source_sheet_id": str(sheet.id),
    }


# --- POST /adaptive/feedback/generate ---------------------------------------


def test_generating_feedback_returns_a_job_rather_than_blocking(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """One model call PER STUDENT, so it cannot run in a request handler.

    A class of twenty-four inside the handler is a timeout with a half-written
    batch behind it — the thing CLAUDE.md forbids outright.
    """
    sheet = _common_sheet(db, tenant)
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/adaptive/feedback/generate", json=_generate_body(tenant, sheet)
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["kind"] == "generate_feedback"
    assert body["status"] == "queued"


def test_a_second_generate_while_one_is_running_returns_the_same_job(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The in-flight dedup, keyed on `(class, source sheet, teacher)`.

    This is the line the audit cared about: `propose` got this test and
    `feedback/generate` did not, though both were written from the same
    argument. A double-click costs a second Job and a second run of one model
    call per student — for a class of twenty-four, forty-eight calls for one
    intended action.
    """
    sheet = _common_sheet(db, tenant)
    login(client, tenant.teacher.email)
    body = _generate_body(tenant, sheet)

    first = client.post("/api/v1/adaptive/feedback/generate", json=body)
    second = client.post("/api/v1/adaptive/feedback/generate", json=body)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert second.json()["id"] == first.json()["id"], (
        "a second POST started a second job: the dedup is not matching"
    )


def test_a_different_source_sheet_is_different_work(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The source sheet is ON the key, and this is why.

    Notes are written from one corrected pile. Two piles are two different
    sets of notes, so returning the first job for the second request would
    silently answer the wrong question.
    """
    first_sheet = _common_sheet(db, tenant)
    second_sheet = _common_sheet(db, tenant)
    login(client, tenant.teacher.email)

    first = client.post(
        "/api/v1/adaptive/feedback/generate", json=_generate_body(tenant, first_sheet)
    )
    second = client.post(
        "/api/v1/adaptive/feedback/generate", json=_generate_body(tenant, second_sheet)
    )

    assert first.status_code == 202 and second.status_code == 202
    assert second.json()["id"] != first.json()["id"]


def test_a_colleagues_run_is_their_own(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The teacher is on the key too, and not for tidiness.

    The payload carries a language. Handing a colleague the job someone else
    started writes their notes in someone else's chosen language (audit 02,
    C1).
    """
    sheet = _common_sheet(db, tenant)
    colleague = make_colleague(db, tenant)
    db.commit()
    body = _generate_body(tenant, sheet)

    login(client, tenant.teacher.email)
    mine = client.post("/api/v1/adaptive/feedback/generate", json=body)
    assert mine.status_code == 202, mine.text

    login(client, colleague.teacher.email)
    theirs = client.post("/api/v1/adaptive/feedback/generate", json=body)

    assert theirs.status_code in (202, 404), theirs.text
    if theirs.status_code == 202:
        assert theirs.json()["id"] != mine.json()["id"], (
            "a colleague was handed the job this teacher started"
        )


def test_a_class_with_no_students_is_refused_before_the_worker(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Queueing a per-student job for nobody is a job that can only fail."""
    from alppy.models import class_student

    sheet = _common_sheet(db, tenant)
    db.execute(
        class_student.delete().where(
            class_student.c.class_id == tenant.school_class.id
        )
    )
    db.commit()
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/adaptive/feedback/generate", json=_generate_body(tenant, sheet)
    )
    assert response.status_code == 422, response.text


def test_the_ai_rate_limiter_fires_on_the_largest_fan_out_in_the_product(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """One POST is one model call per student — twenty-four for one class.

    The audit found this was the only model-reaching route missing the limiter
    every one of its neighbours carries. Emptied rather than exhausted by
    looping, so the test says "the limiter guards this route" instead of
    depending on what the configured ceiling happens to be.
    """
    sheet = _common_sheet(db, tenant)
    login(client, tenant.teacher.email)

    limiter = get_ai_limiter()
    key = str(tenant.teacher.id)
    for _ in range(int(limiter.capacity) + 1):
        limiter.take(key)

    response = client.post(
        "/api/v1/adaptive/feedback/generate", json=_generate_body(tenant, sheet)
    )
    assert response.status_code == 429, response.text
    assert response.json()["error"]["code"] == "rate_limited"


# --- POST /adaptive/regenerate ----------------------------------------------


def test_regenerate_answers_a_foreign_exercise_exactly_as_it_answers_an_absent_one(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, db: Session
) -> None:
    """The property that matters is indistinguishability, not the number.

    `/adaptive/regenerate` answers 422 `unprocessable` here rather than the 404
    the tenancy tests use elsewhere — worth knowing, and NOT a leak: another
    school's exercise and an id that never existed produce the same status and
    the same sentence, so neither confirms the row exists. This asserts the two
    are identical rather than asserting the number, because the number is the
    part a future refactor may reasonably change and the sameness is the part
    it must not.
    """
    foreign = make_exercise(db, other_tenant, statement="3/4 - 1/4 ?")
    db.commit()
    login(client, tenant.teacher.email)

    absent_id = uuid.uuid4()
    foreign_response = client.post(
        "/api/v1/adaptive/regenerate", json={"exercise_id": str(foreign.id)}
    )
    absent_response = client.post(
        "/api/v1/adaptive/regenerate", json={"exercise_id": str(absent_id)}
    )

    assert foreign_response.status_code == absent_response.status_code, (
        "another school's exercise is distinguishable from one that does not "
        "exist: the status alone confirms the row is there"
    )
    assert foreign_response.status_code in (404, 422), foreign_response.text
    assert (
        foreign_response.json()["error"]["code"]
        == absent_response.json()["error"]["code"]
    )


# --- POST /scans/{id}/reopen and /detections/{id}/revert --------------------


def test_reopening_a_pile_that_was_never_confirmed_is_a_conflict(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Reopen withdraws the grades a confirmation wrote. With no confirmation
    there is nothing to withdraw, and saying so beats a silent no-op."""
    exercise = make_exercise(db, tenant, statement="2/3 + 1/3 ?")
    _sheet, scan, _detection = make_paper_trail(db, tenant, exercise, tenant.students[0])
    scan.status = ScanStatus.NEEDS_REVIEW
    db.flush()
    db.commit()
    login(client, tenant.teacher.email)

    response = client.post(f"/api/v1/scans/{scan.id}/reopen")
    assert response.status_code == 409, response.text


def test_reopening_a_confirmed_pile_answers_at_the_address_the_client_calls(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """A route called at the wrong address was a real incident here, twice.

    So this asserts the plain thing: POST to exactly this path, on a pile in
    exactly the state the screen offers the button in, answers 200.
    """
    exercise = make_exercise(db, tenant, statement="2/3 + 1/3 ?")
    _sheet, scan, _detection = make_paper_trail(db, tenant, exercise, tenant.students[0])
    db.commit()
    login(client, tenant.teacher.email)

    response = client.post(f"/api/v1/scans/{scan.id}/reopen")

    assert response.status_code == 200, response.text
    assert client.get(f"/api/v1/scans/{scan.id}").json()["status"] != "CONFIRMED"


def test_reverting_a_detection_that_was_never_corrected_is_refused(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Revert puts back the machine's reading. With no override there is
    nothing to put back."""
    exercise = make_exercise(db, tenant, statement="2/3 + 1/3 ?")
    _sheet, scan, detection = make_paper_trail(db, tenant, exercise, tenant.students[0])
    scan.status = ScanStatus.NEEDS_REVIEW
    # `make_paper_trail` builds a CORRECTED detection — that is what the drill-
    # down needs — so "never corrected" has to be set here rather than assumed.
    detection.outcome = DetectionOutcome.DETECTED
    db.flush()
    db.commit()
    login(client, tenant.teacher.email)

    response = client.post(
        f"/api/v1/scans/{scan.id}/detections/{detection.id}/revert"
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "detection_not_corrected"


def test_reverting_a_detection_on_a_confirmed_pile_is_refused(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Editing a reading a live Attempt was graded from leaves the grade and
    the reading it claims to come from disagreeing. Reopen first."""
    exercise = make_exercise(db, tenant, statement="2/3 + 1/3 ?")
    _sheet, scan, detection = make_paper_trail(db, tenant, exercise, tenant.students[0])
    db.commit()
    login(client, tenant.teacher.email)

    response = client.post(
        f"/api/v1/scans/{scan.id}/detections/{detection.id}/revert"
    )
    assert response.status_code == 409, response.text


def test_a_detection_from_another_pile_is_not_reachable_through_this_one(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The scan id in the path is not decoration.

    `get_detection` takes both, so a detection id from a different pile must
    not resolve — otherwise the path segment is a comment rather than a scope.
    """
    exercise = make_exercise(db, tenant, statement="2/3 + 1/3 ?")
    _s1, scan_a, _d1 = make_paper_trail(db, tenant, exercise, tenant.students[0])
    other_exercise = make_exercise(db, tenant, statement="5/6 - 1/6 ?")
    _s2, _scan_b, detection_b = make_paper_trail(
        db, tenant, other_exercise, tenant.students[1]
    )
    # Both piles out of CONFIRMED: `_refuse_when_confirmed` runs BEFORE the
    # detection is looked up, so a confirmed pile answers 409 and the cross-pile
    # scoping this test is about never gets exercised.
    scan_a.status = ScanStatus.NEEDS_REVIEW
    _scan_b.status = ScanStatus.NEEDS_REVIEW
    db.flush()
    db.commit()
    login(client, tenant.teacher.email)

    response = client.post(
        f"/api/v1/scans/{scan_a.id}/detections/{detection_b.id}/revert"
    )
    assert response.status_code == 404, response.text
