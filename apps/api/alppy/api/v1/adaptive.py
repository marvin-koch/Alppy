"""Adaptive, per-student sheets — the focal deliverable (F4).

Both planning endpoints can reach a model provider, so both are rate limited.
The planning itself lives in ``alppy.services.adaptive_service``; this module
owns the tenancy check, the limit, and turning an approved plan into printable
instances.

The approval endpoints (`/adaptive/approve`, `/adaptive/discard`) reach the gate
in ``alppy.services.approval`` directly rather than through ``load_optional``.
The gate is never optional: a deployment without the adaptive planner still must
not be able to print an unapproved item, and an approval route that 503s would
leave a teacher with items they cannot clear.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from alppy.api import errors
from alppy.api.deps import (
    AiRateLimit,
    DbDep,
    ScopeDep,
    StorageDep,
    TeacherDep,
    load_optional,
    start_job,
)
from alppy.core.config import get_settings
from alppy.models import Job
from alppy.models.enums import JobKind, JobStatus
from alppy.schemas import (
    AdaptiveApproveRequest,
    AdaptiveApproveResponse,
    AdaptiveBatchRequest,
    AdaptiveDiscardRequest,
    AdaptiveDiscardResponse,
    AdaptiveProposeRequest,
    AdaptiveProposeResponse,
    AdaptiveRegenerateRequest,
    AdaptiveRegenerateResponse,
    JobOut,
    SheetOut,
)
from alppy.services import job_out, sheet_out
from alppy.services import sheet_service as sheet_svc
from alppy.services.approval import approve_exercises, discard_exercises
from alppy.services.class_service import get_class, list_students

router = APIRouter(tags=["adaptive"])


@router.post(
    "/adaptive/propose", response_model=AdaptiveProposeResponse, dependencies=[AiRateLimit]
)
def propose(
    payload: AdaptiveProposeRequest, teacher: TeacherDep, scope: ScopeDep, db: DbDep
) -> AdaptiveProposeResponse:
    """Target each student's gaps. Generated items still need approval."""
    school_class = get_class(db, scope, payload.class_id)
    student_ids = list(payload.student_ids)
    if student_ids:
        known = {s.id for s in list_students(db, scope, school_class.id)}
        unknown = [str(i) for i in student_ids if i not in known]
        if unknown:
            raise errors.not_found("student", ids=unknown)
    else:
        student_ids = [s.id for s in list_students(db, scope, school_class.id)]
    if not student_ids:
        raise errors.unprocessable("this class has no students yet")

    propose_adaptive = load_optional(
        "alppy.services.adaptive_service", "propose_adaptive", feature="adaptive planning"
    )
    # `language` stays an explicit override and is normally absent. The sheet's
    # language follows the source material (the service reads it off the
    # corpus); the teacher's locale is only the last resort for a subject with
    # nothing indexed yet. A teacher reading Alppy in English whose class works
    # in French must not be handed English exercises.
    response: AdaptiveProposeResponse = propose_adaptive(
        db,
        school_id=scope.school_id,
        class_id=payload.class_id,
        subject_id=payload.subject_id,
        student_ids=student_ids,
        items_per_student=payload.items_per_student,
        allow_generation=payload.allow_generation,
        language=payload.language,
        fallback_language=str(teacher.locale) or get_settings().default_locale,
        group=payload.group,
    )
    return response


@router.post("/adaptive/approve", response_model=AdaptiveApproveResponse)
def approve(
    payload: AdaptiveApproveRequest, scope: ScopeDep, db: DbDep
) -> AdaptiveApproveResponse:
    """Approve generated exercises for printing.

    Returns the ids actually stamped, which is not necessarily the ids asked
    for: anything that is not an AI-generated exercise in this school is left
    alone. The client compares the two and can say so rather than assuming.
    """
    approved = approve_exercises(
        db, school_id=scope.school_id, exercise_ids=payload.exercise_ids
    )
    db.commit()
    return AdaptiveApproveResponse(approved=len(approved), exercise_ids=approved)


@router.post("/adaptive/discard", response_model=AdaptiveDiscardResponse)
def discard(
    payload: AdaptiveDiscardRequest, scope: ScopeDep, db: DbDep
) -> AdaptiveDiscardResponse:
    """Throw generated exercises away. They are never proposed or printed again."""
    discarded = discard_exercises(
        db, school_id=scope.school_id, exercise_ids=payload.exercise_ids
    )
    db.commit()
    return AdaptiveDiscardResponse(discarded=len(discarded), exercise_ids=discarded)


@router.post(
    "/adaptive/regenerate",
    response_model=AdaptiveRegenerateResponse,
    dependencies=[AiRateLimit],
)
def regenerate(
    payload: AdaptiveRegenerateRequest, scope: ScopeDep, db: DbDep
) -> AdaptiveRegenerateResponse:
    """Replace one generated item with a fresh one aimed at the same gap.

    Replaces, never appends: the old item is discarded in the same transaction,
    so the sheet keeps its length and the rejected version cannot come back.
    """
    regenerate_exercise = load_optional(
        "alppy.services.adaptive_service", "regenerate_exercise", feature="adaptive planning"
    )
    generation_error = load_optional(
        "alppy.services.adaptive_service", "AdaptiveGenerationError", feature="adaptive planning"
    )
    try:
        proposal = regenerate_exercise(db, school_id=scope.school_id, exercise_id=payload.exercise_id)
    except generation_error as exc:
        raise errors.unprocessable(f"could not regenerate this exercise: {exc}") from exc
    return AdaptiveRegenerateResponse(
        replaced_exercise_id=payload.exercise_id, proposal=proposal
    )


@router.post(
    "/adaptive/batch",
    response_model=SheetOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[AiRateLimit],
)
def create_batch(
    payload: AdaptiveBatchRequest,
    teacher: TeacherDep,
    scope: ScopeDep,
    db: DbDep,
    storage: StorageDep,
) -> SheetOut:
    """Turn approved plans into one sheet with a different page per student.

    Creating the sheet is not rendering it: the caller follows this with
    ``POST /adaptive/batch/{id}/render``, which returns the job to poll. Two
    calls because binding 28 students to their item lists is fast and
    synchronous, while driving a headless browser over 170 pages is not.
    """
    sheet = sheet_svc.create_adaptive_sheet(db, scope, teacher.id, payload)
    db.commit()
    db.refresh(sheet)
    return sheet_out(sheet, storage=storage)


@router.post(
    "/adaptive/batch/{sheet_id}/render",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def render_batch(sheet_id: uuid.UUID, scope: ScopeDep, db: DbDep) -> JobOut:
    """Queue the single PDF that holds every student's page, in order."""
    sheet = sheet_svc.get_sheet(db, scope, sheet_id)
    if not sheet.instances:
        raise errors.unprocessable("this batch has no student instances to print")
    load_optional("alppy.sheets.render", "render_adaptive_batch", feature="PDF rendering")

    job = Job(
        id=uuid.uuid4(),
        school_id=scope.school_id,
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
