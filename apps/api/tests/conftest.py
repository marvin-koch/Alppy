from __future__ import annotations

import os
import sys
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
