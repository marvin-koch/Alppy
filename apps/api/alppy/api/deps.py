"""Request dependencies.

Two of these carry the security model:

``get_current_teacher``  resolves the signed cookie to a ``Teacher`` row.
``get_tenant``           yields that teacher's ``school_id``.

Everything below the router takes ``school_id`` as a required argument, so a
handler that forgets the tenant does not type-check rather than leaking rows —
see docs/architecture.md §4. ``scoped_get`` is the one blessed way to fetch a
row by id: it always adds ``school_id`` to the filter and 404s otherwise.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Annotated, Any, Final, TypeVar

from fastapi import Depends, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.core.config import Settings, get_settings
from alppy.core.security import read_session
from alppy.db.base import SchoolScopedMixin
from alppy.models import Teacher
from alppy.storage import Storage, get_storage


def get_db() -> Generator[Session, None, None]:
    """Request-scoped session.

    The engine is built lazily so importing the app never opens a connection
    (and never requires a Postgres driver to be installed — the test suite
    overrides this dependency with an in-memory SQLite session).
    """
    from alppy.db.session import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_app_settings() -> Settings:
    return get_settings()


def get_object_storage() -> Storage:
    return get_storage()


DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
StorageDep = Annotated[Storage, Depends(get_object_storage)]


def get_current_teacher(request: Request, db: DbDep, settings: SettingsDep) -> Teacher:
    token = request.cookies.get(settings.session_cookie)
    if not token:
        raise errors.unauthorized("no session cookie")
    session = read_session(token, settings=settings)
    if session is None:
        raise errors.unauthorized("session cookie is invalid or expired")
    teacher = db.get(Teacher, session.teacher_id)
    if teacher is None or teacher.school_id != session.school_id:
        # The cookie signature was valid but the world moved on (teacher
        # deleted, or moved school). Treat it as no session at all.
        raise errors.unauthorized("session no longer valid")
    return teacher


TeacherDep = Annotated[Teacher, Depends(get_current_teacher)]


def get_tenant(teacher: TeacherDep) -> uuid.UUID:
    return teacher.school_id


TenantDep = Annotated[uuid.UUID, Depends(get_tenant)]

ModelT = TypeVar("ModelT", bound=SchoolScopedMixin)


def scoped_get(
    db: Session, model: type[ModelT], row_id: uuid.UUID, school_id: uuid.UUID, *, label: str
) -> ModelT:
    """Fetch one school-scoped row by id, or 404.

    A row belonging to another school is reported as missing, not as forbidden:
    the response must not confirm that the id exists somewhere else.
    """
    stmt = (
        select(model)
        .where(model.id == row_id)  # type: ignore[attr-defined]
        .where(model.school_id == school_id)
    )
    row = db.execute(stmt).scalar_one_or_none()
    if row is None:
        raise errors.not_found(label, id=str(row_id))
    return row


# --------------------------------------------------------------------------
# Rate limiting for the AI-backed endpoints
# --------------------------------------------------------------------------
@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


@dataclass(slots=True)
class TokenBucketLimiter:
    """In-process token bucket, one bucket per teacher.

    Deliberately not distributed: this is a guard against one teacher holding
    a click, not a billing control. The hard cost ceiling lives in
    ``Settings.ai_max_output_tokens`` and in the provider account.
    """

    rate_per_min: int
    burst: int | None = None
    _buckets: dict[str, _Bucket] = field(default_factory=dict)

    @property
    def capacity(self) -> float:
        return float(self.burst if self.burst is not None else self.rate_per_min)

    def take(self, key: str, *, now: float | None = None) -> float:
        """Consume one token. Returns 0.0 on success, else seconds to wait."""
        if self.rate_per_min <= 0:
            return 0.0
        t = now if now is not None else time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self.capacity, updated_at=t)
            self._buckets[key] = bucket
        refill = (t - bucket.updated_at) * (self.rate_per_min / 60.0)
        bucket.tokens = min(self.capacity, bucket.tokens + refill)
        bucket.updated_at = t
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return 0.0
        return (1.0 - bucket.tokens) / (self.rate_per_min / 60.0)

    def reset(self) -> None:
        self._buckets.clear()


_ai_limiter: TokenBucketLimiter | None = None


def get_ai_limiter() -> TokenBucketLimiter:
    global _ai_limiter
    settings = get_settings()
    if _ai_limiter is None or _ai_limiter.rate_per_min != settings.ai_rate_limit_per_min:
        _ai_limiter = TokenBucketLimiter(rate_per_min=settings.ai_rate_limit_per_min)
    return _ai_limiter


def enforce_ai_rate_limit(teacher: TeacherDep) -> None:
    """Dependency for every endpoint that can reach a model provider."""
    wait = get_ai_limiter().take(str(teacher.id))
    if wait > 0.0:
        raise errors.rate_limited(
            "too many AI requests; try again shortly", retry_after_s=max(1, int(wait) + 1)
        )


AiRateLimit = Depends(enforce_ai_rate_limit)


def load_optional(module: str, attribute: str, *, feature: str) -> Any:
    """Import a collaborating workstream's entry point, or 503.

    Ingestion, retrieval, adaptive planning and PDF rendering live in modules
    another workstream owns. The API must boot and serve everything else when
    they are not present yet, so the import happens here, inside the handler.
    """
    try:
        mod = __import__(module, fromlist=[attribute])
    except ImportError as exc:
        raise errors.service_unavailable(
            f"{feature} is not available in this deployment", module=module, reason=str(exc)
        ) from exc
    fn = getattr(mod, attribute, None)
    if fn is None:
        raise errors.service_unavailable(
            f"{feature} is not available in this deployment",
            module=module,
            reason=f"{module}.{attribute} is missing",
        )
    return fn


# --------------------------------------------------------------------------
# Uploads
# --------------------------------------------------------------------------
_MAGIC: Final[dict[str, tuple[bytes, ...]]] = {
    "application/pdf": (b"%PDF",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}
_UPLOAD_CHUNK: Final = 256 * 1024


@dataclass(frozen=True, slots=True)
class UploadPayload:
    """A validated upload, held in memory. Never a path."""

    filename: str
    content_type: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)


def _sniff(data: bytes, content_type: str) -> bool:
    prefixes = _MAGIC.get(content_type)
    if prefixes is None:
        return True
    if content_type == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return any(data.startswith(p) for p in prefixes)


async def read_upload(
    upload: UploadFile,
    settings: Settings,
    *,
    allowed: tuple[str, ...] | None = None,
) -> UploadPayload:
    """Read an upload with the content-type allowlist and the size cap applied.

    Three separate checks, because each catches a different mistake: the
    declared content type (a wrong picker), the magic bytes (a renamed file or
    a deliberate mismatch), and the byte count, enforced while streaming so an
    oversized body is abandoned rather than buffered whole.
    """
    allowed_types = allowed or settings.allowed_upload_types
    declared = (upload.content_type or "").split(";")[0].strip().lower()
    if declared not in allowed_types:
        raise errors.unsupported_media_type(
            f"content type {declared or 'unknown'!r} is not accepted",
            allowed=list(allowed_types),
        )

    cap = settings.max_upload_bytes
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise errors.payload_too_large(
                f"upload exceeds the {settings.max_upload_mb} MB limit",
                max_bytes=cap,
            )
        chunks.append(chunk)

    data = b"".join(chunks)
    if not data:
        raise errors.unprocessable("uploaded file is empty")
    if not _sniff(data, declared):
        raise errors.unsupported_media_type(
            f"file contents do not look like {declared}", declared=declared
        )

    # The filename is kept for display only; storage keys are built by
    # alppy.storage.storage_key, which sanitises it into a single segment.
    return UploadPayload(
        filename=upload.filename or "upload", content_type=declared, data=data
    )


def start_job(db: Session, job: Any) -> None:
    """Hand a committed ``Job`` row to the worker.

    Call this *after* the row is committed, so the worker cannot pick the job up
    before it is visible. If Redis will not take it the row is marked ``failed``
    rather than left at ``queued``: a job the teacher polls forever is worse
    than one that says it did not start, and this is the exact failure the
    /sources spinner used to hide.
    """
    from alppy.models.enums import JobStatus
    from alppy.worker.queue import QueueUnavailableError, enqueue

    try:
        enqueue(job.kind, job.id)
    except QueueUnavailableError as exc:
        job.status = JobStatus.FAILED
        job.message = "could not be queued"
        job.error = str(exc)[:500]
        db.commit()
        raise errors.service_unavailable(
            "background processing is unavailable; please try again",
            kind=job.kind.value,
            job_id=str(job.id),
        ) from exc
