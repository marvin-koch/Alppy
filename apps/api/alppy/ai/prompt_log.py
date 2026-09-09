"""Persisting the prompt log — the content store, not the audit trail.

Kept apart from ``audit.py`` on purpose. That module's docstring is emphatic
that it stores no content, and it is right: ``ModelCall`` is what a school shows
an auditor. Adding a content-writing function beside it would invite exactly the
confusion the separation exists to prevent, and one careless edit later the
audit log becomes the leak it exists to detect.

This writer is the other half: opt-in, swept, and for an engineer asking "what
did we actually send". Like ``record_calls`` it **never raises** — a debugging
row that cannot be written must not fail the class of children it was written
about.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from alppy.ai.client import PromptTranscript
from alppy.core.config import get_settings
from alppy.core.logging import get_logger
from alppy.models import PromptLog

log = get_logger(__name__)


def record_prompts(
    db: Session,
    *,
    school_id: uuid.UUID,
    transcripts: Iterable[PromptTranscript],
    request_id: str | None = None,
    job_id: uuid.UUID | None = None,
    sheet_id: uuid.UUID | None = None,
) -> int:
    """Write the content rows for one school. Returns how many were written.

    A no-op when the log is off — the client will not have accumulated anything
    either, so this is belt and braces against a caller that built its own
    transcripts.
    """
    if not get_settings().ai_prompt_log_enabled:
        return 0
    written = 0
    try:
        for transcript in transcripts:
            db.add(
                PromptLog(
                    id=uuid.uuid4(),
                    school_id=school_id,
                    request_id=request_id,
                    job_id=job_id,
                    sheet_id=sheet_id,
                    provider=transcript.provider,
                    model=transcript.model,
                    purpose=transcript.purpose,
                    prompt_name=transcript.prompt_name,
                    prompt_version=transcript.prompt_version,
                    prompt_sha256=transcript.prompt_sha256,
                    system_text=transcript.system_text,
                    user_text=transcript.user_text,
                    response_text=transcript.response_text,
                    input_tokens=transcript.input_tokens,
                    output_tokens=transcript.output_tokens,
                    latency_ms=transcript.latency_ms,
                    ok=transcript.ok,
                    error=transcript.error,
                )
            )
            written += 1
        db.flush()
    except Exception as exc:
        log.warning("ai.prompt_log.write_failed", error=type(exc).__name__)
        return 0
    return written


def purge_expired_prompts(db: Session, *, now: datetime | None = None) -> int:
    """Delete rows past the configured retention. Returns how many went.

    The setting alone is a promise; this is the mechanism that keeps it. A
    retention window nothing enforces is the same as no window, and this table
    holds — even after the PII gate — UIDs, wrong answers and how a named class
    thinks.
    """
    days = get_settings().ai_prompt_log_retention_days
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    result = db.execute(delete(PromptLog).where(PromptLog.created_at < cutoff))
    # CursorResult on a DELETE; the generic Result protocol does not declare it.
    deleted = int(result.rowcount or 0)  # type: ignore[attr-defined]
    if deleted:
        log.info("ai.prompt_log.purged", deleted=deleted, older_than_days=days)
    return deleted


__all__ = ["purge_expired_prompts", "record_prompts"]
