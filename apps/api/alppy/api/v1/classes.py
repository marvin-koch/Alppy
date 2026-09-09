"""Classes, rosters, subjects, and the teacher home summary."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from alppy.api import errors
from alppy.api.deps import DbDep, ScopeDep, TeacherDep, TenantDep, scoped_get
from alppy.models import School, Subject
from alppy.schemas import (
    BranchOrder,
    ClassCreate,
    ClassOut,
    ClassTeacherOut,
    ClassUpdate,
    ColleagueOut,
    HomeOut,
    RosterCreate,
    SchoolOut,
    SchoolUpdate,
    StudentOut,
    StudentUpdate,
    SubjectCreate,
    SubjectOut,
    SubjectUpdate,
)
from alppy.services import class_out, school_out, student_out, subject_out
from alppy.services import class_service as svc
from alppy.services import nouns_service as nouns

router = APIRouter(tags=["classes"])


@router.get("/home", response_model=HomeOut)
def home(teacher: TeacherDep, scope: ScopeDep, db: DbDep) -> HomeOut:
    """Everything the teacher home screen needs, in one round trip.

    Per class: how many students, the last sheet, how many scans are waiting to
    be reviewed, how many students have at least one weak or fading
    competency, and the band histogram behind that number.
    """
    return svc.home(db, scope, teacher)


@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(school_id: TenantDep, db: DbDep) -> list[SubjectOut]:
    return [subject_out(s) for s in svc.list_subjects(db, school_id)]


@router.get("/classes", response_model=list[ClassOut])
def list_classes(scope: ScopeDep, db: DbDep) -> list[ClassOut]:
    counts = svc.student_counts(db, scope)
    return [
        class_out(
            c,
            student_count=counts.get(c.id, 0),
            subject_ids=svc.taught_subject_ids_for_class(db, scope, c.id),
        )
        for c in svc.list_classes(db, scope)
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
def list_students(class_id: uuid.UUID, scope: ScopeDep, db: DbDep) -> list[StudentOut]:
    svc.get_class(db, scope, class_id)
    return [student_out(s) for s in svc.list_students(db, scope, class_id)]


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
    return subject_out(nouns.update_subject(db, scope, subject, labels=payload.labels))


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


@router.delete("/students/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_student(
    student_id: uuid.UUID,
    scope: ScopeDep,
    db: DbDep,
    confirm: Annotated[str, Query(description="the pupil's own uid, typed back")],
) -> None:
    """Destroy a pupil and every attempt, snapshot and printed copy of theirs.

    The only endpoint in Alppy that destroys evidence. `confirm` is the pupil's
    UID rather than a boolean, so a caller firing at the wrong row fails
    instead of deleting the wrong child. Unenrolling is `DELETE
    .../enrollment` and is what almost every caller actually wants.
    """
    student = svc.get_student(db, scope, student_id)
    nouns.delete_student(db, scope, student, confirm_uid=confirm)
    db.commit()
