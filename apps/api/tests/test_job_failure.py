"""`Job.error` is polled by a browser, so it holds a code and nothing else."""

from __future__ import annotations

import pytest

from alppy.services.job_failure import (
    FAILURE_CODES,
    INTERNAL_ERROR,
    QUEUE_UNAVAILABLE,
    STORAGE_UNAVAILABLE,
    TIMEOUT,
    failure_code,
)
from alppy.storage import StorageError
from alppy.worker.queue import QueueUnavailableError


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (QueueUnavailableError("could not enqueue ingest: ConnectionError"), QUEUE_UNAVAILABLE),
        (StorageError("no such object: 'scans/7b2f/page-1.png'"), STORAGE_UNAVAILABLE),
        (TimeoutError("timed out after 30s"), TIMEOUT),
        (RuntimeError("anything at all"), INTERNAL_ERROR),
    ],
)
def test_classifies_into_the_closed_set(exc: Exception, expected: str) -> None:
    assert failure_code(exc) == expected


@pytest.mark.parametrize(
    "exc",
    [
        # The shapes that made this worth fixing.
        RuntimeError("relation \"student\" does not have column \"first_name\""),
        OSError(2, "No such file", "/srv/alppy/storage/scans/7b2f.png"),
        StorageError("no such object: 'sources/9c1e/Livre unique 10e.pdf'"),
    ],
)
def test_never_echoes_the_exception(exc: Exception) -> None:
    code = failure_code(exc)
    assert code in FAILURE_CODES
    assert code not in str(exc)
    for leak in ("student", "/srv/", ".pdf", ".png", "column"):
        assert leak not in code
