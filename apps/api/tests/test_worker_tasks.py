"""The worker's job lifecycle — the layer every long-running flow runs inside.

``alppy/worker/tasks.py`` was the least covered module in the API (18%), which
is the wrong way round: CLAUDE.md says nothing blocks a request handler on a
model call, so rendering a sheet, processing a scan, grading a written answer,
proposing an adaptive set and writing feedback *all* execute here. The handler
tests prove a ``Job`` row is written and enqueued; ``test_jobs_queue.py``
proves it reaches the queue. Nothing covered what happens when the worker picks
it up.

Three properties, in the order they can hurt a teacher:

* a job that raises is recorded as ``FAILED`` with its reason — never left
  ``RUNNING`` forever behind a spinner nobody can clear;
* the tenant is bound before anything is read (D84), from the job row itself;
* the ``PROCESS_SCAN`` -> ``GRADE_OPEN_ANSWERS`` chain either hands the
  follow-up to the queue or fails it visibly, so written answers cannot sit
  pending with no grader coming.

These are integration tests: a real ``Session`` on the real schema, the real
``_run_job`` lifecycle, and the real chain. Only the queue and the clock stand
in, because Redis is out of scope here (``conftest`` disables it suite-wide).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant

from alppy.models import Job
from alppy.models.enums import JobKind, JobStatus
from alppy.services.job_failure import INTERNAL_ERROR, QUEUE_UNAVAILABLE
from alppy.worker import tasks as worker_tasks


@pytest.fixture
def worker_db(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Iterator[sessionmaker[Session]]:
    """Point ``tasks.SessionLocal`` at the test's own transaction.

    ``_run_job`` opens and closes its OWN session — that is part of what is
    being tested, since the real worker gets no session handed to it. It has to
    come from the same factory every other session in the test comes from: the
    in-memory engine is a ``StaticPool``, so binding a second factory to the
    *engine* hands back the one connection the test transaction already holds,
    and the worker's ``BEGIN`` fails as "cannot start a transaction within a
    transaction".
    """
    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)
    yield session_factory


def _job(db: Session, tenant: Tenant, *, kind: JobKind = JobKind.RENDER_SHEET, **kw: Any) -> Job:
    job = Job(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        kind=kind,
        status=kw.pop("status", JobStatus.QUEUED),
        progress=0.0,
        payload=kw.pop("payload", {}),
        **kw,
    )
    db.add(job)
    db.commit()
    return job


# --------------------------------------------------------------------------
# The lifecycle
# --------------------------------------------------------------------------
def test_a_successful_job_is_recorded_start_to_finish(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session]
) -> None:
    job = _job(db, tenant)

    def _pipeline(_db: Session, _job: Job, on_progress: Any) -> dict[str, Any]:
        on_progress(0.5, "halfway")
        return {"pages": 3}

    worker_tasks._run_job(str(job.id), _pipeline)

    db.expire_all()
    done = db.get(Job, job.id)
    assert done is not None
    assert done.status is JobStatus.SUCCEEDED
    assert done.progress == 1.0
    assert done.result == {"pages": 3}
    assert done.started_at is not None and done.finished_at is not None
    assert done.error is None


def test_a_raising_job_is_failed_with_its_reason_not_left_running(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session]
) -> None:
    """The one that matters most.

    A job left at ``RUNNING`` is a spinner the teacher cannot clear and a pile
    they cannot re-submit, because the API treats a running job as one somebody
    is still keeping a promise about.
    """
    job = _job(db, tenant)

    def _pipeline(_db: Session, _job: Job, _on_progress: Any) -> None:
        raise RuntimeError("chromium would not start")

    worker_tasks._run_job(str(job.id), _pipeline)

    db.expire_all()
    failed = db.get(Job, job.id)
    assert failed is not None
    assert failed.status is JobStatus.FAILED
    # A code, not the exception. `Job.error` is polled by the browser for the
    # length of every job, so the reason goes to the log and the field carries
    # one of `services.job_failure.FAILURE_CODES`.
    assert failed.error == INTERNAL_ERROR
    assert "chromium" not in (failed.error or "")
    assert failed.finished_at is not None


def test_a_failure_after_partial_writes_still_records_the_failure(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session]
) -> None:
    """``_run_job`` rolls back, then re-loads the job to mark it failed.

    Without the re-load the rollback would have detached the very row it needs
    to write the error onto, and the job would stay RUNNING — the failure mode
    this shape exists to prevent.
    """
    job = _job(db, tenant)

    def _pipeline(session: Session, running: Job, on_progress: Any) -> None:
        on_progress(0.4, "part way")
        running.message = "written but doomed"
        session.flush()
        raise ValueError("the model returned nothing")

    worker_tasks._run_job(str(job.id), _pipeline)

    db.expire_all()
    failed = db.get(Job, job.id)
    assert failed is not None
    assert failed.status is JobStatus.FAILED
    assert failed.error == INTERNAL_ERROR
    assert "model" not in (failed.error or "")


def test_progress_is_clamped_and_persisted_as_it_runs(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session]
) -> None:
    """The teacher's progress bar reads this column while the job runs, so it
    is committed mid-flight rather than at the end — and a pipeline reporting
    1.4 or -0.2 must not drive the bar off the end of its track."""
    job = _job(db, tenant)
    seen: list[float] = []

    def _pipeline(_db: Session, running: Job, on_progress: Any) -> None:
        on_progress(-0.2, "negative")
        seen.append(running.progress)
        on_progress(1.4, "over")
        seen.append(running.progress)

    worker_tasks._run_job(str(job.id), _pipeline)
    assert seen == [0.0, 1.0]


def test_a_message_is_only_replaced_when_one_is_given(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session]
) -> None:
    job = _job(db, tenant)
    job.message = "rendering"
    db.commit()

    def _pipeline(_db: Session, running: Job, on_progress: Any) -> None:
        on_progress(0.6)  # no message: the previous one must survive
        assert running.message == "rendering"

    worker_tasks._run_job(str(job.id), _pipeline)


def test_a_missing_job_row_is_logged_and_not_an_exception(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session]
) -> None:
    """An id with no row must not crash the worker process: arq would retry it
    forever, and there is nothing to retry."""
    called = False

    def _pipeline(*_args: Any) -> None:
        nonlocal called
        called = True

    worker_tasks._run_job(str(uuid.uuid4()), _pipeline)
    assert not called


def test_the_session_is_closed_even_when_the_pipeline_raises(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker leaking a connection per failed job exhausts the pool, and the
    symptom is unrelated jobs timing out much later."""
    opened: list[Session] = []
    factory = worker_db

    def _tracking_factory() -> Session:
        session = factory()
        opened.append(session)
        return session

    monkeypatch.setattr(worker_tasks, "SessionLocal", _tracking_factory)
    job = _job(db, tenant)

    def _pipeline(*_args: Any) -> None:
        raise RuntimeError("boom")

    worker_tasks._run_job(str(job.id), _pipeline)
    assert opened and all(not s.is_active or not s.in_transaction() for s in opened)


# --------------------------------------------------------------------------
# The payload
# --------------------------------------------------------------------------
def test_a_payload_missing_its_id_fails_the_job_loudly(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session]
) -> None:
    """``_uuid_from`` raises rather than returning None: a job that silently
    does nothing is worse than one that fails visibly in the job list."""
    job = _job(db, tenant, kind=JobKind.PROCESS_SCAN, payload={})

    def _pipeline(_db: Session, running: Job, _on_progress: Any) -> None:
        worker_tasks._uuid_from(running, "scan_id")

    worker_tasks._run_job(str(job.id), _pipeline)

    db.expire_all()
    failed = db.get(Job, job.id)
    assert failed is not None
    assert failed.status is JobStatus.FAILED
    # The payload key it could not read is a detail of our own schema; it
    # belongs in the log line, not in a field the browser polls.
    assert failed.error == INTERNAL_ERROR


def test_a_payload_id_is_read_as_a_uuid(db: Session, tenant: Tenant) -> None:
    scan_id = uuid.uuid4()
    job = _job(db, tenant, kind=JobKind.PROCESS_SCAN, payload={"scan_id": str(scan_id)})
    assert worker_tasks._uuid_from(job, "scan_id") == scan_id


# --------------------------------------------------------------------------
# Tenancy — the worker's half of D84
# --------------------------------------------------------------------------
def test_binding_is_attempted_before_the_job_row_is_read(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Order is the whole point: under row-level security the job row is itself
    invisible until the GUC is set, so a bind that happened after the ``db.get``
    would read nothing and the worker would report every job as not found."""
    order: list[str] = []
    real_bind = worker_tasks._bind_job_tenant

    def _spy(session: Session, job_id: uuid.UUID) -> None:
        order.append("bind")
        real_bind(session, job_id)

    monkeypatch.setattr(worker_tasks, "_bind_job_tenant", _spy)
    job = _job(db, tenant)

    def _pipeline(*_args: Any) -> None:
        order.append("run")

    worker_tasks._run_job(str(job.id), _pipeline)
    assert order == ["bind", "run"]


def test_binding_is_a_no_op_on_sqlite_rather_than_an_error(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session]
) -> None:
    """SQLite has no ``set_config`` and no policies. The guard keeps the whole
    suite runnable without Postgres; ``scripts/check-rls.py`` is what proves the
    Postgres half, and the ``row-level-security`` CI job covers the worker path end to end."""
    session = worker_db()
    try:
        worker_tasks._bind_job_tenant(session, uuid.uuid4())  # must not raise
    finally:
        session.close()


# --------------------------------------------------------------------------
# The chain: PROCESS_SCAN -> GRADE_OPEN_ANSWERS
# --------------------------------------------------------------------------
def test_a_scan_with_written_answers_chains_a_grading_job(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    enqueued: list[tuple[JobKind, uuid.UUID]] = []
    monkeypatch.setattr(
        "alppy.worker.queue.enqueue", lambda kind, job_id: enqueued.append((kind, job_id))
    )
    scan_id = uuid.uuid4()
    job = _job(
        db,
        tenant,
        kind=JobKind.PROCESS_SCAN,
        payload={"scan_id": str(scan_id)},
        status=JobStatus.SUCCEEDED,
        result={"pending_open_answers": 4},
    )

    worker_tasks._chain_after(str(job.id))

    db.expire_all()
    follow_up = db.query(Job).filter(Job.kind == JobKind.GRADE_OPEN_ANSWERS).one()
    assert follow_up.payload["scan_id"] == str(scan_id)
    assert follow_up.payload["after_job_id"] == str(job.id)
    assert follow_up.school_id == tenant.school.id
    # The row alone is not enough — it has to reach the queue.
    assert enqueued == [(JobKind.GRADE_OPEN_ANSWERS, follow_up.id)]


def test_a_scan_with_no_written_answers_chains_nothing(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    enqueued: list[Any] = []
    monkeypatch.setattr(
        "alppy.worker.queue.enqueue", lambda kind, job_id: enqueued.append((kind, job_id))
    )
    job = _job(
        db,
        tenant,
        kind=JobKind.PROCESS_SCAN,
        payload={"scan_id": str(uuid.uuid4())},
        status=JobStatus.SUCCEEDED,
        result={"pending_open_answers": 0},
    )

    worker_tasks._chain_after(str(job.id))

    db.expire_all()
    assert db.query(Job).filter(Job.kind == JobKind.GRADE_OPEN_ANSWERS).count() == 0
    assert enqueued == []


def test_a_failed_scan_never_chains_a_grader(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``pending_open_answers`` from a job that did not finish is not a promise
    about anything — the crops it counted may not exist."""
    monkeypatch.setattr("alppy.worker.queue.enqueue", lambda kind, job_id: None)
    job = _job(
        db,
        tenant,
        kind=JobKind.PROCESS_SCAN,
        payload={"scan_id": str(uuid.uuid4())},
        status=JobStatus.FAILED,
        result={"pending_open_answers": 4},
    )

    worker_tasks._chain_after(str(job.id))

    db.expire_all()
    assert db.query(Job).filter(Job.kind == JobKind.GRADE_OPEN_ANSWERS).count() == 0


def test_a_dead_queue_fails_the_chained_job_instead_of_leaving_it_queued(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same rule as the handler seam, one layer down: a grading job nobody will
    run must not look like one that is waiting, or the review screen promises
    verdicts that are never coming."""
    from alppy.worker.queue import QueueUnavailableError

    def _boom(kind: JobKind, job_id: uuid.UUID) -> None:
        raise QueueUnavailableError("redis is down")

    monkeypatch.setattr("alppy.worker.queue.enqueue", _boom)
    job = _job(
        db,
        tenant,
        kind=JobKind.PROCESS_SCAN,
        payload={"scan_id": str(uuid.uuid4())},
        status=JobStatus.SUCCEEDED,
        result={"pending_open_answers": 2},
    )

    worker_tasks._chain_after(str(job.id))

    db.expire_all()
    follow_up = db.query(Job).filter(Job.kind == JobKind.GRADE_OPEN_ANSWERS).one()
    assert follow_up.status is JobStatus.FAILED
    assert follow_up.error == QUEUE_UNAVAILABLE
    assert "redis" not in (follow_up.error or "").lower()
    assert follow_up.finished_at is not None


def test_chaining_a_missing_job_is_survivable(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session]
) -> None:
    worker_tasks._chain_after(str(uuid.uuid4()))  # must not raise


# --------------------------------------------------------------------------
# The arq entry points
# --------------------------------------------------------------------------
def test_process_scan_runs_the_job_then_the_chain(
    db: Session, tenant: Tenant, worker_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``process_scan`` is the only task with two awaits, and their order is
    load-bearing: chaining before the job is marked SUCCEEDED would read a
    status that is still RUNNING and never queue the grader."""
    calls: list[str] = []
    monkeypatch.setattr(
        worker_tasks, "_run_job", lambda job_id, fn: calls.append("run")
    )
    monkeypatch.setattr(worker_tasks, "_chain_after", lambda job_id: calls.append("chain"))

    asyncio.run(worker_tasks.process_scan({}, str(uuid.uuid4())))
    assert calls == ["run", "chain"]


@pytest.mark.parametrize(
    "task_name",
    [
        "ingest_source",
        "extract_section",
        "render_sheet",
        "grade_open_answers",
        "propose_adaptive",
        "generate_adaptive",
        "generate_feedback",
    ],
)
def test_every_task_delegates_to_the_shared_lifecycle(
    task_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each task is a thin adapter around ``_run_job``. A task that ran its
    pipeline directly would skip the status handling entirely — the job would
    never leave QUEUED however well the work went."""
    seen: list[str] = []
    monkeypatch.setattr(worker_tasks, "_run_job", lambda job_id, fn: seen.append(job_id))
    monkeypatch.setattr(worker_tasks, "_chain_after", lambda job_id: None)

    job_id = str(uuid.uuid4())
    asyncio.run(getattr(worker_tasks, task_name)({}, job_id))
    assert seen == [job_id]
