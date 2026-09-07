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
            subject_ids=svc.subject_ids_for_class(db, scope, c.id),
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
