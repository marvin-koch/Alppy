"""The schedule (D2).

Four maintenance commands existed, were correct, and were never run: there was
no cron anywhere in the repository. These tests are what stops that being true
again quietly — a worker config restructured without its schedule looks exactly
like a working worker, and the symptom appears weeks later as an object store
that never shrinks and a teacher who cannot confirm a pile.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from alppy.worker import cron as cron_module
from alppy.worker.main import WorkerSettings

#: Every command that enforces a promise, and what breaks when it stops running.
EXPECTED: dict[str, str] = {
    "reap_jobs": "a stuck RUNNING row refuses a teacher's confirmation forever",
    "purge_scan_images": "photographs of named children's handwriting accumulate without bound",
    "purge_prompt_logs": "the one table holding what was actually sent to a provider never expires",
    "purge_access_log": "the read audit trail grows with every profile a teacher opens",
    "health_signals": "grading quality degrades in one school and nobody learns a number",
}


def _by_name() -> dict[str, Any]:
    return {job.name: job for job in WorkerSettings.cron_jobs}


def test_every_maintenance_command_is_actually_scheduled() -> None:
    scheduled = _by_name()
    for name, consequence in EXPECTED.items():
        assert name in scheduled, f"{name} is not scheduled: {consequence}"


def test_nothing_else_crept_onto_the_schedule() -> None:
    """Pinning the set is what makes adding to it a visible act — the same
    reasoning as the route sweep's allow-list counts."""
    assert set(_by_name()) == set(EXPECTED)


def test_the_reaper_runs_often_and_on_startup() -> None:
    """This is the one that unblocks a human waiting on a pile.

    `job_stale_after_s` is twice `job_timeout_s`, so a slow-but-alive job is
    never reaped out from under itself and running every few minutes costs
    nothing. On startup as well, because a worker coming back from a crash is
    precisely when there are stale rows to clear.
    """
    reaper = _by_name()["reap_jobs"]
    assert reaper.run_at_startup is True
    assert isinstance(reaper.minute, set)
    assert len(reaper.minute) == 12
    assert reaper.hour is None  # every hour


@pytest.mark.parametrize(
    "name", ["purge_prompt_logs", "purge_access_log", "purge_scan_images"]
)
def test_the_purges_run_nightly_and_not_at_startup(name: str) -> None:
    """A worker restarting six times during a deploy must not purge six times.

    Staggered rather than all at 03:00: three of them open an admin session and
    one also talks to object storage.
    """
    job = _by_name()[name]
    assert job.run_at_startup is False
    assert job.hour == 3
    assert isinstance(job.minute, int)


def test_the_purges_do_not_share_a_minute() -> None:
    nightly = [j for j in WorkerSettings.cron_jobs if j.hour == 3]
    assert len({j.minute for j in nightly}) == len(nightly)


def test_the_health_signals_run_weekly_over_the_week_they_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The question is a trend — is this school's printer drifting — and a
    daily number over a class set or two is noise. Monday morning, so the week
    being reported is the week that just finished."""
    job = _by_name()["health_signals"]
    assert job.weekday == "mon"
    assert job.hour == 4
    assert job.run_at_startup is False

    days_seen: list[int] = []
    monkeypatch.setattr("alppy.cli._health_signals", lambda *, days: days_seen.append(days) or 0)
    asyncio.run(cron_module.health_signals({}))
    assert days_seen == [7]  # the window matches the schedule


# --- what the job bodies actually do ---------------------------------------


def test_a_cron_body_runs_the_same_cli_function_an_operator_would(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduled path and the hand-run path are one piece of code.

    That is the whole reason these wrap `alppy.cli` rather than reimplementing
    it: `python -m alppy.cli reap-jobs` is what an operator runs to check, and
    it is what runs at :05.
    """
    calls: list[bool] = []
    monkeypatch.setattr(
        "alppy.cli._reap_jobs", lambda *, dry_run: calls.append(dry_run) or 0
    )
    asyncio.run(cron_module.reap_jobs({}))
    assert calls == [False]  # never a dry run on the schedule


def test_a_failing_command_is_logged_and_does_not_take_the_schedule_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A purge that cannot reach object storage must not stop the reaper.

    Every one of these is idempotent, so the next run does the work the failed
    one did not — which makes swallowing the right answer here and would not be
    anywhere a result is expected.
    """

    def _boom(**_: object) -> int:
        raise RuntimeError("object storage is unreachable")

    monkeypatch.setattr("alppy.cli._purge_scan_images", _boom)
    asyncio.run(cron_module.purge_scan_images({}))  # does not raise


def test_the_purge_is_scheduled_even_while_its_window_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`purge-scan-images` is a logged no-op while the retention window is 0.

    Scheduling it anyway is deliberate: the day a school states its window, the
    window is enforced that night, with nothing else to remember.
    """
    seen: list[int | None] = []
    monkeypatch.setattr(
        "alppy.cli._purge_scan_images",
        lambda *, older_than_days, dry_run: seen.append(older_than_days) or 0,
    )
    asyncio.run(cron_module.purge_scan_images({}))
    # None, so the command reads the setting rather than being told a number.
    assert seen == [None]
