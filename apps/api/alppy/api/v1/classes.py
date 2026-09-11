"""Classes, rosters, subjects, and the teacher home summary."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from alppy.api import errors
from alppy.api.deps import DbDep, ScopeDep, StorageDep, TeacherDep, TenantDep, scoped_get
from alppy.models import School, Subject, Teacher
from alppy.models.enums import EventKind, EventSubject
from alppy.schemas import (
    BranchOrder,
    ClassCreate,
    ClassExportOut,
    ClassOut,
    ClassTeacherOut,
    ClassUpdate,
    ColleagueOut,
    HomeOut,
    RosterCreate,
    SchoolCreate,
    SchoolOut,
    SchoolUpdate,
    SchoolYearOut,
    StudentConfirmation,
    StudentExportOut,
    StudentOut,
    StudentUpdate,
    SubjectCreate,
    SubjectOut,
    SubjectUpdate,
)
from alppy.services import (
    class_out,
    event_service,
    export_service,
    school_out,
    student_out,
    subject_out,
)
from alppy.services import class_service as svc
from alppy.services import nouns_service as nouns

router = APIRouter(tags=["classes"])


@router.get("/home", response_model=HomeOut)
def home(
    teacher: TeacherDep,
    scope: ScopeDep,
    db: DbDep,
    school_year_id: Annotated[uuid.UUID | None, Query()] = None,
) -> HomeOut:
    """Everything the teacher home screen needs, in one round trip.

    Per class: how many students, the last sheet, how many scans are waiting to
    be reviewed, how many students have at least one weak or fading
    competency, and the band histogram behind that number.

    ``school_year_id`` shows a past year's groups instead of the ones running
    now. Discover the ids from ``GET /school-years``.
    """
    return svc.home(db, scope, teacher, school_year_id=school_year_id)


@router.get("/school-years", response_model=list[SchoolYearOut])
def list_school_years(school_id: TenantDep, db: DbDep) -> list[SchoolYearOut]:
    """This establishment's years, newest first.

    Every `school_year_id` filter in this API needs an id, and until now there
    was no way to be told one (audit 02, C3).
    """
    return [
        SchoolYearOut(
            id=y.id,
            label=y.label,
            starts_on=y.starts_on,
            ends_on=y.ends_on,
            is_current=y.is_current,
        )
        for y in svc.list_school_years(db, school_id)
    ]


@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(school_id: TenantDep, db: DbDep) -> list[SubjectOut]:
    return [subject_out(s) for s in svc.list_subjects(db, school_id)]


@router.get("/classes", response_model=list[ClassOut])
def list_classes(
    scope: ScopeDep,
    db: DbDep,
    school_year_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ClassOut]:
    """The classes this teacher has a footing in.

    ``school_year_id`` selects a past year's groups. It does not change whose
    footing is read: that is still today's, because "may I open this" is a
    question about the reader and not about the year.
    """
    counts = svc.student_counts(db, scope)
    # Both maps are one query each. The branch nav used to be resolved per
    # card, so a teacher with six classes paid six extra round trips for a list
    # (audit 03, B23) — the same shape `counts` had already been batched into.
    branches = svc.taught_subject_ids_by_class(db, scope)
    return [
        class_out(
            c,
            student_count=counts.get(c.id, 0),
            subject_ids=branches.get(c.id, []),
        )
        for c in svc.list_classes(db, scope, school_year_id=school_year_id)
    ]


@router.post("/classes", response_model=ClassOut, status_code=status.HTTP_201_CREATED)
def create_class(
    payload: ClassCreate, teacher: TeacherDep, scope: ScopeDep, db: DbDep
) -> ClassOut:
    school_class = svc.create_class(db, scope, teacher, payload)
    db.commit()
    return class_out(school_class, student_count=0, subject_ids=[])


@router.get("/classes/{class_id}", response_model=ClassOut)
def get_class(class_id: uuid.UUID, scope: ScopeDep, db: DbDep) -> ClassOut:
    school_class = svc.get_class(db, scope, class_id)
    return svc.class_out_with_counts(db, scope, school_class, detail=True)


@router.get("/classes/{class_id}/students", response_model=list[StudentOut])
def list_students(
    class_id: uuid.UUID,
    scope: ScopeDep,
    db: DbDep,
    on: Annotated[date | None, Query()] = None,
) -> list[StudentOut]:
    """Who sits in this class, today or on a past day.

    ``on`` is what makes a pile from November reconcile against November's
    group rather than against the one sitting there now — the enrolment rows
    are time-bound (0027), and without a way to ask, every read of a roster
    silently meant "today" (audit 02, C3).
    """
    svc.get_class(db, scope, class_id)
    return [student_out(s) for s in svc.list_students(db, scope, class_id, on=on)]


@router.post(
    "/classes/{class_id}/students",
    response_model=list[StudentOut],
    status_code=status.HTTP_201_CREATED,
)
def add_students(
    class_id: uuid.UUID, payload: RosterCreate, scope: ScopeDep, db: DbDep
) -> list[StudentOut]:
    """Paste a roster. Numbers are assigned sequentially and become the UIDs."""
    school_class = svc.get_class(db, scope, class_id)
    created = svc.add_students(db, scope, school_class, payload)
    db.commit()
    return [student_out(s) for s in created]


@router.post(
    "/classes/{class_id}/students/{student_id}/enrollment",
    response_model=list[StudentOut],
    status_code=status.HTTP_201_CREATED,
)
def enroll_student(
    class_id: uuid.UUID, student_id: uuid.UUID, scope: ScopeDep, db: DbDep
) -> list[StudentOut]:
    """Seat an existing pupil in another of this teacher's classes.

    Deliberately not part of the roster paste: that mints a UID and a number
    and is how a pupil comes to EXIST. This one says a pupil who already exists
    also sits here — their identifier is untouched, which is what keeps every
    sheet already in a pile decodable (I-platform-09).

    Idempotent, and returns the roster rather than the enrollment: what the
    caller wanted to know is who is in the room now.
    """
    school_class = svc.get_class(db, scope, class_id)
    student = svc.get_student(db, scope, student_id)
    svc.enroll(db, school_class, student)
    db.commit()
    return [student_out(s) for s in svc.list_students(db, scope, class_id)]


@router.delete(
    "/classes/{class_id}/students/{student_id}/enrollment",
    response_model=list[StudentOut],
)
def unenroll_student(
    class_id: uuid.UUID, student_id: uuid.UUID, scope: ScopeDep, db: DbDep
) -> list[StudentOut]:
    """Take a pupil out of a class without touching their record.

    Not a delete: the pupil, their UID, their attempts and their snapshots all
    survive — they simply stop appearing in this class's roster, matrix and
    tree. Refused on the pupil's own home class, which is where the UID came
    from and is a NOT NULL column.
    """
    school_class = svc.get_class(db, scope, class_id)
    student = svc.get_student(db, scope, student_id)
    svc.unenroll(db, school_class, student)
    db.commit()
    return [student_out(s) for s in svc.list_students(db, scope, class_id)]


# --------------------------------------------------------------------------
# Who teaches which branch here (D75 — the endpoints D57 deferred)
#
# Shaped like the enrollment pair above: idempotent, and each returns the LIST
# the caller wanted to know about rather than the row it wrote.
# --------------------------------------------------------------------------
@router.get("/colleagues", response_model=list[ColleagueOut])
def list_colleagues(tenant: TenantDep, db: DbDep) -> list[ColleagueOut]:
    """Everyone in this staffroom, for the branch picker.

    ``TenantDep``, not ``ScopeDep``: the staffroom is a school-level fact and
    carries no ownership. No email in the payload — see ``ColleagueOut``.
    """
    return [
        ColleagueOut(id=t.id, first_name=t.first_name, last_name=t.last_name)
        for t in svc.list_colleagues(db, tenant)
    ]


@router.get("/classes/{class_id}/teachers", response_model=list[ClassTeacherOut])
def class_teachers(class_id: uuid.UUID, scope: ScopeDep, db: DbDep) -> list[ClassTeacherOut]:
    return svc.teachers_for_class(db, scope, class_id)


@router.post(
    "/classes/{class_id}/teachers/{teacher_id}/branches/{subject_id}",
    response_model=list[ClassTeacherOut],
    status_code=status.HTTP_201_CREATED,
)
def assign_branch(
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
    subject_id: uuid.UUID,
    scope: ScopeDep,
    db: DbDep,
) -> list[ClassTeacherOut]:
    """Record that a teacher takes this branch in this class.

    Any owner of the class may do this, matching ``enroll``. A head-teacher-only
    rule is one `if`, but every ownership failure in this codebase is a 404 and
    this would be the first 403 — worth deciding once, alongside who may rename
    a school, rather than three times.
    """
    school_class = svc.get_class(db, scope, class_id)
    teacher = svc.get_colleague(db, scope.school_id, teacher_id)
    subject = scoped_get(db, Subject, subject_id, scope.school_id, label="subject")
    svc.assign_branch(db, scope, school_class, teacher, subject)
    db.commit()
    return svc.teachers_for_class(db, scope, class_id)


@router.delete(
    "/classes/{class_id}/teachers/{teacher_id}/branches/{subject_id}",
    response_model=list[ClassTeacherOut],
)
def unassign_branch(
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
    subject_id: uuid.UUID,
    scope: ScopeDep,
    db: DbDep,
) -> list[ClassTeacherOut]:
    """Stop a teacher taking this branch here.

    Not a delete of anything else: the sheets, piles and attempts stay, they
    simply stop being visible to that teacher. A class can never become
    unowned this way — `head_teacher_id` is NOT NULL.
    """
    school_class = svc.get_class(db, scope, class_id)
    svc.unassign_branch(db, scope, school_class, teacher_id, subject_id)
    db.commit()
    return svc.teachers_for_class(db, scope, class_id)


@router.post(
    "/classes/{class_id}/subjects/{subject_id}",
    response_model=ClassOut,
    status_code=status.HTTP_201_CREATED,
)
def declare_branch(
    class_id: uuid.UUID, subject_id: uuid.UUID, scope: ScopeDep, db: DbDep
) -> ClassOut:
    """Say this class studies this Branch, and that the caller takes it."""
    school_class = svc.get_class(db, scope, class_id)
    svc.declare_subject(db, scope, school_class.id, subject_id)
    db.commit()
    return svc.class_out_with_counts(db, scope, school_class, detail=True)


@router.delete("/classes/{class_id}/subjects/{subject_id}", response_model=ClassOut)
def undeclare_branch(
    class_id: uuid.UUID, subject_id: uuid.UUID, scope: ScopeDep, db: DbDep
) -> ClassOut:
    """Remove a Branch from a class. Refused while it still holds sheets."""
    school_class = svc.get_class(db, scope, class_id)
    svc.undeclare_subject(db, scope, school_class, subject_id)
    db.commit()
    return svc.class_out_with_counts(db, scope, school_class, detail=True)


@router.put("/classes/{class_id}/subjects", response_model=ClassOut)
def reorder_branches(
    class_id: uuid.UUID, payload: BranchOrder, scope: ScopeDep, db: DbDep
) -> ClassOut:
    """Set the Branch nav order. It is the class's order, not one teacher's."""
    school_class = svc.get_class(db, scope, class_id)
    svc.reorder_subjects(db, scope, school_class, payload.subject_ids)
    db.commit()
    return svc.class_out_with_counts(db, scope, school_class, detail=True)


# --------------------------------------------------------------------------
# Editing the nouns a school owns (D76)
#
# Everything below writes to something only the seed could create before. Each
# route is thin: the refusals live in `nouns_service`, next to the reasons.
# --------------------------------------------------------------------------
@router.post("/subjects", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
def create_subject(payload: SubjectCreate, scope: ScopeDep, db: DbDep) -> SubjectOut:
    row = nouns.create_subject(db, scope, key=payload.key, labels=payload.labels)
    db.commit()
    return subject_out(row)


@router.patch("/subjects/{subject_id}", response_model=SubjectOut)
def update_subject(
    subject_id: uuid.UUID, payload: SubjectUpdate, scope: ScopeDep, db: DbDep
) -> SubjectOut:
    subject = scoped_get(db, Subject, subject_id, scope.school_id, label="subject")
    renamed = nouns.update_subject(db, scope, subject, labels=payload.labels)
    # The service flushes; the commit is the router's, as it is in this file's
    # ten other write handlers. Without it `get_db` closes the session on the
    # way out and rolls the rename back — while the response, serialised from
    # the in-memory object, faithfully reports the new labels (audit 02, H1).
    db.commit()
    return subject_out(renamed)


@router.patch("/classes/{class_id}", response_model=ClassOut)
def update_class(
    class_id: uuid.UUID, payload: ClassUpdate, scope: ScopeDep, db: DbDep
) -> ClassOut:
    school_class = svc.get_class(db, scope, class_id)
    nouns.rename_class(db, scope, school_class, label=payload.label, code=payload.code)
    db.commit()
    return svc.class_out_with_counts(db, scope, school_class, detail=True)


@router.patch("/schools/me", response_model=SchoolOut)
def update_school(payload: SchoolUpdate, tenant: TenantDep, db: DbDep) -> SchoolOut:
    """Rename the school this session acts for.

    `default_curriculum` is not in `SchoolUpdate` and that is deliberate: it
    was resolved into every `Chapter.primary_competency_id` at seed time (D56),
    so changing it here would silently re-file the whole tree.

    Any member may rename the school, and that is a decision rather than a
    missing check: the staffroom is flat (D85). A rename touches no other
    school's data and is reversible by the next colleague to notice.
    """
    school = db.get(School, tenant)
    if school is None:
        raise errors.not_found("school", id=str(tenant))
    row = nouns.rename_school(db, school, name=payload.name, canton=payload.canton)
    db.commit()
    return school_out(row)


@router.patch("/students/{student_id}", response_model=StudentOut)
def update_student(
    student_id: uuid.UUID, payload: StudentUpdate, scope: ScopeDep, db: DbDep
) -> StudentOut:
    student = svc.get_student(db, scope, student_id)
    nouns.rename_student(
        db, scope, student, first_name=payload.first_name, last_name=payload.last_name
    )
    db.commit()
    return student_out(student)


@router.get("/classes/{class_id}/export", response_model=ClassExportOut)
def export_class(class_id: uuid.UUID, scope: ScopeDep, db: DbDep) -> ClassExportOut:
    """The whole class, in one document (D36).

    `docs/privacy.md` §4 has promised this since it was written — "the mechanism
    a school uses to take its data with it" — and only the per-pupil route
    existed, so a school of four hundred children exercised its portability
    right twenty-four pupils at a time. A procurement question about leaving now
    has an answer that is a URL.

    Gated by `get_class`, the same gate every other class route uses, and the
    roster it exports is `list_students` — the pupils sitting here **today**.
    Deliberately not everyone who ever sat here: a teacher who arrived in March
    has no standing over a pupil who left in October, and that gate is narrower
    than "ever enrolled" for a reason. A pupil who has left is still exportable
    through the per-pupil route, under the gate that governs them.
    """
    klass = svc.get_class(db, scope, class_id)
    students = svc.list_students(db, scope, class_id)
    return export_service.class_export(db, scope.school_id, klass, students)


@router.get("/students/{student_id}/export", response_model=StudentExportOut)
def export_student(student_id: uuid.UUID, scope: ScopeDep, db: DbDep) -> StudentExportOut:
    """Everything held about one pupil, in one document.

    A parent may ask what is held, and a school leaving Alppy has to be able to
    take it. Until now the only route out of the product was `DELETE`, which
    answers "what do you have on my child" with "nothing, now" (audit 02, H8).

    Reads across every year the pupil has been here: `Person` is the durable
    identity and `Student` one year's enrolment record, so a pupil who repeated
    a year has two enrolments and one continuous record behind them (0028).

    Gated exactly like the destructive route below — `get_student` — so a
    teacher who can erase a pupil can read what they would be erasing, and
    nobody else can do either.
    """
    student = svc.get_student(db, scope, student_id)
    return export_service.student_export(db, scope.school_id, student.person_id)


@router.post("/students/{student_id}/anonymise", response_model=StudentOut)
def anonymise_student(
    student_id: uuid.UUID,
    payload: StudentConfirmation,
    scope: ScopeDep,
    db: DbDep,
) -> StudentOut:
    """Answer a parent's erasure request without destroying the evidence.

    The default path, and the one to reach for first. The names go; the uid,
    the attempts, the snapshots and the notes stay — so a class statistic keeps
    its shape and a band already shown to somebody does not change underneath
    them, while the pupil stops being identifiable. `DELETE` below is still
    there for the cases that genuinely need erasure.

    Same confirmation and same gate as deletion: the pupil's own uid typed
    back, and the head teacher of their home class. It destroys nothing, but it
    is irreversible and it is an answer to a request made about a named child.

    Idempotent. A second request for the same pupil is the same request, and
    re-stamping `anonymised_at` would move a date somebody may already have
    been shown.
    """
    student = svc.get_student(db, scope, student_id)
    nouns.anonymise_student(db, scope, student, confirm_uid=payload.confirm)
    db.commit()
    db.refresh(student)
    return student_out(student)


@router.delete("/students/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_student(
    student_id: uuid.UUID,
    payload: StudentConfirmation,
    scope: ScopeDep,
    db: DbDep,
    storage: StorageDep,
) -> None:
    """Destroy a pupil and every attempt, snapshot and printed copy of theirs.

    The only endpoint in Alppy that destroys evidence. The confirmation is the
    pupil's UID rather than a boolean, so a caller firing at the wrong row
    fails instead of deleting the wrong child — and it travels in the BODY,
    because a uid in the URL is written to every log between here and the
    browser. Unenrolling is `DELETE .../enrollment` and is what almost every
    caller actually wants.

    The storage handle is here because erasure now means erasure: the page
    images and the answer-box crops go too. Until B14 the rows cascaded and
    every photograph of the child's handwriting stayed in object storage
    forever — unreachable through the product, which is not the same as gone,
    and not what a parent asking for erasure was told had happened.
    """
    student = svc.get_student(db, scope, student_id)
    nouns.delete_student(
        db, scope, student, confirm_uid=payload.confirm, storage=storage
    )
    db.commit()


@router.post("/schools", response_model=SchoolOut, status_code=status.HTTP_201_CREATED)
def create_school(
    payload: SchoolCreate, teacher: TeacherDep, db: DbDep
) -> SchoolOut:
    """Create a second establishment, and join it.

    The creator becomes a member in the same breath, because a school nobody
    can act for is not a school — and `get_membership` would refuse the very
    next request if they had to be added separately.

    It does NOT switch the session. Creating a school and acting for it are two
    decisions, and doing both at once would move the tenant out from under a
    teacher who was only setting things up; `POST /auth/school/{id}` is the
    deliberate move.

    `default_curriculum` is settable here and nowhere else: it is resolved into
    every chapter's primary competency (D56), so the one safe time to choose it
    is before any chapters exist.

    Any teacher may do this, and nothing caps how often (D85). It reaches no
    existing data — the school it makes is empty and the caller is its only
    member — so this is housekeeping rather than a privilege question, but it is
    the one action here a script could repeat.
    """
    school = School(
        id=uuid.uuid4(),
        name=payload.name.strip(),
        canton=(payload.canton or "").strip().upper() or None,
        default_curriculum=payload.default_curriculum,
    )
    db.add(school)
    db.flush()
    svc.join_school(db, teacher.id, school.id)
    db.commit()
    return school_out(school)


@router.post(
    "/schools/{school_id}/teachers/{teacher_id}",
    response_model=list[ColleagueOut],
    status_code=status.HTTP_201_CREATED,
)
def add_teacher_to_school(
    school_id: uuid.UUID, teacher_id: uuid.UUID, teacher: TeacherDep, db: DbDep
) -> list[ColleagueOut]:
    """Add a colleague to a staffroom this teacher works in. Idempotent.

    Gated on the CALLER's own membership, not on the school existing: a school
    you do not work at reads as missing, so this cannot be used to discover
    which school ids are real.

    Membership is the whole check — there is no admin tier, deliberately (D85),
    which is exactly why the act is recorded: joining a staffroom is gaining
    sight of every class in the school, and in a flat model that is the change
    most worth being able to point at afterwards (audit 03, B16).
    """
    mine = {s.id for s in svc.schools_for_teacher(db, teacher.id)}
    if school_id not in mine:
        raise errors.not_found("school", id=str(school_id))
    joining = db.get(Teacher, teacher_id)
    if joining is None:
        raise errors.not_found("teacher", id=str(teacher_id))
    svc.join_school(db, joining.id, school_id)
    event_service.record(
        db,
        school_id=school_id,
        kind=EventKind.TEACHER_JOINED,
        subject_type=EventSubject.TEACHER,
        subject_id=joining.id,
        summary=f"{joining.first_name} {joining.last_name}".strip(),
        actor_id=teacher.id,
    )
    db.commit()
    return [
        ColleagueOut(id=t.id, first_name=t.first_name, last_name=t.last_name)
        for t in svc.list_colleagues(db, school_id)
    ]


@router.delete(
    "/schools/{school_id}/teachers/{teacher_id}",
    response_model=list[ColleagueOut],
)
def remove_teacher_from_school(
    school_id: uuid.UUID, teacher_id: uuid.UUID, teacher: TeacherDep, db: DbDep
) -> list[ColleagueOut]:
    """End a colleague's membership of a staffroom this teacher works in.

    The counterpart `add_teacher_to_school` never had. Gated the same way — on
    the caller's own membership, so a school you do not work at reads as
    missing — and idempotent in the same sense: removing someone already gone
    changes nothing and still answers with the staffroom.

    Ends the membership rather than deleting the row (D87): "they were here from
    August to February" is what justifies every grade they recorded, and it is
    what lets `ever_shared_student_ids` say a substitute and a pupil once shared
    a room. `svc.leave_school` holds the two refusals — the last member, and a
    teacher still named as a class's head — and says why.

    Note there is no self-check: a teacher may remove themselves, which is how
    someone leaves a school they no longer work at. The last-member refusal is
    what stops that emptying a staffroom nobody could then re-enter.
    """
    mine = {s.id for s in svc.schools_for_teacher(db, teacher.id)}
    if school_id not in mine:
        raise errors.not_found("school", id=str(school_id))
    leaving = db.get(Teacher, teacher_id)
    if leaving is None:
        raise errors.not_found("teacher", id=str(teacher_id))
    svc.leave_school(db, leaving.id, school_id)
    event_service.record(
        db,
        school_id=school_id,
        kind=EventKind.TEACHER_LEFT,
        subject_type=EventSubject.TEACHER,
        subject_id=leaving.id,
        summary=f"{leaving.first_name} {leaving.last_name}".strip(),
        actor_id=teacher.id,
    )
    db.commit()
    return [
        ColleagueOut(id=t.id, first_name=t.first_name, last_name=t.last_name)
        for t in svc.list_colleagues(db, school_id)
    ]
