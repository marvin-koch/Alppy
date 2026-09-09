"""Sheets: build one, edit one, bind it to students.

A sheet has two layers. ``SheetItem`` is the class-level item list a teacher
sees and reorders. ``SheetInstance`` is the printed artefact: one per student,
carrying that student's UID and — for a differentiated batch — its own item
plan. Both are created here so the renderer never has to guess which items a
given child's page should hold.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.api.deps import Scope
from alppy.models import (
    Attempt,
    Exercise,
    MisconceptionNote,
    Sheet,
    SheetInstance,
    SheetItem,
    Student,
    Subject,
)
from alppy.models.enums import EventKind, EventSubject, ExerciseType, SheetTarget
from alppy.schemas import AdaptiveBatchRequest, SheetCreate, SheetItemIn, SheetUpdate
from alppy.services import event_service
from alppy.services.approval import (
    UnapprovedExerciseError,
    UnapprovedFeedbackError,
    ensure_notes_printable,
    ensure_printable,
)
from alppy.services.class_service import get_class, list_students, owned_class_ids
from alppy.sheets.layout import LAYOUT_VERSION


def get_sheet(db: Session, scope: Scope, sheet_id: uuid.UUID) -> Sheet:
    """One sheet for a class the caller owns, or 404.

    A sheet carries its class's roster on paper, so it inherits that class's
    ownership rather than only the school boundary (decisions-log D23).
    """
    sheet = db.execute(
        select(Sheet)
        .where(Sheet.id == sheet_id)
        .where(Sheet.school_id == scope.school_id)
        .where(Sheet.class_id.in_(owned_class_ids(scope)))
    ).scalar_one_or_none()
    if sheet is None:
        raise errors.not_found("sheet", id=str(sheet_id))
    return sheet


def list_sheets(
    db: Session,
    scope: Scope,
    *,
    class_id: uuid.UUID | None = None,
    subject_id: uuid.UUID | None = None,
) -> list[Sheet]:
    stmt = (
        select(Sheet)
        .where(Sheet.school_id == scope.school_id)
        .where(Sheet.class_id.in_(owned_class_ids(scope)))
    )
    if class_id is not None:
        stmt = stmt.where(Sheet.class_id == class_id)
    if subject_id is not None:
        stmt = stmt.where(Sheet.subject_id == subject_id)
    return list(db.execute(stmt.order_by(Sheet.created_at.desc())).scalars())


def _require_subject(db: Session, school_id: uuid.UUID, subject_id: uuid.UUID) -> Subject:
    subject = db.execute(
        select(Subject).where(Subject.id == subject_id).where(Subject.school_id == school_id)
    ).scalar_one_or_none()
    if subject is None:
        raise errors.not_found("subject", id=str(subject_id))
    return subject


def _load_exercises(
    db: Session, school_id: uuid.UUID, exercise_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Exercise]:
    if not exercise_ids:
        return {}
    rows = db.execute(
        select(Exercise)
        .where(Exercise.school_id == school_id)
        .where(Exercise.id.in_(exercise_ids))
    ).scalars()
    found = {e.id: e for e in rows}
    missing = [str(i) for i in exercise_ids if i not in found]
    if missing:
        raise errors.not_found("exercise", ids=missing)
    return found


def _validate_positions(items: list[SheetItemIn]) -> None:
    positions = [i.position for i in items]
    if len(set(positions)) != len(positions):
        raise errors.unprocessable("sheet item positions must be unique")


def _replace_items(
    db: Session, school_id: uuid.UUID, sheet: Sheet, items: list[SheetItemIn]
) -> None:
    _validate_positions(items)
    exercises = _load_exercises(db, school_id, [i.exercise_id for i in items])
    for existing in list(sheet.items):
        db.delete(existing)
    db.flush()
    for entry in sorted(items, key=lambda i: i.position):
        db.add(
            SheetItem(
                id=uuid.uuid4(),
                school_id=school_id,
                sheet_id=sheet.id,
                exercise_id=exercises[entry.exercise_id].id,
                position=entry.position,
                statement_override=entry.statement_override,
                answer_box_lines=entry.answer_box_lines,
                answer_box_fill=entry.answer_box_fill,
                expected_answer=(
                    entry.expected_answer
                    if exercises[entry.exercise_id].type is ExerciseType.OPEN
                    else None
                ),
                # Deliberately not type-gated, unlike the wording, the box and
                # the expected answer above. The answer of an MCQ is the
                # bubble, so an expected answer on one is meaningless — but
                # what a bubble is WORTH is not, and neither is what a written
                # item is worth once a verdict grades it.
                points_correct=entry.points_correct,
                points_penalty=entry.points_penalty,
            )
        )
    db.flush()


def _item_plan(items: list[SheetItemIn]) -> list[dict[str, Any]]:
    return [
        {"exercise_id": str(i.exercise_id), "variant_id": None, "position": i.position}
        for i in sorted(items, key=lambda i: i.position)
    ]


def _bind_instances(
    db: Session,
    school_id: uuid.UUID,
    sheet: Sheet,
    students: list[Student],
    plans: dict[uuid.UUID, list[dict[str, Any]]] | None = None,
    group_labels: dict[uuid.UUID, str] | None = None,
    feedback_ids: dict[uuid.UUID, uuid.UUID] | None = None,
) -> None:
    """One printed instance per student, each carrying the student's UID."""
    existing = {i.student_id for i in sheet.instances}
    for student in students:
        if student.id in existing:
            continue
        db.add(
            SheetInstance(
                id=uuid.uuid4(),
                school_id=school_id,
                sheet_id=sheet.id,
                student_id=student.id,
                student_uid=student.uid,
                item_plan=(plans or {}).get(student.id, []),
                group_label=(group_labels or {}).get(student.id),
                feedback_id=(feedback_ids or {}).get(student.id),
            )
        )
    db.flush()


def create_sheet(db: Session, scope: Scope, teacher_id: uuid.UUID, payload: SheetCreate) -> Sheet:
    school_id = scope.school_id
    school_class = get_class(db, scope, payload.class_id)
    _require_subject(db, school_id, payload.subject_id)

    sheet = Sheet(
        id=uuid.uuid4(),
        school_id=school_id,
        class_id=school_class.id,
        subject_id=payload.subject_id,
        created_by_id=teacher_id,
        title=payload.title,
        target=payload.target,
        language=payload.language,
        intent=payload.intent,
        layout_version=LAYOUT_VERSION,
        default_points_correct=payload.default_points_correct,
        default_points_penalty=payload.default_points_penalty,
    )
    db.add(sheet)
    db.flush()

    _replace_items(db, school_id, sheet, payload.items)
    plan = _item_plan(payload.items)
    students = list_students(db, scope, school_class.id)
    _bind_instances(db, school_id, sheet, students, {s.id: plan for s in students})
    event_service.record(
        db,
        school_id=school_id,
        kind=EventKind.SHEET_CREATED,
        subject_type=EventSubject.SHEET,
        subject_id=sheet.id,
        summary=sheet.title,
        actor_id=teacher_id,
        class_id=sheet.class_id,
        subject_area_id=sheet.subject_id,
        detail={"items": len(payload.items), "copies": len(students)},
    )
    db.refresh(sheet)
    return sheet


def update_sheet(
    db: Session, scope: Scope, sheet_id: uuid.UUID, payload: SheetUpdate
) -> Sheet:
    school_id = scope.school_id
    sheet = get_sheet(db, scope, sheet_id)
    if payload.title is not None:
        sheet.title = payload.title
    # A barème edit changes the paper: every statement prints what it is worth.
    # So it invalidates the render exactly as an item edit does — otherwise the
    # teacher downloads a PDF whose "(1 pt)" disagrees with how it will grade.
    stale = False
    if payload.default_points_correct is not None:
        sheet.default_points_correct = payload.default_points_correct
        stale = True
    if payload.default_points_penalty is not None:
        sheet.default_points_penalty = payload.default_points_penalty
        stale = True
    if payload.items is not None:
        _replace_items(db, school_id, sheet, payload.items)
        plan = _item_plan(payload.items)
        for instance in sheet.instances:
            instance.item_plan = plan
        stale = True
    if stale:
        sheet.blank_pdf_key = None
        sheet.answer_key_pdf_key = None
        sheet.rendered_at = None
    db.flush()
    db.refresh(sheet)
    return sheet


def create_adaptive_sheet(
    db: Session, scope: Scope, teacher_id: uuid.UUID, payload: AdaptiveBatchRequest
) -> Sheet:
    """One sheet, N different printed pages — the F4 deliverable.

    The class-level item list is the union of every student's items so the
    corpus reference is complete; each instance's ``item_plan`` is that
    student's own ordered subset, which is what the renderer prints.
    """
    school_id = scope.school_id
    school_class = get_class(db, scope, payload.class_id)
    _require_subject(db, school_id, payload.subject_id)
    if not payload.plans:
        raise errors.unprocessable("an adaptive batch needs at least one student plan")

    students = {s.id: s for s in list_students(db, scope, school_class.id)}
    unknown = [str(p.student_id) for p in payload.plans if p.student_id not in students]
    if unknown:
        raise errors.not_found("student", ids=unknown)

    union: list[uuid.UUID] = []
    for plan in payload.plans:
        for proposal in [*plan.retrieved, *plan.generated]:
            if proposal.exercise.id not in union:
                union.append(proposal.exercise.id)
    exercises = _load_exercises(db, school_id, union)

    # The approval gate, at the first door rather than the last. The client
    # sends exercise ids, so "the UI would not offer an unapproved item" is not
    # a guarantee — it is a hope about one caller. Refusing here means the
    # teacher hears about it while they are still looking at the plan, not when
    # a render job fails half an hour later.
    try:
        ensure_printable(exercises.values())
    except UnapprovedExerciseError as exc:
        raise errors.unprocessable(
            "this batch contains AI-generated exercises that have not been approved",
            exercise_ids=[str(i) for i in exc.exercise_ids],
        ) from exc

    # The same door, for the notes. A feedback page is generated text handed to
    # a child; it gets the gate the generated exercises get.
    note_ids = [p.feedback_id for p in payload.plans if p.feedback_id is not None]
    notes = _load_notes(db, school_id, note_ids)
    missing_notes = [str(i) for i in note_ids if i not in notes]
    if missing_notes:
        raise errors.not_found("feedback", ids=missing_notes)
    try:
        ensure_notes_printable(notes.values())
    except UnapprovedFeedbackError as exc:
        raise errors.unprocessable(
            "this batch contains feedback notes that have not been approved",
            feedback_ids=[str(i) for i in exc.feedback_ids],
        ) from exc

    # `SheetTarget.GROUP` has sat in the enum since 0001 with nothing ever
    # assigning it. A batch built from more than one personalised group is
    # exactly what it was reserved for.
    grouped = (payload.group_count or 0) > 1
    sheet = Sheet(
        id=uuid.uuid4(),
        school_id=school_id,
        class_id=school_class.id,
        subject_id=payload.subject_id,
        created_by_id=teacher_id,
        title=payload.title,
        target=SheetTarget.GROUP if grouped else SheetTarget.STUDENT,
        language=payload.language,
        intent="adaptive batch",
        layout_version=LAYOUT_VERSION,
        derived_from_id=payload.source_sheet_id,
    )
    db.add(sheet)
    db.flush()

    _replace_items(
        db,
        school_id,
        sheet,
        [SheetItemIn(exercise_id=eid, position=idx) for idx, eid in enumerate(union)],
    )

    plans: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for plan in payload.plans:
        plans[plan.student_id] = [
            {"exercise_id": str(p.exercise.id), "variant_id": None, "position": idx}
            for idx, p in enumerate([*plan.retrieved, *plan.generated])
        ]
    _bind_instances(
        db,
        school_id,
        sheet,
        [students[p.student_id] for p in payload.plans],
        plans,
        group_labels={
            p.student_id: p.group_label for p in payload.plans if p.group_label
        },
        feedback_ids={
            p.student_id: p.feedback_id for p in payload.plans if p.feedback_id is not None
        },
    )
    event_service.record(
        db,
        school_id=school_id,
        kind=EventKind.ADAPTIVE_EXPORTED,
        subject_type=EventSubject.SHEET,
        subject_id=sheet.id,
        summary=sheet.title,
        actor_id=teacher_id,
        class_id=sheet.class_id,
        subject_area_id=sheet.subject_id,
        detail={
            "groups": payload.group_count or 1,
            "copies": len(payload.plans),
            "items": len(union),
            "feedback": len(note_ids),
        },
    )
    db.refresh(sheet)
    return sheet


def _load_notes(
    db: Session, school_id: uuid.UUID, note_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, MisconceptionNote]:
    """The notes this batch references, scoped to the school."""
    if not note_ids:
        return {}
    rows = db.scalars(
        select(MisconceptionNote).where(
            MisconceptionNote.school_id == school_id,
            MisconceptionNote.id.in_(list(note_ids)),
        )
    )
    return {row.id: row for row in rows}


@dataclass(frozen=True, slots=True)
class SheetPoints:
    """One copy's marks: what the student has, and what the copy was worth."""

    #: Points earned, floored at 0. None when nothing has been graded yet —
    #: which is not the same as zero, and a report that showed 0 for a pile
    #: nobody has scanned would be saying something false.
    earned: float | None
    #: The sum of what a correct answer earns over this copy's own items.
    possible: float


def _possible_by_student(sheet: Sheet) -> dict[uuid.UUID, float]:
    """What each copy of this sheet was worth, from ITS OWN item plan.

    Factored out so a class-wide rollup reuses this instead of re-deriving what
    a differentiated copy was worth. A differentiated batch hands each student
    a different subset, so the sheet's class-wide item list is not what any one
    student held, and two places computing that separately would eventually
    disagree.
    """
    items_by_exercise = {item.exercise_id: item for item in sheet.items}
    default_points = sheet.default_points_correct
    possible: dict[uuid.UUID, float] = {}
    for instance in sheet.instances:
        plan = instance.item_plan or [
            {"exercise_id": str(item.exercise_id)} for item in sheet.items
        ]
        total = 0.0
        for entry in plan:
            raw = entry.get("exercise_id")
            if raw is None:
                continue
            item = items_by_exercise.get(uuid.UUID(str(raw)))
            # `is not None` rather than `or`: a deliberate 0 is an item that
            # earns nothing, not an item with no override.
            if item is not None and item.points_correct is not None:
                total += item.points_correct
            else:
                total += default_points
        possible[instance.student_id] = total
    return possible


def _earned_by_sheet(
    db: Session, school_id: uuid.UUID, sheet_ids: Sequence[uuid.UUID]
) -> dict[tuple[uuid.UUID, uuid.UUID], float]:
    """``(student, sheet) -> earned``, floored at zero, in one query for N sheets.

    One query rather than one per sheet: a term's worth of sheets for a class is
    the normal case, and this is read on every dashboard load.
    """
    if not sheet_ids:
        return {}
    rows = db.execute(
        select(Attempt.student_id, Attempt.sheet_id, func.sum(Attempt.score))
        .where(Attempt.sheet_id.in_(list(sheet_ids)))
        .where(Attempt.school_id == school_id)
        .group_by(Attempt.student_id, Attempt.sheet_id)
    ).all()
    return {
        (student_id, sheet_id): max(0.0, float(total))
        for student_id, sheet_id, total in rows
        if total is not None
    }


def points_totals_for_sheet(
    db: Session, school_id: uuid.UUID, sheet: Sheet
) -> dict[uuid.UUID, SheetPoints]:
    """Each copy's total, keyed by student.

    Computed, never stored. ``Attempt.score`` is already the durable per-item
    record and is rewritten on every confirmation, so a SUM over it is exactly
    as fresh as the attempts themselves; a stored total would be one more place
    to disagree with them the first time a teacher corrects a single detection.

    The total floors at zero. Individual scores stay signed in the record, so a
    teacher can still see which answers cost points — only the sum is clamped,
    because a mark below zero says nothing a report can use.
    """
    earned = _earned_by_sheet(db, school_id, [sheet.id])
    return {
        student_id: SheetPoints(earned=earned.get((student_id, sheet.id)), possible=possible)
        for student_id, possible in _possible_by_student(sheet).items()
    }


@dataclass(frozen=True, slots=True)
class ClassSheetPoints:
    """One sheet, as the class did on it."""

    sheet_id: uuid.UUID
    sheet_title: str
    #: Mean of each graded copy's own ratio. None when nobody has been graded
    #: on it yet — which is not zero, and a report that showed 0% for a pile
    #: nobody has scanned would be saying something false.
    average_ratio: float | None
    per_student: dict[uuid.UUID, SheetPoints]


@dataclass(frozen=True, slots=True)
class ClassPointsReport:
    #: Totals ACROSS every sheet in scope, per student.
    students: dict[uuid.UUID, SheetPoints]
    sheets: list[ClassSheetPoints]


def class_points_totals(
    db: Session,
    scope: Scope,
    class_id: uuid.UUID,
    *,
    subject_id: uuid.UUID | None = None,
) -> ClassPointsReport:
    """Every sheet of a class, rolled up per student and per sheet.

    ``possible`` accumulates over every sheet whether or not it has been
    scanned: it is a fact about the paper the student was handed. ``earned``
    accumulates only where there is a grade, and stays ``None`` for a student
    with none — the same "absent is not zero" rule ``SheetPoints`` already
    states, one level up. A term where two of five sheets are marked must not
    read as though the other three were failed.
    """
    school_id = scope.school_id
    get_class(db, scope, class_id)
    sheets = list_sheets(db, scope, class_id=class_id, subject_id=subject_id)
    if not sheets:
        return ClassPointsReport(students={}, sheets=[])

    earned_by_sheet = _earned_by_sheet(db, school_id, [sheet.id for sheet in sheets])
    earned_total: dict[uuid.UUID, float] = {}
    possible_total: dict[uuid.UUID, float] = {}
    graded_students: set[uuid.UUID] = set()
    per_sheet: list[ClassSheetPoints] = []

    for sheet in sheets:
        per_student: dict[uuid.UUID, SheetPoints] = {}
        ratios: list[float] = []
        for student_id, possible in _possible_by_student(sheet).items():
            earned = earned_by_sheet.get((student_id, sheet.id))
            per_student[student_id] = SheetPoints(earned=earned, possible=possible)
            possible_total[student_id] = possible_total.get(student_id, 0.0) + possible
            if earned is not None:
                earned_total[student_id] = earned_total.get(student_id, 0.0) + earned
                graded_students.add(student_id)
                if possible > 0:
                    ratios.append(earned / possible)
        per_sheet.append(
            ClassSheetPoints(
                sheet_id=sheet.id,
                sheet_title=sheet.title,
                average_ratio=(sum(ratios) / len(ratios)) if ratios else None,
                per_student=per_student,
            )
        )

    students = {
        student_id: SheetPoints(
            earned=earned_total.get(student_id) if student_id in graded_students else None,
            possible=possible,
        )
        for student_id, possible in possible_total.items()
    }
    return ClassPointsReport(students=students, sheets=per_sheet)
