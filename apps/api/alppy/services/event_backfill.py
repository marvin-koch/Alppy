"""Reconstruct the agenda for work that happened before the log existed.

Without this, `/timeline` on an existing database is an empty screen that says
nothing happened until the day the feature shipped — which is untrue, and is
exactly the impression that makes a teacher stop opening it.

What can honestly be reconstructed
----------------------------------
Only what a real timestamp already recorded:

* ``Source.created_at``      -> a textbook was imported
* ``SourceSection.extracted_at`` -> a chapter was read
* ``Sheet.created_at``       -> a sheet was built
* ``Sheet.rendered_at``      -> its PDFs were produced
* ``Scan.created_at``        -> copies were uploaded
* the newest ``Attempt.answered_at`` per scanned sheet -> the pile was confirmed

What cannot, and is therefore not invented
------------------------------------------
**A sheet being printed.** Nothing ever recorded it — that absence is half the
reason the log exists — so no `SHEET_PRINTED` event is manufactured here.
Deriving one from `rendered_at` would put a fact in the log that nobody
observed, and an agenda that quietly guesses is worse than one with a gap: the
teacher cannot tell which lines are evidence and which are inference.

Confirmation is the one derived event, and it is honest: it uses the attempts'
own `answered_at`, the same stamp `confirm_scan` writes, so the reconstructed
line lands on the day the class actually sat the sheet.

Idempotent by construction: every event carries the subject it describes, so a
second run finds the `(kind, subject_id)` pair already present and adds nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alppy.core.logging import get_logger
from alppy.models import Attempt, Event, Scan, Sheet, Source, SourceSection
from alppy.models.enums import EventKind, EventSubject
from alppy.services.event_service import record

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BackfillResult:
    """What the reconstruction added, by kind, so a run can be read at a glance."""

    sources: int = 0
    chapters: int = 0
    sheets: int = 0
    rendered: int = 0
    scans: int = 0
    confirmed: int = 0

    @property
    def total(self) -> int:
        return self.sources + self.chapters + self.sheets + self.rendered + self.scans + self.confirmed


def _existing(db: Session) -> set[tuple[EventKind, uuid.UUID]]:
    """Every (kind, subject) already logged — the whole idempotency check."""
    return {
        (kind, subject_id)
        for kind, subject_id in db.execute(select(Event.kind, Event.subject_id)).all()
    }


def backfill_events(db: Session) -> BackfillResult:
    """Reconstruct what can be reconstructed. Safe to run more than once."""
    seen = _existing(db)
    counts = {"sources": 0, "chapters": 0, "sheets": 0, "rendered": 0, "scans": 0, "confirmed": 0}

    def add(
        bucket: str,
        kind: EventKind,
        subject_type: EventSubject,
        subject_id: uuid.UUID,
        **kwargs: object,
    ) -> None:
        if (kind, subject_id) in seen:
            return
        if record(db, kind=kind, subject_type=subject_type, subject_id=subject_id, **kwargs) is not None:  # type: ignore[arg-type]
            seen.add((kind, subject_id))
            counts[bucket] += 1

    for source in db.scalars(select(Source)):
        add(
            "sources",
            EventKind.SOURCE_IMPORTED,
            EventSubject.SOURCE,
            source.id,
            school_id=source.school_id,
            summary=source.filename,
            subject_area_id=source.subject_id,
            occurred_at=source.created_at,
        )

    for section in db.scalars(select(SourceSection).where(SourceSection.extracted_at.is_not(None))):
        add(
            "chapters",
            EventKind.CHAPTER_READ,
            EventSubject.SOURCE,
            section.id,
            school_id=section.school_id,
            summary=section.title,
            occurred_at=section.extracted_at,
        )

    for sheet in db.scalars(select(Sheet)):
        add(
            "sheets",
            EventKind.SHEET_CREATED,
            EventSubject.SHEET,
            sheet.id,
            school_id=sheet.school_id,
            summary=sheet.title,
            actor_id=sheet.created_by_id,
            class_id=sheet.class_id,
            subject_area_id=sheet.subject_id,
            occurred_at=sheet.created_at,
        )
        if sheet.rendered_at is not None:
            add(
                "rendered",
                EventKind.SHEET_RENDERED,
                EventSubject.SHEET,
                sheet.id,
                school_id=sheet.school_id,
                summary=sheet.title,
                actor_id=sheet.created_by_id,
                class_id=sheet.class_id,
                subject_area_id=sheet.subject_id,
                occurred_at=sheet.rendered_at,
            )

    # The newest attempt per sheet is when that pile was confirmed: `confirm_scan`
    # stamps every attempt it writes with one shared `at`.
    confirmed_at: dict[uuid.UUID, datetime] = {}
    for sheet_id, when in db.execute(
        select(Attempt.sheet_id, func.max(Attempt.answered_at))
        .where(Attempt.sheet_id.is_not(None))
        .group_by(Attempt.sheet_id)
    ).all():
        if sheet_id is not None and when is not None:
            confirmed_at[sheet_id] = when

    for scan in db.scalars(select(Scan)):
        scanned = db.get(Sheet, scan.sheet_id) if scan.sheet_id else None
        common: dict[str, object] = {
            "school_id": scan.school_id,
            "summary": (scanned.title if scanned else scan.original_filename or ""),
            "class_id": scanned.class_id if scanned else None,
            "subject_area_id": scanned.subject_id if scanned else None,
        }
        add(
            "scans",
            EventKind.SCAN_UPLOADED,
            EventSubject.SCAN,
            scan.id,
            occurred_at=scan.created_at,
            **common,
        )
        when = confirmed_at.get(scan.sheet_id) if scan.sheet_id else None
        if when is not None:
            add(
                "confirmed",
                EventKind.SCAN_CONFIRMED,
                EventSubject.SCAN,
                scan.id,
                occurred_at=when,
                **common,
            )

    result = BackfillResult(**counts)
    log.info("events.backfilled", total=result.total, **counts)
    return result


__all__ = ["BackfillResult", "backfill_events"]
