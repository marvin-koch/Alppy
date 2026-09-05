"""arq task functions — the only place a slow pipeline (model call, OpenCV,
Chromium render) runs. See ``docs/architecture.md`` §3: a FastAPI handler
never awaits one of these directly; it writes a ``Job`` row and enqueues one
of the four functions below by name, then the client polls ``GET /jobs/{id}``.

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

from sqlalchemy.orm import Session

from alppy.core.logging import get_logger
from alppy.db.session import SessionLocal
from alppy.models import Job
from alppy.models.enums import JobStatus

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
    ``docs/architecture.md`` Flow 3."""

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


async def generate_adaptive(ctx: dict[str, Any], job_id: str) -> None:
    """``JobKind.GENERATE_ADAPTIVE`` — retrieval + AI generation per student,
    then one batch PDF with one ``.print-page`` per physical page. See
    ``docs/architecture.md`` Flow 4."""

    def _call(db: Session, job: Job, on_progress: ProgressCB) -> dict[str, Any] | None:
        from alppy.sheets.render import render_adaptive_batch

        sheet_id = _uuid_from(job, "sheet_id")
        # One PDF for the whole class, one .print-page per physical page, every
        # page carrying its own header and UID.
        key = render_adaptive_batch(db, sheet_id=sheet_id)
        on_progress(1.0, "batch rendered")
        return {"batch_pdf_key": key}

    await asyncio.to_thread(_run_job, job_id, _call)
