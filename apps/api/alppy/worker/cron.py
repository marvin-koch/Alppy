"""Scheduled maintenance, run by the worker (D2).

Four commands enforce every retention window this product promises and unblock
every stuck grading pile — `purge-scan-images`, `purge-prompt-logs`,
`purge-access-log` and `reap-jobs`. All four existed, all four were correct, and
**nothing ever ran them**: there was no cron anywhere in the repository, no
scheduler in the compose file, no scheduled workflow. A retention window nothing
enforces is not a window, and a stuck pile that self-heals only when a human
remembers a CLI command does not self-heal.

**Why arq's own `cron_jobs` and not a platform scheduler.** It lives in this
repository, so it is reviewed and tested beside the tasks it schedules; the
worker is already a persistent process holding the right credentials, so there
is nothing new to provision; and it survives a host migration without anybody
having to remember to recreate it somewhere else. A scheduler configured in a
provider's console is a scheduler that exists on exactly one provider, and the
host is not decided yet.

**Why every job body runs in a thread.** These are the synchronous `alppy.cli`
functions, unchanged — they open their own `admin_session()` and do blocking
database and object-store I/O. Called directly from the worker's event loop they
would stall every other job on this worker for the duration of a purge. The
whole point of putting them here rather than reimplementing them is that the
scheduled path and the hand-run path are the same code: `python -m alppy.cli
purge-scan-images` is what an operator runs to check, and it is what runs at
03:30.

**Failures are logged and swallowed.** A purge that cannot reach object storage
must not take the worker's cron loop down with it, and every one of these is
idempotent — the next run does the work the failed one did not. `arq` would
otherwise surface a raised exception as a failed job with no route to a human,
which is a worse silence than a log line.

Times are the worker's own clock (arq cron is not timezone-aware), which in a
deployment is UTC. The nightly window is chosen so that on Swiss local time it
falls between roughly 04:00 and 05:00 in winter — comfortably outside any lesson
and outside the hour a teacher might be preparing one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from arq import cron
from arq.cron import CronJob

from alppy.core.logging import get_logger

log = get_logger(__name__)


async def _in_thread(name: str, fn: Callable[[], int]) -> None:
    """Run one synchronous maintenance command off the event loop.

    Swallows, after logging: see the module docstring. The `cron.start` line is
    what tells an operator reading the worker log that the schedule is alive at
    all, which is the question asked first when a window looks unenforced.
    """
    log.info("cron.start", task=name)
    try:
        await asyncio.to_thread(fn)
    except Exception:
        log.exception("cron.failed", task=name)
    else:
        log.info("cron.done", task=name)


async def reap_jobs(ctx: dict[str, Any]) -> None:
    """Fail the jobs that stopped reporting (D2, D20).

    Every few minutes, not nightly, and that is the point: a `RUNNING` row with
    nobody behind it is what `grading_in_progress` reads to refuse a
    confirmation, so a worker killed mid-pile used to leave a teacher unable to
    confirm thirty copies until somebody ran a command. `job_stale_after_s` is
    twice `job_timeout_s`, so a slow-but-alive job is never reaped out from
    under itself and running this often costs nothing.
    """
    from alppy.cli import _reap_jobs

    await _in_thread("reap_jobs", lambda: _reap_jobs(dry_run=False))


async def purge_scan_images(ctx: dict[str, Any]) -> None:
    """Delete scanned page images and crops past their window (D2, D3).

    A no-op that logs `scan_images.purge.disabled` while
    `ALPPY_SCAN_IMAGE_RETENTION_DAYS` is 0 or less. Scheduling it anyway is
    deliberate: the day a school states its window, the window is enforced from
    that night, with nothing else to remember.
    """
    from alppy.cli import _purge_scan_images

    await _in_thread(
        "purge_scan_images",
        lambda: _purge_scan_images(older_than_days=None, dry_run=False),
    )


async def purge_prompt_logs(ctx: dict[str, Any]) -> None:
    """Enforce `ALPPY_AI_PROMPT_LOG_RETENTION_DAYS` (D2).

    The one table that holds what was actually sent to a model provider. Off by
    default, capped when on — and this is the sweep that makes "capped" true
    over time rather than at one moment.
    """
    from alppy.cli import _purge_prompt_logs

    await _in_thread("purge_prompt_logs", _purge_prompt_logs)


async def purge_access_log(ctx: dict[str, Any]) -> None:
    """Enforce `ALPPY_ACCESS_LOG_RETENTION_DAYS` (D2).

    The read audit trail — "who opened my child's file" — which grows with every
    profile a teacher opens and defaults to a year.
    """
    from alppy.cli import _purge_access_log

    await _in_thread("purge_access_log", _purge_access_log)


async def health_signals(ctx: dict[str, Any]) -> None:
    """Log the override rate and the confidence distribution (D8).

    Weekly, because the question it answers is a trend — "is this school's
    printer, photocopier or lighting drifting away from what the detector was
    tuned against" — and a daily number over a class set or two is noise.
    Monday morning, so the week that just finished is the week being reported.
    """
    from alppy.cli import _health_signals

    await _in_thread("health_signals", lambda: _health_signals(days=7))


#: Every fifth minute. Written out rather than computed so the schedule can be
#: read at a glance and diffed.
EVERY_FIVE_MINUTES = {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}


def cron_jobs() -> list[CronJob]:
    """The schedule. `WorkerSettings.cron_jobs` is this, and a test asserts it.

    Staggered by ten minutes rather than all at 03:00: three of these open an
    admin session and one of them also talks to object storage, and there is no
    reason to make them contend. `run_at_startup` is off for the purges — a
    worker restarting six times during a deploy must not run six purges — and on
    for the reaper, because a worker coming back up after a crash is exactly
    when there are stale `RUNNING` rows to clear.
    """
    return [
        cron(
            reap_jobs,
            name="reap_jobs",
            minute=EVERY_FIVE_MINUTES,
            run_at_startup=True,
        ),
        cron(purge_prompt_logs, name="purge_prompt_logs", hour=3, minute=10),
        cron(purge_access_log, name="purge_access_log", hour=3, minute=20),
        cron(purge_scan_images, name="purge_scan_images", hour=3, minute=30),
        cron(
            health_signals,
            name="health_signals",
            weekday="mon",
            hour=4,
            minute=0,
        ),
    ]
