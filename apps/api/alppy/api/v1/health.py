"""Infrastructure endpoints: the health probe and the dev object-store proxy."""

from __future__ import annotations

import hmac
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Header, Response
from sqlalchemy import text

from alppy.api import errors
from alppy.api.deps import SettingsDep, StorageDep, TenantDep, get_db
from alppy.core.logging import get_logger
from alppy.schemas import HealthDetailOut, HealthOut, LivenessOut
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
    except Exception:
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
    except Exception:
        return False


@router.get("/health/live", response_model=LivenessOut)
def liveness() -> LivenessOut:
    """Is this process running? No I/O, ever (audit 03, B29).

    A liveness probe answers one question — should the orchestrator restart
    this container — and `/health` answered a different one: it opens a
    connection to Postgres, Redis and object storage. So a Redis outage made
    every API pod fail its liveness probe and get killed and restarted, in a
    loop, while the API itself was perfectly capable of serving every request
    that does not touch Redis. An outage in a dependency became an outage in
    the thing that depends on it.

    `/health` keeps its shape and its meaning: it is the READINESS probe, and
    checking three connections is exactly right for deciding whether to send
    this instance traffic.
    """
    return LivenessOut(status="ok", version=_app_version())


#: The header carrying `ALPPY_HEALTH_DETAIL_TOKEN`.
HEALTH_DETAIL_HEADER = "X-Alppy-Health-Token"


def _check(settings: SettingsDep, storage: StorageDep) -> HealthDetailOut:
    """The readiness check itself. Both routes below are views onto this."""
    database = _database_ok()
    redis_ok = _redis_ok(str(settings.redis_url))
    try:
        storage_ok = storage.healthy()
    except Exception:
        storage_ok = False

    ok = database and redis_ok and storage_ok
    return HealthDetailOut(
        status="ok" if ok else "degraded",
        version=_app_version(),
        database=database,
        redis=redis_ok,
        storage=storage_ok,
    )


@router.get("/health", response_model=HealthOut)
def health(settings: SettingsDep, storage: StorageDep) -> HealthOut:
    """READINESS, for a load balancer: `ok` or `degraded`, and nothing else.

    It used to name the failing component (D35). That is genuinely useful and it
    was offered to anyone on the internet, with no session, on a route whose
    whole job is to be reachable when everything else is not — which is to say
    it published a live map of which dependency was down at the one moment we
    were least able to do anything about it. The breakdown moved to
    `/health/detail` and the verdict stayed here, because the verdict is the
    whole of what an orchestrator does with this.
    """
    detail = _check(settings, storage)
    return HealthOut(status=detail.status, version=detail.version)


@router.get("/health/detail", response_model=HealthDetailOut)
def health_detail(
    settings: SettingsDep,
    storage: StorageDep,
    token: str | None = Header(default=None, alias=HEALTH_DETAIL_HEADER),
) -> HealthDetailOut:
    """The same check, with the components. For an operator, not a probe.

    Open in `local` and `ci` — that is where it is read, and there is nothing
    behind it worth protecting from a developer's own machine. Everywhere else
    it needs `ALPPY_HEALTH_DETAIL_TOKEN`, and answers **404** rather than 401
    when the token is absent or wrong: a 401 confirms the route is there, which
    is half of what an unauthenticated prober came for.

    A token, not a network check, because behind a reverse proxy every request
    arrives from the proxy and "the peer is on a private address" is then true
    of the whole internet. Binding this to a genuinely internal listener is an
    infrastructure decision that has not been made yet (audit 07, Phase 3).
    """
    if settings.env in ("staging", "production"):
        expected = settings.health_detail_token
        if not expected or not token or not hmac.compare_digest(token, expected):
            log.info("health.detail.denied", reason="token")
            raise errors.not_found("route")
    return _check(settings, storage)


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
        log.info("files.denied", reason="tenant", key=key)
        raise errors.not_found("file")
    try:
        data = storage.get_bytes(key)
    except StorageError as exc:
        log.info("files.denied", reason="missing", key=key)
        raise errors.not_found("file") from exc
    # The key is deliberately NOT echoed in either envelope: it is the caller's
    # own input, and reflecting it turns a 404 into a mirror for whatever they
    # put in the path. The log keeps it, which is where it is useful.
    return Response(content=data, media_type=_media_type(key))


_MEDIA_TYPES = {".png": "image/png", ".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _media_type(key: str) -> str:
    """By extension, for the two kinds of object this route actually serves.

    An ``<img>`` given ``application/octet-stream`` under ``nosniff`` is a
    broken image, which is how the exercise figures would have shown up."""
    suffix = key[key.rfind(".") :].lower() if "." in key.rsplit("/", 1)[-1] else ""
    return _MEDIA_TYPES.get(suffix, "application/octet-stream")
