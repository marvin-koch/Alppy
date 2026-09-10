from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("ALPPY_ENV", "ci")
# The suite must not need a live Redis, and must never push work onto a real
# queue. Tests that care about enqueueing assert on the call instead — see
# test_jobs_queue.py.
os.environ.setdefault("ALPPY_JOB_QUEUE_ENABLED", "false")

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def days_ago():
    def _days_ago(d: float) -> datetime:
        return NOW - timedelta(days=d)

    return _days_ago


@pytest.fixture(autouse=True)
def _reset_rate_limiters() -> Iterator[None]:
    """Empty every rate-limit bucket around each test.

    The limiters are module-level singletons, so without this a test that
    exhausts one throttles whatever runs next — which reads as a mysterious 429
    in an unrelated file.

    This lived in ``test_api_fixtures`` and was collected by nobody: the other
    modules pull that file in with ``import *``, and a leading underscore is
    exactly what ``*`` leaves behind. It was inert for the whole life of the
    suite, which did not show because nothing exhausted a bucket until the
    sign-in tests did. A conftest fixture needs no importing at all.
    """
    from alppy.api import deps

    limiters = (
        deps.get_ai_limiter(),
        deps.get_render_limiter(),
        deps.get_login_limiter(),
        deps.get_login_ip_limiter(),
    )
    for limiter in limiters:
        limiter.reset()
    yield
    for limiter in limiters:
        limiter.reset()
