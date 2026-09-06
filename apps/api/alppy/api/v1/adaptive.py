"""Adaptive, per-student sheets — the focal deliverable (F4).

Both endpoints can reach a model provider, so both are rate limited. The
planning itself lives in ``alppy.services.adaptive_service``; this module owns
the tenancy check, the limit, and turning an approved plan into printable
instances.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from alppy.api import errors
from alppy.api.deps import (
    AiRateLimit,
    DbDep,
    StorageDep,
    TeacherDep,
    TenantDep,
    load_optional,
    start_job,
)
from alppy.core.config import get_settings
from alppy.models import Job
from alppy.models.enums import JobKind, JobStatus
from alppy.schemas import (
    AdaptiveBatchRequest,
    AdaptiveProposeRequest,
    AdaptiveProposeResponse,
    JobOut,
    SheetOut,
)
from alppy.services import job_out, sheet_out
from alppy.services import sheet_service as sheet_svc
from alppy.services.class_service import get_class, list_students

router = APIRouter(tags=["adaptive"])


@router.post(
    "/adaptive/propose", response_model=AdaptiveProposeResponse, dependencies=[AiRateLimit]
)
def propose(
    payload: AdaptiveProposeRequest, teacher: TeacherDep, school_id: TenantDep, db: DbDep
) -> AdaptiveProposeResponse:
    """Target each student's gaps. Generated items still need approval."""
    school_class = get_class(db, school_id, payload.class_id)
    student_ids = list(payload.student_ids)
    if student_ids:
        known = {s.id for s in list_students(db, school_id, school_class.id)}
        unknown = [str(i) for i in student_ids if i not in known]
        if unknown:
            raise errors.not_found("student", ids=unknown)
    else:
        student_ids = [s.id for s in list_students(db, school_id, school_class.id)]
    if not student_ids:
        raise errors.unprocessable("this class has no students yet")

    propose_adaptive = load_optional(
        "alppy.services.adaptive_service", "propose_adaptive", feature="adaptive planning"
    )
    language = payload.language or str(teacher.locale) or get_settings().default_locale
    response: AdaptiveProposeResponse = propose_adaptive(
        db,
        school_id=school_id,
        class_id=payload.class_id,
        subject_id=payload.subject_id,
        student_ids=student_ids,
        items_per_student=payload.items_per_student,
        allow_generation=payload.allow_generation,
        language=language,
    )
    return response


@router.post(
    "/adaptive/batch",
    response_model=SheetOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[AiRateLimit],
)
def create_batch(
    payload: AdaptiveBatchRequest,
    teacher: TeacherDep,
    school_id: TenantDep,
    db: DbDep,
    storage: StorageDep,
) -> SheetOut:
    """Turn approved plans into one sheet with a different page per student."""
    sheet = sheet_svc.create_adaptive_sheet(db, school_id, teacher.id, payload)
    db.commit()
    db.refresh(sheet)
    return sheet_out(sheet, storage=storage)


@router.post(
    "/adaptive/batch/{sheet_id}/render",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def render_batch(sheet_id: uuid.UUID, school_id: TenantDep, db: DbDep) -> JobOut:
    """Queue the single PDF that holds every student's page, in order."""
    sheet = sheet_svc.get_sheet(db, school_id, sheet_id)
    if not sheet.instances:
        raise errors.unprocessable("this batch has no student instances to print")
    load_optional("alppy.sheets.render", "render_adaptive_batch", feature="PDF rendering")

    job = Job(
        id=uuid.uuid4(),
        school_id=school_id,
        kind=JobKind.GENERATE_ADAPTIVE,
        status=JobStatus.QUEUED,
        progress=0.0,
        message="queued for batch rendering",
        payload={"sheet_id": str(sheet.id)},
    )
    db.add(job)
    db.commit()
    start_job(db, job)
    db.refresh(job)
    return job_out(job)
