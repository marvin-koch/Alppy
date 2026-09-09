"""The agenda's write side: recording what happened, once, where it happened.

Why this exists
---------------
A teacher's question is chronological — *what did I do with 7B in March, and
which of it still needs correcting?* — and nothing in the schema could answer
it. Rows carry ``created_at`` and ``updated_at``; the second is overwritten by
whatever edit came last, so it cannot say when a pile was confirmed, and two of
the moments that matter most (a sheet going to the photocopier, a scan being
confirmed) left no trace at all.

The shape of the rule
---------------------
``record`` is the only writer, it never raises, and it never commits. Those
three properties together are what make it safe to call from inside a service
that is doing real work: a failure to log must never roll back the thing being
logged. An agenda missing one line is a small loss; a confirmed scan lost
because its log row would not write is a class's evening of marking.

What may go in
--------------
``summary`` is what the agenda shows when the row it describes has been
deleted, so it holds a sheet title, a filename, a chapter — **never a student
name**. ``detail`` holds counts, never free text. The log is read back by a
teacher and, one day, exported; keeping PII out of it by construction is
cheaper than scrubbing it later.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from alppy.core.logging import get_logger
from alppy.models import Event
from alppy.models.enums import EventKind, EventSubject

log = get_logger(__name__)

MAX_SUMMARY = 200


def record(
    db: Session,
    *,
    school_id: uuid.UUID,
    kind: EventKind,
    subject_type: EventSubject,
    subject_id: uuid.UUID,
    summary: str = "",
    actor_id: uuid.UUID | None = None,
    class_id: uuid.UUID | None = None,
    subject_area_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> Event | None:
    """Append one event. Never raises, never commits.

    Swallowing its own errors is deliberate and is the same choice
    ``ai.audit.record_calls`` makes: this is a bookkeeping write riding inside
    somebody else's transaction, and it may not be the reason that transaction
    fails.
    """
    try:
        event = Event(
            id=uuid.uuid4(),
            school_id=school_id,
            kind=kind,
            occurred_at=occurred_at or datetime.now(UTC),
            actor_id=actor_id,
            subject_type=subject_type,
            subject_id=subject_id,
            class_id=class_id,
            subject_area_id=subject_area_id,
            summary=(summary or "")[:MAX_SUMMARY],
            detail=detail,
        )
        db.add(event)
        db.flush()
        return event
    except Exception:
        log.warning("event.record_failed", kind=str(kind), subject_id=str(subject_id))
        return None


def list_events(
    db: Session,
    *,
    school_id: uuid.UUID,
    class_ids: Sequence[uuid.UUID],
    visibility: ColumnElement[bool] | None = None,
    kinds: Sequence[EventKind] | None = None,
    subject_area_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    query: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Event], int, dict[str, int]]:
    """One page of the agenda, newest first, plus the total and the facets.

    The filter list is built once and applied identically to the page query,
    the count and the facets, for the same reason the exercise listing does it:
    a facet that counted a different set than the page would offer the teacher
    a filter that does not return what the chip promised.

    Facets are computed with every filter EXCEPT the kind filter, so a chip
    reports what selecting it would give rather than what is already selected.
    """
    from sqlalchemy import func

    common: list[Any] = [Event.school_id == school_id]
    # A teacher sees their own classes' events, plus the school-wide ones that
    # belong to no class (importing a textbook, for instance).
    if visibility is not None:
        # Built by the caller, because it is a TENANCY predicate and those live
        # in `services.enrollment` — one definition, or a new read path invents
        # a laxer one (I-platform-03, I-platform-11).
        common.append(visibility)
    elif class_ids:
        common.append(
            (Event.class_id.in_(list(class_ids))) | (Event.class_id.is_(None))
        )
    else:
        common.append(Event.class_id.is_(None))
    if subject_area_id is not None:
        common.append(Event.subject_area_id == subject_area_id)
    if since is not None:
        common.append(Event.occurred_at >= since)
    if until is not None:
        common.append(Event.occurred_at <= until)
    if query:
        common.append(Event.summary.ilike(f"%{query}%"))

    facet_rows = db.execute(
        select(Event.kind, func.count(Event.id)).where(*common).group_by(Event.kind)
    ).all()
    facets = {str(kind.value if hasattr(kind, "value") else kind): int(n) for kind, n in facet_rows}

    page_filters = list(common)
    if kinds:
        page_filters.append(Event.kind.in_(list(kinds)))

    total = int(
        db.execute(select(func.count(Event.id)).where(*page_filters)).scalar_one_or_none() or 0
    )
    rows = list(
        db.scalars(
            select(Event)
            .where(*page_filters)
            # A stable secondary sort: two events in the same transaction share
            # a timestamp, and a page boundary must not shuffle between reads.
            .order_by(Event.occurred_at.desc(), Event.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return rows, total, facets


__all__ = ["list_events", "record"]
