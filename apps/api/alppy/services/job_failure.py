"""What a failed ``Job`` is allowed to say about itself.

``JobOut.error`` is returned by ``GET /jobs`` and ``GET /jobs/{id}``, which the
sheet builder polls for the length of every extraction. It used to carry
``str(exc)`` — the raw text of whatever the worker hit, uncapped in one of the
three places that wrote it. No screen renders it today, which is the only
reason this was a payload problem rather than a visible one; the field is still
sent to the browser on every poll, where it sits in DevTools and in anything
that ships client-side errors onward.

So the column carries a *code* from a closed set. The diagnostic is not lost:
``worker/tasks.py`` logs the exception with its traceback in the same breath,
which is where an operator should be reading it from anyway.
"""

from __future__ import annotations

QUEUE_UNAVAILABLE = "queue_unavailable"
STORAGE_UNAVAILABLE = "storage_unavailable"
TIMEOUT = "timeout"
INTERNAL_ERROR = "internal_error"

#: Every value ``Job.error`` may hold. A test asserts the classifier cannot
#: return anything outside it, which is what keeps "just this once" honest.
FAILURE_CODES = frozenset({QUEUE_UNAVAILABLE, STORAGE_UNAVAILABLE, TIMEOUT, INTERNAL_ERROR})


def failure_code(exc: BaseException) -> str:
    """Classify a worker failure into one of ``FAILURE_CODES``.

    The imports are deferred because ``alppy.worker.queue`` reaches back into
    the API layer that calls this — the same cycle ``api/deps.py`` already
    steps around at its own call site.
    """
    from alppy.storage import StorageError
    from alppy.worker.queue import QueueUnavailableError

    if isinstance(exc, QueueUnavailableError):
        return QUEUE_UNAVAILABLE
    if isinstance(exc, StorageError):
        return STORAGE_UNAVAILABLE
    if isinstance(exc, TimeoutError):
        return TIMEOUT
    return INTERNAL_ERROR
