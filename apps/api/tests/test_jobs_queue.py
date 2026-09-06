"""The request-handler -> queue -> worker seam.

This file exists because 277 tests passed while no job was ever enqueued: the
handlers wrote a ``Job`` row to Postgres and nothing pushed it to Redis, so
every upload sat at ``queued`` forever and no sheet was ever rendered. Nothing
covered the seam, so nothing caught it.

The rule these tests encode: a handler that answers 202 with a job id has put
that job somewhere a worker will find it, or it has failed loudly.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import PDF_BYTES, Tenant, login

from alppy.models import Job, Source
from alppy.models.enums import JobKind, JobStatus
from alppy.worker import queue as queue_mod


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[JobKind, uuid.UUID]]:
    """Record every enqueue instead of talking to Redis."""
    calls: list[tuple[JobKind, uuid.UUID]] = []
    monkeypatch.setattr(
        queue_mod, "enqueue", lambda kind, job_id: calls.append((kind, job_id))
    )
    return calls


# --------------------------------------------------------------------------
# Every kind maps to a real worker task
# --------------------------------------------------------------------------
def test_every_job_kind_names_a_task_the_worker_registers() -> None:
    from alppy.worker.main import WorkerSettings

    registered = {fn.__name__ for fn in WorkerSettings.functions}
    for kind in JobKind:
        assert queue_mod.TASK_NAMES[kind] in registered, kind


# --------------------------------------------------------------------------
# Uploading a source enqueues its ingestion
# --------------------------------------------------------------------------
def test_uploading_a_source_enqueues_the_ingestion_job(
    client: TestClient, tenant: Tenant, db: Session, enqueued: list[tuple[JobKind, uuid.UUID]]
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/sources",
        files={"file": ("book.pdf", PDF_BYTES, "application/pdf")},
        data={"subject_id": str(tenant.subject.id)},
    )
    assert response.status_code == 202, response.text

    job = db.query(Job).filter(Job.kind == JobKind.INGEST_SOURCE).one()
    assert job.payload["source_id"] == response.json()["id"]
    # The row alone is not enough: it has to be handed to the worker.
    assert enqueued == [(JobKind.INGEST_SOURCE, job.id)]


def test_upload_requires_a_subject(client: TestClient, tenant: Tenant) -> None:
    """The web client omitted this field, so every upload was a silent 422."""
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/sources", files={"file": ("book.pdf", PDF_BYTES, "application/pdf")}
    )
    assert response.status_code == 422
    locs = [e["loc"] for e in response.json()["error"]["details"]["errors"]]
    assert ["body", "subject_id"] in locs


# --------------------------------------------------------------------------
# A queue that will not take the job must not leave a lie in the table
# --------------------------------------------------------------------------
def test_a_dead_queue_fails_the_job_instead_of_leaving_it_queued(
    client: TestClient, tenant: Tenant, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(kind: JobKind, job_id: uuid.UUID) -> None:
        raise queue_mod.QueueUnavailableError("redis is down")

    monkeypatch.setattr(queue_mod, "enqueue", _boom)
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/sources",
        files={"file": ("book.pdf", PDF_BYTES, "application/pdf")},
        data={"subject_id": str(tenant.subject.id)},
    )
    assert response.status_code == 503

    job = db.query(Job).filter(Job.kind == JobKind.INGEST_SOURCE).one()
    db.refresh(job)
    # Not QUEUED: a job nobody will run must not look like one that is waiting.
    assert job.status is JobStatus.FAILED
    assert "redis" in (job.error or "").lower()


# --------------------------------------------------------------------------
# The worker reads the bytes from where the handler put them
# --------------------------------------------------------------------------
def test_the_ingest_loader_reads_object_storage_not_the_filesystem(
    client: TestClient,
    tenant: Tenant,
    db: Session,
    storage: object,
    enqueued: list[tuple[JobKind, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``default_loader`` used to read ``storage_key`` as a filesystem path
    while the handler wrote the bytes to object storage, so every ingestion job
    failed with FileNotFoundError even once it was enqueued."""
    from alppy import storage as storage_mod
    from alppy.ingest.pipeline import default_loader

    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/sources",
        files={"file": ("book.pdf", PDF_BYTES, "application/pdf")},
        data={"subject_id": str(tenant.subject.id)},
    )
    source = db.get(Source, uuid.UUID(response.json()["id"]))
    assert source is not None
    # The key is an object-storage key, not a path on disk.
    assert not Path(source.storage_key).exists()

    monkeypatch.setattr(storage_mod, "get_storage", lambda: storage)
    assert default_loader(source) == PDF_BYTES
