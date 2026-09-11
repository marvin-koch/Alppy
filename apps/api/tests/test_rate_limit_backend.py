"""Where a rate-limit bucket lives (D30), and why it has to be a decision.

A dict in the API process is correct for one uvicorn worker and worth N times
its stated value for N — each worker holds its own, the same teacher is
load-balanced across all of them, and nothing about that is visible. So raising
`ALPPY_API_WORKERS` (D19) and moving the buckets to Redis are one change, and
these tests are what keeps them one change.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from alppy.api.limits import (
    RedisTokenBucketLimiter,
    TokenBucketLimiter,
    build_limiter,
    resolve_backend,
)
from alppy.core.config import Settings

GOOD = {
    "secret_key": "a-real-and-sufficiently-long-secret",
    "s3_secret_key": "a-real-bucket-password",
    "database_url": "postgresql+psycopg://alppy_app:pw@db.internal:5432/alppy",
    "admin_database_url": "postgresql+psycopg://alppy:pw@db.internal:5432/alppy",
    "cors_origins": ("https://app.alppy.ch",),
    "s3_bucket": "alppy-staging-scans",
    "production_s3_bucket": "alppy-scans",
}


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**GOOD, **overrides})  # type: ignore[arg-type]


# --- which backend, and where -----------------------------------------------


@pytest.mark.parametrize("env", ["local", "ci"])
def test_development_needs_no_redis(env: str) -> None:
    """The suite runs on SQLite with nothing else up; a limiter that demanded
    Redis would make every rate-limit test an integration test."""
    settings = Settings(_env_file=None, env=env)
    assert resolve_backend(settings) == "memory"
    assert isinstance(build_limiter("ai", rate_per_min=5, settings=settings), TokenBucketLimiter)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_a_real_deployment_shares_its_buckets(env: str) -> None:
    settings = _settings(env=env)
    assert resolve_backend(settings) == "redis"
    assert isinstance(
        build_limiter("ai", rate_per_min=5, settings=settings), RedisTokenBucketLimiter
    )


def test_the_backend_can_be_named_explicitly() -> None:
    assert resolve_backend(_settings(env="production", rate_limit_backend="memory")) == "memory"
    assert resolve_backend(Settings(_env_file=None, rate_limit_backend="redis")) == "redis"


# --- the guard that keeps the two changes together --------------------------


@pytest.mark.parametrize("env", ["staging", "production"])
def test_more_than_one_worker_on_in_process_buckets_is_refused(env: str) -> None:
    """The failure this prevents is invisible: the limit is still configured,
    still enforced, and worth four times what it says."""
    with pytest.raises(ValidationError) as caught:
        _settings(env=env, api_workers=4, rate_limit_backend="memory")
    message = str(caught.value)
    assert "ALPPY_API_WORKERS" in message
    assert "ALPPY_RATE_LIMIT_BACKEND" in message


@pytest.mark.parametrize("env", ["staging", "production"])
def test_four_workers_on_shared_buckets_boots(env: str) -> None:
    assert _settings(env=env, api_workers=4, rate_limit_backend="redis").api_workers == 4


@pytest.mark.parametrize("env", ["staging", "production"])
def test_one_worker_on_in_process_buckets_is_fine(env: str) -> None:
    """It is the combination that is wrong, not either half."""
    assert _settings(env=env, api_workers=1, rate_limit_backend="memory").api_workers == 1


def test_the_default_is_one_worker() -> None:
    """Right for `docker compose up` and for CI. Raising it is deliberate."""
    assert Settings(_env_file=None).api_workers == 1


# --- what the Redis-backed limiter does when Redis is not there -------------


class _DeadRedis:
    def __getattr__(self, name: str) -> object:
        raise ConnectionError("redis is unreachable")


def test_an_unreachable_redis_degrades_to_this_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not an outage and not an open door.

    A sign-in limiter that raised on a Redis blip would lock a school out of
    its own product; one that answered "no wait" would remove the brake in
    front of Argon2id exactly when the system is already unhealthy. The
    in-process bucket is the honest middle: a weaker limit, never no limit.
    """
    limiter = RedisTokenBucketLimiter(
        name="login", rate_per_min=2, url="redis://127.0.0.1:1/0"
    )
    monkeypatch.setattr(limiter, "_ensure", lambda: (_ for _ in ()).throw(ConnectionError()))

    assert limiter.take("teacher-1") == 0.0
    assert limiter.take("teacher-1") == 0.0
    # Third attempt inside the minute: the fallback bucket is empty and says so.
    assert limiter.take("teacher-1") > 0.0


def test_a_recovered_redis_is_picked_up_without_a_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cached script is dropped on failure, so the next call rebuilds it."""
    limiter = RedisTokenBucketLimiter(name="ai", rate_per_min=5, url="redis://127.0.0.1:1/0")
    limiter._script = object()  # pretend a client was built
    monkeypatch.setattr(limiter, "_ensure", lambda: (_ for _ in ()).throw(ConnectionError()))
    limiter.take("teacher-1")
    assert limiter._script is None


def test_each_limiter_owns_its_own_keyspace() -> None:
    """A teacher's render ceiling and their AI ceiling are different limits and
    were different dicts; one shared Redis key would silently merge them."""
    ai = RedisTokenBucketLimiter(name="ai", rate_per_min=5, url="redis://x/0")
    render = RedisTokenBucketLimiter(name="render", rate_per_min=5, url="redis://x/0")
    assert ai._redis_key("t1") != render._redis_key("t1")
    assert ai._redis_key("t1").startswith("alppy:ratelimit:ai:")


def test_a_zero_rate_is_off_rather_than_closed() -> None:
    """0 means "no limit" everywhere else in this file; it must not become
    "nobody may ever call this" the moment the backend changes."""
    limiter = RedisTokenBucketLimiter(name="ai", rate_per_min=0, url="redis://x/0")
    assert limiter.take("t1") == 0.0
    assert limiter.peek("t1") == 0.0


def test_the_ttl_outlives_a_full_refill() -> None:
    """A key that expires while still throttling is the same as no limit for
    anybody patient enough to wait for it to vanish."""
    limiter = RedisTokenBucketLimiter(name="ai", rate_per_min=6, url="redis://x/0")
    seconds_to_refill = limiter.capacity / (limiter.rate_per_min / 60.0)
    assert limiter._ttl >= seconds_to_refill


# --- against a real Redis ---------------------------------------------------
# The Lua script is the part that cannot be checked by reading it: refill,
# consume and expiry have to be one atomic step, `peek` must not write, and two
# processes must see one bucket. CI runs a redis service, so this runs there.


def _redis_url() -> str | None:
    import os

    url = os.environ.get("ALPPY_REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis

        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        client.close()
    except Exception:
        return None
    return url


requires_redis = pytest.mark.skipif(_redis_url() is None, reason="no Redis reachable")


@pytest.fixture
def shared_limiter() -> object:
    """A limiter on a keyspace of its own, so a rerun cannot inherit a bucket."""
    import uuid as _uuid

    url = _redis_url()
    assert url is not None
    limiter = RedisTokenBucketLimiter(
        name=f"test-{_uuid.uuid4().hex[:8]}", rate_per_min=60, url=url
    )
    yield limiter  # type: ignore[misc]
    limiter.reset()


@requires_redis
def test_the_bucket_empties_and_then_refills(shared_limiter: RedisTokenBucketLimiter) -> None:
    """Capacity 60 at one token a second: sixty free, then a wait of about one."""
    assert all(shared_limiter.take("t1") == 0.0 for _ in range(60))
    wait = shared_limiter.take("t1")
    assert 0.5 < wait <= 1.0


@requires_redis
def test_a_second_process_sees_the_same_bucket(
    shared_limiter: RedisTokenBucketLimiter,
) -> None:
    """The whole reason this exists. Two workers, one ceiling."""
    for _ in range(60):
        shared_limiter.take("t1")
    other = RedisTokenBucketLimiter(
        name=shared_limiter.name, rate_per_min=60, url=shared_limiter._url
    )
    assert other.take("t1") > 0.0


@requires_redis
def test_peek_neither_consumes_nor_creates(shared_limiter: RedisTokenBucketLimiter) -> None:
    """A peek that refilled — or that wrote at all — would let a caller poll
    their way past the limit, and would turn every health check into a write."""
    import redis

    client = redis.Redis.from_url(shared_limiter._url)
    assert shared_limiter.peek("never-seen") == 0.0
    assert not client.exists(shared_limiter._redis_key("never-seen"))

    for _ in range(60):
        shared_limiter.take("t1")
    first = shared_limiter.peek("t1")
    assert first > 0.0
    assert shared_limiter.peek("t1") == pytest.approx(first, abs=0.05)
    client.close()


@requires_redis
def test_a_correct_password_clears_its_bucket(
    shared_limiter: RedisTokenBucketLimiter,
) -> None:
    for _ in range(60):
        shared_limiter.take("t1")
    assert shared_limiter.take("t1") > 0.0
    shared_limiter.reset_key("t1")
    assert shared_limiter.take("t1") == 0.0
