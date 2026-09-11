"""Scans: upload, teacher correction, confirmation.

Three rules shape this module.

1. **The request never blocks on the pipeline.** ``create_scan`` stores the
   bytes, writes a ``Scan`` and a queued ``Job``, and returns. Registration,
   UID reading and bubble detection happen in the worker.
2. **The teacher is the authority, and the machine keeps its story.** A
   correction is recorded as ``CORRECTED`` with who and when; the reading it
   replaced stays in ``machine_index``/``machine_outcome``/``machine_confidence``,
   which are written once at detection time and never updated. "The teacher
   disagreed with the scanner" is the fact worth auditing.
3. **Nothing is guessed.** An item the grader cannot grade (free text, two
   bubbles filled, no answer key) produces no ``Attempt`` at all rather than a
   zero, because a zero is a claim about the student and "unreadable" is not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.api.deps import Scope, UploadPayload
from alppy.db.validity import today
from alppy.models import (
    Attempt,
    Class,
    Detection,
    Exercise,
    Job,
    Scan,
    ScanPage,
    Sheet,
    SheetItem,
    Student,
)
from alppy.models.enums import (
    DetectionOutcome,
    EventKind,
    EventSubject,
    ExerciseType,
    JobKind,
    JobStatus,
    ScanStatus,
)
from alppy.scan.grading import AnswerKey, DetectedAnswer, grade_item
from alppy.schemas import (
    DetectionCorrection,
    ScanConfirmResponse,
    ScanUnvalidateResponse,
)
from alppy.services import event_service
from alppy.services.enrollment import enrolled_student_ids, taught_here
from alppy.services.mastery_service import recompute_for_people
from alppy.storage import Storage, storage_key

CONFIRMABLE_STATUSES = (ScanStatus.UPLOADED, ScanStatus.PROCESSING, ScanStatus.NEEDS_REVIEW)


def _owned_scan(scope: Scope) -> Any:
    """A scan this teacher may read.

    Normally that means the pile was printed from a sheet in a branch they
    teach — PAIR-GRAINED since D73, because a sheet belongs to a
    (class, subject) and a colleague taking another branch in the same class
    has no business reading the marks on it.

    But a scan is uploaded *before* its sheet is always known — a pile
    photographed with nothing behind it has ``sheet_id IS NULL`` and must stay
    visible to the person who uploaded it, or the "which sheet was this?" step
    becomes unreachable and the upload is orphaned. ``NULL IN (...)`` is never
    true, so that case needs saying out loud (decisions-log D23).

    That second arm is **deliberately not narrowed**, and strict isolation is
    what makes it obviously right rather than merely convenient: an unmatched
    pile has no subject at all, so the only person who can say what it is, is
    the one holding the paper. Nor can the pile later flip out of their list —
    the sheet is attached through ``sheet_service.get_sheet``, which is itself
    pair-grained, so a teacher can only attach a sheet they already teach.
    """
    owned_sheets = select(Sheet.id).where(
        taught_here(Sheet.class_id, Sheet.subject_id, scope, on=today())
    )
    return or_(
        Scan.sheet_id.in_(owned_sheets),
        and_(Scan.sheet_id.is_(None), Scan.uploaded_by_id == scope.teacher_id),
    )


def get_scan(db: Session, scope: Scope, scan_id: uuid.UUID) -> Scan:
    scan = db.execute(
        select(Scan)
        .where(Scan.id == scan_id)
        .where(Scan.school_id == scope.school_id)
        .where(_owned_scan(scope))
    ).scalar_one_or_none()
    if scan is None:
        raise errors.not_found("scan", id=str(scan_id))
    return scan


def list_scans(
    db: Session,
    scope: Scope,
    *,
    sheet_id: uuid.UUID | None = None,
    school_year_id: uuid.UUID | None = None,
) -> list[Scan]:
    stmt = (
        select(Scan)
        .where(Scan.school_id == scope.school_id)
        .where(_owned_scan(scope))
    )
    if sheet_id is not None:
        stmt = stmt.where(Scan.sheet_id == sheet_id)
    if school_year_id is not None:
        # Two joins out: a pile belongs to the sheet it was printed from, and
        # the sheet to the class's year.
        stmt = stmt.where(
            Scan.sheet_id.in_(
                select(Sheet.id).where(
                    Sheet.class_id.in_(
                        select(Class.id).where(Class.school_year_id == school_year_id)
                    )
                )
            )
        )
    return list(db.execute(stmt.order_by(Scan.created_at.desc())).scalars())


def create_scan(
    db: Session,
    scope: Scope,
    storage: Storage,
    payloads: list[UploadPayload],
    *,
    sheet_id: uuid.UUID | None = None,
) -> tuple[Scan, Job]:
    """One pile, however many files it arrived in.

    A phone upload is one file per copy — the teacher selects 28 photos and
    expects one review session, not 28. The pages of every file concatenate, in
    the order they were selected.
    """
    if not payloads:
        raise errors.unprocessable("no file was uploaded")

    school_id = scope.school_id
    teacher_id = scope.teacher_id

    sheet: Sheet | None = None
    if sheet_id is not None:
        # Pair-grained, not tenant-grained (audit 03, B27). Validating on
        # `school_id` alone accepted a pile against a sheet in a branch this
        # teacher does not take — `_owned_scan` then hid the scan from them the
        # moment it had a sheet, so the upload succeeded, the worker processed
        # it, and the teacher had no route to the review screen. A 404 at upload
        # is the honest answer, and it is the same gate every other sheet read
        # goes through.
        from alppy.services.sheet_service import get_sheet

        sheet = get_sheet(db, scope, sheet_id)

    scan_id = uuid.uuid4()
    keys: list[str] = []
    for index, payload in enumerate(payloads):
        key = storage_key("scans", school_id, scan_id, f"{index:03d}-{payload.filename}")
        storage.put_bytes(key, payload.data, payload.content_type)
        keys.append(key)

    scan = Scan(
        id=scan_id,
        school_id=school_id,
        sheet_id=sheet_id,
        uploaded_by_id=teacher_id,
        original_filename=", ".join(p.filename for p in payloads)[:255],
        storage_key=keys[0],
        storage_keys=keys,
        # Pin the layout the paper was printed with, now, so a later sheet
        # re-render cannot change how an already-scanned pile is read.
        layout_version=sheet.layout_version if sheet is not None else None,
        # And which render of it, for the same reason and by the same means:
        # the answer-box rectangles this pile must be cropped at belong to the
        # render it was printed from, not to whichever one is newest when the
        # photographs are finally uploaded (B7).
        render_generation=sheet.render_generation if sheet is not None else None,
        status=ScanStatus.UPLOADED,
    )
    db.add(scan)

    job = Job(
        id=uuid.uuid4(),
        school_id=school_id,
        kind=JobKind.PROCESS_SCAN,
        status=JobStatus.QUEUED,
        progress=0.0,
        message="queued for registration and detection",
        scan_id=scan_id,
        payload={"scan_id": str(scan_id), "sheet_id": str(sheet_id) if sheet_id else None},
    )
    db.add(job)
    db.flush()

    sheet = db.get(Sheet, sheet_id) if sheet_id else None
    event_service.record(
        db,
        school_id=school_id,
        kind=EventKind.SCAN_UPLOADED,
        subject_type=EventSubject.SCAN,
        subject_id=scan.id,
        summary=(sheet.title if sheet else scan.original_filename or ""),
        actor_id=teacher_id,
        class_id=sheet.class_id if sheet else None,
        subject_area_id=sheet.subject_id if sheet else None,
        detail={"pages": len(payloads)},
    )
    return scan, job


def append_pages(
    db: Session,
    scope: Scope,
    teacher_id: uuid.UUID,
    storage: Storage,
    payloads: list[UploadPayload],
    *,
    scan_id: uuid.UUID,
    supersedes_page_id: uuid.UUID | None = None,
) -> tuple[Scan, Job]:
    """More photographs into a pile that already exists.

    Three of thirty copies were shot at an angle that lost a corner, so their
    fiducials were not found and the pages carry advice — *"reprenez la photo en
    cadrant les quatre coins"* — that there was nowhere to act on. Uploading the
    retakes made a SECOND scan against the same sheet: a second review, a second
    confirmation, and one class's work split across two records for no reason
    but a missing route. The likelier alternative was worse — discard the three,
    confirm the twenty-seven, and three pupils are silently unassessed.

    The job processes only what was added (``from_file``). Nothing deletes the
    pages already read, and that is the point: the teacher's corrections hang
    off those rows, and re-reading the pile would either duplicate every page or
    throw that work away.

    ``supersedes_page_id`` marks the failed page discarded in the same
    transaction — "this photograph is not one of this copy's pages", which is
    exactly what makes the pile ordinary again once the retake lands.
    """
    if not payloads:
        raise errors.unprocessable("no file was uploaded")

    scan = get_scan(db, scope, scan_id)
    # A confirmed pile is read-only: its grades were computed from the readings
    # as they stood. Adding a page underneath them would leave a grade
    # disagreeing with its own evidence.
    _refuse_when_confirmed(scan)

    # One reader at a time, per pile. Both the page numbers and the stored
    # image keys (`page-003.png`) continue from the rows already written, and
    # the worker runs four jobs at once (`WorkerSettings.max_jobs`), so two
    # runs over one scan would count the same rows, write colliding
    # `page_index` values and overwrite each other's registered images in the
    # bucket. Reachable in practice: pages appear as they are read, so a
    # teacher can see page 1 fail while page 20 is still being processed.
    #
    # Refused rather than queued behind it: "the pile is still being read" is
    # a sentence a teacher can act on, and the retake is one tap to repeat.
    in_flight = db.execute(
        select(Job.id)
        .where(Job.scan_id == scan.id)
        .where(Job.kind == JobKind.PROCESS_SCAN)
        .where(Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
        .limit(1)
    ).scalar_one_or_none()
    if in_flight is not None:
        raise errors.conflict(
            "this pile is still being read; wait for it to finish",
            code="scan_processing",
            scan_id=str(scan.id),
        )

    existing = list(scan.storage_keys or [scan.storage_key])
    keys: list[str] = []
    for offset, payload in enumerate(payloads, start=len(existing)):
        key = storage_key("scans", scan.school_id, scan.id, f"{offset:03d}-{payload.filename}")
        storage.put_bytes(key, payload.data, payload.content_type)
        keys.append(key)

    # Reassigned rather than appended in place: the column is JSON, and a list
    # mutated under SQLAlchemy is a list the session never hears about.
    scan.storage_keys = [*existing, *keys]
    names = [p.strip() for p in (scan.original_filename or "").split(",") if p.strip()]
    scan.original_filename = ", ".join([*names, *(p.filename for p in payloads)])[:255]
    scan.status = ScanStatus.UPLOADED

    if supersedes_page_id is not None:
        superseded = db.execute(
            select(ScanPage)
            .where(ScanPage.id == supersedes_page_id)
            .where(ScanPage.scan_id == scan.id)
        ).scalar_one_or_none()
        if superseded is None:
            raise errors.not_found("scan page", id=str(supersedes_page_id))
        # A re-shot copy retires the failed page, and the teacher uploading the
        # replacement is who did it (0047).
        superseded.discarded_at = datetime.now(UTC)
        superseded.discarded_by_id = scope.teacher_id

    job = Job(
        id=uuid.uuid4(),
        school_id=scan.school_id,
        kind=JobKind.PROCESS_SCAN,
        status=JobStatus.QUEUED,
        progress=0.0,
        message="queued for registration and detection",
        scan_id=scan.id,
        payload={
            "scan_id": str(scan.id),
            "sheet_id": str(scan.sheet_id) if scan.sheet_id else None,
            # Where this run starts. Everything before it has been read, and
            # may since have been corrected by hand.
            "from_file": len(existing),
        },
    )
    db.add(job)
    db.flush()

    event_service.record(
        db,
        school_id=scan.school_id,
        kind=EventKind.SCAN_UPLOADED,
        subject_type=EventSubject.SCAN,
        subject_id=scan.id,
        summary=scan.original_filename or "",
        actor_id=teacher_id,
        detail={"pages": len(payloads), "added_to_existing": True},
    )
    return scan, job


def _scan_for_school(db: Session, school_id: uuid.UUID, scan_id: uuid.UUID) -> Scan:
    """The scan, checked against the school. ``get_scan`` takes a ``Scope``;
    the correction path only carries a school id."""
    scan = db.execute(
        select(Scan).where(Scan.id == scan_id).where(Scan.school_id == school_id)
    ).scalar_one_or_none()
    if scan is None:
        raise errors.not_found("scan", id=str(scan_id))
    return scan


def _refuse_when_confirmed(scan: Scan) -> None:
    """A confirmed pile is read-only until it is reopened.

    Everything a confirmation wrote is graded from the readings as they stood
    at that moment. Editing one underneath is not an edit, it is a
    disagreement between a grade and its own evidence.
    """
    if scan.status is ScanStatus.CONFIRMED:
        raise errors.conflict(
            "this pile is confirmed; reopen it before changing a reading",
            code="scan_confirmed",
            scan_id=str(scan.id),
        )


def get_detection(
    db: Session, school_id: uuid.UUID, scan_id: uuid.UUID, detection_id: uuid.UUID
) -> Detection:
    detection = db.execute(
        select(Detection)
        .join(ScanPage, ScanPage.id == Detection.scan_page_id)
        .where(Detection.id == detection_id)
        .where(Detection.school_id == school_id)
        .where(ScanPage.scan_id == scan_id)
    ).scalar_one_or_none()
    if detection is None:
        raise errors.not_found("detection", id=str(detection_id))
    return detection


def _detections_query(school_id: uuid.UUID, scan_id: uuid.UUID) -> Select[tuple[Detection]]:
    """One pile's readings, in the order a teacher reads the paper: page by
    page, and within a page item by item."""
    return (
        select(Detection)
        .join(ScanPage, ScanPage.id == Detection.scan_page_id)
        .where(Detection.school_id == school_id)
        .where(ScanPage.scan_id == scan_id)
        .order_by(ScanPage.page_index.asc(), Detection.item_index.asc())
    )


def list_detections(db: Session, school_id: uuid.UUID, scan_id: uuid.UUID) -> list[Detection]:
    """Every reading in the pile. Internal callers only — the HTTP route pages
    (`list_detections_page`), because a pile is 336 rows for one ordinary class
    set and each row carries a presigned crop URL."""
    return list(db.execute(_detections_query(school_id, scan_id)).scalars())


def list_detections_page(
    db: Session, school_id: uuid.UUID, scan_id: uuid.UUID, *, offset: int, limit: int
) -> tuple[list[Detection], int]:
    """One page of them, and how many there are in total."""
    stmt = _detections_query(school_id, scan_id)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(db.execute(stmt.offset(offset).limit(limit)).scalars())
    return rows, total


def _exercise_for_detection(
    db: Session, school_id: uuid.UUID, detection: Detection
) -> Exercise | None:
    """The exercise this reading is graded against.

    ``exercise_id`` is resolved when the page is detected, from the pagination
    of *that student's own copy*. Reading it back from the row rather than from
    a position in the sheet's item list is what keeps a differentiated copy
    graded against the questions it actually printed.
    """
    if detection.exercise_id is not None:
        return db.execute(
            select(Exercise)
            .where(Exercise.id == detection.exercise_id)
            .where(Exercise.school_id == school_id)
        ).scalar_one_or_none()
    if detection.sheet_item_id is None:
        return None
    # Rows written before exercise_id existed.
    return db.execute(
        select(Exercise)
        .join(SheetItem, SheetItem.exercise_id == Exercise.id)
        .where(SheetItem.id == detection.sheet_item_id)
        .where(Exercise.school_id == school_id)
    ).scalar_one_or_none()


def correct_detection(
    db: Session,
    school_id: uuid.UUID,
    teacher_id: uuid.UUID,
    scan_id: uuid.UUID,
    detection_id: uuid.UUID,
    payload: DetectionCorrection,
    *,
    now: datetime | None = None,
) -> Detection:
    """Record a teacher override, always attributed.

    The machine's reading is *not* touched: ``machine_index``,
    ``machine_outcome`` and ``machine_confidence`` were written when the page
    was detected and stay as they were.

    Refused once the pile is confirmed. Until now nothing on the server said
    so — only the review screen's ``readOnly`` prop did, which meant a direct
    PATCH could edit a reading that a live ``Attempt`` had already been graded
    from, leaving the grade and the reading it claims to come from disagreeing.
    Reopen the pile first; that is what withdraws the grades.
    """
    scan = _scan_for_school(db, school_id, scan_id)
    _refuse_when_confirmed(scan)
    detection = get_detection(db, school_id, scan_id, detection_id)
    exercise = _exercise_for_detection(db, school_id, detection)

    if exercise is not None and exercise.type is ExerciseType.OPEN:
        return _correct_written_answer(detection, payload, teacher_id=teacher_id, now=now)

    # Bound the override by the options this item actually printed. A global
    # 0..3 let a two-bubble true/false item be "corrected" to option 3, which
    # then graded the child wrong against an answer they could not have given.
    if payload.detected_index is not None and exercise is not None:
        options = exercise.option_count
        if options and payload.detected_index >= options:
            raise errors.unprocessable(
                f"this item has {options} options, so {payload.detected_index} is not one of them",
                option_count=options,
            )

    detection.detected_index = payload.detected_index
    if exercise is not None and exercise.type is ExerciseType.TRUE_FALSE:
        # Bubble 0 is "true", bubble 1 is "false" in every sheet language.
        detection.detected_bool = (
            None if payload.detected_index is None else payload.detected_index == 0
        )
    else:
        detection.detected_bool = None
    detection.outcome = DetectionOutcome.CORRECTED
    detection.confidence = 1.0
    detection.corrected_by_id = teacher_id
    detection.corrected_at = now or datetime.now(UTC)
    db.flush()
    return detection


def _correct_written_answer(
    detection: Detection,
    payload: DetectionCorrection,
    *,
    teacher_id: uuid.UUID,
    now: datetime | None,
) -> Detection:
    """The teacher's word on a written answer: a verdict, a transcription, or
    both. The machine's stay where they were.

    ``verdict_correct`` may be set to ``None`` on purpose — "I cannot tell
    either" — and that is recorded as a correction too, so the row no longer
    looks like something the machine decided. A bare transcription fix keeps
    the verdict as it was."""
    if payload.detected_index is not None:
        raise errors.unprocessable("a written answer has no bubble to correct")
    if "verdict_correct" in payload.model_fields_set:
        detection.verdict_correct = payload.verdict_correct
    if payload.transcription is not None:
        detection.transcription = payload.transcription.strip() or None
    detection.outcome = DetectionOutcome.CORRECTED
    detection.confidence = 1.0
    detection.corrected_by_id = teacher_id
    detection.corrected_at = now or datetime.now(UTC)
    return detection


def revert_detection(
    db: Session, scope: Scope, scan_id: uuid.UUID, detection_id: uuid.UUID
) -> Detection:
    """Undo a teacher's correction: put back exactly what the machine read.

    Nothing here is invented. Every value written back was already sitting in
    ``machine_index`` / ``machine_outcome`` / ``machine_confidence`` (a bubble)
    or ``machine_transcription`` / ``machine_verdict_correct`` (a written
    answer) — columns written once at detection time and never touched by a
    correction, precisely so that this is possible.

    Two refusals rather than two silent no-ops:

    * a detection that was never corrected has nothing to revert, and a caller
      that believes it undid something must be told it did not;
    * a confirmed pile is read-only (``_refuse_when_confirmed``) — the grade
      was computed from the corrected reading, so replacing the reading
      underneath would leave the two disagreeing. Reopening withdraws the
      grade first, which is what makes the revert safe.
    """
    school_id = scope.school_id
    scan = get_scan(db, scope, scan_id)
    _refuse_when_confirmed(scan)
    detection = get_detection(db, school_id, scan_id, detection_id)
    if detection.outcome is not DetectionOutcome.CORRECTED:
        raise errors.conflict(
            "this reading was never corrected",
            code="detection_not_corrected",
            detection_id=str(detection_id),
        )

    exercise = _exercise_for_detection(db, school_id, detection)
    if exercise is not None and exercise.type is ExerciseType.OPEN:
        detection.transcription = detection.machine_transcription
        detection.verdict_correct = detection.machine_verdict_correct
    else:
        detection.detected_index = detection.machine_index
        detection.detected_bool = (
            None
            if exercise is None
            or exercise.type is not ExerciseType.TRUE_FALSE
            or detection.machine_index is None
            else detection.machine_index == 0
        )
    # `machine_outcome` is written for every detection the pipeline produces,
    # so the fallback is defensive only — a row with none was never machine-read
    # at all, and NOT_GRADEABLE is the honest reading of that.
    detection.outcome = detection.machine_outcome or DetectionOutcome.NOT_GRADEABLE
    detection.confidence = detection.machine_confidence or 0.0
    detection.corrected_by_id = None
    detection.corrected_at = None
    db.flush()
    return detection


def _newest_other_confirmed(
    db: Session,
    school_id: uuid.UUID,
    *,
    exclude_scan_id: uuid.UUID,
    person_id: uuid.UUID,
    exercise_id: uuid.UUID,
    sheet_id: uuid.UUID | None,
) -> tuple[Detection, Scan, ScanPage] | None:
    """The reading a freed item falls back to when a pile is reopened.

    Ordered by ``Scan.confirmed_at``, not by upload time: what matters is which
    pile the teacher most recently signed off, not which arrived last.

    Takes a ``person_id`` because that is what a freed ``Attempt`` carries
    since 0028, and joins out to ``student`` to reach the page: a scan page is
    a fact about one year's paper and keeps its ``student_id``. The join is
    the translation, and it is exact — a page can only belong to a student row
    of the year the sheet was printed for.
    """
    sheet_clause = Scan.sheet_id.is_(None) if sheet_id is None else Scan.sheet_id == sheet_id
    row = db.execute(
        select(Detection, Scan, ScanPage)
        .join(ScanPage, ScanPage.id == Detection.scan_page_id)
        .join(Scan, Scan.id == ScanPage.scan_id)
        .where(Scan.school_id == school_id)
        .where(Scan.id != exclude_scan_id)
        .where(Scan.status == ScanStatus.CONFIRMED)
        .where(sheet_clause)
        .join(Student, Student.id == ScanPage.student_id)
        .where(Student.person_id == person_id)
        .where(ScanPage.discarded_at.is_(None))
        .where(ScanPage.wrong_class.is_(False))
        .where(Detection.exercise_id == exercise_id)
        .order_by(Scan.confirmed_at.desc().nullslast())
        .limit(1)
    ).first()
    return None if row is None else (row[0], row[1], row[2])


def unvalidate_scan(
    db: Session,
    scope: Scope,
    scan_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> ScanUnvalidateResponse:
    """Reopen a confirmed pile: withdraw exactly what it wrote, then put back
    whatever confirmed evidence still stands.

    This works without a history table because two things are already true.
    ``grade_item`` is a pure function of an answer key and a reading, and a
    confirmation never deletes a ``Detection`` — so every grade this pile wrote
    can be recomputed, and every grade it *superseded* can be recomputed from
    whichever older pile is now the newest one still signed off for that
    student and exercise. Mastery needs no special handling at all: it is a
    pure recompute over attempts, so correcting the attempts corrects it.

    An item with no older confirmed reading goes back to having no attempt —
    which is not a zero. Nobody has asserted anything about that item any more,
    and that is the honest record (D5).
    """
    at = now or datetime.now(UTC)
    school_id = scope.school_id
    scan = get_scan(db, scope, scan_id)
    if scan.status is not ScanStatus.CONFIRMED:
        raise errors.conflict(
            "this pile is not confirmed, so there is nothing to reopen",
            code="scan_not_confirmed",
            scan_id=str(scan_id),
        )

    written = list(
        db.execute(
            select(Attempt)
            .where(Attempt.confirmed_scan_id == scan_id)
            .where(Attempt.school_id == school_id)
        ).scalars()
    )
    freed: set[tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]] = set()
    people: set[uuid.UUID] = set()
    for attempt in written:
        freed.add((attempt.person_id, attempt.exercise_id, attempt.sheet_id))
        people.add(attempt.person_id)
        db.delete(attempt)
    # Flushed before re-inserting: the unique key on
    # (student, exercise, sheet) allows exactly one live row per triple, so the
    # delete has to land before a replacement is added for the same triple.
    db.flush()

    rederived = 0
    for person_id, exercise_id, sheet_id in sorted(freed, key=lambda t: (str(t[0]), str(t[1]))):
        found = _newest_other_confirmed(
            db,
            school_id,
            exclude_scan_id=scan_id,
            person_id=person_id,
            exercise_id=exercise_id,
            sheet_id=sheet_id,
        )
        if found is None:
            continue
        detection, older_scan, page = found
        exercise = db.execute(
            select(Exercise)
            .where(Exercise.id == exercise_id)
            .where(Exercise.school_id == school_id)
        ).scalar_one_or_none()
        if exercise is None:
            continue
        sheet = db.get(Sheet, sheet_id) if sheet_id else None
        graded = grade_item(
            _answer_key(exercise, detection.sheet_item, sheet), _detected_answer(detection)
        )
        if not graded.gradeable:
            continue
        db.add(
            Attempt(
                id=uuid.uuid4(),
                school_id=school_id,
                person_id=person_id,
                exercise_id=exercise_id,
                sheet_id=sheet_id,
                sheet_instance_id=page.sheet_instance_id,
                detection_id=detection.id,
                correct=graded.correct,
                score=graded.score,
                difficulty=exercise.difficulty,
                answered_at=_answered_at(older_scan, at),
                confirmed_scan_id=older_scan.id,
            )
        )
        rederived += 1
        people.add(person_id)

    scan.status = ScanStatus.NEEDS_REVIEW
    scan.reopened_at = at
    db.flush()

    competencies_updated = recompute_for_people(db, school_id, sorted(people), now=at)

    sheet_row = db.get(Sheet, scan.sheet_id) if scan.sheet_id else None
    event_service.record(
        db,
        school_id=school_id,
        kind=EventKind.SCAN_REOPENED,
        subject_type=EventSubject.SCAN,
        subject_id=scan.id,
        summary=(sheet_row.title if sheet_row else scan.original_filename or ""),
        actor_id=scope.teacher_id,
        class_id=sheet_row.class_id if sheet_row else None,
        subject_area_id=sheet_row.subject_id if sheet_row else None,
        occurred_at=at,
        detail={
            "attempts_removed": len(written),
            "attempts_rederived": rederived,
            "students": len(people),
        },
    )
    return ScanUnvalidateResponse(
        attempts_removed=len(written),
        attempts_rederived=rederived,
        students_affected=len(people),
        competencies_updated=competencies_updated,
    )


def _resolve_policy(sheet_item: SheetItem | None, sheet: Sheet | None) -> tuple[float, float]:
    """The barème that governs one item: its own, else the sheet's.

    NULL on a sheet item means "use the sheet's default", the same convention
    ``answer_box_lines`` uses — which is why each column is tested with ``is
    not None`` rather than for truth. A deliberate 0 is a real override (a
    bonus item worth nothing, or an item that costs nothing to get wrong), and
    reading it as absent would silently hand the item the sheet's value back.

    The fallback when there is no sheet at all is the 1.0/0.0 this pipeline
    graded with before a barème existed. It is reachable: a scan may be
    uploaded before anyone links it to the sheet it was printed from.
    """
    points_correct = sheet.default_points_correct if sheet is not None else 1.0
    penalty = sheet.default_points_penalty if sheet is not None else 0.0
    if sheet_item is not None:
        if sheet_item.points_correct is not None:
            points_correct = sheet_item.points_correct
        if sheet_item.points_penalty is not None:
            penalty = sheet_item.points_penalty
    return (points_correct, penalty)


def _answer_key(
    exercise: Exercise, sheet_item: SheetItem | None, sheet: Sheet | None
) -> AnswerKey:
    """What the answer is, and what it is worth.

    The barème resolves HERE, at grading time, from the rows as they stand —
    deliberately not frozen at print time the way an answer box's rectangle is.
    A box's rectangle is a physical fact about a page the browser laid out, and
    recomputing it would crop the wrong pixels from a real photograph. A barème
    touches no coordinate: it is arithmetic applied after every physical fact
    is already fixed. And the correctness key beside it has always resolved
    live — a teacher who fixes a typo'd answer after printing grades against
    the fix. Freezing what an answer is WORTH while leaving what it IS live
    would split one question down the middle for no reason.
    """
    points_correct, penalty = _resolve_policy(sheet_item, sheet)
    return AnswerKey(
        type=exercise.type,
        answer_index=exercise.answer_index,
        answer_bool=exercise.answer_bool,
        option_count=exercise.option_count,
        points_correct=points_correct,
        penalty=penalty,
    )


def _detected_answer(detection: Detection) -> DetectedAnswer:
    index = detection.detected_index
    if index is None and detection.detected_bool is not None:
        index = 0 if detection.detected_bool else 1
    return DetectedAnswer(
        outcome=detection.outcome,
        index=index,
        confidence=detection.confidence,
        transcription=detection.transcription,
        verdict_correct=detection.verdict_correct,
    )


def _answered_at(scan: Scan, now: datetime) -> datetime:
    created = scan.created_at
    if created is None:  # pragma: no cover - NOT NULL
        return now
    return created if created.tzinfo is not None else created.replace(tzinfo=UTC)


def confirm_scan(
    db: Session,
    scope: Scope,
    scan_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> ScanConfirmResponse:
    """Turn confirmed detections into attempts, then recompute mastery.

    Re-confirming a pile **supersedes** what the previous confirmation wrote for
    the same student and exercise on the same sheet. Mastery is a weighted mean
    over attempts, so inserting a second row for a re-scanned copy would not
    change the score much but would silently double that lesson's weight against
    every other one. Correcting a scan and scanning it again must fix the
    record, not accumulate.
    """
    at = now or datetime.now(UTC)
    school_id = scope.school_id

    # Serialise one pile's confirmation against itself, BEFORE the status is
    # read (T6).
    #
    # The status is read on the next line and written about 150 lines later,
    # and everything between — settling abandoned grading jobs, resolving the
    # bareme per item, writing every Attempt — is not instantaneous. Two
    # teachers on a co-taught class, or one teacher double-tapping on a slow
    # connection, both passed the guard and both wrote. Nothing downstream
    # objected, because `confirm_scan` supersedes BY DESIGN — a re-scan is
    # meant to overwrite — so no unique constraint stands behind the guard.
    # Measured, not assumed: without this line both confirmations succeed and
    # the pupil is graded twice.
    #
    # A bare row lock rather than a re-read through `get_scan`, so the second
    # caller blocks here and then sees CONFIRMED on the read below rather than
    # racing it. Held until the transaction commits, which is the whole
    # handler. SQLite ignores FOR UPDATE, which is why the test that proves
    # this lives in `test_schema_constraints.py` against real Postgres: the
    # default engine is one connection on a StaticPool and cannot race.
    db.execute(select(Scan.id).where(Scan.id == scan_id).with_for_update())

    scan = get_scan(db, scope, scan_id)
    if scan.status is ScanStatus.CONFIRMED:
        raise errors.conflict(
            "scan is already confirmed", code="scan_already_confirmed", scan_id=str(scan_id)
        )
    if scan.status is ScanStatus.FAILED:
        raise errors.conflict("scan failed processing and cannot be confirmed")

    # A pile with no sheet behind it, said before anything else, because it is
    # the one refusal here the teacher cannot act on. There is no route that
    # attaches a sheet to an existing scan, and `assignable_students` answers
    # nobody without one — so the "assign every page first" message below would
    # be asking for something the product cannot do. Since B3 this arrives more
    # often: a UID is only resolved within the school year the sheet's class
    # sits in, so a sheetless pile now identifies nobody rather than guessing
    # across years, and its pages stay unassigned by design.
    if scan.sheet_id is None:
        raise errors.conflict(
            "this pile is not linked to the sheet it was printed from, "
            "so there is nothing to grade",
            code="scan_no_sheet",
            scan_id=str(scan_id),
        )

    # A discarded page (a cover sheet, a lens-cap frame, a re-shot copy) is not
    # part of the pile, and a page from another class belongs to another sheet.
    # Neither has to be assigned for the other 27 copies to be gradeable.
    pending = [p for p in scan.pages if not p.discarded and not p.wrong_class]
    unassigned = [str(p.id) for p in pending if p.student_id is None]
    if unassigned:
        raise errors.conflict(
            "every scanned page must be assigned to a student, or discarded, before confirming",
            code="scan_pages_unassigned",
            page_ids=unassigned,
        )

    # A written answer still with the grader is a promise. While a grading job
    # is queued or running the promise is being kept, and confirming now would
    # lock the pile with that child's answer unrecorded — so wait. When no job
    # is coming (a dead provider, a job that never chained), the promise is
    # broken honestly: the rows become NOT_GRADEABLE and are counted as
    # skipped, and the teacher can still confirm.
    from alppy.services.open_answer_grading import (
        grading_in_progress,
        pending_detections,
        settle_abandoned,
    )

    if pending_detections(db, scan.id):
        if grading_in_progress(db, scan.id):
            raise errors.conflict(
                "written answers are still being read; confirm once the reading is done",
                code="scan_open_grading_pending",
                scan_id=str(scan_id),
            )
        settle_abandoned(db, scan.id)

    # A reading the machine was unsure of is not a grade until a person has
    # looked at it (D-scan-low-confidence, Q4 of audit 06).
    #
    # `LOW_CONFIDENCE` used to be counted for a report and nothing else, so a
    # teacher who confirmed a pile without opening it turned every unsure
    # reading into a mark — silently, and on the one axis where the product
    # promises not to guess about a child. Every other outcome is either a
    # reading the detector stands behind, a teacher's own word (`CORRECTED`),
    # or an honest refusal that scores nothing (`MULTIPLE`, `NOT_GRADEABLE`,
    # `BLANK`). This one is the machine saying it does not know.
    #
    # Reviewing does not mean disagreeing: `correct_detection` stamps
    # `CORRECTED` whatever value is sent, so a teacher who agrees affirms by
    # re-sending the same reading. That is what keeps the gate from being a
    # wall in front of a thirty-copy pile — and it is why the message names
    # the rows rather than the count.
    unreviewed = [
        str(detection.id)
        for page in pending
        for detection in page.detections
        if detection.outcome is DetectionOutcome.LOW_CONFIDENCE
    ]
    if unreviewed:
        raise errors.conflict(
            "some readings are too unsure to grade; open each one and confirm "
            "or correct it before confirming the pile",
            code="scan_low_confidence_unreviewed",
            detection_ids=unreviewed,
        )

    answered_at = _answered_at(scan, at)
    attempts_created = 0
    attempts_superseded = 0
    items_skipped = 0
    people: set[uuid.UUID] = set()
    confirmed_students: set[uuid.UUID] = set()

    # Fetched once, before the loop: it carries the sheet's default barème, so
    # every item on every page resolves against the same row. It is also what
    # names the sheet in the event recorded at the end.
    sheet = db.get(Sheet, scan.sheet_id) if scan.sheet_id else None

    for page in pending:
        student_id = page.student_id
        if student_id is None:  # pragma: no cover - guarded above
            continue
        student = db.execute(
            select(Student)
            .where(Student.id == student_id)
            .where(Student.school_id == school_id)
        ).scalar_one_or_none()
        if student is None:
            raise errors.not_found("student", id=str(student_id))

        for detection in page.detections:
            exercise = _exercise_for_detection(db, school_id, detection)
            if exercise is None:
                # No item behind this reading — a position on the default grid
                # that this copy never printed. Nothing to grade against, and
                # nothing the teacher needs to know about either.
                continue
            graded = grade_item(
                _answer_key(exercise, detection.sheet_item, sheet), _detected_answer(detection)
            )
            if not graded.gradeable:
                # Two bubbles filled, or free text. Deliberately not a zero —
                # but it IS an item that went in on paper and comes out of the
                # pipeline with no record, so it is counted and reported rather
                # than dropped in silence.
                items_skipped += 1
                continue

            existing = db.execute(
                select(Attempt)
                .where(Attempt.person_id == student.person_id)
                .where(Attempt.exercise_id == exercise.id)
                .where(Attempt.sheet_id == scan.sheet_id)
                .where(Attempt.school_id == school_id)
            ).scalar_one_or_none()
            if existing is not None:
                existing.sheet_instance_id = page.sheet_instance_id
                existing.detection_id = detection.id
                existing.correct = graded.correct
                existing.score = graded.score
                existing.difficulty = exercise.difficulty
                existing.answered_at = answered_at
                # This pile now owns the row, whoever wrote it before. Reopening
                # reads this to know what to withdraw.
                existing.confirmed_scan_id = scan.id
                attempts_superseded += 1
            else:
                db.add(
                    Attempt(
                        id=uuid.uuid4(),
                        school_id=school_id,
                        person_id=student.person_id,
                        exercise_id=exercise.id,
                        sheet_id=scan.sheet_id,
                        sheet_instance_id=page.sheet_instance_id,
                        detection_id=detection.id,
                        correct=graded.correct,
                        score=graded.score,
                        difficulty=exercise.difficulty,
                        answered_at=answered_at,
                        confirmed_scan_id=scan.id,
                    )
                )
                attempts_created += 1
            people.add(student.person_id)
            # The year-bound row too: `points_possible` is frozen onto the COPY,
            # and a copy belongs to one year's `student` (audit 03, B18).
            confirmed_students.add(student.id)

    if not people and any(p.detections for p in pending):
        # Marks were read and not one of them could be matched to a question:
        # the pile is not linked to the sheet it was printed from. Confirming
        # would flip the scan to CONFIRMED, write nothing, and tell the teacher
        # their marking was saved.
        raise errors.conflict(
            "none of these pages could be matched to the sheet they were printed from, "
            "so there is nothing to grade",
            code="scan_matches_no_sheet",
            scan_id=str(scan_id),
            sheet_id=str(scan.sheet_id) if scan.sheet_id else None,
        )

    # `scan.error` is left as it is. Confirming does not undo whatever the
    # processing stage recorded — a batch that came back with a page it could
    # not read stays a batch that came back with a page it could not read.
    scan.status = ScanStatus.CONFIRMED
    # The history, not a status. `confirmed_at` orders this pile against any
    # other still-confirmed one when a reopen has to choose a fallback reading;
    # the count is what makes a re-signed pile read as "revised" (D48).
    scan.confirmed_at = at
    scan.confirmation_count += 1
    db.flush()

    _freeze_points_possible(db, sheet, confirmed_students)

    competencies_updated = recompute_for_people(db, school_id, sorted(people), now=at)

    # The moment the agenda most needs and the schema never recorded: a status
    # enum flipped and `updated_at` moved, and `updated_at` is overwritten by
    # the next edit to the row, whatever it is. `occurred_at` is `at`, the same
    # stamp the attempts carry, so a pile corrected on Sunday for Friday's
    # lesson lands on the day the class actually sat it.
    event_service.record(
        db,
        school_id=school_id,
        kind=EventKind.SCAN_CONFIRMED,
        subject_type=EventSubject.SCAN,
        subject_id=scan.id,
        summary=(sheet.title if sheet else scan.original_filename or ""),
        actor_id=scope.teacher_id,
        class_id=sheet.class_id if sheet else None,
        subject_area_id=sheet.subject_id if sheet else None,
        occurred_at=at,
        detail={
            "attempts": attempts_created,
            "superseded": attempts_superseded,
            "students": len(people),
            "competencies": competencies_updated,
        },
    )

    return ScanConfirmResponse(
        attempts_created=attempts_created,
        attempts_superseded=attempts_superseded,
        items_skipped=items_skipped,
        students_affected=len(people),
        competencies_updated=competencies_updated,
    )


def _freeze_points_possible(
    db: Session, sheet: Sheet | None, student_ids: set[uuid.UUID]
) -> None:
    """Record what each confirmed copy was worth, once (audit 03, B18).

    Confirmation is the moment the number becomes a promise: the paper goes
    back to the child with a mark on it. Until this, `points_possible` was
    recomputed live on every read, so editing the barème afterwards rewrote the
    denominator of every paper already handed back.

    Written **only for the copies in this pile**, and only for those that were
    actually confirmed — a classmate whose copy is still in the drawer keeps a
    live total, because theirs has not been promised to anyone yet.

    Overwritten on re-confirmation rather than left alone. Re-confirming
    supersedes what the previous run wrote, attempts included; a frozen
    denominator that survived a re-confirmation would be the one number in the
    fraction still describing the older run.
    """
    if sheet is None or not student_ids:
        return
    from alppy.services.sheet_service import _possible_by_student

    possible = _possible_by_student(sheet, live=True)
    for instance in sheet.instances:
        if instance.student_id in student_ids:
            instance.points_possible = possible.get(instance.student_id)
    db.flush()


def _get_page(
    db: Session, school_id: uuid.UUID, scan_id: uuid.UUID, page_id: uuid.UUID
) -> ScanPage:
    page = db.execute(
        select(ScanPage)
        .where(ScanPage.id == page_id)
        .where(ScanPage.scan_id == scan_id)
        .where(ScanPage.school_id == school_id)
    ).scalar_one_or_none()
    if page is None:
        raise errors.not_found("scan page", id=str(page_id))
    return page


def assignable_students(
    db: Session, scope: Scope, scan_id: uuid.UUID, *, on: date | None = None
) -> list[Student]:
    """Who a page of this scan could belong to.

    The class of the sheet the pile was printed from, and nobody else. Offering
    the whole school invites a mis-assignment that files one child's answers
    under another's name — the exact failure the checksummed UID grid exists to
    prevent, reintroduced by hand at the last step.
    """
    school_id = scope.school_id
    scan = get_scan(db, scope, scan_id)
    if scan.sheet_id is None:
        # `Scan.sheet_id` is nullable and detaches on ondelete="SET NULL":
        # deleting the sheet leaves the pile with no class to scope to. There
        # is no safe answer here, and "everyone in the school" is the least
        # safe one — offer nobody rather than the whole roster.
        return []
    sheet = db.execute(
        select(Sheet).where(Sheet.id == scan.sheet_id).where(Sheet.school_id == school_id)
    ).scalar_one_or_none()
    if sheet is None:
        return []
    # The roster as it stood when the sheet was MADE, not today's. This is the
    # list a page may be assigned to, and a pile scanned in March may hold a
    # copy sat in October by a pupil who has since changed group — offering
    # today's roster would leave that copy unassignable and its marks
    # unrecorded, which is the one outcome the scan path must never produce.
    # `on` overrides that when the teacher knows better — a sheet made in
    # September and sat in November wants November's group.
    on = on or (sheet.created_at or datetime.now(UTC)).date()
    stmt = (
        select(Student)
        .where(Student.school_id == school_id)
        .where(Student.id.in_(enrolled_student_ids(sheet.class_id, on=on)))
    )
    return list(db.execute(stmt.order_by(Student.uid.asc())).scalars())


def assign_page_student(
    db: Session,
    scope: Scope,
    scan_id: uuid.UUID,
    page_id: uuid.UUID,
    student_id: uuid.UUID,
    *,
    storage: Storage | None = None,
) -> tuple[ScanPage, tuple[int, ...]]:
    """Manual fallback when the printed UID grid could not be read.

    Assigning does not only name the student: until the copy was known the page
    was read against the full default grid and every reading was left unpaired,
    because "item 3" means nothing without a copy. Naming the student settles
    that, so the page is read again against their own paper — otherwise the
    fallback hands back a screen full of detections that grade nothing.

    Which is exactly why it is a **write**, and why the confirmed guard below
    is not boilerplate. Its three siblings — ``correct_detection``,
    ``revert_detection`` and ``set_page_discarded`` — have refused a confirmed
    pile since the beginning; this one did not, and it is the most destructive
    of the four. It re-reads the page, so on a confirmed pile it rewrites the
    very detections the attempts were graded from, leaving a grade that no
    longer matches its own evidence and no record that anything moved.
    """
    school_id = scope.school_id
    page = _get_page(db, school_id, scan_id, page_id)
    # Before anything is resolved or re-read: a confirmed pile is read-only
    # until it is reopened (audit 03, B6).
    _refuse_when_confirmed(get_scan(db, scope, scan_id))
    candidates = {s.id: s for s in assignable_students(db, scope, scan_id)}
    student = candidates.get(student_id)
    if student is None:
        raise errors.unprocessable(
            "that student is not in the class this sheet was printed for",
            student_id=str(student_id),
        )

    dropped: tuple[int, ...] = ()
    page.student_id = student.id
    # Assigning by hand settles the question the UID could not: this page is
    # this student's, and it is part of this sheet.
    page.wrong_class = False
    page.discarded_at = None
    page.discarded_by_id = None
    if page.sheet_instance_id is None:
        scan = get_scan(db, scope, scan_id)
        if scan.sheet_id is not None:
            from alppy.models import SheetInstance

            instance = db.execute(
                select(SheetInstance)
                .where(SheetInstance.sheet_id == scan.sheet_id)
                .where(SheetInstance.student_id == student.id)
                .where(SheetInstance.school_id == school_id)
            ).scalar_one_or_none()
            if instance is not None:
                page.sheet_instance_id = instance.id
    db.flush()

    if storage is not None:
        from alppy.services.scan_processing import _flag_duplicate_slots, redetect_page

        outcome = redetect_page(db, storage, page=page, student=student)
        db.flush()
        # Assigning is what actually produces a duplicate slot: the re-shot page
        # the detector left unpaired gets slot 0 here, while the blurred
        # original still holds it (B5). Flag, never block — discarding the bad
        # photo is one click.
        _flag_duplicate_slots(db, get_scan(db, scope, scan_id))
        db.flush()
        # Corrections the new reading had nowhere to put. Carried out to the
        # caller so the review screen can name them: a teacher who fixed a
        # bubble by hand and then re-assigned the page must not have to
        # discover the loss by re-reading every answer (audit 03, B6).
        dropped = outcome.corrections_dropped
    return page, dropped


def queue_grading_if_pending(db: Session, scope: Scope, scan_id: uuid.UUID) -> Job | None:
    """A grading job for this scan's pending written answers, unless one is
    already on its way. Called after a page is assigned by hand: re-reading
    the page may have cut boxes that no job was ever chained for, and a
    pending row nobody is coming for is a promise nobody keeps."""
    from alppy.services.open_answer_grading import (
        grading_in_progress,
        pending_detections,
        queue_open_grading,
    )

    scan = get_scan(db, scope, scan_id)
    if not pending_detections(db, scan.id) or grading_in_progress(db, scan.id):
        return None
    return queue_open_grading(db, school_id=scope.school_id, scan_id=scan.id)


def set_page_discarded(
    db: Session,
    scope: Scope,
    scan_id: uuid.UUID,
    page_id: uuid.UUID,
    *,
    discarded: bool,
) -> ScanPage:
    """Take a page out of the pile, or put it back.

    A cover sheet, a lens-cap frame or a page re-shot later is not anybody's
    copy, and there used to be no way to say so: confirmation refused while any
    page was unassigned, and the only route forward was to attribute the junk
    page to a real child. One bad photo held twenty-seven good copies hostage.

    The row is kept — the page was in the pile and that is part of the record.
    """
    school_id = scope.school_id
    page = _get_page(db, school_id, scan_id, page_id)
    scan = get_scan(db, scope, scan_id)
    if scan.status is ScanStatus.CONFIRMED:
        raise errors.conflict(
            "scan is already confirmed", code="scan_already_confirmed", scan_id=str(scan_id)
        )
    if discarded:
        page.discarded_at = datetime.now(UTC)
        page.discarded_by_id = scope.teacher_id
        page.student_id = None
        page.sheet_instance_id = None
    else:
        # Putting a page back clears the actor with the timestamp: the record
        # is "this page is in the pile", and a stale name beside it would read
        # as somebody having discarded it and nobody having undone that.
        page.discarded_at = None
        page.discarded_by_id = None
    db.flush()
    return page


@dataclass(frozen=True, slots=True)
class ItemConfidence:
    """How one printed item was read across a whole class's copies."""

    sheet_item_id: uuid.UUID | None
    exercise_id: uuid.UUID | None
    number: int | None
    statement: str | None
    copies_read: int
    low_confidence: int
    ambiguous: int
    corrected: int


def confidence_by_item(db: Session, scope: Scope, sheet_id: uuid.UUID) -> list[ItemConfidence]:
    """Per printed item: how many copies came back unsure, ambiguous, or fixed.

    The point of aggregating by ITEM rather than by student: one child misreading
    question 7 is a child; twenty of them is a smudged photocopy or a fold across
    the answer grid. This is the view that tells those two apart, and it names a
    piece of paper rather than a student.

    One reading per (student, item) — the newest non-discarded page — so a copy
    photographed twice is not counted twice. That is the same rule confirmation
    already applies to attempts, applied here to a report.

    A `corrected` item is not also counted as low-confidence: the teacher has
    already dealt with it. A high corrected count is itself the signal.
    """
    from alppy.services.sheet_service import get_sheet_for_read

    # REPORT: per-item confidence over a pile already scanned. It names a
    # piece of paper, never a child, so the teacher who printed and marked
    # it keeps it after the group moves on (D88).
    sheet = get_sheet_for_read(db, scope, sheet_id)
    school_id = scope.school_id

    rows = db.execute(
        select(
            Detection,
            ScanPage.student_id,
            ScanPage.page_in_copy,
            ScanPage.created_at,
            Scan.created_at,
        )
        .join(ScanPage, ScanPage.id == Detection.scan_page_id)
        .join(Scan, Scan.id == ScanPage.scan_id)
        .where(Scan.sheet_id == sheet.id)
        .where(Scan.school_id == school_id)
        .where(ScanPage.discarded_at.is_(None))
        .where(ScanPage.wrong_class.is_(False))
    ).all()

    # Deduplicated per QUESTION, not per `item_index`. `item_index` is
    # page-local and restarts at 0 on every physical page (I6), so keying on it
    # makes page two's first item collide with page one's and silently drop a
    # question from the report. The exercise is what identifies a question
    # across pages; only a detection with no exercise at all falls back to a
    # position, and then the folio has to be part of the key too.
    newest: dict[tuple[Any, ...], tuple[Detection, Any, Any]] = {}
    for detection, student_id, page_in_copy, page_created, scan_created in rows:
        if student_id is None:
            continue
        key: tuple[Any, ...] = (
            (student_id, detection.exercise_id)
            if detection.exercise_id is not None
            else (student_id, page_in_copy, detection.item_index)
        )
        current = newest.get(key)
        if current is None or (page_created, scan_created) > (current[1], current[2]):
            newest[key] = (detection, page_created, scan_created)

    counts: dict[tuple[uuid.UUID | None, uuid.UUID | None], dict[str, int]] = {}
    labels: dict[tuple[uuid.UUID | None, uuid.UUID | None], tuple[int | None, str | None]] = {}
    for detection, _page_at, _scan_at in newest.values():
        key = (detection.sheet_item_id, detection.exercise_id)
        bucket = counts.setdefault(
            key, {"copies_read": 0, "low_confidence": 0, "ambiguous": 0, "corrected": 0}
        )
        bucket["copies_read"] += 1
        if detection.outcome is DetectionOutcome.CORRECTED:
            bucket["corrected"] += 1
        elif detection.outcome is DetectionOutcome.LOW_CONFIDENCE:
            bucket["low_confidence"] += 1
        elif detection.outcome in (DetectionOutcome.MULTIPLE, DetectionOutcome.NOT_GRADEABLE):
            bucket["ambiguous"] += 1
        labels[key] = (
            detection.printed_number,
            detection.exercise.statement if detection.exercise is not None else None,
        )

    return sorted(
        (
            ItemConfidence(
                sheet_item_id=key[0],
                exercise_id=key[1],
                number=labels[key][0],
                statement=labels[key][1],
                **bucket,
            )
            for key, bucket in counts.items()
        ),
        key=lambda item: (item.number is None, item.number or 0),
    )
