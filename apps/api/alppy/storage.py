"""Object storage.

Production is S3-compatible (MinIO locally, see docs/privacy.md §100). Tests and
a bare developer checkout use the local-filesystem backend so nothing has to be
running to exercise an upload path.

The one rule this module exists to enforce: **a client-supplied filename never
becomes a storage path**. ``storage_key`` builds every key from server-side
values and a sanitised leaf: the leaf keeps only the final path segment, so
``../../etc/passwd`` is stored as ``passwd`` under the requesting school's own
prefix, never anywhere near ``/etc``.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from alppy.core.config import Settings, get_settings
from alppy.core.logging import get_logger

log = get_logger(__name__)

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_LEAF = 100


class StorageError(RuntimeError):
    """Raised when the backend cannot serve a read or a write."""


def sanitise_filename(filename: str) -> str:
    """Reduce a client-supplied name to a safe single path segment.

    Never returns an empty string, a dot-segment, or anything containing a
    separator — so the result cannot escape its prefix.
    """
    leaf = filename.replace("\\", "/").rsplit("/", 1)[-1]
    leaf = _SAFE_CHARS.sub("_", leaf).strip("._-")
    if not leaf or leaf in {".", ".."}:
        leaf = "upload"
    if len(leaf) > _MAX_LEAF:
        stem, dot, ext = leaf.rpartition(".")
        leaf = (stem[: _MAX_LEAF - len(ext) - 1] + dot + ext) if dot else leaf[:_MAX_LEAF]
    return leaf


def storage_key(kind: str, school_id: uuid.UUID, entity_id: uuid.UUID, filename: str) -> str:
    """Build the canonical key. Every component but the leaf is server-side."""
    return f"{kind}/{school_id}/{entity_id}/{sanitise_filename(filename)}"


class Storage(Protocol):
    """The narrow surface the API needs. The worker may need more."""

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str: ...

    def get_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> bool: ...
    """Remove one object. True if it was there, False if it was already gone.

    **Never call this from a request handler, and never from a cascade**
    (audit 03, B14). It exists for two callers and no others: the
    `purge-scan-images` command, which enforces a retention window an operator
    set, and `delete_student`, which is a parent exercising erasure. Both are
    deliberate acts by a person who meant them.

    The reason is that an image is evidence. A crop is what a written answer
    was graded from, and a registered page is what a contested mark can be
    checked against — so anything that reaches this method by accident, on the
    way to doing something else, destroys the only copy of the thing a grade
    rests on. `delete_source` already argues the same case in its own
    docstring; this is that argument given a method.

    Missing is not an error: purging is idempotent by nature, and a key that
    has already gone is the outcome the caller wanted."""

    def url_for(self, key: str, *, ttl_s: int | None = None) -> str: ...

    def healthy(self) -> bool: ...


DEFAULT_URL_TTL_S = 900
"""Fifteen minutes: long enough to open a PDF the teacher just rendered."""

CROP_URL_TTL_S = 120
"""Two minutes, for a photograph of one child's handwriting.

The review screen fetches a crop as it draws the row, so it needs seconds, not
minutes. Every other signed URL in the product is a document the teacher asked
for; a crop is a picture of a named pupil's own paper, and it is the most
personal artefact this product holds (audit 02, L3).
"""


class LocalStorage:
    """Filesystem backend. Keys are relative paths under ``root``."""

    backend = "local"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        root = self.root.resolve()
        if not candidate.is_relative_to(root):
            raise StorageError(f"key escapes storage root: {key!r}")
        return candidate

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise StorageError(f"no such object: {key!r}")
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        try:
            return self._path(key).is_file()
        except StorageError:
            return False

    def delete(self, key: str) -> bool:
        # Through `_path`, so the traversal guard applies to deletion exactly as
        # it applies to reads. A key like `../../etc/something` raising here is
        # the entire point: this is the one method where following it would be
        # unrecoverable.
        path = self._path(key)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def url_for(self, key: str, *, ttl_s: int | None = None) -> str:
        """`ttl_s` is accepted and ignored: this backend serves through the
        API, which authenticates every request, so there is no signature to
        put a lifetime on."""
        del ttl_s
        return f"/api/v1/files/{key}"

    def healthy(self) -> bool:
        try:
            probe = self.root / ".healthcheck"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except OSError:  # pragma: no cover - depends on the filesystem
            return False


class S3Storage:
    """S3-compatible backend (MinIO locally)."""

    backend = "s3"

    def __init__(self, settings: Settings) -> None:
        import boto3  # imported lazily: the local backend must not need it
        from botocore.config import Config

        self._bucket = settings.s3_bucket
        # Explicit budgets for the same reason the providers have them: botocore
        # defaults to a 60 s read timeout with retries on top, and a worker
        # thread blocked on a wedged object store is indistinguishable from one
        # doing work — it just stops reporting, and the job sits RUNNING
        # (audit 03, B10). More retries than a model call gets, and a much
        # shorter ceiling: a GET of a page image either answers quickly or is
        # not going to.
        boto_config = Config(
            connect_timeout=settings.storage_connect_timeout_s,
            read_timeout=settings.storage_read_timeout_s,
            retries={"max_attempts": settings.storage_max_retries, "mode": "standard"},
        )
        # One factory rather than a `creds` dict unpacked twice. The dict was
        # inferred as `dict[str, object]` — it mixes strings with a `Config` —
        # and `**`-unpacking it defeated overload resolution on `boto3.client`,
        # so both calls type-checked as "no overload variant matches" and any
        # real mistake in either would have been reported the same unhelpful
        # way. The two clients still differ in exactly one argument, which is
        # the property worth being able to see at a glance.
        def _s3(endpoint_url: str) -> Any:
            return boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                region_name=settings.s3_region,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
                config=boto_config,
            )

        # Reads and writes go over the internal endpoint.
        self._client = _s3(settings.s3_endpoint_url)

        # Download links are handed to a browser, which cannot resolve the
        # compose network's hostname. SigV4 signs the Host header, so the origin
        # cannot be swapped after signing — the URL has to be *signed* against
        # the public origin by a second client that differs only in endpoint.
        public = settings.s3_public_endpoint_url
        self._url_client = _s3(public) if public else self._client

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )
        return key

    def get_bytes(self, key: str) -> bytes:
        try:
            obj = self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise StorageError(f"no such object: {key!r}") from exc
        body: bytes = obj["Body"].read()
        return body

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception:
            return False
        return True

    def delete(self, key: str) -> bool:
        """Remove one object, reporting whether it was there.

        `delete_object` answers 204 for a key that never existed, so existence
        is checked first — a purge that cannot tell the difference between
        "removed 400 images" and "removed nothing" cannot be trusted to report
        what it did.
        """
        if not self.exists(key):
            return False
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise StorageError(f"could not delete: {key!r}") from exc
        return True

    def url_for(self, key: str, *, ttl_s: int | None = None) -> str:
        """A time-limited download URL the teacher's browser can actually fetch.

        Signed by ``_url_client``, which points at the public origin: SigV4
        covers the Host header, so rewriting the origin after signing yields a
        403 rather than a download.

        `ttl_s` narrows the window for the things that deserve a narrower one.
        A signed URL is a bearer token — anyone holding the string has the
        object until it expires, with no session and no tenancy behind it —
        so the default is the longest any of these should live, not a
        convenient round number (audit 02, L3).
        """
        url: str = self._url_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=ttl_s if ttl_s is not None else DEFAULT_URL_TTL_S,
        )
        return url

    def healthy(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            return False
        return True


def default_local_root(settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    if s.storage_dir:
        return Path(s.storage_dir)
    return Path(tempfile.gettempdir()) / "alppy-storage"


def build_storage(settings: Settings | None = None) -> Storage:
    """Pick a backend, from settings rather than from the environment.

    Both of these were `os.getenv` calls, which put them outside every check
    `Settings` performs (audit 03, B25). `ALPPY_STORAGE_BACKEND` in particular
    was invisible to `_refuse_unsafe_deployment`, so a production deployment
    that never set it — or misspelled it — silently wrote scanned answer sheets
    to a temporary directory. It worked until the container restarted.
    """
    s = settings or get_settings()
    backend = s.resolved_storage_backend
    if backend == "local":
        return LocalStorage(default_local_root(s))
    try:
        return S3Storage(s)
    except ImportError:  # pragma: no cover - boto3 is a declared dependency
        log.warning("storage.s3_unavailable", fallback="local")
        return LocalStorage(default_local_root(s))


@lru_cache
def get_storage() -> Storage:
    return build_storage()


def reset_storage_cache() -> None:
    """Test hook: forget the memoised backend."""
    get_storage.cache_clear()


def clear_local_storage() -> None:  # pragma: no cover - developer convenience
    shutil.rmtree(default_local_root(), ignore_errors=True)
