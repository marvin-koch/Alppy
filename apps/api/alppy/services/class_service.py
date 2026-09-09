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
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from alppy.api import errors
from alppy.api.deps import Scope
from alppy.core.uid import MAX_STUDENT_NUMBER, InvalidUidError, format_uid
from alppy.models import (
    Class,
    Scan,
    SchoolYear,
    Sheet,
    Student,
    Subject,
    Teacher,
    class_student,
    class_subject,
)
from alppy.models.enums import ScanStatus
from alppy.schemas import ClassCreate, ClassOut, ClassSummary, HomeOut, RosterCreate
from alppy.services import class_out, subject_out, teacher_out
from alppy.services.enrollment import (
    enrolled_in_owned_classes,
    enrolled_student_ids,
    owned_class_ids,
)

__all__ = [
    "add_students",
    "class_out_with_counts",
    "class_summary",
    "create_class",
    "current_school_year",
    "declare_subject",
    "enroll",
    "enrolled_in_owned_classes",
    "enrolled_student_ids",
    "get_class",
    "get_student",
    "home",
    "home_students",
    "list_classes",
    "list_students",
    "list_subjects",
    "owned_class_ids",
    "student_counts",
    "subject_ids_for_class",
    "unenroll",
]
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
def list_classes(db: Session, scope: Scope) -> list[Class]:
    return list(
        db.execute(
            select(Class)
            .where(Class.school_id == scope.school_id)
            .where(Class.teacher_id == scope.teacher_id)
            .order_by(Class.code.asc())
        ).scalars()
    )


def get_class(db: Session, scope: Scope, class_id: uuid.UUID) -> Class:
    """One class the caller owns, or 404.

    A colleague's class reads as missing rather than forbidden, for the same
    reason another school's does: the response must not confirm the id exists.
    """
    row = db.execute(
        select(Class)
        .where(Class.id == class_id)
        .where(Class.school_id == scope.school_id)
        .where(Class.teacher_id == scope.teacher_id)
    ).scalar_one_or_none()
    if row is None:
        raise errors.not_found("class", id=str(class_id))
    return row


def student_counts(db: Session, scope: Scope) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(class_student.c.class_id, func.count(Student.id))
        .join(Student, Student.id == class_student.c.student_id)
        .where(Student.school_id == scope.school_id)
        .where(class_student.c.class_id.in_(owned_class_ids(scope)))
        .group_by(class_student.c.class_id)
    ).all()
    return {class_id: int(count) for class_id, count in rows}


def subject_ids_for_class(db: Session, scope: Scope, class_id: uuid.UUID) -> list[uuid.UUID]:
    """The Branches this class studies, in the order it met them.

    Declared in ``class_subject``, not derived. Until D57 this was
    `SELECT DISTINCT sheet.subject_id`, which was circular: the Branch level of
    the navigation only existed once somebody had already built a sheet inside
    one, so a new class opened onto nothing. ``declare_subject`` keeps the
    table current from the one place a class and a subject first meet.

    The ownership filter is joined in here rather than trusting the caller's
    ``class_id``, the same as every other read in this module.
    """
    rows = db.execute(
        select(class_subject.c.subject_id)
        .join(Class, Class.id == class_subject.c.class_id)
        .where(Class.id == class_id)
        .where(Class.school_id == scope.school_id)
        .where(Class.teacher_id == scope.teacher_id)
        # `subject_id` breaks a tie: two subjects first taught in the same
        # instant can be assigned the same position (the PK is
        # (class_id, subject_id), so ON CONFLICT cannot serialise that), and a
        # branch list whose order wobbles between requests is worse than one
        # whose tie is resolved arbitrarily but consistently.
        .order_by(class_subject.c.position.asc(), class_subject.c.subject_id.asc())
    ).scalars()
    return list(rows)


def declare_subject(
    db: Session, scope: Scope, class_id: uuid.UUID, subject_id: uuid.UUID
) -> None:
    """Record that this class studies this Branch. Idempotent.

    Called from ``sheet_service.create_sheet`` — the one place a class and a
    subject first come together — so the Branch list stays populated with no
    new step for the teacher, exactly as the old derived query did implicitly.

    ``ON CONFLICT DO NOTHING`` rather than a read-then-write: two sheets
    created in the same new subject at once would otherwise race into a
    duplicate-key error on a perfectly ordinary action.
    """
    next_position = db.execute(
        select(func.coalesce(func.max(class_subject.c.position), -1) + 1).where(
            class_subject.c.class_id == class_id
        )
    ).scalar_one()
    db.execute(
        pg_insert(class_subject)
        .values(class_id=class_id, subject_id=subject_id, position=next_position)
        .on_conflict_do_nothing(index_elements=["class_id", "subject_id"])
    )


def create_class(db: Session, scope: Scope, teacher: Teacher, payload: ClassCreate) -> Class:
    if payload.school_year_id is not None:
        year = db.execute(
            select(SchoolYear)
            .where(SchoolYear.id == payload.school_year_id)
            .where(SchoolYear.school_id == scope.school_id)
        ).scalar_one_or_none()
        if year is None:
            raise errors.not_found("school year", id=str(payload.school_year_id))
    else:
        year = current_school_year(db, scope.school_id)

    clash = db.execute(
        select(Class)
        .where(Class.school_id == scope.school_id)
        .where(Class.school_year_id == year.id)
        .where(Class.code == payload.code)
    ).scalar_one_or_none()
    if clash is not None:
        raise errors.conflict(
            f"class {payload.code} already exists this school year", class_id=str(clash.id)
        )

    row = Class(
        id=uuid.uuid4(),
        school_id=scope.school_id,
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
def list_students(db: Session, scope: Scope, class_id: uuid.UUID) -> list[Student]:
    """Everyone sitting in this class — home pupils and visitors alike.

    This is what a roster, a mastery matrix, a curriculum tree and a printed
    pile all mean by "the students", and nearly every other service funnels
    through it. If you want the pupils this class is HOME to — because you are
    minting a UID or a number — use ``home_students``.
    """
    return list(
        db.execute(
            select(Student)
            # `student_out` names every class a pupil sits in, and a roster is
            # 24 of them: without these two the serialiser fires 48 queries.
            .options(selectinload(Student.classes), selectinload(Student.home_class))
            .where(Student.school_id == scope.school_id)
            .where(Student.id.in_(enrolled_in_owned_classes(scope)))
            .where(Student.id.in_(enrolled_student_ids(class_id)))
            .order_by(Student.number.asc())
        ).scalars()
    )


def home_students(db: Session, scope: Scope, class_id: uuid.UUID) -> list[Student]:
    """The pupils whose uid and number THIS class minted.

    Only the roster paste wants this. A visiting pupil carries their home
    class's number — a 9A pupil numbered 4 sitting in 7B — and that number
    says nothing about whether ``7B_04`` is free.
    """
    return list(
        db.execute(
            select(Student)
            .where(Student.school_id == scope.school_id)
            .where(Student.home_class_id.in_(owned_class_ids(scope)))
            .where(Student.home_class_id == class_id)
            .order_by(Student.number.asc())
        ).scalars()
    )


def get_student(db: Session, scope: Scope, student_id: uuid.UUID) -> Student:
    """One student the caller may act on, or 404.

    Reachable through ANY class this teacher owns, not just the home one: a
    pupil co-enrolled in two teachers' classes is each teacher's to see, which
    is the whole point of D69. The school filter on top is what keeps that
    widening inside one tenant (I-platform-10).
    """
    row = db.execute(
        select(Student)
        .where(Student.id == student_id)
        .where(Student.school_id == scope.school_id)
        .where(Student.id.in_(enrolled_in_owned_classes(scope)))
    ).scalar_one_or_none()
    if row is None:
        raise errors.not_found("student", id=str(student_id))
    return row


def enroll(db: Session, school_class: Class, student: Student) -> None:
    """Seat a student in a class. Idempotent.

    Asserts school AND school year (I-platform-10): ``uq_student_uid`` is
    unique per school year, so an enrollment spanning two years would make a
    printed UID ambiguous — the one identifier the detector has to trust.
    """
    if student.school_id != school_class.school_id:
        raise errors.unprocessable("a student cannot be enrolled in another school's class")
    if student.school_year_id != school_class.school_year_id:
        raise errors.unprocessable(
            "a student cannot be enrolled in a class from another school year"
        )
    db.execute(
        pg_insert(class_student)
        .values(class_id=school_class.id, student_id=student.id)
        .on_conflict_do_nothing(index_elements=["class_id", "student_id"])
    )


def unenroll(db: Session, school_class: Class, student: Student) -> None:
    """Remove a student from a class without touching their record.

    Refused on the home class: the home is where the UID came from and the
    column is NOT NULL. Unenrolling drops one row — the student, their uid,
    their attempts and their snapshots all survive. Deleting a student stays
    the only operation that destroys evidence.
    """
    if student.home_class_id == school_class.id:
        raise errors.conflict(
            "a student cannot leave the class that minted their uid",
            uid=student.uid,
        )
    db.execute(
        class_student.delete().where(
            class_student.c.class_id == school_class.id,
            class_student.c.student_id == student.id,
        )
    )


def add_students(
    db: Session, scope: Scope, school_class: Class, payload: RosterCreate
) -> list[Student]:
    """Add a pasted roster. Numbers are sequential from the first free slot.

    An explicit number is honoured (a teacher re-adding student 7 after a
    mistake), but a collision is a 409 rather than a silent renumber: student
    numbers are printed on paper that may already be in a pile on the desk.
    """
    # HOME students, deliberately — not the enrolled roster. A visiting pupil
    # numbered 4 by their own class does not make `7B_04` taken, and reading
    # the wider set here would 409 on a number this class actually has free.
    taken = {s.number for s in home_students(db, scope, school_class.id)}
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
            school_id=scope.school_id,
            home_class_id=school_class.id,
            school_year_id=school_class.school_year_id,
            uid=uid,
            number=number,
            first_name=entry.first_name.strip(),
            last_name=entry.last_name.strip(),
        )
        db.add(student)
        created.append(student)

    # Flush before enrolling: the join row carries a real FK to student.id.
    db.flush()
    for student in created:
        enroll(db, school_class, student)
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


def _pending_scan_counts(db: Session, scope: Scope) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(Sheet.class_id, func.count(Scan.id))
        .join(Sheet, Sheet.id == Scan.sheet_id)
        .where(Scan.school_id == scope.school_id)
        .where(Sheet.class_id.in_(owned_class_ids(scope)))
        .where(Scan.status.in_(PENDING_SCAN_STATUSES))
        .group_by(Sheet.class_id)
    ).all()
    return {class_id: int(count) for class_id, count in rows}


def _last_sheets(db: Session, scope: Scope) -> dict[uuid.UUID, Sheet]:
    rows = db.execute(
        select(Sheet)
        .where(Sheet.school_id == scope.school_id)
        .where(Sheet.class_id.in_(owned_class_ids(scope)))
        .order_by(Sheet.created_at.asc(), Sheet.title.asc())
    ).scalars()
    return {sheet.class_id: sheet for sheet in rows}  # last write per class wins


def class_summary(
    db: Session,
    scope: Scope,
    school_class: Class,
    *,
    counts: dict[uuid.UUID, int] | None = None,
    pending: dict[uuid.UUID, int] | None = None,
    last_sheets: dict[uuid.UUID, Sheet] | None = None,
) -> ClassSummary:
    counts = counts if counts is not None else student_counts(db, scope)
    pending = pending if pending is not None else _pending_scan_counts(db, scope)
    last_sheets = last_sheets if last_sheets is not None else _last_sheets(db, scope)

    student_ids = [s.id for s in list_students(db, scope, school_class.id)]
    bands, needing = band_summary(db, scope.school_id, student_ids)
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


def home(db: Session, scope: Scope, teacher: Teacher) -> HomeOut:
    counts = student_counts(db, scope)
    pending = _pending_scan_counts(db, scope)
    last_sheets = _last_sheets(db, scope)
    return HomeOut(
        teacher=teacher_out(teacher),
        subjects=[subject_out(s) for s in list_subjects(db, scope.school_id)],
        classes=[
            class_summary(
                db,
                scope,
                c,
                counts=counts,
                pending=pending,
                last_sheets=last_sheets,
            )
            for c in list_classes(db, scope)
        ],
    )


def class_out_with_counts(db: Session, scope: Scope, school_class: Class) -> ClassOut:
    return class_out(
        school_class,
        student_count=student_counts(db, scope).get(school_class.id, 0),
        subject_ids=subject_ids_for_class(db, scope, school_class.id),
    )
