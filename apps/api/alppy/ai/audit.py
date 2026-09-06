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

from sqlalchemy.orm import Session

from alppy.ai.client import CallRecord
from alppy.core.logging import get_logger
from alppy.models import ModelCall

log = get_logger(__name__)


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


__all__ = ["record_calls"]
