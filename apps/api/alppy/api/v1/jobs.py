"""Job status. Every slow operation in Alppy has a row here to poll."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from alppy.api import errors
from alppy.api.deps import DbDep, TenantDep
from alppy.models import Job
from alppy.models.enums import JobKind, JobStatus
from alppy.schemas import JobOut
from alppy.services import job_out

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    school_id: TenantDep,
    db: DbDep,
    kind: Annotated[JobKind | None, Query()] = None,
    job_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[JobOut]:
    stmt = select(Job).where(Job.school_id == school_id)
    if kind is not None:
        stmt = stmt.where(Job.kind == kind)
    if job_status is not None:
        stmt = stmt.where(Job.status == job_status)
    rows = db.execute(stmt.order_by(Job.created_at.desc()).limit(limit)).scalars()
    return [job_out(j) for j in rows]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, school_id: TenantDep, db: DbDep) -> JobOut:
    job = db.execute(
        select(Job).where(Job.id == job_id).where(Job.school_id == school_id)
    ).scalar_one_or_none()
    if job is None:
        raise errors.not_found("job", id=str(job_id))
    return job_out(job)
