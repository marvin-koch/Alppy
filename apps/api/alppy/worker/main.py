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
    configure_logging(debug=get_settings().debug)
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

    # A stuck pipeline (a wedged model call, a hung Chromium render) must
    # never hold a worker slot forever.
    job_timeout = 600  # seconds
    max_jobs = 4
    keep_result = 3600  # seconds; job status is also durable in Postgres


if __name__ == "__main__":
    from arq.worker import run_worker

    run_worker(WorkerSettings)  # type: ignore[arg-type]
