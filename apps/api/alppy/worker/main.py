"""arq worker entry point.

Run with either::

    python -m alppy.worker.main
    arq alppy.worker.main.WorkerSettings

Both start the same worker: it connects to Redis (``ALPPY_REDIS_URL``),
listens on the default arq queue, and dispatches every job kind in
``alppy.worker.tasks``. The Docker image's worker service (see
``docker-compose.yml``) runs the ``arq`` CLI form.
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from alppy.core.config import get_settings
from alppy.core.logging import configure_logging, get_logger
from alppy.core.observability import configure as configure_observability
from alppy.worker.cron import cron_jobs as _build_cron_jobs
from alppy.worker.tasks import (
    extract_section,
    generate_adaptive,
    generate_feedback,
    grade_open_answers,
    ingest_source,
    process_scan,
    propose_adaptive,
    render_sheet,
)

log = get_logger(__name__)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(str(get_settings().redis_url))


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(debug=settings.debug)
    # The worker is where the long, expensive, unattended work happens — a scan
    # pipeline, a Chromium render, a class set of vision calls — so it is the
    # half where a failure is least likely to be noticed by a human. No-op
    # unless ALPPY_SENTRY_DSN is set (D8).
    configure_observability(settings)
    log.info("worker.startup")


async def on_shutdown(ctx: dict[str, Any]) -> None:
    log.info("worker.shutdown")


class WorkerSettings:
    """See https://arq-docs.helpmanual.io/#worker-settings."""

    functions: ClassVar = [
        ingest_source,
        extract_section,
        render_sheet,
        process_scan,
        propose_adaptive,
        generate_adaptive,
        generate_feedback,
        grade_open_answers,
    ]
    redis_settings = _redis_settings()
    on_startup = on_startup
    on_shutdown = on_shutdown

    # The schedule (D2). Four correct, tested maintenance commands existed and
    # nothing ran any of them: every retention window was a promise kept by
    # somebody remembering, and a stuck grading pile waited for a human to
    # notice. See `alppy/worker/cron.py` for what each one does and why it runs
    # when it does.
    cron_jobs: ClassVar = _build_cron_jobs()

    # A stuck pipeline (a wedged model call, a hung Chromium render) must
    # never hold a worker slot forever.
    #
    # Both read from settings rather than being literals (D22). They were 600
    # and 4 here while `job_timeout_s`'s own docstring said this class read it,
    # and `job_stale_after_s` — what the reaper uses to decide a RUNNING row has
    # nobody behind it — is derived from `job_timeout_s`. A deployment that
    # raised the setting therefore moved the reaper's threshold and not arq's
    # ceiling, so the two stopped describing the same job.
    job_timeout = get_settings().job_timeout_s
    max_jobs = get_settings().worker_max_jobs
    keep_result = 3600  # seconds; job status is also durable in Postgres


if __name__ == "__main__":
    from arq.worker import run_worker

    run_worker(WorkerSettings)  # type: ignore[arg-type]
