"""Sheets: build one, edit one, bind it to students.

A sheet has two layers. ``SheetItem`` is the class-level item list a teacher
sees and reorders. ``SheetInstance`` is the printed artefact: one per student,
carrying that student's UID and — for a differentiated batch — its own item
plan. Both are created here so the renderer never has to guess which items a
given child's page should hold.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.models import Class, Exercise, Sheet, SheetInstance, SheetItem, Student, Subject
from alppy.models.enums import SheetTarget
from alppy.schemas import AdaptiveBatchRequest, SheetCreate, SheetItemIn, SheetUpdate
from alppy.services.class_service import get_class, list_students
from alppy.sheets.layout import LAYOUT_VERSION


def get_sheet(db: Session, school_id: uuid.UUID, sheet_id: uuid.UUID) -> Sheet:
    sheet = db.execute(
        select(Sheet).where(Sheet.id == sheet_id).where(Sheet.school_id == school_id)
    ).scalar_one_or_none()
    if sheet is None:
        raise errors.not_found("sheet", id=str(sheet_id))
    return sheet


def list_sheets(
    db: Session, school_id: uuid.UUID, *, class_id: uuid.UUID | None = None
) -> list[Sheet]:
    stmt = select(Sheet).where(Sheet.school_id == school_id)
    if class_id is not None:
        stmt = stmt.where(Sheet.class_id == class_id)
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
            )
        )
    db.flush()


def create_sheet(
    db: Session, school_id: uuid.UUID, teacher_id: uuid.UUID, payload: SheetCreate
) -> Sheet:
    school_class = get_class(db, school_id, payload.class_id)
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
    )
    db.add(sheet)
    db.flush()

    _replace_items(db, school_id, sheet, payload.items)
    plan = _item_plan(payload.items)
    students = list_students(db, school_id, school_class.id)
    _bind_instances(db, school_id, sheet, students, {s.id: plan for s in students})
    db.refresh(sheet)
    return sheet


def update_sheet(
    db: Session, school_id: uuid.UUID, sheet_id: uuid.UUID, payload: SheetUpdate
) -> Sheet:
    sheet = get_sheet(db, school_id, sheet_id)
    if payload.title is not None:
        sheet.title = payload.title
    if payload.items is not None:
        _replace_items(db, school_id, sheet, payload.items)
        plan = _item_plan(payload.items)
        for instance in sheet.instances:
            instance.item_plan = plan
        # Editing the items invalidates whatever was rendered from the old ones.
        sheet.blank_pdf_key = None
        sheet.answer_key_pdf_key = None
        sheet.rendered_at = None
    db.flush()
    db.refresh(sheet)
    return sheet


def create_adaptive_sheet(
    db: Session, school_id: uuid.UUID, teacher_id: uuid.UUID, payload: AdaptiveBatchRequest
) -> Sheet:
    """One sheet, N different printed pages — the F4 deliverable.

    The class-level item list is the union of every student's items so the
    corpus reference is complete; each instance's ``item_plan`` is that
    student's own ordered subset, which is what the renderer prints.
    """
    school_class = get_class(db, school_id, payload.class_id)
    _require_subject(db, school_id, payload.subject_id)
    if not payload.plans:
        raise errors.unprocessable("an adaptive batch needs at least one student plan")

    students = {s.id: s for s in list_students(db, school_id, school_class.id)}
    unknown = [str(p.student_id) for p in payload.plans if p.student_id not in students]
    if unknown:
        raise errors.not_found("student", ids=unknown)

    union: list[uuid.UUID] = []
    for plan in payload.plans:
        for proposal in [*plan.retrieved, *plan.generated]:
            if proposal.exercise.id not in union:
                union.append(proposal.exercise.id)
    _load_exercises(db, school_id, union)

    sheet = Sheet(
        id=uuid.uuid4(),
        school_id=school_id,
        class_id=school_class.id,
        subject_id=payload.subject_id,
        created_by_id=teacher_id,
        title=payload.title,
        target=SheetTarget.STUDENT,
        language=payload.language,
        intent="adaptive batch",
        layout_version=LAYOUT_VERSION,
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
    )
    db.refresh(sheet)
    return sheet
