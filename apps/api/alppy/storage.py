"""Object storage.

Production is S3-compatible (MinIO locally, see docs/privacy.md §100). Tests and
a bare developer checkout use the local-filesystem backend so nothing has to be
running to exercise an upload path.

The one rule this module exists to enforce: **a client-supplied filename never
becomes a storage path**. ``storage_key`` builds every key from server-side
values and a sanitised leaf, so ``../../etc/passwd`` is stored as
``etc_passwd``.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

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

    def url_for(self, key: str) -> str: ...

    def healthy(self) -> bool: ...


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

    def url_for(self, key: str) -> str:
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

        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )

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

    def url_for(self, key: str) -> str:
        url: str = self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=900
        )
        return url

    def healthy(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            return False
        return True


def default_local_root() -> Path:
    configured = os.getenv("ALPPY_STORAGE_DIR")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "alppy-storage"


def build_storage(settings: Settings | None = None) -> Storage:
    """Pick a backend. ``ALPPY_STORAGE_BACKEND`` wins; CI defaults to local."""
    s = settings or get_settings()
    backend = os.getenv("ALPPY_STORAGE_BACKEND", "local" if s.env == "ci" else "s3").lower()
    if backend == "local":
        return LocalStorage(default_local_root())
    try:
        return S3Storage(s)
    except ImportError:  # pragma: no cover - boto3 is a declared dependency
        log.warning("storage.s3_unavailable", fallback="local")
        return LocalStorage(default_local_root())


@lru_cache
def get_storage() -> Storage:
    return build_storage()


def reset_storage_cache() -> None:
    """Test hook: forget the memoised backend."""
    get_storage.cache_clear()


def clear_local_storage() -> None:  # pragma: no cover - developer convenience
    shutil.rmtree(default_local_root(), ignore_errors=True)
