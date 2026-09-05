"""Uploaded textbook PDFs and the exercises extracted from them.

The upload handler does exactly three things: validate, store, enqueue. Parsing
a 300-page PDF, chunking it, embedding it and asking a model to extract
exercises all happen in the worker (``alppy.ingest.pipeline``), which is why
this endpoint answers in milliseconds regardless of the file.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.api.deps import (
    DbDep,
    SettingsDep,
    StorageDep,
    TeacherDep,
    TenantDep,
    load_optional,
    read_upload,
)
from alppy.models import Exercise, Job, Source, Subject
from alppy.models.enums import JobKind, JobStatus
from alppy.schemas import ExerciseOut, ExerciseUpdate, JobOut, SourceOut
from alppy.services import exercise_out, job_out, source_out
from alppy.storage import storage_key

router = APIRouter(tags=["sources"])

PDF_ONLY = ("application/pdf",)


def _exercise_counts(db: Session, school_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(Exercise.source_id, func.count(Exercise.id))
        .where(Exercise.school_id == school_id)
        .where(Exercise.source_id.is_not(None))
        .group_by(Exercise.source_id)
    ).all()
    return {source_id: int(count) for source_id, count in rows if source_id is not None}


def _get_source(db: Session, school_id: uuid.UUID, source_id: uuid.UUID) -> Source:
    source = db.execute(
        select(Source).where(Source.id == source_id).where(Source.school_id == school_id)
    ).scalar_one_or_none()
    if source is None:
        raise errors.not_found("source", id=str(source_id))
    return source


@router.get("/sources", response_model=list[SourceOut])
def list_sources(school_id: TenantDep, db: DbDep) -> list[SourceOut]:
    counts = _exercise_counts(db, school_id)
    rows = db.execute(
        select(Source).where(Source.school_id == school_id).order_by(Source.created_at.desc())
    ).scalars()
    return [source_out(s, exercise_count=counts.get(s.id, 0)) for s in rows]


@router.post("/sources", response_model=SourceOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_source(
    teacher: TeacherDep,
    school_id: TenantDep,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    subject_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File()],
) -> SourceOut:
    subject = db.execute(
        select(Subject).where(Subject.id == subject_id).where(Subject.school_id == school_id)
    ).scalar_one_or_none()
    if subject is None:
        raise errors.not_found("subject", id=str(subject_id))

    payload = await read_upload(file, settings, allowed=PDF_ONLY)
    digest = hashlib.sha256(payload.data).hexdigest()

    duplicate = db.execute(
        select(Source).where(Source.school_id == school_id).where(Source.sha256 == digest)
    ).scalar_one_or_none()
    if duplicate is not None:
        # Re-uploading the same book should not re-ingest it, and must not
        # produce a second copy of every exercise.
        counts = _exercise_counts(db, school_id)
        return source_out(duplicate, exercise_count=counts.get(duplicate.id, 0))

    source_id = uuid.uuid4()
    key = storage_key("sources", school_id, source_id, payload.filename)
    storage.put_bytes(key, payload.data, payload.content_type)

    source = Source(
        id=source_id,
        school_id=school_id,
        subject_id=subject.id,
        uploaded_by_id=teacher.id,
        filename=payload.filename,
        storage_key=key,
        content_type=payload.content_type,
        size_bytes=payload.size,
        sha256=digest,
        status=JobStatus.QUEUED,
    )
    db.add(source)
    db.add(
        Job(
            id=uuid.uuid4(),
            school_id=school_id,
            kind=JobKind.INGEST_SOURCE,
            status=JobStatus.QUEUED,
            progress=0.0,
            message="queued for ingestion",
            payload={"source_id": str(source_id)},
        )
    )
    # Fail loudly here rather than accepting a file nothing will ever read.
    load_optional("alppy.ingest.pipeline", "ingest_source", feature="source ingestion")
    db.commit()
    db.refresh(source)
    return source_out(source, exercise_count=0)


@router.get("/sources/{source_id}", response_model=SourceOut)
def get_source(source_id: uuid.UUID, school_id: TenantDep, db: DbDep) -> SourceOut:
    source = _get_source(db, school_id, source_id)
    return source_out(source, exercise_count=_exercise_counts(db, school_id).get(source.id, 0))


@router.get("/sources/{source_id}/status", response_model=JobOut)
def get_source_status(source_id: uuid.UUID, school_id: TenantDep, db: DbDep) -> JobOut:
    """The ingestion job for this source, for the polling client."""
    source = _get_source(db, school_id, source_id)
    jobs = db.execute(
        select(Job)
        .where(Job.school_id == school_id)
        .where(Job.kind == JobKind.INGEST_SOURCE)
        .order_by(Job.created_at.desc())
    ).scalars()
    for job in jobs:
        if str((job.payload or {}).get("source_id")) == str(source.id):
            return job_out(job)
    raise errors.not_found("ingestion job", source_id=str(source_id))


@router.get("/sources/{source_id}/exercises", response_model=list[ExerciseOut])
def list_source_exercises(
    source_id: uuid.UUID, school_id: TenantDep, db: DbDep
) -> list[ExerciseOut]:
    source = _get_source(db, school_id, source_id)
    rows = db.execute(
        select(Exercise)
        .where(Exercise.school_id == school_id)
        .where(Exercise.source_id == source.id)
        .order_by(Exercise.source_page.asc(), Exercise.created_at.asc())
    ).scalars()
    return [exercise_out(e) for e in rows]


@router.patch("/exercises/{exercise_id}", response_model=ExerciseOut)
def update_exercise(
    exercise_id: uuid.UUID,
    payload: ExerciseUpdate,
    school_id: TenantDep,
    db: DbDep,
) -> ExerciseOut:
    """Edit an extracted or generated exercise, and approve it for printing.

    Approval is the gate an AI-generated exercise must pass before it can be
    printed — the teacher is the one who signs off, never the model.
    """
    exercise = db.execute(
        select(Exercise).where(Exercise.id == exercise_id).where(Exercise.school_id == school_id)
    ).scalar_one_or_none()
    if exercise is None:
        raise errors.not_found("exercise", id=str(exercise_id))

    if payload.statement is not None:
        exercise.statement = payload.statement
    if payload.options is not None:
        exercise.options = payload.options
    if payload.answer_index is not None:
        exercise.answer_index = payload.answer_index
    if payload.explanation is not None:
        exercise.explanation = payload.explanation
    if payload.difficulty is not None:
        exercise.difficulty = payload.difficulty
    if payload.approved is not None:
        exercise.approved_at = datetime.now(UTC) if payload.approved else None

    db.commit()
    db.refresh(exercise)
    return exercise_out(exercise)
