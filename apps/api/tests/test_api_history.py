"""Reading the past: `as_of`, `on`, and the school year.

Every read in this API answered "now", and could not be asked otherwise. That
is fine until August, and until a pupil changes group mid-year — at which point
a matrix column claims that today's niveau-2 group scored what October's group
scored on a sheet half of them never sat (audit 02, C3).

0027 made the enrolment rows time-bound and 0028 gave a pupil an identity that
outlives the year. These are the tests that the HTTP surface can actually reach
that work: a parameter that exists but resolves to "now" anyway would look
exactly like a working one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise

from alppy.models import Attempt, SchoolYear, class_student


def test_the_school_years_are_listable_newest_first(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """The discovery route. Every `school_year_id` filter needs an id, and
    until this existed a client had no way to be told one."""
    db.add(
        SchoolYear(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            label="2025/26",
            starts_on=date(2025, 8, 1),
            ends_on=date(2026, 7, 31),
            is_current=False,
        )
    )
    db.commit()

    login(client, tenant.teacher.email)
    response = client.get("/api/v1/school-years")
    assert response.status_code == 200
    years = response.json()
    assert [y["label"] for y in years] == ["2026/27", "2025/26"]
    assert [y["is_current"] for y in years] == [True, False]


def test_another_schools_years_are_not_listed(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    labels = {y["id"] for y in client.get("/api/v1/school-years").json()}
    login(client, other_tenant.teacher.email)
    theirs = {y["id"] for y in client.get("/api/v1/school-years").json()}
    assert labels.isdisjoint(theirs)


def test_a_class_names_the_year_it_belongs_to(
    client: TestClient, tenant: Tenant
) -> None:
    """A class code is reused every August, so the code alone does not identify
    a group across years."""
    login(client, tenant.teacher.email)
    rows = client.get("/api/v1/classes").json()
    assert rows
    assert all(row["school_year_id"] for row in rows)
    assert rows[0]["school_year_id"] == str(tenant.school_class.school_year_id)


def test_filtering_classes_by_a_year_they_are_not_in_gives_none(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    other_year = SchoolYear(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        label="2025/26",
        starts_on=date(2025, 8, 1),
        ends_on=date(2026, 7, 31),
        is_current=False,
    )
    db.add(other_year)
    db.commit()

    login(client, tenant.teacher.email)
    current = client.get(
        f"/api/v1/classes?school_year_id={tenant.school_class.school_year_id}"
    )
    assert current.status_code == 200
    assert len(current.json()) == 1

    past = client.get(f"/api/v1/classes?school_year_id={other_year.id}")
    assert past.status_code == 200
    assert past.json() == []


def test_a_roster_can_be_read_as_it_stood_on_a_past_day(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """The point of 0027, reached through HTTP.

    Léa was streamed out of the niveau-2 group at the start of September.
    Today's roster is two children; the one that sat August's sheet is three.
    Without `on` the second question cannot be asked at all, and every read of
    that sheet silently answers with today's group.

    The window is half-open — `valid_from <= on < valid_to` — so a row ending
    on the 1st does not count on the 1st.
    """
    left = tenant.students[0]
    db.execute(
        update(class_student)
        .where(class_student.c.student_id == left.id)
        .where(class_student.c.class_id == tenant.school_class.id)
        .values(valid_from=date(2025, 8, 1), valid_to=date(2026, 9, 1))
    )
    db.commit()

    login(client, tenant.teacher.email)
    today = client.get(f"/api/v1/classes/{tenant.school_class.id}/students")
    assert today.status_code == 200
    assert left.uid not in {s["uid"] for s in today.json()}, (
        "a membership that ended is not in today's roster"
    )

    august = client.get(
        f"/api/v1/classes/{tenant.school_class.id}/students?on=2026-08-15"
    )
    assert august.status_code == 200
    assert left.uid in {s["uid"] for s in august.json()}, (
        "the roster as of August must hold the pupil who left in September"
    )

    # The boundary itself, stated rather than assumed.
    on_the_day = client.get(
        f"/api/v1/classes/{tenant.school_class.id}/students?on=2026-09-01"
    )
    assert left.uid not in {s["uid"] for s in on_the_day.json()}


def test_a_matrix_as_of_a_date_ignores_what_happened_after_it(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """`as_of` is not decoration: it drops the evidence that came later.

    A band computed as of the end of term must not move because the pupil
    answered three more questions in the holidays.
    """
    exercise = make_exercise(db, tenant, statement="2/4 = ?")
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
            answered_at=datetime(2026, 9, 3, tzinfo=UTC),
        )
    )
    db.commit()

    login(client, tenant.teacher.email)
    after = client.get(f"/api/v1/classes/{tenant.school_class.id}/mastery")
    assert after.status_code == 200
    before = client.get(
        f"/api/v1/classes/{tenant.school_class.id}/mastery?as_of=2026-09-01T00:00:00Z"
    )
    assert before.status_code == 200

    def attempts(body: dict) -> int:
        return sum(cell.get("attempts_count", 0) for cell in body.get("cells", []))

    assert attempts(after.json()) >= 1, "the attempt is visible without as_of"
    assert attempts(before.json()) == 0, (
        "an attempt answered after the as_of moment must not count towards it"
    )
