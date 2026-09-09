"""arq task functions — the only place a slow pipeline (model call, OpenCV,
Chromium render) runs. See ``docs/architecture.md`` §3: a FastAPI handler
never awaits one of these directly; it writes a ``Job`` row and enqueues one
of the functions below by name, then the client polls ``GET /jobs/{id}``.

Each task:

1. loads the ``Job`` row,
2. sets ``status=running`` and ``started_at``,
3. calls into the owning module — imported **lazily**, inside the task, so
   the worker still starts even if that module does not exist yet (earlier
   milestones) or fails to import (e.g. an optional native dependency is
   missing in a dev environment),
4. reports progress through a callback that updates ``Job.progress`` (and
   optionally ``Job.message``),
5. writes ``succeeded``/``failed`` plus ``finished_at`` (and ``error`` on
   failure) and stores the pipeline's return value in ``Job.result``.

Contract for the owning modules (documented here since this file is their
only caller): every pipeline function has the signature

    def fn(db: Session, job: Job, *, on_progress: ProgressCB) -> dict[str, Any] | None

and may raise freely — any exception is caught, logged, written to
``Job.error``, and the job is marked failed. A pipeline function must not
commit or close ``db`` itself; the task below owns the transaction boundary
and reads whatever it needs from ``job.payload`` (e.g. ``source_id``,
``sheet_id``, ``scan_id``) and ``job.school_id`` for tenancy scoping.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.core.logging import get_logger
from alppy.db.session import SessionLocal
from alppy.models import Job
from alppy.models.enums import JobStatus
from alppy.services.enrollment import enrolled_student_ids

log = get_logger(__name__)

ProgressCB = Callable[[float, str | None], None]
PipelineFn = Callable[[Session, Job, ProgressCB], "dict[str, Any] | None"]


def _make_progress_cb(db: Session, job: Job) -> ProgressCB:
    def _progress(fraction: float, message: str | None = None) -> None:
        job.progress = max(0.0, min(1.0, fraction))
        if message is not None:
            job.message = message
        db.commit()

    return _progress


def _uuid_from(job: Job, key: str) -> UUID:
    """Pull an id out of the job payload, failing loudly if it is missing.

    The payload is written by the request handler that enqueued the job; a
    missing key is a programming error, and a job that silently does nothing is
    worse than one that fails visibly in the teacher's job list.
    """
    raw = (job.payload or {}).get(key)
    if not raw:
        raise ValueError(f"job {job.id} ({job.kind}) has no {key} in its payload")
    return UUID(str(raw))


def _run_job(job_id: str, fn: PipelineFn) -> None:
    """Shared lifecycle for every job kind: load, run, record outcome.

    Synchronous by design — the pipelines themselves (DB, OpenCV, Chromium,
    a model call) are blocking. Each ``async def`` task below schedules this
    on a worker thread via ``asyncio.to_thread`` so it never blocks arq's
    event loop, which is what lets one worker process run several jobs
    concurrently (``WorkerSettings.max_jobs`` in ``alppy.worker.main``).
    """
    db = SessionLocal()
    try:
        job = db.get(Job, UUID(job_id))
        if job is None:
            log.warning("job.not_found", job_id=job_id)
            return

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        job.progress = 0.0
        job.error = None
        db.commit()

        on_progress = _make_progress_cb(db, job)

        try:
            result = fn(db, job, on_progress)
        except Exception as exc:
            log.exception("job.failed", job_id=job_id, kind=str(job.kind))
            db.rollback()
            job = db.get(Job, UUID(job_id))
            if job is not None:
                job.status = JobStatus.FAILED
                job.error = str(exc)
                job.finished_at = datetime.now(UTC)
                db.commit()
            return

        job.status = JobStatus.SUCCEEDED
        job.progress = 1.0
        if result:
            job.result = result
        job.finished_at = datetime.now(UTC)
        db.commit()
    finally:
        db.close()


async def ingest_source(ctx: dict[str, Any], job_id: str) -> None:
    """``JobKind.INGEST_SOURCE`` — chunk + embed a ``Source``, extract
    candidate exercises. See ``docs/architecture.md`` Flow 1."""

    def _call(db: Session, job: Job, on_progress: ProgressCB) -> dict[str, Any] | None:
        from alppy.ingest.pipeline import ingest_source as run_ingest_source

        source_id = _uuid_from(job, "source_id")
        run_ingest_source(db, source_id=source_id)
        on_progress(1.0, "indexed")
        return {"source_id": str(source_id)}

    await asyncio.to_thread(_run_job, job_id, _call)


async def extract_section(ctx: dict[str, Any], job_id: str) -> None:
    """``JobKind.EXTRACT_SECTION`` — read one chapter of a document on demand.

    Importing a book maps its chapters and indexes every page but transcribes
    only as many chapters as the import budget allows, so this is how the rest
    of a 400-page textbook becomes exercises: the first time a teacher opens a
    chapter in the sheet builder. Idempotent — a section already carrying
    ``extracted_at`` returns immediately rather than transcribing twice.
    """

    def _call(db: Session, job: Job, on_progress: ProgressCB) -> dict[str, Any] | None:
        from alppy.ingest.pipeline import extract_section as run_extract_section

        section_id = _uuid_from(job, "section_id")
        on_progress(0.1, "reading the chapter")
        result = run_extract_section(db, section_id=section_id)
        on_progress(1.0, "chapter read")
        return {
            "section_id": str(section_id),
            "exercises_created": result.exercises_created,
            "exercises_total": result.exercises_total,
            "skipped": result.skipped,
            "notice": result.notice,
        }

    await asyncio.to_thread(_run_job, job_id, _call)


async def render_sheet(ctx: dict[str, Any], job_id: str) -> None:
    """``JobKind.RENDER_SHEET`` — headless Chromium renders ``blank.pdf`` and
    ``answer-key.pdf`` from the same print-styled markup the in-app preview
    uses. See ``docs/architecture.md`` Flow 2."""

    def _call(db: Session, job: Job, on_progress: ProgressCB) -> dict[str, Any] | None:
        from alppy.sheets.render import render_sheet_pdfs

        sheet_id = _uuid_from(job, "sheet_id")
        blank_key, answer_key = render_sheet_pdfs(db, sheet_id=sheet_id)
        on_progress(1.0, "sheet and answer key rendered")
        # Always two documents: the blank sheet and its answer key.
        return {"blank_pdf_key": blank_key, "answer_key_pdf_key": answer_key}

    await asyncio.to_thread(_run_job, job_id, _call)


async def process_scan(ctx: dict[str, Any], job_id: str) -> None:
    """``JobKind.PROCESS_SCAN`` — OpenCV fiducial registration, deskew, UID
    read, bubble/mark detection with per-item confidence. See
    ``docs/architecture.md`` Flow 3.

    When the pile carries written answers, a ``GRADE_OPEN_ANSWERS`` job is
    chained afterwards: the review opens now, on the marks, and the verdicts
    arrive while the teacher is already looking."""

    def _call(db: Session, job: Job, on_progress: ProgressCB) -> dict[str, Any] | None:
        from alppy.services.scan_processing import process_scan as run_process_scan
        from alppy.storage import get_storage

        return run_process_scan(
            db,
            get_storage(),
            scan_id=_uuid_from(job, "scan_id"),
            on_progress=on_progress,
        )

    await asyncio.to_thread(_run_job, job_id, _call)
    await asyncio.to_thread(_chain_after, job_id)


def _chain_after(job_id: str) -> None:
    """Enqueue whatever a finished job asks for next. Its own session: the
    finished job's transaction is closed, and the follow-up must be committed
    before the worker can be handed it."""
    from alppy.services.open_answer_grading import chain_open_grading
    from alppy.worker.queue import QueueUnavailableError, enqueue

    db = SessionLocal()
    try:
        job = db.get(Job, UUID(job_id))
        if job is None:
            return
        follow_up = chain_open_grading(db, job)
        if follow_up is None:
            return
        db.commit()
        try:
            enqueue(follow_up.kind, follow_up.id)
        except QueueUnavailableError as exc:
            follow_up.status = JobStatus.FAILED
            follow_up.error = str(exc)[:500]
            follow_up.finished_at = datetime.now(UTC)
            db.commit()
            log.warning("job.chain_failed", job_id=job_id, kind=follow_up.kind.value)
    finally:
        db.close()


async def grade_open_answers(ctx: dict[str, Any], job_id: str) -> None:
    """``JobKind.GRADE_OPEN_ANSWERS`` — one vision-model call per written
    answer cropped by ``PROCESS_SCAN``, each row settled as it lands. Nothing
    is left pending: a failed call is recorded as not gradeable."""

    def _call(db: Session, job: Job, on_progress: ProgressCB) -> dict[str, Any] | None:
        from alppy.ai.client import AiClient
        from alppy.services.open_answer_grading import grade_open_answers as run
        from alppy.storage import get_storage

        return run(
            db,
            get_storage(),
            AiClient(),
            scan_id=_uuid_from(job, "scan_id"),
            on_progress=on_progress,
        )

    await asyncio.to_thread(_run_job, job_id, _call)


async def propose_adaptive(ctx: dict[str, Any], job_id: str) -> None:
    """``JobKind.PROPOSE_ADAPTIVE`` — targeting, retrieval, and the model calls
    that fill whatever the corpus could not.

    A job rather than part of the request handler for the reason
    ``generate_feedback`` states below and CLAUDE.md states outright: nothing
    blocks a request handler on a model call. Batching cut a class of
    twenty-four from twenty-four calls to three, which made it survivable, not
    correct.

    The proposal itself is **not** stored in ``Job.result``. A class of
    twenty-four with eight items each, carrying full statements, options and
    provenance, is a megabyte of JSON that ``JobOut`` would re-serialise on every
    900 ms poll. The result is a summary; the proposal is read back from
    ``GET /adaptive/proposal/{job_id}``.
    """

    def _call(db: Session, job: Job, on_progress: ProgressCB) -> dict[str, Any] | None:
        from alppy.ai.client import AiClient
        from alppy.services.adaptive_service import propose_adaptive as build_proposal

        payload = job.payload or {}
        on_progress(0.05, "targeting")
        response = build_proposal(
            db,
            school_id=job.school_id,
            class_id=_uuid_from(job, "class_id"),
            subject_id=_uuid_from(job, "subject_id"),
            student_ids=[UUID(str(s)) for s in payload.get("student_ids") or []],
            items_per_student=int(payload.get("items_per_student") or 8),
            allow_generation=bool(payload.get("allow_generation", True)),
            language=payload.get("language"),
            fallback_language=str(payload.get("fallback_language") or "fr"),
            group=bool(payload.get("group", False)),
            n_groups=payload.get("n_groups"),
            source_sheet_id=(
                UUID(str(payload["source_sheet_id"]))
                if payload.get("source_sheet_id")
                else None
            ),
            llm_grouping=bool(payload.get("llm_grouping", False)),
            # The task owns the transaction boundary, not the pipeline.
            commit=False,
            ai=AiClient(),
        )
        on_progress(0.9, "proposal built")

        # Its own row so the poll stays small. `mode="json"` because the
        # response is full of UUIDs and JSONB will not take them.
        from alppy.models import AdaptiveProposal

        db.add(
            AdaptiveProposal(
                school_id=job.school_id,
                job_id=job.id,
                payload=response.model_dump(mode="json"),
            )
        )
        db.flush()
        return {
            "students": len(response.plans),
            "groups": len(response.groups),
            "generated": response.generated_count,
            "needs_approval": response.needs_approval,
            "failures": len(response.failures),
        }

    await asyncio.to_thread(_run_job, job_id, _call)


async def generate_adaptive(ctx: dict[str, Any], job_id: str) -> None:
    """``JobKind.GENERATE_ADAPTIVE`` — one batch PDF with one ``.print-page`` per
    physical page. See ``docs/architecture.md`` Flow 4.

    The name is older than the split and now misleads: this renders an approved
    batch and generates nothing. ``PROPOSE_ADAPTIVE`` above is the one that calls
    a model. Left alone deliberately — renaming an enum value in the same change
    that adds one is how a migration ends up half-applied.
    """

    def _call(db: Session, job: Job, on_progress: ProgressCB) -> dict[str, Any] | None:
        from alppy.sheets.render import render_adaptive_batch

        sheet_id = _uuid_from(job, "sheet_id")
        # One PDF for the whole class, one .print-page per physical page, every
        # page carrying its own header and UID — and the answer key beside it,
        # in the same copy order.
        blank_key, answer_key = render_adaptive_batch(db, sheet_id=sheet_id)
        on_progress(1.0, "batch rendered")
        return {"batch_pdf_key": blank_key, "answer_key_pdf_key": answer_key}

    await asyncio.to_thread(_run_job, job_id, _call)


async def generate_feedback(ctx: dict[str, Any], job_id: str) -> None:
    """``JobKind.GENERATE_FEEDBACK`` — one misconception note per student, read
    off their corrected answers on a common sheet.

    A job rather than part of ``POST /adaptive/propose`` because it is one model
    call per student: a class of twenty inside a request handler is a timeout
    with a half-written batch behind it, and CLAUDE.md is explicit that nothing
    blocks a request handler on a model call.
    """

    def _call(db: Session, job: Job, on_progress: ProgressCB) -> dict[str, Any] | None:
        from alppy.ai.client import AiClient
        from alppy.models import Student
        from alppy.services.feedback_service import generate_for_sheet

        source_sheet_id = _uuid_from(job, "source_sheet_id")
        subject_id = _uuid_from(job, "subject_id")
        class_id = _uuid_from(job, "class_id")
        language = str((job.payload or {}).get("language") or "fr")

        students = list(
            db.scalars(
                select(Student)
                .where(
                    Student.school_id == job.school_id,
                    Student.id.in_(enrolled_student_ids(class_id)),
                )
                .order_by(Student.number)
            )
        )
        notes = generate_for_sheet(
            db,
            school_id=job.school_id,
            source_sheet_id=source_sheet_id,
            subject_id=subject_id,
            students=students,
            language=language,
            ai=AiClient(),
            on_progress=on_progress,
        )
        # Every note lands unapproved. The count is what the review screen
        # polls for; nothing here may print.
        return {
            "feedback_ids": [str(n.id) for n in notes],
            "written": len(notes),
            "students": len(students),
        }

    await asyncio.to_thread(_run_job, job_id, _call)
