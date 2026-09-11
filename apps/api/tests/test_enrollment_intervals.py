"""Leaving and coming back, on the engine the unit suite actually runs.

`test_schema_constraints.py` proves the three open-membership indexes are
partial *on Postgres*. This module asserts the behaviour that depends on it
through the service, on the default engine — and it exists because those two
were not the same thing.

SQLAlchemy applies ``postgresql_where`` only on PostgreSQL. With that as the
only predicate, ``create_all()`` on SQLite built ``uq_class_student_open`` as
an **unconditionally** unique index over ``(class_id, student_id)`` — so the
unit suite was stricter than production, forbidding a pair of rows the real
database allows and the product depends on. That is the worst direction for an
engine divergence to run: nothing fails, so nothing is noticed. Lea leaving the
niveau-2 group in February and rejoining in May is legal in Postgres and was an
``IntegrityError`` here, and no test exercised the path at all.

``sqlite_where`` on the same three indexes is what makes the engines agree.
This module is what would notice if it were removed again.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant

from alppy.models import Class, Student, class_student
from alppy.models.enums import ClassKind
from alppy.services import class_service


@pytest.fixture
def niveau(db: Session, tenant: Tenant) -> Class:
    """A course group that is nobody's home class.

    ``unenroll`` refuses the home class — the home is where the UID came from
    and the column is NOT NULL — so the interval behaviour can only be
    exercised on a second class the pupil merely attends. That is also the real
    shape of the problem 0027 exists for: Cycle 3 streams pupils into maths
    niveaux across homerooms.
    """
    row = Class(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        school_year_id=tenant.school_class.school_year_id,
        head_teacher_id=tenant.teacher.id,
        code="MA-N2",
        kind=ClassKind.COURSE,
    )
    db.add(row)
    db.flush()
    return row


def _memberships(db: Session, student: Student, klass: Class) -> list[tuple[date, date | None]]:
    return [
        (r.valid_from, r.valid_to)
        for r in db.execute(
            class_student.select()
            .where(class_student.c.class_id == klass.id)
            .where(class_student.c.student_id == student.id)
            .order_by(class_student.c.valid_from)
        ).all()
    ]


def test_a_pupil_whose_spell_ended_can_be_enrolled_again(
    db: Session, tenant: Tenant, niveau: Class
) -> None:
    """The case the partial index exists to allow.

    The closed row is written directly rather than through ``unenroll``,
    because ``unenroll`` ends a membership *today* (``db/validity.py``'s
    ``today()`` is not injectable — see T5) and the interesting case is a spell
    that ended months ago. What is under test is ``enroll`` — whether seating a
    pupil who has a CLOSED, PAST row for this class inserts a second, open one.

    The dates have to be genuinely in the past. A spell ending later this
    school year is still *current*, and ``_open_membership``'s second read
    correctly finds it and returns — which is right, and is not what this test
    is about.

    Against an unconditionally-unique index this raises ``IntegrityError``.
    """
    student = tenant.students[0]
    db.execute(
        class_student.insert().values(
            class_id=niveau.id,
            student_id=student.id,
            valid_from=date(2025, 8, 20),
            valid_to=date(2026, 2, 15),
        )
    )
    db.flush()

    class_service.enroll(db, niveau, student)
    db.flush()

    rows = _memberships(db, student, niveau)
    assert len(rows) == 2, f"the return could not be recorded: {rows}"
    assert rows[0][1] == date(2026, 2, 15), "the old spell lost its end date"
    assert rows[1][1] is None, "the new spell is not open"


def test_a_pupil_is_on_the_roster_once_after_coming_back(
    db: Session, tenant: Tenant, niveau: Class
) -> None:
    """Two rows, one of them open — the count a matrix column reads.

    The history is what makes October's sheet still reconcile; "exactly one
    open" is what stops the pupil being drawn twice today.
    """
    student = tenant.students[0]
    db.execute(
        class_student.insert().values(
            class_id=niveau.id,
            student_id=student.id,
            valid_from=date(2025, 8, 20),
            valid_to=date(2026, 2, 15),
        )
    )
    db.flush()
    class_service.enroll(db, niveau, student)
    db.flush()

    open_rows = [r for r in _memberships(db, student, niveau) if r[1] is None]
    assert len(open_rows) == 1


def test_leaving_and_returning_the_same_day_reopens_the_row(
    db: Session, tenant: Tenant, niveau: Class
) -> None:
    """The other branch of ``_open_membership``, and the one with the trap.

    Since 0027 the key carries ``valid_from``, so a pupil unenrolled this
    morning and put back this afternoon collides on the PRIMARY KEY rather than
    on the pair — which is why this is a reopen rather than an insert, and why
    the old ``ON CONFLICT DO NOTHING`` would have dropped the re-enrolment
    silently and left the roster one child short.
    """
    student = tenant.students[0]
    class_service.enroll(db, niveau, student)
    db.flush()
    class_service.unenroll(db, niveau, student)
    db.flush()
    assert _memberships(db, student, niveau)[0][1] is not None

    class_service.enroll(db, niveau, student)
    db.flush()

    rows = _memberships(db, student, niveau)
    assert len(rows) == 1, f"a same-day return made a second row: {rows}"
    assert rows[0][1] is None, "the re-enrolment was dropped"


def test_enrolling_an_already_seated_pupil_changes_nothing(
    db: Session, tenant: Tenant, niveau: Class
) -> None:
    """Idempotent, as the docstring promises."""
    student = tenant.students[0]
    class_service.enroll(db, niveau, student)
    db.flush()
    before = _memberships(db, student, niveau)

    class_service.enroll(db, niveau, student)
    db.flush()

    assert _memberships(db, student, niveau) == before
