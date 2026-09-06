"""Handing a ``Job`` row to the worker.

A request handler writes a ``Job`` row and then calls :func:`enqueue`. Without
that second half the row is a note nobody reads: the worker listens on the arq
queue in Redis and never looks at Postgres, so a job that is only written to the
database stays ``QUEUED`` forever and the teacher watches a spinner that will
never stop.

``JobKind`` values are exactly the task function names in
:mod:`alppy.worker.tasks`, so the mapping is the identity and there is no table
to keep in sync. :data:`TASK_NAMES` asserts that at import time.

Sync on purpose
---------------
Every handler that enqueues is a plain ``def`` handler, which FastAPI runs in a
threadpool, so there is no running event loop to reuse and ``asyncio.run`` is
safe. :func:`enqueue` still checks for a loop and moves to a worker thread if it
finds one, so an ``async def`` caller cannot deadlock on it.

The pool is short-lived. Enqueueing happens a handful of times per lesson, never
in a hot path, and a connection per call is cheaper than owning a pool whose
lifetime has to survive both the API and the test suite.
"""

from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Final

from alppy.core.config import get_settings
from alppy.core.logging import get_logger
from alppy.models.enums import JobKind

log = get_logger(__name__)

TASK_NAMES: Final[dict[JobKind, str]] = {kind: kind.value for kind in JobKind}
"""Job kind -> arq task function name. Identity, asserted in tests."""

ENQUEUE_TIMEOUT_S: Final = 5.0
"""A slow Redis must fail the upload loudly, not hang the request thread."""


class QueueUnavailableError(RuntimeError):
    """Redis would not accept the job.

    Distinct from a validation error: the request was good and the row is
    written, but the work will not start. The caller turns this into a 503 so
    the teacher is told to try again rather than being shown a job that will
    never move.
    """


async def _push(kind: JobKind, job_id: uuid.UUID) -> None:
    from arq.connections import create_pool

    from alppy.worker.main import _redis_settings

    pool = await create_pool(_redis_settings())
    try:
        # _job_id makes the enqueue idempotent: arq refuses a second job with an
        # id it has already seen, so a retried request cannot double-ingest.
        await pool.enqueue_job(TASK_NAMES[kind], str(job_id), _job_id=str(job_id))
    finally:
        await pool.aclose()


def enqueue(kind: JobKind, job_id: uuid.UUID) -> None:
    """Push one job onto the worker queue.

    Raises :class:`QueueUnavailableError` if Redis cannot be reached, so a
    handler can answer 503 instead of returning a job id that will never run.
    """
    if not get_settings().job_queue_enabled:
        # Tests and any single-process deployment that runs pipelines inline.
        log.info("queue.disabled", kind=kind.value, job_id=str(job_id))
        return

    async def _run() -> None:
        await asyncio.wait_for(_push(kind, job_id), timeout=ENQUEUE_TIMEOUT_S)

    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_run())
        else:
            # An async caller: run the pool on its own loop in another thread.
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(asyncio.run, _run()).result()
    except Exception as exc:
        log.warning(
            "queue.enqueue_failed",
            kind=kind.value,
            job_id=str(job_id),
            error=type(exc).__name__,
        )
        raise QueueUnavailableError(
            f"could not enqueue {kind.value}: {type(exc).__name__}"
        ) from exc

    log.info("queue.enqueued", kind=kind.value, job_id=str(job_id))


__all__ = ["ENQUEUE_TIMEOUT_S", "TASK_NAMES", "QueueUnavailableError", "enqueue"]
