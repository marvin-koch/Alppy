"""Cross-tenant isolation.

A teacher signed into one school must not be able to read another school's
rows, and the API must not confirm that the id exists at all — every one of
these is a 404, never a 403.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_colleague, make_exercise, make_tenant

from alppy.api.errors import ApiError
from alppy.models import Class, SchoolYear
from alppy.services import class_service, mastery_service


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
    assert len(other_tenant.school_class.roster) == 1


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


# --------------------------------------------------------------------------
# F7 P1 · the boundary INSIDE a school
#
# Every test above compares two schools. The leak that shipped was one level
# in: two teachers in one staffroom, where `Class.teacher_id` existed, was
# NOT NULL and indexed, and no read path consulted it. See decisions-log D23.
# --------------------------------------------------------------------------
def test_a_colleagues_class_is_not_listed(
    client: TestClient, tenant: Tenant, colleague: Tenant
) -> None:
    login(client, tenant.teacher.email)

    codes = {c["code"] for c in client.get("/api/v1/classes").json()}
    assert codes == {tenant.school_class.code}
    assert colleague.school_class.code not in codes

    home_codes = {c["code"] for c in client.get("/api/v1/home").json()["classes"]}
    assert home_codes == {tenant.school_class.code}


def test_a_colleagues_class_reads_as_missing(
    client: TestClient, tenant: Tenant, colleague: Tenant
) -> None:
    """Not 403: the response must not confirm the id exists somewhere else."""
    login(client, tenant.teacher.email)
    foreign = colleague.school_class.id

    for path in (
        f"/api/v1/classes/{foreign}",
        f"/api/v1/classes/{foreign}/students",
        f"/api/v1/classes/{foreign}/mastery",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "not_found"


def test_a_colleagues_roster_never_reaches_another_teacher(
    client: TestClient, tenant: Tenant, colleague: Tenant
) -> None:
    """The regression that matters: names of children, read by the wrong adult."""
    login(client, colleague.teacher.email)
    response = client.get(f"/api/v1/classes/{tenant.school_class.id}/students")
    assert response.status_code == 404

    names = {s.first_name for s in tenant.students}
    assert names, "fixture sanity: the host class has a roster"
    assert not (names & {s["first_name"] for s in _all_students_visible_to(client)})


def _all_students_visible_to(client: TestClient) -> list[dict[str, object]]:
    seen: list[dict[str, object]] = []
    for school_class in client.get("/api/v1/classes").json():
        seen.extend(client.get(f"/api/v1/classes/{school_class['id']}/students").json())
    return seen


def test_a_colleagues_student_profile_reads_as_missing(
    client: TestClient, tenant: Tenant, colleague: Tenant
) -> None:
    login(client, colleague.teacher.email)
    foreign = tenant.students[0].id
    assert client.get(f"/api/v1/students/{foreign}/mastery").status_code == 404


def test_a_colleague_cannot_write_into_another_teachers_roster(
    client: TestClient, tenant: Tenant, colleague: Tenant
) -> None:
    login(client, colleague.teacher.email)
    before = len(tenant.school_class.roster)
    response = client.post(
        f"/api/v1/classes/{tenant.school_class.id}/students",
        json={"students": [{"first_name": "Eve", "last_name": "Attacker"}]},
    )
    assert response.status_code == 404
    assert len(tenant.school_class.roster) == before


def test_subjects_stay_shared_across_the_staffroom(
    client: TestClient, tenant: Tenant, colleague: Tenant
) -> None:
    """Ownership is about classes, not about teaching material.

    Subjects, chapters, textbooks and extracted exercises are deliberately
    school-wide — a colleague's uploaded corpus is meant to be usable.
    """
    login(client, colleague.teacher.email)
    ids = {s["id"] for s in client.get("/api/v1/subjects").json()}
    assert str(tenant.subject.id) in ids


# --------------------------------------------------------------------------
# Enrollment widens WHO, never which school or year (I-platform-10)
# --------------------------------------------------------------------------
def test_enrollment_never_crosses_a_school(db: Session, tenant: Tenant) -> None:
    other = make_tenant(db, name="Autre école", email="rita@autre.ch", class_code="8C")
    with pytest.raises(ApiError):
        class_service.enroll(db, tenant.school_class, other.students[0])


def test_enrollment_never_crosses_a_school_year(db: Session, tenant: Tenant) -> None:
    """``uq_student_uid`` is unique per school YEAR.

    An enrollment spanning two of them would make a printed UID ambiguous —
    the one identifier the detector has to be able to trust.
    """
    next_year = SchoolYear(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        label="2027/28",
        starts_on=date(2027, 8, 1),
        ends_on=date(2028, 7, 1),
        is_current=False,
    )
    db.add(next_year)
    db.flush()
    later = Class(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        school_year_id=next_year.id,
        head_teacher_id=tenant.teacher.id,
        code="8B",
        label="L'an prochain",
    )
    db.add(later)
    db.flush()

    with pytest.raises(ApiError):
        class_service.enroll(db, later, tenant.students[0])


def test_a_co_enrolled_student_is_readable_by_both_their_teachers(
    db: Session, tenant: Tenant
) -> None:
    """The widening this change exists for, and its boundary.

    A colleague who teaches the same child sees them. A colleague who does not
    still gets a 404 — enrollment is the rule, not the school (D69, D23).
    """
    colleague = make_colleague(db, tenant, email="bea@alpes.ch", class_code="8A")
    visitor = tenant.students[0]
    class_service.enroll(db, colleague.school_class, visitor)
    db.commit()

    assert mastery_service._owned_student(db, colleague.scope, visitor.id).id == visitor.id

    stranger = make_colleague(db, tenant, email="carl@alpes.ch", class_code="8D")
    with pytest.raises(ApiError):
        mastery_service._owned_student(db, stranger.scope, visitor.id)


# --- The second half: the database's own boundary --------------------------
#
# Everything above is application-level — a `.where(school_id == ...)` that a
# handler has to remember. Since D84 there is a policy underneath it, keyed on
# `app.current_school_id`, and these two tests guard the seam: they check that
# the tenant is bound onto the session, and only after the membership has been
# proved. What the policies then DO with it is Postgres's, and is checked by
# `scripts/check-rls.py` — this suite runs on SQLite, which has no row-level
# security at all and so cannot notice a policy that was never created.


def test_a_request_binds_its_tenant_onto_the_session(
    client: TestClient, tenant: Tenant, request_sessions: list[Session]
) -> None:
    login(client, tenant.teacher.email)
    assert client.get(f"/api/v1/classes/{tenant.school_class.id}").status_code == 200

    # The session the HANDLER held, not the test's — they are two objects now,
    # and binding the tenant onto the test's would prove nothing about either.
    bound = request_sessions[-1]
    assert getattr(bound, "school_id", None) == tenant.school.id
    # The teacher goes with it for the one policy that needs it: `school`,
    # which has to keep listing the other schools this teacher works at (D74).
    assert getattr(bound, "teacher_id", None) == tenant.teacher.id


def test_a_session_with_no_membership_is_left_blind(
    client: TestClient, tenant: Tenant, request_sessions: list[Session]
) -> None:
    """Unset is "see nothing", not "see everything".

    A request that never resolves a membership must not leave a tenant bound
    for the next one to inherit — and must not be handed a permissive default
    either. `get_membership` binds after the `teacher_school` check and nowhere
    else, so a 401 leaves the session exactly as blind as it started.
    """
    assert client.get(f"/api/v1/classes/{tenant.school_class.id}").status_code == 401
    assert request_sessions, "the request opened no session to leave blind"
    assert getattr(request_sessions[-1], "school_id", None) is None
