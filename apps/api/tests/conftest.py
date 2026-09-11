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

# The suite must never reach a real provider, and until this block existed it
# did. ``Settings`` resolves ``.env`` from the repo root (``core/config.py``),
# so a developer's working key and ``ALPPY_AI_CHAT_PROVIDER=openai`` were in
# force for every test in the file — including the ones asserting that an
# *ungrounded* provider refuses to invent a verdict, which is the one thing
# they could not have been testing. Every model-reaching test was a real,
# billed call against a live account.
#
# Environment beats dotenv in pydantic-settings, so pinning here is what
# overrides the file. Three variables, not two, and the third is the trap:
#
#   * the two providers, pinned to their offline stand-ins;
#   * ``ALPPY_AI_CHAT_MODEL``, which must be cleared *as well*. ``.env`` names
#     a ``gpt-*`` model, and ``_resolve_chat_model`` refuses a known-foreign
#     (provider, model) pair — so pinning the provider alone makes every
#     ``Settings()`` raise ``ValueError`` and takes the whole suite down at
#     collection. Empty means "take that provider's default", which is
#     ``echo``.
#
# The keys are cleared rather than left alone so this cannot come back through
# a different variable: ``build_chat_provider`` falls through to the echo
# provider on a missing key and says so in a log line, which is exactly the
# behaviour the offline assertions want to exercise. A test that genuinely
# needs a live provider should opt in with an explicit marker, never by
# inheriting the ambient environment.
os.environ.setdefault("ALPPY_AI_CHAT_PROVIDER", "echo")
os.environ.setdefault("ALPPY_AI_EMBEDDINGS_PROVIDER", "hash")
os.environ["ALPPY_AI_CHAT_MODEL"] = ""
os.environ["ALPPY_OPENAI_API_KEY"] = ""
os.environ["ALPPY_ANTHROPIC_API_KEY"] = ""

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


def printed_body(html: str) -> str:
    """The document minus its ``<head>``.

    The print document inlines ``fonts.css`` — 242 KiB of base64 — so the
    ``<head>`` now contains, by pure chance, most short strings. Any assertion
    of the form ``html.count("7/8") == 1`` ("this prints once on the page") is
    really an assertion about the *page*, and the head is not the page. Reach
    for this whenever the token being counted is short enough to collide.
    """
    _, _, body = html.partition("</head>")
    return body or html
