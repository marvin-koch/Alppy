"""The read audit trail: what it records, and what it must never do.

`event` says what happened TO a class. This says who LOOKED at a child, which
is the question a parent asks and the one nothing could answer before (audit
H7). Its value rests on three properties, and each has a test here because
each is easy to lose in a refactor that looks harmless.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant

from alppy.api import errors
from alppy.models import AccessLog
from alppy.models.enums import AccessSubject
from alppy.services import access_log, class_service, mastery_service


def _rows(db: Session) -> list[AccessLog]:
    return list(db.query(AccessLog).order_by(AccessLog.occurred_at).all())


def test_opening_a_pupils_profile_is_recorded(db: Session, tenant: Tenant) -> None:
    """The whole point: reading a child's record leaves a trace."""
    student = tenant.students[0]

    mastery_service._owned_student(db, tenant.scope, student.id)
    db.flush()

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0].subject_type is AccessSubject.STUDENT
    assert rows[0].subject_id == student.id
    assert rows[0].teacher_id == tenant.teacher.id
    assert rows[0].school_id == tenant.school.id
    assert rows[0].action == access_log.PROFILE_READ


def test_a_refused_read_records_nothing(db: Session, tenant: Tenant, colleague: Tenant) -> None:
    """A 404 is not an access.

    The row is written after the gate, never before it — otherwise the trail
    fills with reads that did not happen, and "who saw this child" stops
    meaning anything.
    """
    outsider = colleague.students[0]

    with pytest.raises(errors.ApiError):
        mastery_service._owned_student(db, tenant.scope, outsider.id)

    assert _rows(db) == []


def test_the_trail_carries_no_names(db: Session, tenant: Tenant) -> None:
    """Two ids and a verb.

    A log that copied the name would be the leak it exists to detect, and would
    survive `anonymise` — which is exactly the wrong way round.
    """
    student = tenant.students[0]
    class_service.get_student(db, tenant.scope, student.id)
    db.flush()

    row = _rows(db)[0]
    written = " ".join(
        str(v) for v in (row.action, row.subject_type, row.subject_id, row.request_id)
    )
    assert student.first_name not in written
    assert student.last_name not in written
    assert student.uid not in written


def test_a_broken_write_never_fails_the_read(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A teacher's roster must not fail to open because the audit table did.

    The trade is deliberate and stated in `access_log.py`: a lost row is a gap
    in the trail, and a raised exception is a class nobody can open on a Monday
    morning. This test is what keeps the swallow from being quietly removed.
    """
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("audit table is on fire")

    monkeypatch.setattr(db, "add", _boom)
    student = tenant.students[0]

    found = mastery_service._owned_student(db, tenant.scope, student.id)
    assert found.id == student.id


def test_the_sweep_keeps_what_is_inside_the_window(db: Session, tenant: Tenant) -> None:
    """Retention is a promise; the sweep is what keeps it."""
    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    for age_days in (10, 400):
        db.add(
            AccessLog(
                id=uuid.uuid4(),
                school_id=tenant.school.id,
                teacher_id=tenant.teacher.id,
                subject_type=AccessSubject.STUDENT,
                subject_id=tenant.students[0].id,
                action=access_log.PROFILE_READ,
                occurred_at=now - timedelta(days=age_days),
            )
        )
    db.flush()

    deleted = access_log.purge_expired(db, now=now)

    assert deleted == 1, "the 400-day-old row is past a 365-day window"
    remaining = _rows(db)
    assert len(remaining) == 1
    assert remaining[0].occurred_at.replace(tzinfo=UTC) > now - timedelta(days=365)
