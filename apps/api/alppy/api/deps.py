"""Request dependencies.

One of these carries the security model:

``get_membership``  resolves the signed cookie to a ``Teacher`` **and** the
                    school that cookie is entitled to act for, checking the
                    pair against ``teacher_school``. ``get_current_teacher``,
                    ``get_tenant`` and ``get_scope`` all derive from it, so the
                    entitlement is answered once per request and in one place
                    (I-platform-14).

Everything below the router takes ``school_id`` as a required argument, so a
handler that forgets the tenant does not type-check rather than leaking rows —
see docs/architecture.md §4. ``scoped_get`` is the one blessed way to fetch a
row by id: it always adds ``school_id`` to the filter and 404s otherwise.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Final, TypeVar

from fastapi import Depends, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.core.config import Settings, get_settings
from alppy.core.security import read_session
from alppy.db import tenancy
from alppy.db.base import SchoolScopedMixin
from alppy.models import Teacher, teacher_school
from alppy.storage import Storage, get_storage


def get_db() -> Generator[Session, None, None]:
    """Request-scoped session, opened blind.

    The engine is built lazily so importing the app never opens a connection
    (and never requires a Postgres driver to be installed — the test suite
    overrides this dependency with an in-memory SQLite session).

    It yields a ``TenantSession`` that does not yet know its tenant, because
    nobody does: resolving the school means reading ``teacher_school``, which
    needs a session. ``get_membership`` binds it the moment that read answers.
    Until then — and for any handler that takes ``DbDep`` without also taking
    ``TenantDep`` or ``ScopeDep`` — row-level security shows the session
    nothing at all (D84, ``alppy/db/tenancy.py``).
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


def _demo_teacher(db: Session, settings: Settings) -> Teacher:
    """The teacher a demo instance answers as.

    By email rather than "the first teacher in the table", so an instance that
    happens to hold two schools cannot silently start answering as whichever
    one sorts first.
    """
    teacher = db.execute(
        select(Teacher).where(Teacher.email == settings.demo_teacher_email)
    ).scalar_one_or_none()
    if teacher is None:
        # Demo mode is on but the seed has not run. Say so, rather than
        # returning 401 and sending the reader hunting for a login that would
        # not have helped.
        raise errors.unauthorized(
            "demo mode is on but no demo teacher exists; run the seed",
        )
    return teacher


@dataclass(frozen=True, slots=True)
class Membership:
    """The teacher, and the school this request is acting for.

    The two are resolved together, once, because they are one question:
    *is this cookie still entitled to this tenant?* Since D74 a teacher may
    work at several schools, so the tenant comes from the **session** and
    never from ``Teacher.home_school_id`` — which answers where the account is
    based, not what it is doing (I-platform-14).
    """

    teacher: Teacher
    school_id: uuid.UUID


def get_membership(request: Request, db: DbDep, settings: SettingsDep) -> Membership:
    token = request.cookies.get(settings.session_cookie)
    if not token:
        # The one bypass, and it stays behind an explicit flag that defaults to
        # False (`Settings.demo_mode`). Everything below this line — the roster,
        # every child's real name — is what the cookie exists to protect.
        if settings.demo_mode:
            teacher = _demo_teacher(db, settings)
            tenancy.bind(db, school_id=teacher.home_school_id, teacher_id=teacher.id)
            return Membership(teacher=teacher, school_id=teacher.home_school_id)
        raise errors.unauthorized("no session cookie")
    session = read_session(token, settings=settings)
    if session is None:
        raise errors.unauthorized("session cookie is invalid or expired")
    row = db.get(Teacher, session.teacher_id)
    if row is None:
        # The cookie signature was valid but the world moved on. Treat it as
        # no session at all.
        raise errors.unauthorized("session no longer valid")
    teacher = row
    # A SELECT, deliberately — not `session.school_id in teacher.schools`. A
    # relationship read can be answered from a stale identity map, and this is
    # the single line standing between a cookie and another school's roster.
    member = db.execute(
        select(teacher_school.c.school_id)
        .where(teacher_school.c.teacher_id == teacher.id)
        .where(teacher_school.c.school_id == session.school_id)
    ).scalar_one_or_none()
    if member is None:
        # Valid signature, but this teacher no longer works at the school the
        # cookie names — they left, or it was never theirs.
        raise errors.unauthorized("session no longer valid")
    # Entitlement proved. From here to the end of the request the database
    # itself will refuse rows belonging to any other school — the second half
    # of D84, and the reason this line sits after the check above rather than
    # anywhere more convenient. The teacher id goes with it for the one policy
    # that needs it: `school`, which has to keep showing a teacher the OTHER
    # schools they work at, or login and `POST /auth/school/{id}` stop
    # answering (D74).
    tenancy.bind(db, school_id=session.school_id, teacher_id=teacher.id)
    return Membership(teacher=teacher, school_id=session.school_id)


MembershipDep = Annotated[Membership, Depends(get_membership)]


def get_current_teacher(membership: MembershipDep) -> Teacher:
    return membership.teacher


TeacherDep = Annotated[Teacher, Depends(get_current_teacher)]


def get_tenant(membership: MembershipDep) -> uuid.UUID:
    return membership.school_id


TenantDep = Annotated[uuid.UUID, Depends(get_tenant)]


@dataclass(frozen=True, slots=True)
class Scope:
    """Who is asking, and for which tenant.

    Two boundaries, not one, because the domain has two:

    ``school_id`` is the **tenant** boundary. Teaching material is shared by the
    staffroom on purpose — subjects, chapters, uploaded textbooks, extracted
    exercises and the curriculum are school-wide, and a colleague's scan of a
    textbook is meant to be usable.

    ``teacher_id`` is the **ownership** boundary. A class is personal: its
    roster of named children, its mastery matrix, its sheets and its scans
    belong to the teachers who teach it. Since D73 that is a set: ownership is
    ``Class.head_teacher_id`` OR a ``class_teacher_subject`` row, resolved in
    ``services.enrollment``. See decisions-log D23 and D73.

    ``school_id`` comes from the SESSION, not from the teacher's row: since D74
    a teacher may work at several schools (D74, I-platform-14).

    Handlers that touch a class take ``ScopeDep`` rather than ``TenantDep``, so
    forgetting the owner is a type error and not a leak.
    """

    school_id: uuid.UUID
    teacher_id: uuid.UUID


def get_scope(membership: MembershipDep) -> Scope:
    return Scope(school_id=membership.school_id, teacher_id=membership.teacher.id)


ScopeDep = Annotated[Scope, Depends(get_scope)]

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
# Rate limiting for the AI-backed and otherwise expensive endpoints
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
_render_limiter: TokenBucketLimiter | None = None


def get_ai_limiter() -> TokenBucketLimiter:
    global _ai_limiter
    settings = get_settings()
    if _ai_limiter is None or _ai_limiter.rate_per_min != settings.ai_rate_limit_per_min:
        _ai_limiter = TokenBucketLimiter(rate_per_min=settings.ai_rate_limit_per_min)
    return _ai_limiter


def get_render_limiter() -> TokenBucketLimiter:
    global _render_limiter
    settings = get_settings()
    rate = settings.render_rate_limit_per_min
    if _render_limiter is None or _render_limiter.rate_per_min != rate:
        _render_limiter = TokenBucketLimiter(rate_per_min=rate)
    return _render_limiter


def enforce_ai_rate_limit(teacher: TeacherDep) -> None:
    """Dependency for every endpoint that can reach a model provider.

    Directly or through the job it queues: an endpoint that queues nothing but
    a chain ending in a provider call is exactly as expensive as one that calls
    out itself, and a pile of 28 copies with 6 open items is ~168 calls behind
    a single POST.

    The bucket is per teacher and **per process** (``TokenBucketLimiter`` holds
    it in memory, deliberately — see its docstring). The effective ceiling for
    one teacher is therefore ``ai_rate_limit_per_min x uvicorn workers``, not
    ``ai_rate_limit_per_min``: with 4 workers the default 20/min admits up to
    80/min. Size the setting against the worker count, and do not read this as
    a global cost control — that lives in ``Settings.ai_max_output_tokens`` and
    in the provider account.
    """
    wait = get_ai_limiter().take(str(teacher.id))
    if wait > 0.0:
        raise errors.rate_limited(
            "too many AI requests; try again shortly", retry_after_s=max(1, int(wait) + 1)
        )


def enforce_render_rate_limit(teacher: TeacherDep) -> None:
    """Dependency for the expensive endpoints that never reach a provider.

    Rendering spawns headless Chromium; preview paginates synchronously inside
    the request handler. Neither bills the school, so they do not belong in the
    AI bucket — but held down, either one can eat the box the API is served
    from. Separate bucket, separate setting.

    Per teacher and per process, like the AI bucket above: the real ceiling is
    ``render_rate_limit_per_min x uvicorn workers``.
    """
    wait = get_render_limiter().take(str(teacher.id))
    if wait > 0.0:
        raise errors.rate_limited(
            "too many render requests; try again shortly", retry_after_s=max(1, int(wait) + 1)
        )


AiRateLimit = Depends(enforce_ai_rate_limit)
RenderRateLimit = Depends(enforce_render_rate_limit)


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
    "image/heic": (b"ftyp",),
    "image/heif": (b"ftyp",),
}

_HEIF_BRANDS: Final = (
    b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx",
    b"mif1", b"msf1", b"avif", b"avis",
)
"""ISO-BMFF brands a HEIF-family still can carry. An iPhone writes `heic` for a
single photo and `mif1` for one out of a burst or a Live Photo."""
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
    if content_type in ("image/heic", "image/heif"):
        # ISO-BMFF: a 4-byte box length, then "ftyp", then the brand.
        return data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS
    return any(data.startswith(p) for p in prefixes)


def check_upload_count(files: Sequence[UploadFile], settings: Settings) -> None:
    """Refuse a pile too large to hold, before anything is read.

    `read_upload` bounds one file; nothing bounds how many of them a handler
    reads into a list, and every payload stays in memory until the request
    ends. The check has to happen here, ahead of the first `await`, or the
    bytes are already buffered by the time we could say no.
    """
    limit = settings.max_upload_files
    if len(files) > limit:
        raise errors.payload_too_large(
            f"{len(files)} files were uploaded; at most {limit} can be sent at once",
            max_files=limit,
            received=len(files),
        )


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
