"""Classes, rosters, subjects, and the teacher home summary."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from alppy.api.deps import DbDep, ScopeDep, TeacherDep, TenantDep
from alppy.schemas import (
    ClassCreate,
    ClassOut,
    HomeOut,
    RosterCreate,
    StudentOut,
    SubjectOut,
)
from alppy.services import class_out, student_out, subject_out
from alppy.services import class_service as svc

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
    return svc.class_out_with_counts(db, scope, school_class)


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
