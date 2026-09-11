"""Recording who read a pupil's record, and sweeping the record clean.

`event_service` is the write log a teacher reads on the agenda. This is the
other thing: an append-only trail of **reads**, for the question a parent or a
cantonal DPO asks — "who looked at my child's file" — which looking previously
left no trace of at all (audit H7, `models.AccessLog`).

Two rules hold this together and both are easy to lose:

**A read is never failed by its own logging.** The row is best-effort: a broken
audit write must not take a teacher's screen down with it, because the failure
mode of the opposite choice is a class that cannot open a roster on a Monday
morning. The failure is logged loudly instead. That is a real trade — a lost
row is a gap in the trail — and it is the right way round for a product that
sits between a teacher and a lesson, but it is the reason the sweep below is
the ONLY other writer: every other guarantee this table has comes from nothing
else being able to touch it.

**No names.** Two ids and a verb. Resolving them is a deliberate query against
the tables that hold names, which is what keeps the trail readable after a
pupil has been anonymised (0041) and what stops the audit log becoming the leak
it exists to detect — the same argument `ModelCall` makes against `PromptLog`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from alppy.api.deps import Scope
from alppy.core.config import get_settings
from alppy.core.logging import get_logger, request_id_var
from alppy.models import AccessLog
from alppy.models.enums import AccessSubject

log = get_logger(__name__)

#: The verbs this table uses. A closed set rather than free text, for the
#: reason `FAILURE_CODES` is one: a column somebody types a sentence into stops
#: being queryable the first time two people phrase the same act differently.
PROFILE_READ = "profile_read"
"""A pupil's own record — the profile, their attempts, their history."""

RECORD_OPENED = "record_opened"
"""A pupil fetched in order to act on them: rename, re-enrol, delete."""

ROSTER_READ = "roster_read"
"""A class's roster of named children."""


def record(
    db: Session,
    scope: Scope,
    *,
    subject_type: AccessSubject,
    subject_id: uuid.UUID,
    action: str,
) -> None:
    """Append one row. Never raises.

    Flushed rather than committed: the row belongs to the caller's transaction,
    so a read that ends up rolling back does not leave a trail claiming it
    happened.
    """
    try:
        db.add(
            AccessLog(
                id=uuid.uuid4(),
                school_id=scope.school_id,
                teacher_id=scope.teacher_id,
                subject_type=subject_type,
                subject_id=subject_id,
                action=action,
                occurred_at=datetime.now(UTC),
                request_id=request_id_var.get(),
            )
        )
        db.flush()
    except Exception:  # pragma: no cover - defended, not expected
        # Deliberately broad, and deliberately swallowed. See the module
        # docstring: a teacher's roster must not fail to open because the audit
        # table did. The exception text goes to the log, never to a response
        # (D86).
        log.exception(
            "access_log.write_failed",
            subject_type=str(subject_type),
            action=action,
        )


def student_read(db: Session, scope: Scope, student_id: uuid.UUID, action: str) -> None:
    """The common case, spelled once so call sites stay one line."""
    record(
        db, scope, subject_type=AccessSubject.STUDENT, subject_id=student_id, action=action
    )


def purge_expired(db: Session, *, now: datetime | None = None) -> int:
    """Delete rows past the retention window. Returns how many went.

    The one writer besides `record`. Zero or a negative retention means keep
    forever — an audit trail's default should not be "quietly disappears" — so
    unlike the prompt log this is opt-OUT rather than opt-in.
    """
    days = get_settings().access_log_retention_days
    if days <= 0:
        return 0
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    ids = list(db.scalars(select(AccessLog.id).where(AccessLog.occurred_at < cutoff)))
    if not ids:
        return 0
    db.execute(delete(AccessLog).where(AccessLog.id.in_(ids)))
    db.commit()
    return len(ids)
