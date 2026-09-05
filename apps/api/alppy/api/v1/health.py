"""Infrastructure endpoints: the health probe and the dev object-store proxy."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Response
from sqlalchemy import text

from alppy.api import errors
from alppy.api.deps import SettingsDep, StorageDep, TenantDep, get_db
from alppy.core.logging import get_logger
from alppy.schemas import HealthOut
from alppy.storage import StorageError

log = get_logger(__name__)
router = APIRouter(tags=["health"])


def _app_version() -> str:
    try:
        return version("alppy-api")
    except PackageNotFoundError:  # pragma: no cover - running from a checkout
        return "0.0.0-dev"


def _database_ok() -> bool:
    """Never raises: a health probe that 500s tells the orchestrator nothing."""
    gen = None
    try:
        gen = get_db()
        db = next(gen)
        db.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - any failure is simply "not healthy"
        return False
    finally:
        if gen is not None:
            gen.close()


def _redis_ok(url: str) -> bool:
    try:
        import redis

        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        try:
            return bool(client.ping())
        finally:
            client.close()
    except Exception:  # noqa: BLE001
        return False


@router.get("/health", response_model=HealthOut)
def health(settings: SettingsDep, storage: StorageDep) -> HealthOut:
    database = _database_ok()
    redis_ok = _redis_ok(str(settings.redis_url))
    try:
        storage_ok = storage.healthy()
    except Exception:  # noqa: BLE001
        storage_ok = False

    ok = database and redis_ok and storage_ok
    return HealthOut(
        status="ok" if ok else "degraded",
        version=_app_version(),
        database=database,
        redis=redis_ok,
        storage=storage_ok,
    )


@router.get("/files/{key:path}", response_class=Response)
def get_file(key: str, school_id: TenantDep, storage: StorageDep) -> Response:
    """Serve an object from the local storage backend.

    The key layout is ``<kind>/<school_id>/<entity_id>/<name>`` (see
    ``alppy.storage.storage_key``), so the tenant check is a segment
    comparison. In production this route is unused — the S3 backend hands out
    presigned URLs instead.
    """
    parts = key.split("/")
    if len(parts) < 3 or parts[1] != str(school_id):
        raise errors.not_found("file", key=key)
    try:
        data = storage.get_bytes(key)
    except StorageError as exc:
        raise errors.not_found("file", key=key) from exc
    return Response(content=data, media_type="application/octet-stream")
