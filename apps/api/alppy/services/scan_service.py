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
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.api.deps import Scope, UploadPayload
from alppy.models import (
    Attempt,
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
from alppy.schemas import DetectionCorrection, ScanConfirmResponse
from alppy.services import event_service
from alppy.services.class_service import owned_class_ids
from alppy.services.mastery_service import recompute_for_students
from alppy.storage import Storage, storage_key

CONFIRMABLE_STATUSES = (ScanStatus.UPLOADED, ScanStatus.PROCESSING, ScanStatus.NEEDS_REVIEW)


def _owned_scan(scope: Scope) -> Any:
    """A scan this teacher may read.

    Normally that means the pile was printed from a sheet of one of their own
    classes. But a scan is uploaded *before* its sheet is always known — a pile
    photographed with nothing behind it has ``sheet_id IS NULL`` and must stay
    visible to the person who uploaded it, or the "which sheet was this?" step
    becomes unreachable and the upload is orphaned. ``NULL IN (...)`` is never
    true, so that case needs saying out loud (decisions-log D23).
    """
    owned_sheets = select(Sheet.id).where(Sheet.class_id.in_(owned_class_ids(scope)))
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
    db: Session, scope: Scope, *, sheet_id: uuid.UUID | None = None
) -> list[Scan]:
    stmt = (
        select(Scan)
        .where(Scan.school_id == scope.school_id)
        .where(_owned_scan(scope))
    )
    if sheet_id is not None:
        stmt = stmt.where(Scan.sheet_id == sheet_id)
    return list(db.execute(stmt.order_by(Scan.created_at.desc())).scalars())


def create_scan(
    db: Session,
    school_id: uuid.UUID,
    teacher_id: uuid.UUID,
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

    sheet: Sheet | None = None
    if sheet_id is not None:
        sheet = db.execute(
            select(Sheet).where(Sheet.id == sheet_id).where(Sheet.school_id == school_id)
        ).scalar_one_or_none()
        if sheet is None:
            raise errors.not_found("sheet", id=str(sheet_id))

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


def list_detections(db: Session, school_id: uuid.UUID, scan_id: uuid.UUID) -> list[Detection]:
    return list(
        db.execute(
            select(Detection)
            .join(ScanPage, ScanPage.id == Detection.scan_page_id)
            .where(Detection.school_id == school_id)
            .where(ScanPage.scan_id == scan_id)
            .order_by(ScanPage.page_index.asc(), Detection.item_index.asc())
        ).scalars()
    )


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
    """Record a teacher override. Always allowed, always attributed.

    The machine's reading is *not* touched: ``machine_index``,
    ``machine_outcome`` and ``machine_confidence`` were written when the page
    was detected and stay as they were.
    """
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


def _answer_key(exercise: Exercise) -> AnswerKey:
    return AnswerKey(
        type=exercise.type,
        answer_index=exercise.answer_index,
        answer_bool=exercise.answer_bool,
        option_count=exercise.option_count,
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
    scan = get_scan(db, scope, scan_id)
    if scan.status is ScanStatus.CONFIRMED:
        raise errors.conflict(
            "scan is already confirmed", code="scan_already_confirmed", scan_id=str(scan_id)
        )
    if scan.status is ScanStatus.FAILED:
        raise errors.conflict("scan failed processing and cannot be confirmed")

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

    answered_at = _answered_at(scan, at)
    attempts_created = 0
    attempts_superseded = 0
    items_skipped = 0
    students: set[uuid.UUID] = set()

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
            graded = grade_item(_answer_key(exercise), _detected_answer(detection))
            if not graded.gradeable:
                # Two bubbles filled, or free text. Deliberately not a zero —
                # but it IS an item that went in on paper and comes out of the
                # pipeline with no record, so it is counted and reported rather
                # than dropped in silence.
                items_skipped += 1
                continue

            existing = db.execute(
                select(Attempt)
                .where(Attempt.student_id == student.id)
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
                attempts_superseded += 1
            else:
                db.add(
                    Attempt(
                        id=uuid.uuid4(),
                        school_id=school_id,
                        student_id=student.id,
                        exercise_id=exercise.id,
                        sheet_id=scan.sheet_id,
                        sheet_instance_id=page.sheet_instance_id,
                        detection_id=detection.id,
                        correct=graded.correct,
                        score=graded.score,
                        difficulty=exercise.difficulty,
                        answered_at=answered_at,
                    )
                )
                attempts_created += 1
            students.add(student.id)

    if not students and any(p.detections for p in pending):
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
    db.flush()

    competencies_updated = recompute_for_students(db, school_id, sorted(students), now=at)

    # The moment the agenda most needs and the schema never recorded: a status
    # enum flipped and `updated_at` moved, and `updated_at` is overwritten by
    # the next edit to the row, whatever it is. `occurred_at` is `at`, the same
    # stamp the attempts carry, so a pile corrected on Sunday for Friday's
    # lesson lands on the day the class actually sat it.
    sheet = db.get(Sheet, scan.sheet_id) if scan.sheet_id else None
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
            "students": len(students),
            "competencies": competencies_updated,
        },
    )

    return ScanConfirmResponse(
        attempts_created=attempts_created,
        attempts_superseded=attempts_superseded,
        items_skipped=items_skipped,
        students_affected=len(students),
        competencies_updated=competencies_updated,
    )


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
    db: Session, scope: Scope, scan_id: uuid.UUID
) -> list[Student]:
    """Who a page of this scan could belong to.

    The class of the sheet the pile was printed from, and nobody else. Offering
    the whole school invites a mis-assignment that files one child's answers
    under another's name — the exact failure the checksummed UID grid exists to
    prevent, reintroduced by hand at the last step.
    """
    school_id = scope.school_id
    scan = get_scan(db, scope, scan_id)
    stmt = select(Student).where(Student.school_id == school_id)
    if scan.sheet_id is not None:
        sheet = db.execute(
            select(Sheet).where(Sheet.id == scan.sheet_id).where(Sheet.school_id == school_id)
        ).scalar_one_or_none()
        if sheet is not None:
            stmt = stmt.where(Student.class_id == sheet.class_id)
    return list(db.execute(stmt.order_by(Student.uid.asc())).scalars())


def assign_page_student(
    db: Session,
    scope: Scope,
    scan_id: uuid.UUID,
    page_id: uuid.UUID,
    student_id: uuid.UUID,
    *,
    storage: Storage | None = None,
) -> ScanPage:
    """Manual fallback when the printed UID grid could not be read.

    Assigning does not only name the student: until the copy was known the page
    was read against the full default grid and every reading was left unpaired,
    because "item 3" means nothing without a copy. Naming the student settles
    that, so the page is read again against their own paper — otherwise the
    fallback hands back a screen full of detections that grade nothing.
    """
    school_id = scope.school_id
    page = _get_page(db, school_id, scan_id, page_id)
    candidates = {s.id: s for s in assignable_students(db, scope, scan_id)}
    student = candidates.get(student_id)
    if student is None:
        raise errors.unprocessable(
            "that student is not in the class this sheet was printed for",
            student_id=str(student_id),
        )

    page.student_id = student.id
    # Assigning by hand settles the question the UID could not: this page is
    # this student's, and it is part of this sheet.
    page.wrong_class = False
    page.discarded = False
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
        from alppy.services.scan_processing import redetect_page

        redetect_page(db, storage, page=page, student=student)
        db.flush()
    return page


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
    page.discarded = discarded
    if discarded:
        page.student_id = None
        page.sheet_instance_id = None
    db.flush()
    return page
