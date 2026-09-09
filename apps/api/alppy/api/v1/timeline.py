"""The agenda — everything that happened, in order (F8).

One endpoint, reading the append-only ``event`` log. It follows the shape of
the exercise listing in ``sources.py``: one list of filter conditions built
once and applied identically to the page, the count and the facets, so a chip
can never promise a different set than selecting it returns.

The log stores what happened; the titles are resolved here, at read time,
against the rows the events point at. An event whose subject has since been
deleted still shows — deleting a sheet does not un-print it — and is marked
``resolved: false`` so the client renders the line without a link that 404s.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from alppy.api.deps import DbDep, ScopeDep
from alppy.models import Class, Event, Scan, Sheet, Source, SourceSection
from alppy.models.enums import EventKind, EventSubject
from alppy.schemas import TimelineEventOut, TimelineFacets, TimelineOut
from alppy.services.enrollment import owned_class_ids
from alppy.services.event_service import list_events

router = APIRouter(tags=["timeline"])


def _titles(db: DbDep, events: list[Event]) -> dict[tuple[EventSubject, uuid.UUID], str]:
    """Current titles for everything the page points at, in three queries.

    Batched rather than per row: an agenda page is twenty events and a naive
    resolve would be twenty round trips for a screen a teacher opens daily.
    """
    wanted: dict[EventSubject, set[uuid.UUID]] = {}
    for event in events:
        wanted.setdefault(event.subject_type, set()).add(event.subject_id)

    out: dict[tuple[EventSubject, uuid.UUID], str] = {}

    def resolve(kind: EventSubject, rows: Any, attr: str) -> None:
        for row in rows:
            out[(kind, row.id)] = str(getattr(row, attr, "") or "")

    if ids := wanted.get(EventSubject.SHEET):
        resolve(EventSubject.SHEET, db.scalars(select(Sheet).where(Sheet.id.in_(list(ids)))), "title")
    if ids := wanted.get(EventSubject.SOURCE):
        resolve(
            EventSubject.SOURCE,
            db.scalars(select(Source).where(Source.id.in_(list(ids)))),
            "filename",
        )
        # A chapter-read event points at the SECTION, not the document: one
        # source has many chapters, and keying those events on the source id
        # would collapse them all into one under the log's (kind, subject)
        # identity. So the same subject type resolves against both tables.
        resolve(
            EventSubject.SOURCE,
            db.scalars(select(SourceSection).where(SourceSection.id.in_(list(ids)))),
            "title",
        )
    if ids := wanted.get(EventSubject.SCAN):
        resolve(
            EventSubject.SCAN,
            db.scalars(select(Scan).where(Scan.id.in_(list(ids)))),
            "original_filename",
        )
    if ids := wanted.get(EventSubject.CLASS):
        resolve(EventSubject.CLASS, db.scalars(select(Class).where(Class.id.in_(list(ids)))), "code")
    return out


@router.get("/timeline", response_model=TimelineOut)
def get_timeline(
    scope: ScopeDep,
    db: DbDep,
    kind: list[EventKind] | None = Query(default=None),
    subject_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    q: str | None = Query(default=None, max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> TimelineOut:
    """One page of the agenda, newest first.

    Scoped to the classes this teacher owns, plus the school-wide events that
    belong to no class — importing a textbook is staffroom work and shows for
    everyone, a class's scans do not (decisions-log D23).
    """
    class_ids = list(db.scalars(owned_class_ids(scope)))
    events, total, facets = list_events(
        db,
        school_id=scope.school_id,
        class_ids=class_ids,
        kinds=kind,
        subject_area_id=subject_id,
        since=since,
        until=until,
        query=q,
        offset=offset,
        limit=limit,
    )

    titles = _titles(db, events)
    codes = {
        c.id: c.code
        for c in db.scalars(
            select(Class).where(Class.id.in_([e.class_id for e in events if e.class_id] or [uuid.UUID(int=0)]))
        )
    }

    items = []
    for event in events:
        resolved = (event.subject_type, event.subject_id) in titles
        items.append(
            TimelineEventOut(
                id=event.id,
                kind=event.kind,
                occurred_at=event.occurred_at,
                subject_type=event.subject_type,
                subject_id=event.subject_id,
                # The live title when the row is still there, the stored
                # summary when it is not.
                title=titles.get((event.subject_type, event.subject_id)) or event.summary,
                class_id=event.class_id,
                class_code=codes.get(event.class_id) if event.class_id else None,
                subject_area_id=event.subject_area_id,
                detail=event.detail or {},
                resolved=resolved,
            )
        )

    return TimelineOut(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        facets=TimelineFacets(by_kind=facets),
    )
