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
    School,
    SchoolYear,
    Sheet,
    Student,
    Subject,
    Teacher,
    class_student,
    class_subject,
    class_teacher_subject,
    teacher_school,
)
from alppy.models.enums import ScanStatus
from alppy.schemas import (
    ClassCreate,
    ClassOut,
    ClassSummary,
    ClassTeacherOut,
    HomeOut,
    RosterCreate,
)
from alppy.services import class_out, subject_out, teacher_out
from alppy.services.enrollment import (
    enrolled_in_owned_classes,
    enrolled_student_ids,
    owned_class_ids,
    taught_here,
    taught_subject_ids,
)

__all__ = [
    "add_students",
    "assign_branch",
    "class_out_with_counts",
    "class_summary",
    "create_class",
    "current_school_year",
    "declare_subject",
    "declared_subject_ids_for_class",
    "enroll",
    "enrolled_in_owned_classes",
    "enrolled_student_ids",
    "get_class",
    "get_student",
    "home",
    "home_students",
    "join_school",
    "list_classes",
    "list_colleagues",
    "list_students",
    "list_subjects",
    "owned_class_ids",
    "reorder_subjects",
    "schools_for_teacher",
    "student_counts",
    "taught_subject_ids_for_class",
    "teachers_for_class",
    "unassign_branch",
    "undeclare_subject",
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
            .where(Class.id.in_(owned_class_ids(scope)))
            .order_by(Class.code.asc())
        ).scalars()
    )


def get_class(db: Session, scope: Scope, class_id: uuid.UUID) -> Class:
    """One class the caller has a footing in, or 404.

    A colleague's class reads as missing rather than forbidden, for the same
    reason another school's does: the response must not confirm the id exists.

    CLASS-GRAINED (D73): the head teacher, or anyone holding a branch here.
    That a teacher may open the class says nothing about which of its sheets,
    piles or bands they may see — those are ``taught_here``.
    """
    row = db.execute(
        select(Class).where(Class.id == class_id).where(Class.id.in_(owned_class_ids(scope)))
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


def _branch_ids(
    db: Session, scope: Scope, class_id: uuid.UUID, *, mine: bool
) -> list[uuid.UUID]:
    """The shared body of the two branch-list reads below.

    Order always comes from ``class_subject.position`` — the CLASS's nav
    order — even when the rows are narrowed to one teacher, so two co-teachers
    never see the same branches in different orders.

    The ownership filter is joined in here rather than trusting the caller's
    ``class_id``, the same as every other read in this module.
    """
    stmt = (
        select(class_subject.c.subject_id)
        .join(Class, Class.id == class_subject.c.class_id)
        .where(Class.id == class_id)
        .where(Class.id.in_(owned_class_ids(scope)))
        # `subject_id` breaks a tie: two subjects first taught in the same
        # instant can be assigned the same position (the PK is
        # (class_id, subject_id), so ON CONFLICT cannot serialise that), and a
        # branch list whose order wobbles between requests is worse than one
        # whose tie is resolved arbitrarily but consistently.
        .order_by(class_subject.c.position.asc(), class_subject.c.subject_id.asc())
    )
    if mine:
        stmt = stmt.where(
            class_subject.c.subject_id.in_(taught_subject_ids(scope, class_id))
        )
    return list(db.execute(stmt).scalars())


def taught_subject_ids_for_class(
    db: Session, scope: Scope, class_id: uuid.UUID
) -> list[uuid.UUID]:
    """The Branches THIS TEACHER takes in this class, in the class's order.

    What the Branch nav shows and what the tree walks (D73). Renamed from
    ``subject_ids_for_class`` rather than narrowed in place: the old name had
    two possible meanings after co-teaching, and under it every call site
    nobody reviewed would have gone on compiling with the other one.

    May be empty — a maître de classe who teaches nothing gets a roster and an
    empty tree. That is the honest answer, not a 404.
    """
    return _branch_ids(db, scope, class_id, mine=True)


def declared_subject_ids_for_class(
    db: Session, scope: Scope, class_id: uuid.UUID
) -> list[uuid.UUID]:
    """The Branches THE CLASS studies, in the order it met them.

    Declared in ``class_subject``, not derived. Until D57 this was
    `SELECT DISTINCT sheet.subject_id`, which was circular: the Branch level of
    the navigation only existed once somebody had already built a sheet inside
    one, so a new class opened onto nothing. ``declare_subject`` keeps the
    table current from the one place a class and a subject first meet.

    This is the superset. Only branch management wants it; everything a
    teacher reads wants ``taught_subject_ids_for_class``.
    """
    return _branch_ids(db, scope, class_id, mine=False)


def declare_subject(
    db: Session, scope: Scope, class_id: uuid.UUID, subject_id: uuid.UUID
) -> None:
    """Record that this class studies this Branch, and that the caller takes
    it. Idempotent in both halves.

    Called from ``sheet_service.create_sheet`` — the one place a class and a
    subject first come together — so the Branch list stays populated with no
    new step for the teacher, exactly as the old derived query did implicitly.

    **It writes both facts because the Branch nav now reads the second one**
    (``taught_subject_ids_for_class``, D73). A teacher who builds a French
    sheet and is not recorded as teaching French would immediately lose the
    sheet they just made: the branch would not be in their tree. Recording the
    assignment here is D57's own argument for recording the declaration here.

    The two writes are ordered, not merely grouped: ``class_teacher_subject``
    carries a composite FK onto ``class_subject``, so the declaration must
    land first or the assignment cannot.

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
    db.execute(
        pg_insert(class_teacher_subject)
        .values(class_id=class_id, teacher_id=scope.teacher_id, subject_id=subject_id)
        .on_conflict_do_nothing(index_elements=["class_id", "teacher_id", "subject_id"])
    )


def join_school(db: Session, teacher_id: uuid.UUID, school_id: uuid.UUID) -> None:
    """Record that this teacher works at this school. Idempotent.

    Membership is what ``deps.get_membership`` checks a cookie against, so a
    teacher without a row here can hold a valid signature and still act on
    nothing — which is the correct answer for someone who has left, and a
    silent lockout for someone who was never added. Every path that mints a
    teacher calls this: the seed, the migration's backfill, and the fixtures.
    """
    db.execute(
        pg_insert(teacher_school)
        .values(teacher_id=teacher_id, school_id=school_id)
        .on_conflict_do_nothing(index_elements=["teacher_id", "school_id"])
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
        head_teacher_id=teacher.id,
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
        # Pair-grained: "3 piles waiting" must mean three piles THIS teacher
        # has to mark, not three that happen to sit in a class they share.
        .where(taught_here(Sheet.class_id, Sheet.subject_id, scope))
        .where(Scan.status.in_(PENDING_SCAN_STATUSES))
        .group_by(Sheet.class_id)
    ).all()
    return {class_id: int(count) for class_id, count in rows}


def _last_sheets(db: Session, scope: Scope) -> dict[uuid.UUID, Sheet]:
    rows = db.execute(
        select(Sheet)
        .where(Sheet.school_id == scope.school_id)
        # Likewise: "last sheet" is the last one the reader made, not a
        # colleague's history homework showing up on their maths card.
        .where(taught_here(Sheet.class_id, Sheet.subject_id, scope))
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
        teacher=teacher_out(teacher, scope.school_id),
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


def get_colleague(db: Session, school_id: uuid.UUID, teacher_id: uuid.UUID) -> Teacher:
    """One teacher who works at this school, or 404.

    Reads ``teacher_school``, not ``home_school_id``: since D74 a teacher based
    elsewhere may still work here, and a picker that could not find them would
    make co-teaching impossible for exactly the people it is for.
    """
    row = db.execute(
        select(Teacher)
        .join(teacher_school, teacher_school.c.teacher_id == Teacher.id)
        .where(Teacher.id == teacher_id)
        .where(teacher_school.c.school_id == school_id)
    ).scalar_one_or_none()
    if row is None:
        raise errors.not_found("teacher", id=str(teacher_id))
    return row


def class_out_with_counts(
    db: Session, scope: Scope, school_class: Class, *, detail: bool = False
) -> ClassOut:
    """One class as the API reports it.

    ``detail`` adds the two fields only the class screen needs: what the class
    STUDIES (the superset of what the caller takes) and who teaches what. The
    list route leaves them off, or it would fan out a query per class.
    """
    row = class_out(
        school_class,
        student_count=student_counts(db, scope).get(school_class.id, 0),
        subject_ids=taught_subject_ids_for_class(db, scope, school_class.id),
    )
    row.head_teacher_id = school_class.head_teacher_id
    row.is_head = school_class.head_teacher_id == scope.teacher_id
    if detail:
        row.declared_subject_ids = declared_subject_ids_for_class(db, scope, school_class.id)
        row.teachers = teachers_for_class(db, scope, school_class.id)
    return row


# --------------------------------------------------------------------------
# Who teaches which branch here (D73, D75)
#
# D57 deferred this deliberately: "a teacher-facing endpoint to add and reorder
# branches ... is a real feature with its own review". This is that feature.
# --------------------------------------------------------------------------
def assign_branch(
    db: Session,
    scope: Scope,
    school_class: Class,
    teacher: Teacher,
    subject: Subject,
) -> None:
    """Record that this teacher takes this branch in this class. Idempotent.

    The security-bearing function of the pair, and the reason
    ``class_teacher_subject`` can safely carry no ``school_id``: the table's
    teacher end CAN belong to another school, and this is what closes it
    (I-platform-12). The membership check is against ``teacher_school``, not
    ``home_school_id`` — since D74 the first is where a teacher may work and
    the second only where their account is based.

    Declares the branch FIRST, for two reasons: the composite FK onto
    ``class_subject`` cannot be satisfied otherwise, and assigning history to
    5A plainly means 5A studies history — which is what a teacher means by it.

    ``ON CONFLICT DO NOTHING``: two colleagues added at once must not race into
    a duplicate-key error on an ordinary action.
    """
    if subject.school_id != school_class.school_id:
        raise errors.unprocessable("subject belongs to another school")
    member = db.execute(
        select(teacher_school.c.school_id)
        .where(teacher_school.c.teacher_id == teacher.id)
        .where(teacher_school.c.school_id == school_class.school_id)
    ).scalar_one_or_none()
    if member is None:
        raise errors.unprocessable("teacher does not work at this school")

    declare_subject(db, scope, school_class.id, subject.id)
    db.execute(
        pg_insert(class_teacher_subject)
        .values(class_id=school_class.id, teacher_id=teacher.id, subject_id=subject.id)
        .on_conflict_do_nothing(index_elements=["class_id", "teacher_id", "subject_id"])
    )
    db.flush()


def unassign_branch(
    db: Session,
    scope: Scope,
    school_class: Class,
    teacher_id: uuid.UUID,
    subject_id: uuid.UUID,
) -> None:
    """Drop one assignment. Nothing else moves.

    The sheets, the piles and the attempts all stay exactly where they are;
    they simply stop being visible to that teacher. Needs no "you cannot remove
    the last owner" guard because ``head_teacher_id`` is NOT NULL — a class can
    never become unowned this way, which is the same trick that lets
    ``unenroll`` refuse only on the home class.

    Deleting an assignment that is not there is a no-op, not an error: the
    caller's intent is already satisfied.
    """
    db.execute(
        class_teacher_subject.delete()
        .where(class_teacher_subject.c.class_id == school_class.id)
        .where(class_teacher_subject.c.teacher_id == teacher_id)
        .where(class_teacher_subject.c.subject_id == subject_id)
    )
    db.flush()


def teachers_for_class(
    db: Session, scope: Scope, class_id: uuid.UUID
) -> list[ClassTeacherOut]:
    """Everyone with a footing in this class, and what each of them takes.

    The head teacher appears even when they take nothing — they are still the
    maître de classe, and a screen that omitted them would suggest the class
    has no owner.
    """
    school_class = get_class(db, scope, class_id)
    rows = db.execute(
        select(class_teacher_subject.c.teacher_id, class_teacher_subject.c.subject_id)
        .where(class_teacher_subject.c.class_id == class_id)
        .order_by(class_teacher_subject.c.assigned_at.asc())
    ).all()

    held: dict[uuid.UUID, list[uuid.UUID]] = {school_class.head_teacher_id: []}
    for teacher_id, subject_id in rows:
        held.setdefault(teacher_id, []).append(subject_id)

    order = {sid: i for i, sid in enumerate(declared_subject_ids_for_class(db, scope, class_id))}
    people = db.execute(select(Teacher).where(Teacher.id.in_(held))).scalars().all()
    return [
        ClassTeacherOut(
            teacher_id=t.id,
            first_name=t.first_name,
            last_name=t.last_name,
            # The CLASS's nav order, so two co-teachers never see the same
            # branches listed differently.
            subject_ids=sorted(held[t.id], key=lambda s: order.get(s, 10_000)),
            is_head=t.id == school_class.head_teacher_id,
        )
        for t in sorted(people, key=lambda t: (t.last_name, t.first_name))
    ]


def undeclare_subject(
    db: Session, scope: Scope, school_class: Class, subject_id: uuid.UUID
) -> None:
    """Remove a Branch from a class, refusing while it still holds sheets.

    A conflict rather than a cascade, for the same reason ``unenroll`` refuses
    on the home class: removing the branch would take existing sheets off the
    tree, and a teacher deleting a row from a settings screen is not saying
    "throw away the term's worksheets". The assignments beneath it go with it,
    which the composite FK handles.
    """
    held = db.execute(
        select(func.count(Sheet.id))
        .where(Sheet.class_id == school_class.id)
        .where(Sheet.subject_id == subject_id)
    ).scalar_one()
    if held:
        raise errors.conflict(
            "this branch still holds sheets in this class",
            # Its own code, not the generic `conflict`: this is a refusal the
            # teacher resolves by moving the sheets, and the screen has to be
            # able to say HOW MANY stand in the way. The generic sentence
            # ("no longer possible in the current state") names nothing.
            code="branch_holds_sheets",
            sheet_count=str(held),
        )
    db.execute(
        class_subject.delete()
        .where(class_subject.c.class_id == school_class.id)
        .where(class_subject.c.subject_id == subject_id)
    )
    db.flush()


def reorder_subjects(
    db: Session, scope: Scope, school_class: Class, subject_ids: list[uuid.UUID]
) -> None:
    """Set the Branch nav order for a class.

    Order is a property of the CLASS, not of a teacher (D73) — so this is one
    list, and every co-teacher sees the result. Any branch the caller omits
    keeps its place after the ones they named, rather than being dropped: a
    teacher reordering the two branches they can see must not silently
    renumber a colleague's.
    """
    declared = declared_subject_ids_for_class(db, scope, school_class.id)
    unknown = set(subject_ids) - set(declared)
    if unknown:
        raise errors.unprocessable("class does not study one of those branches")
    ordered = subject_ids + [s for s in declared if s not in subject_ids]
    for position, subject_id in enumerate(ordered):
        db.execute(
            class_subject.update()
            .where(class_subject.c.class_id == school_class.id)
            .where(class_subject.c.subject_id == subject_id)
            .values(position=position)
        )
    db.flush()


def schools_for_teacher(db: Session, teacher_id: uuid.UUID) -> list[School]:
    """Every staffroom this teacher works in, for the switcher.

    Reads ``teacher_school``, never ``home_school_id``: the column says where
    an account is based, this says where it may act (D74). Ordered by name so
    the rail does not reshuffle between requests.
    """
    return list(
        db.execute(
            select(School)
            .join(teacher_school, teacher_school.c.school_id == School.id)
            .where(teacher_school.c.teacher_id == teacher_id)
            .order_by(School.name.asc())
        ).scalars()
    )


def list_colleagues(db: Session, school_id: uuid.UUID) -> list[Teacher]:
    """Everyone in this staffroom, for the branch picker.

    Reads ``teacher_school`` rather than ``home_school_id``: a teacher based
    elsewhere who also works here belongs in the list (D74).
    """
    return list(
        db.execute(
            select(Teacher)
            .join(teacher_school, teacher_school.c.teacher_id == Teacher.id)
            .where(teacher_school.c.school_id == school_id)
            .order_by(Teacher.last_name.asc(), Teacher.first_name.asc())
        ).scalars()
    )
