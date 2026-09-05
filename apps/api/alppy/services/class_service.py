"""Classes, rosters and the teacher home summary.

The roster is the one place where a teacher's real workflow drove the design:
they paste a class list once, and every student gets a number and a UID
(``7B_15``) derived from the class code. That UID is the only student
identifier that is ever printed or sent to a model provider — see
docs/privacy.md — so it is assigned here, deterministically, and never
regenerated.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.core.uid import MAX_STUDENT_NUMBER, InvalidUidError, format_uid
from alppy.models import Class, Scan, SchoolYear, Sheet, Student, Subject, Teacher
from alppy.models.enums import ScanStatus
from alppy.schemas import ClassCreate, ClassOut, ClassSummary, HomeOut, RosterCreate
from alppy.services import class_out, subject_out, teacher_out
from alppy.services.mastery_service import band_summary

PENDING_SCAN_STATUSES = (
    ScanStatus.UPLOADED,
    ScanStatus.PROCESSING,
    ScanStatus.NEEDS_REVIEW,
)


# --------------------------------------------------------------------------
# School years
# --------------------------------------------------------------------------
def _school_year_bounds(today: date) -> tuple[str, date, date]:
    """Swiss school years run August to July."""
    start_year = today.year if today.month >= 8 else today.year - 1
    return (
        f"{start_year}/{str(start_year + 1)[-2:]}",
        date(start_year, 8, 1),
        date(start_year + 1, 7, 31),
    )


def current_school_year(
    db: Session, school_id: uuid.UUID, *, today: date | None = None
) -> SchoolYear:
    """The tenant's current year, created on first use.

    A brand-new school has no year row yet, and asking a teacher to create one
    before they can create a class would be a pointless step.
    """
    existing = db.execute(
        select(SchoolYear)
        .where(SchoolYear.school_id == school_id)
        .where(SchoolYear.is_current.is_(True))
        .order_by(SchoolYear.starts_on.desc())
    ).scalars().first()
    if existing is not None:
        return existing

    label, starts_on, ends_on = _school_year_bounds(today or datetime.now(UTC).date())
    by_label = db.execute(
        select(SchoolYear)
        .where(SchoolYear.school_id == school_id)
        .where(SchoolYear.label == label)
    ).scalar_one_or_none()
    if by_label is not None:
        by_label.is_current = True
        db.flush()
        return by_label

    year = SchoolYear(
        id=uuid.uuid4(),
        school_id=school_id,
        label=label,
        starts_on=starts_on,
        ends_on=ends_on,
        is_current=True,
    )
    db.add(year)
    db.flush()
    return year


# --------------------------------------------------------------------------
# Classes
# --------------------------------------------------------------------------
def list_classes(db: Session, school_id: uuid.UUID) -> list[Class]:
    return list(
        db.execute(
            select(Class).where(Class.school_id == school_id).order_by(Class.code.asc())
        ).scalars()
    )


def get_class(db: Session, school_id: uuid.UUID, class_id: uuid.UUID) -> Class:
    row = db.execute(
        select(Class).where(Class.id == class_id).where(Class.school_id == school_id)
    ).scalar_one_or_none()
    if row is None:
        raise errors.not_found("class", id=str(class_id))
    return row


def student_counts(db: Session, school_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(Student.class_id, func.count(Student.id))
        .where(Student.school_id == school_id)
        .group_by(Student.class_id)
    ).all()
    return {class_id: int(count) for class_id, count in rows}


def subject_ids_for_class(db: Session, school_id: uuid.UUID, class_id: uuid.UUID) -> list[uuid.UUID]:
    """Subjects this class has sheets for.

    There is no Class-Subject association table in the model, so "the subjects
    of a class" is derived from what has actually been taught to it.
    """
    rows = db.execute(
        select(Sheet.subject_id)
        .where(Sheet.school_id == school_id)
        .where(Sheet.class_id == class_id)
        .distinct()
    ).scalars()
    return list(rows)


def create_class(
    db: Session, school_id: uuid.UUID, teacher: Teacher, payload: ClassCreate
) -> Class:
    if payload.school_year_id is not None:
        year = db.execute(
            select(SchoolYear)
            .where(SchoolYear.id == payload.school_year_id)
            .where(SchoolYear.school_id == school_id)
        ).scalar_one_or_none()
        if year is None:
            raise errors.not_found("school year", id=str(payload.school_year_id))
    else:
        year = current_school_year(db, school_id)

    clash = db.execute(
        select(Class)
        .where(Class.school_id == school_id)
        .where(Class.school_year_id == year.id)
        .where(Class.code == payload.code)
    ).scalar_one_or_none()
    if clash is not None:
        raise errors.conflict(
            f"class {payload.code} already exists this school year", class_id=str(clash.id)
        )

    row = Class(
        id=uuid.uuid4(),
        school_id=school_id,
        school_year_id=year.id,
        teacher_id=teacher.id,
        code=payload.code,
        label=payload.label,
    )
    db.add(row)
    db.flush()
    return row


# --------------------------------------------------------------------------
# Roster
# --------------------------------------------------------------------------
def list_students(db: Session, school_id: uuid.UUID, class_id: uuid.UUID) -> list[Student]:
    return list(
        db.execute(
            select(Student)
            .where(Student.school_id == school_id)
            .where(Student.class_id == class_id)
            .order_by(Student.number.asc())
        ).scalars()
    )


def add_students(
    db: Session, school_id: uuid.UUID, school_class: Class, payload: RosterCreate
) -> list[Student]:
    """Add a pasted roster. Numbers are sequential from the first free slot.

    An explicit number is honoured (a teacher re-adding student 7 after a
    mistake), but a collision is a 409 rather than a silent renumber: student
    numbers are printed on paper that may already be in a pile on the desk.
    """
    taken = {s.number for s in list_students(db, school_id, school_class.id)}
    next_free = 1
    created: list[Student] = []

    for entry in payload.students:
        if entry.number is not None:
            number = entry.number
            if number in taken:
                raise errors.conflict(
                    f"student number {number} is already used in {school_class.code}",
                    number=number,
                )
        else:
            while next_free in taken:
                next_free += 1
            number = next_free
        if number > MAX_STUDENT_NUMBER:
            raise errors.unprocessable(
                f"a class cannot hold more than {MAX_STUDENT_NUMBER} students"
            )
        taken.add(number)

        try:
            uid = format_uid(school_class.code, number)
        except InvalidUidError as exc:
            raise errors.unprocessable(str(exc)) from exc

        student = Student(
            id=uuid.uuid4(),
            school_id=school_id,
            class_id=school_class.id,
            school_year_id=school_class.school_year_id,
            uid=uid,
            number=number,
            first_name=entry.first_name.strip(),
            last_name=entry.last_name.strip(),
        )
        db.add(student)
        created.append(student)

    db.flush()
    return sorted(created, key=lambda s: s.number)


# --------------------------------------------------------------------------
# Home
# --------------------------------------------------------------------------
def list_subjects(db: Session, school_id: uuid.UUID) -> list[Subject]:
    return list(
        db.execute(
            select(Subject).where(Subject.school_id == school_id).order_by(Subject.key.asc())
        ).scalars()
    )


def _pending_scan_counts(db: Session, school_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(Sheet.class_id, func.count(Scan.id))
        .join(Sheet, Sheet.id == Scan.sheet_id)
        .where(Scan.school_id == school_id)
        .where(Scan.status.in_(PENDING_SCAN_STATUSES))
        .group_by(Sheet.class_id)
    ).all()
    return {class_id: int(count) for class_id, count in rows}


def _last_sheets(db: Session, school_id: uuid.UUID) -> dict[uuid.UUID, Sheet]:
    rows = db.execute(
        select(Sheet)
        .where(Sheet.school_id == school_id)
        .order_by(Sheet.created_at.asc(), Sheet.title.asc())
    ).scalars()
    return {sheet.class_id: sheet for sheet in rows}  # last write per class wins


def class_summary(
    db: Session,
    school_id: uuid.UUID,
    school_class: Class,
    *,
    counts: dict[uuid.UUID, int] | None = None,
    pending: dict[uuid.UUID, int] | None = None,
    last_sheets: dict[uuid.UUID, Sheet] | None = None,
) -> ClassSummary:
    counts = counts if counts is not None else student_counts(db, school_id)
    pending = pending if pending is not None else _pending_scan_counts(db, school_id)
    last_sheets = last_sheets if last_sheets is not None else _last_sheets(db, school_id)

    student_ids = [s.id for s in list_students(db, school_id, school_class.id)]
    bands, needing = band_summary(db, school_id, student_ids)
    last = last_sheets.get(school_class.id)

    return ClassSummary(
        class_id=school_class.id,
        code=school_class.code,
        label=school_class.label,
        student_count=counts.get(school_class.id, 0),
        last_sheet_title=last.title if last is not None else None,
        last_sheet_at=last.created_at if last is not None else None,
        pending_scans=pending.get(school_class.id, 0),
        students_needing_attention=needing,
        band_counts=bands,
    )


def home(db: Session, teacher: Teacher) -> HomeOut:
    school_id = teacher.school_id
    counts = student_counts(db, school_id)
    pending = _pending_scan_counts(db, school_id)
    last_sheets = _last_sheets(db, school_id)
    return HomeOut(
        teacher=teacher_out(teacher),
        subjects=[subject_out(s) for s in list_subjects(db, school_id)],
        classes=[
            class_summary(
                db,
                school_id,
                c,
                counts=counts,
                pending=pending,
                last_sheets=last_sheets,
            )
            for c in list_classes(db, school_id)
        ],
    )


def class_out_with_counts(
    db: Session, school_id: uuid.UUID, school_class: Class
) -> ClassOut:
    return class_out(
        school_class,
        student_count=student_counts(db, school_id).get(school_class.id, 0),
        subject_ids=subject_ids_for_class(db, school_id, school_class.id),
    )
