"""Persisting the model-call audit log.

``AiClient`` records every call in memory (``AiClient.records``), and until now
that was the end of it: ``ModelCall`` was declared, exported and never written,
so the audit trail ``docs/privacy.md`` relies on did not exist. After a full
ingestion run the table was empty.

This module is the writer, kept out of ``client.py`` on purpose: the client
must stay usable with no database — the seed loader, the tests and any offline
path construct one and call it directly.

What is stored is deliberately thin: provider, model, purpose, a hash of the
prompt, token counts, latency, a cost estimate. **Never the prompt content and
never a student name** — the row is safe to keep for as long as a school wants
it, which is the only reason it can be an audit trail at all.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from alppy.ai.client import CallRecord
from alppy.core.config import get_settings
from alppy.core.logging import get_logger
from alppy.models import ModelCall

log = get_logger(__name__)

if TYPE_CHECKING:
    from alppy.ai.client import AiClient


def record_calls(
    db: Session, *, school_id: uuid.UUID, records: Iterable[CallRecord]
) -> int:
    """Write model-call records for one school. Returns how many were written.

    Never raises: an audit row that cannot be written must not fail the
    ingestion that produced it. It logs instead, loudly enough to notice.
    """
    written = 0
    try:
        for record in records:
            db.add(
                ModelCall(
                    id=uuid.uuid4(),
                    school_id=school_id,
                    provider=record.provider,
                    model=record.model,
                    purpose=record.purpose,
                    prompt_name=record.prompt_name,
                    prompt_version=record.prompt_version,
                    prompt_sha256=record.prompt_sha256,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    latency_ms=record.latency_ms,
                    cost_estimate_chf=record.cost_estimate_chf,
                    ok=record.ok,
                    error=record.error,
                )
            )
            written += 1
        db.flush()
    except Exception as exc:
        log.warning("ai.audit.write_failed", error=type(exc).__name__)
        return 0
    return written


def flush(
    db: Session,
    *,
    school_id: uuid.UUID,
    ai: AiClient,
    request_id: str | None = None,
    job_id: uuid.UUID | None = None,
    sheet_id: uuid.UUID | None = None,
) -> int:
    """Write everything one client accumulated: the audit rows and, if a school
    turned it on, the prompt log.

    One call so that a call site never grows a second logging concern.
    Idempotent: it drains, so flushing after every call and flushing once at the
    end of a job both write each row exactly once.

    The import is local because ``prompt_log`` imports the models and this
    module is reached from paths that must work without them loaded.
    """
    from alppy.ai.prompt_log import record_prompts

    records, transcripts = ai.drain()
    written = record_calls(db, school_id=school_id, records=records)
    record_prompts(
        db,
        school_id=school_id,
        transcripts=transcripts,
        request_id=request_id,
        job_id=job_id,
        sheet_id=sheet_id,
    )
    return written


def purge_expired_calls(db: Session, *, now: datetime | None = None) -> int:
    """Delete `ModelCall` rows past `ALPPY_MODEL_CALL_RETENTION_DAYS`.

    The audit trail had no window at all — a decision nobody took, on the one
    table written on EVERY model call, so a school running full ingests
    accumulates millions of rows against a question nobody will ask about 2029.

    Opt-OUT, like the access log: 0 or less keeps forever, because an audit
    trail whose default is "quietly disappears" is not one. The shipped window
    is three years, which is long enough for a procurement review to ask about
    the year before last.

    Deletes by id in one statement rather than by predicate, so the count
    returned is the count that went.
    """
    days = get_settings().model_call_retention_days
    if days <= 0:
        return 0
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    ids = list(db.scalars(select(ModelCall.id).where(ModelCall.created_at < cutoff)))
    if not ids:
        return 0
    db.execute(delete(ModelCall).where(ModelCall.id.in_(ids)))
    return len(ids)


__all__ = ["flush", "purge_expired_calls", "record_calls"]
