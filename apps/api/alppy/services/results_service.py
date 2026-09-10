"""One student's copy of one sheet, question by question.

The bottom of the tracking drill-down: Tracking → student → the sheet they sat →
what they answered, what was expected, and what it was worth. Everything here
already exists in rows elsewhere; this assembles it into the shape a teacher
reads while handing a paper back.

Computed, never stored — the same rule the other two reports follow, for the
same reason: a stored breakdown is one more thing to disagree with the attempt
the first time a detection is corrected.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.api.deps import Scope
from alppy.models import (
    Attempt,
    Detection,
    Exercise,
    Scan,
    ScanPage,
    Sheet,
    SheetItem,
    Student,
)
from alppy.models.enums import DetectionOutcome, ExerciseType
from alppy.services.enrollment import ever_shared_student_ids
from alppy.sheets.layout import OptionLetters, tf_letters


@dataclass(frozen=True, slots=True)
class StudentSheetItem:
    """One question, as this student answered it."""

    position: int
    number: int | None
    exercise_id: uuid.UUID
    statement: str
    exercise_type: ExerciseType
    ai_generated: bool
    options: list[str]
    #: What the student put, already turned into something readable: "B. 2/3",
    #: "Vrai", or the transcription of what they wrote.
    given: str | None
    given_index: int | None
    #: What the sheet expected. For a written item this is the teacher's
    #: expected answer, else the book's, else nothing — never a placeholder.
    expected: str | None
    expected_index: int | None
    outcome: DetectionOutcome | None
    confidence: float | None
    #: None when the item produced no attempt at all. NOT the same as wrong.
    correct: bool | None
    #: None when ungraded. Never rendered as a zero.
    points_earned: float | None
    points_possible: float
    crop_key: str | None


@dataclass(frozen=True, slots=True)
class StudentSheet:
    student: Student
    sheet: Sheet
    scan_id: uuid.UUID | None
    answered_at: datetime | None
    points_earned: float | None
    points_possible: float
    items: list[StudentSheetItem]


def _option_letters(exercise: Exercise, language: str) -> str:
    if exercise.type is ExerciseType.TRUE_FALSE:
        return tf_letters(language)
    return OptionLetters.MCQ.value


def _readable_choice(exercise: Exercise, index: int | None, language: str) -> str | None:
    """A bubble index as a teacher would say it: "B. 2/3", or "Vrai"."""
    if index is None:
        return None
    letters = _option_letters(exercise, language)
    letter = letters[index] if index < len(letters) else str(index + 1)
    if exercise.type is ExerciseType.TRUE_FALSE:
        return letter
    options = exercise.options or []
    return f"{letter}. {options[index]}" if index < len(options) else letter


def _expected_index(exercise: Exercise) -> int | None:
    if exercise.type is ExerciseType.TRUE_FALSE:
        return None if exercise.answer_bool is None else (0 if exercise.answer_bool else 1)
    return exercise.answer_index


def student_sheet_breakdown(
    db: Session,
    scope: Scope,
    student_id: uuid.UUID,
    sheet_id: uuid.UUID,
    *,
    as_of: datetime | None = None,
) -> StudentSheet:
    """This student's copy of this sheet, question by question.

    The items come from the copy's own ``item_plan`` where it has one, because a
    differentiated batch hands each pupil a different paper and the sheet's
    class-wide list is not what this one held.

    Readings are deduplicated per QUESTION, newest page first — never per
    ``item_index``, which is page-local and restarts at 0 on every physical page
    (I-scanning-12). A copy photographed twice contributes once.
    """
    from alppy.services.sheet_service import get_sheet

    school_id = scope.school_id
    sheet = get_sheet(db, scope, sheet_id)
    # Ownership, not just tenancy: this report names the child and quotes every
    # answer they gave, so it follows the same rule as the class they sit in
    # (D23) — reachable through ANY class this teacher owns, and the school
    # filter on top is what keeps that widening inside one tenant
    # (I-platform-10). A bare school_id lookup would let a colleague confirm a
    # student exists and read their identity back with an empty item list.
    student = db.execute(
        select(Student)
        .where(Student.id == student_id)
        .where(Student.school_id == school_id)
        # Overlap, not current enrollment: this report is one sheet's answers,
        # and the teacher who marked it in October keeps it in June even after
        # the pupil has moved to another niveau group. Same widening as
        # `mastery_service._owned_student`, for the same reason (D87).
        .where(Student.id.in_(ever_shared_student_ids(scope)))
    ).scalar_one_or_none()
    if student is None:
        from alppy.api import errors

        raise errors.not_found("student", id=str(student_id))

    items_by_exercise: dict[uuid.UUID, SheetItem] = {si.exercise_id: si for si in sheet.items}
    instance = next(
        (i for i in sheet.instances if i.student_id == student_id),
        None,
    )
    plan = (instance.item_plan if instance else None) or [
        {"exercise_id": str(si.exercise_id), "position": si.position} for si in sheet.items
    ]

    # The newest reading per question, across every pile of this sheet.
    readings: dict[uuid.UUID, tuple[Detection, Any, uuid.UUID, int | None]] = {}
    stmt = (
        select(Detection, ScanPage.created_at, Scan.id, ScanPage.page_in_copy)
        .join(ScanPage, ScanPage.id == Detection.scan_page_id)
        .join(Scan, Scan.id == ScanPage.scan_id)
        .where(Scan.sheet_id == sheet.id)
        .where(Scan.school_id == school_id)
        .where(ScanPage.student_id == student_id)
        .where(ScanPage.discarded.is_(False))
        .where(ScanPage.wrong_class.is_(False))
        .where(Detection.exercise_id.is_not(None))
    )
    if as_of is not None:
        # "The paper as I graded it in November", when a copy was re-shot
        # later and the newest-page rule would otherwise answer with a pile
        # that did not exist yet.
        stmt = stmt.where(ScanPage.created_at <= as_of)
    rows = db.execute(stmt).all()
    for detection, page_created, page_scan_id, page_in_copy in rows:
        if detection.exercise_id is None:  # pragma: no cover - filtered in SQL
            continue
        current = readings.get(detection.exercise_id)
        if current is None or page_created > current[1]:
            readings[detection.exercise_id] = (
                detection,
                page_created,
                page_scan_id,
                page_in_copy,
            )

    attempts = {
        attempt.exercise_id: attempt
        for attempt in db.execute(
            select(Attempt)
            .where(Attempt.person_id == student.person_id)
            .where(Attempt.sheet_id == sheet.id)
            .where(Attempt.school_id == school_id)
        ).scalars()
    }

    default_points = sheet.default_points_correct
    built: list[StudentSheetItem] = []
    earned_total = 0.0
    possible_total = 0.0
    any_graded = False
    scan_id: uuid.UUID | None = None
    answered_at: datetime | None = None

    for position, entry in enumerate(sorted(plan, key=lambda e: e.get("position", 0))):
        raw = entry.get("exercise_id")
        if raw is None:
            continue
        exercise_id = uuid.UUID(str(raw))
        exercise = db.get(Exercise, exercise_id)
        if exercise is None:
            continue
        sheet_item = items_by_exercise.get(exercise_id)
        possible = (
            sheet_item.points_correct
            if sheet_item is not None and sheet_item.points_correct is not None
            else default_points
        )
        possible_total += possible

        reading = readings.get(exercise_id)
        detection = reading[0] if reading else None
        if reading and scan_id is None:
            scan_id = reading[2]

        attempt = attempts.get(exercise_id)
        if attempt is not None:
            earned_total += attempt.score
            any_graded = True
            if answered_at is None or attempt.answered_at > answered_at:
                answered_at = attempt.answered_at

        if exercise.type is ExerciseType.OPEN:
            given = detection.transcription if detection else None
            expected = (
                sheet_item.expected_answer
                if sheet_item is not None and sheet_item.expected_answer
                else exercise.answer_text
            )
            given_index = None
            expected_index = None
        else:
            given_index = detection.detected_index if detection else None
            expected_index = _expected_index(exercise)
            given = _readable_choice(exercise, given_index, sheet.language)
            expected = _readable_choice(exercise, expected_index, sheet.language)

        built.append(
            StudentSheetItem(
                position=position,
                number=detection.printed_number if detection else position + 1,
                exercise_id=exercise_id,
                statement=(
                    sheet_item.statement_override
                    if sheet_item is not None and sheet_item.statement_override
                    else exercise.statement
                ),
                exercise_type=exercise.type,
                ai_generated=exercise.origin.value == "ai_generated",
                options=list(exercise.options or []),
                given=given,
                given_index=given_index,
                expected=expected,
                expected_index=expected_index,
                outcome=detection.outcome if detection else None,
                confidence=detection.confidence if detection else None,
                correct=attempt.correct if attempt is not None else None,
                points_earned=attempt.score if attempt is not None else None,
                points_possible=possible,
                crop_key=detection.crop_key if detection else None,
            )
        )

    return StudentSheet(
        student=student,
        sheet=sheet,
        scan_id=scan_id,
        answered_at=answered_at,
        # Floored at zero like every other total, and null — not zero — when
        # nothing on this copy has been graded.
        points_earned=max(0.0, earned_total) if any_graded else None,
        points_possible=possible_total,
        items=built,
    )
