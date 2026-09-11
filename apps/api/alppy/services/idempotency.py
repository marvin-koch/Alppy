"""Doing a write once, however many times the client asks for it.

Nothing in the product was idempotent (audit 03, B17). A phone on a staffroom
connection retries a POST whose answer never arrived; a teacher taps "print"
again because the screen has not moved yet. Both produced a second render job,
a second batch of unapproved exercises, a second pile of scans — and the few
endpoints that guarded against it each grew their own in-flight query with its
own idea of what "the same request" meant.

**The claim is committed before the work starts.** That ordering is the whole
design and it is the part that is easy to get wrong: a row written *after* the
work lets two simultaneous retries both run and remembers only whichever
finished last. Claiming first means the two race on a unique constraint,
exactly one wins, and the loser is told the work is already in flight.

**A failed attempt releases its claim.** Otherwise the first 500 poisons that
key forever and the teacher's retry — the one thing they will certainly do —
is refused with a conflict about a request that never succeeded.

``POST /scans/{id}/confirm`` deliberately does not use this. It is already
idempotent the better way, by superseding rather than accumulating, and it is
the pattern the rest should grow towards rather than something to wrap.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.core.logging import get_logger
from alppy.models import IdempotencyKey

log = get_logger(__name__)

M = TypeVar("M", bound=BaseModel)

#: Cap on a client-supplied key. Long enough for a uuid or a ULID with room to
#: spare, short enough that the column cannot be used as free storage.
MAX_KEY_LENGTH = 200


def run(
    db: Session,
    *,
    school_id: uuid.UUID,
    endpoint: str,
    key: str | None,
    model: type[M],
    work: Callable[[], M],
) -> M:
    """Run ``work`` once for this key, replaying the first answer afterwards.

    With no key this is a plain call: idempotency is opt-in per request, so
    every existing client keeps working unchanged and a caller that wants the
    guarantee asks for it with a header.

    ``work`` owns its own transaction and is expected to commit. This function
    commits twice around it — once to publish the claim, once to store the
    answer — and both are deliberate: an uncommitted claim is invisible to the
    concurrent retry it exists to stop.
    """
    if not key:
        return work()
    if len(key) > MAX_KEY_LENGTH:
        raise errors.unprocessable(
            f"Idempotency-Key must be at most {MAX_KEY_LENGTH} characters",
            code="idempotency_key_too_long",
        )

    replay = _claim(db, school_id=school_id, endpoint=endpoint, key=key)
    if replay is not None:
        log.info("idempotency.replay", endpoint=endpoint)
        return model.model_validate(replay)

    try:
        result = work()
    except Exception:
        # Release, so the retry the teacher is about to make can actually run.
        # Best-effort: if this fails too, the original exception is the one
        # worth raising.
        try:
            _release(db, school_id=school_id, endpoint=endpoint, key=key)
        except Exception:  # pragma: no cover - defensive
            log.exception("idempotency.release_failed", endpoint=endpoint)
        raise

    _finish(
        db,
        school_id=school_id,
        endpoint=endpoint,
        key=key,
        payload=result.model_dump(mode="json"),
    )
    return result


def _claim(
    db: Session, *, school_id: uuid.UUID, endpoint: str, key: str
) -> dict[str, Any] | None:
    """Take the key, or hand back what the first attempt answered.

    Returns ``None`` when this caller now owns the work. Raises a 409 when
    another attempt holds the claim and has not finished.
    """
    row = IdempotencyKey(
        id=uuid.uuid4(), school_id=school_id, endpoint=endpoint, key=key, response=None
    )
    try:
        with db.begin_nested():
            db.add(row)
        db.commit()
    except IntegrityError:
        # Somebody already has it. The savepoint has rolled back, so the
        # session is usable and the existing row can be read.
        db.rollback()
        existing = db.execute(
            select(IdempotencyKey)
            .where(IdempotencyKey.school_id == school_id)
            .where(IdempotencyKey.endpoint == endpoint)
            .where(IdempotencyKey.key == key)
        ).scalar_one_or_none()
        if existing is None:  # pragma: no cover - the row that just collided
            raise
        if existing.response is None:
            raise errors.conflict(
                "a request with this Idempotency-Key is still being processed",
                code="idempotency_in_flight",
            ) from None
        return dict(existing.response)
    return None


def _finish(
    db: Session,
    *,
    school_id: uuid.UUID,
    endpoint: str,
    key: str,
    payload: dict[str, Any],
) -> None:
    row = db.execute(
        select(IdempotencyKey)
        .where(IdempotencyKey.school_id == school_id)
        .where(IdempotencyKey.endpoint == endpoint)
        .where(IdempotencyKey.key == key)
    ).scalar_one_or_none()
    if row is None:  # pragma: no cover - only if something deleted it mid-flight
        return
    row.response = payload
    db.commit()


def _release(db: Session, *, school_id: uuid.UUID, endpoint: str, key: str) -> None:
    db.rollback()
    db.execute(
        delete(IdempotencyKey)
        .where(IdempotencyKey.school_id == school_id)
        .where(IdempotencyKey.endpoint == endpoint)
        .where(IdempotencyKey.key == key)
    )
    db.commit()
