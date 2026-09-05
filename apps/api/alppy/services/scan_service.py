"""Scans: upload, teacher correction, confirmation.

Three rules shape this module.

1. **The request never blocks on the pipeline.** ``create_scan`` stores the
   bytes, writes a ``Scan`` and a queued ``Job``, and returns. Registration,
   UID reading and bubble detection happen in the worker.
2. **The teacher is the authority.** A correction is recorded as
   ``CORRECTED`` with who and when, never as a silent overwrite of the
   machine's reading — the original detection stays in the row for audit.
3. **Nothing is guessed.** An item the grader cannot grade (free text, two
   bubbles filled, no answer key) produces no ``Attempt`` at all rather than a
   zero, because a zero is a claim about the student and "unreadable" is not.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.api.deps import UploadPayload
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
    ExerciseType,
    JobKind,
    JobStatus,
    ScanStatus,
)
from alppy.scan.grading import AnswerKey, DetectedAnswer, grade_item
from alppy.schemas import DetectionCorrection, ScanConfirmResponse
from alppy.services.mastery_service import recompute_for_students
from alppy.storage import Storage, storage_key

CONFIRMABLE_STATUSES = (ScanStatus.UPLOADED, ScanStatus.PROCESSING, ScanStatus.NEEDS_REVIEW)


def get_scan(db: Session, school_id: uuid.UUID, scan_id: uuid.UUID) -> Scan:
    scan = db.execute(
        select(Scan).where(Scan.id == scan_id).where(Scan.school_id == school_id)
    ).scalar_one_or_none()
    if scan is None:
        raise errors.not_found("scan", id=str(scan_id))
    return scan


def list_scans(
    db: Session, school_id: uuid.UUID, *, sheet_id: uuid.UUID | None = None
) -> list[Scan]:
    stmt = select(Scan).where(Scan.school_id == school_id)
    if sheet_id is not None:
        stmt = stmt.where(Scan.sheet_id == sheet_id)
    return list(db.execute(stmt.order_by(Scan.created_at.desc())).scalars())


def create_scan(
    db: Session,
    school_id: uuid.UUID,
    teacher_id: uuid.UUID,
    storage: Storage,
    payload: UploadPayload,
    *,
    sheet_id: uuid.UUID | None = None,
) -> tuple[Scan, Job]:
    if sheet_id is not None:
        sheet = db.execute(
            select(Sheet).where(Sheet.id == sheet_id).where(Sheet.school_id == school_id)
        ).scalar_one_or_none()
        if sheet is None:
            raise errors.not_found("sheet", id=str(sheet_id))

    scan_id = uuid.uuid4()
    key = storage_key("scans", school_id, scan_id, payload.filename)
    storage.put_bytes(key, payload.data, payload.content_type)

    scan = Scan(
        id=scan_id,
        school_id=school_id,
        sheet_id=sheet_id,
        uploaded_by_id=teacher_id,
        original_filename=payload.filename,
        storage_key=key,
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
    if detection.sheet_item_id is None:
        return None
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
    """Record a teacher override. Always allowed, always attributed."""
    detection = get_detection(db, school_id, scan_id, detection_id)
    exercise = _exercise_for_detection(db, school_id, detection)

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
        outcome=detection.outcome, index=index, confidence=detection.confidence
    )


def _answered_at(scan: Scan, now: datetime) -> datetime:
    created = scan.created_at
    if created is None:  # pragma: no cover - NOT NULL
        return now
    return created if created.tzinfo is not None else created.replace(tzinfo=UTC)


def confirm_scan(
    db: Session,
    school_id: uuid.UUID,
    scan_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> ScanConfirmResponse:
    """Turn confirmed detections into attempts, then recompute mastery."""
    at = now or datetime.now(UTC)
    scan = get_scan(db, school_id, scan_id)
    if scan.status is ScanStatus.CONFIRMED:
        raise errors.conflict("scan is already confirmed", scan_id=str(scan_id))
    if scan.status is ScanStatus.FAILED:
        raise errors.conflict("scan failed processing and cannot be confirmed")

    unassigned = [str(p.id) for p in scan.pages if p.student_id is None]
    if unassigned:
        raise errors.conflict(
            "every scanned page must be assigned to a student before confirming",
            page_ids=unassigned,
        )

    answered_at = _answered_at(scan, at)
    attempts_created = 0
    students: set[uuid.UUID] = set()

    for page in scan.pages:
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
                # No sheet item behind this reading: nothing to grade against.
                continue
            graded = grade_item(_answer_key(exercise), _detected_answer(detection))
            if not graded.gradeable:
                continue
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

    scan.status = ScanStatus.CONFIRMED
    scan.error = None
    db.flush()

    competencies_updated = recompute_for_students(db, school_id, sorted(students), now=at)

    return ScanConfirmResponse(
        attempts_created=attempts_created,
        students_affected=len(students),
        competencies_updated=competencies_updated,
    )


def assign_page_student(
    db: Session,
    school_id: uuid.UUID,
    scan_id: uuid.UUID,
    page_id: uuid.UUID,
    student_id: uuid.UUID,
) -> ScanPage:
    """Manual fallback when the printed UID grid could not be read."""
    page = db.execute(
        select(ScanPage)
        .where(ScanPage.id == page_id)
        .where(ScanPage.scan_id == scan_id)
        .where(ScanPage.school_id == school_id)
    ).scalar_one_or_none()
    if page is None:
        raise errors.not_found("scan page", id=str(page_id))
    student = db.execute(
        select(Student).where(Student.id == student_id).where(Student.school_id == school_id)
    ).scalar_one_or_none()
    if student is None:
        raise errors.not_found("student", id=str(student_id))

    page.student_id = student.id
    if page.sheet_instance_id is None:
        scan = get_scan(db, school_id, scan_id)
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
    return page
