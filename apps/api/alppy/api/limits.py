"""Rate-limit buckets, in this process or in Redis (D30).

One bucket per teacher (or per client address, for sign-in), refilled by the
clock. The algorithm has not changed; **where the bucket lives** has.

**Why it had to move.** Every bucket was a dict in the API process. With one
uvicorn worker that is the whole deployment and the limit means what it says.
The moment there are two workers — and there have to be, one process cannot
serve an establishment between lessons (D19) — each holds its own dict, the
same teacher is load-balanced across both, and every ceiling is silently
multiplied by the worker count. That is the opposite of what adding workers is
supposed to do, and nothing about it is visible: the limit is still configured,
still enforced, and worth twice what it says.

So the two changes land together and the configuration says so:
``_refuse_unsafe_deployment`` refuses to boot a deployment that runs more than
one worker on in-process buckets.

**Failure is degradation, not an outage.** If Redis is unreachable the limiter
falls back to this process's own dict for that call. A sign-in limiter that
raised on a Redis blip would lock a school out of its own product; one that
returned "no wait" would remove the brake in front of Argon2id at the moment
the system is already unhealthy. The in-process bucket is the honest middle: a
weaker limit while Redis is down, never no limit and never a refusal.

**Redis's clock, not ours.** The script reads `TIME` inside Redis, so every
worker measures the same second. Two processes with drifting monotonic clocks
sharing one bucket would refill it twice.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from alppy.core.logging import get_logger

if TYPE_CHECKING:
    from alppy.core.config import Settings

log = get_logger(__name__)


class Limiter(Protocol):
    """What a rate-limited handler needs, whichever backend is behind it."""

    rate_per_min: int

    def take(self, key: str, *, now: float | None = None) -> float: ...
    def peek(self, key: str, *, now: float | None = None) -> float: ...
    def reset_key(self, key: str) -> None: ...
    def reset(self) -> None: ...


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


@dataclass(slots=True)
class TokenBucketLimiter:
    """In-process token bucket, one bucket per teacher.

    Correct for a single process, and only for a single process — see the
    module docstring. This stays the local-development and CI backend (the test
    suite needs no Redis), and the fallback when Redis cannot be reached.
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

    def peek(self, key: str, *, now: float | None = None) -> float:
        """Seconds to wait, WITHOUT consuming a token. 0.0 when one is free.

        The login path needs to know it is throttled *before* it does the
        expensive thing (Argon2id), and it charges a token only for a failure —
        so asking and taking have to be separable. Deliberately non-mutating:
        a peek that refilled the bucket would let a caller poll their way past
        the limit.
        """
        if self.rate_per_min <= 0:
            return 0.0
        bucket = self._buckets.get(key)
        if bucket is None:
            return 0.0
        t = now if now is not None else time.monotonic()
        refill = (t - bucket.updated_at) * (self.rate_per_min / 60.0)
        tokens = min(self.capacity, bucket.tokens + refill)
        if tokens >= 1.0:
            return 0.0
        return (1.0 - tokens) / (self.rate_per_min / 60.0)

    def reset_key(self, key: str) -> None:
        """Forget one bucket. A correct password clears the account's."""
        self._buckets.pop(key, None)

    def reset(self) -> None:
        self._buckets.clear()


#: The bucket, in Lua, so refill-and-consume is one atomic step.
#:
#: Read-modify-write from Python would be three round trips with two other
#: workers racing between them, which is how a "12 per minute" limit becomes
#: "12 per minute per worker, plus whatever slips through the gap".
#:
#: `TIME` is Redis's own clock. Redis replicates script *effects* rather than
#: the script, so a non-deterministic command here is allowed and is the only
#: way several processes can agree on when the bucket was last touched.
#:
#: ARGV: rate per second, capacity, consume (1) or peek (0), key ttl.
#: Returns the seconds to wait, as a string — Lua has no float return type.
_BUCKET_SCRIPT = """
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local consume = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local clock = redis.call('TIME')
local now = tonumber(clock[1]) + (tonumber(clock[2]) / 1000000)

local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])

if tokens == nil or ts == nil then
  -- A bucket that does not exist is a full one. `peek` must not create it:
  -- an unknown caller is not throttled, and writing here would turn every
  -- health check into a write.
  if consume == 0 then return '0' end
  tokens = capacity
  ts = now
end

tokens = math.min(capacity, tokens + ((now - ts) * rate))

local wait = 0
if tokens >= 1 then
  if consume == 1 then tokens = tokens - 1 end
else
  wait = (1 - tokens) / rate
end

if consume == 1 then
  redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
  redis.call('EXPIRE', KEYS[1], ttl)
end

return tostring(wait)
"""


class RedisTokenBucketLimiter:
    """The same bucket, shared by every API process.

    One Redis key per (limiter name, bucket key), so the four limiters cannot
    collide: a teacher's render bucket and their AI bucket are different
    ceilings and were different dicts.
    """

    def __init__(self, *, name: str, rate_per_min: int, url: str, burst: int | None = None) -> None:
        self.name = name
        self.rate_per_min = rate_per_min
        self.burst = burst
        self._url = url
        self._client: Any | None = None
        self._script: Any | None = None
        # What answers when Redis does not. Shares this process only, which is
        # a weaker limit than intended and a much better one than none.
        self._fallback = TokenBucketLimiter(rate_per_min=rate_per_min, burst=burst)

    @property
    def capacity(self) -> float:
        return float(self.burst if self.burst is not None else self.rate_per_min)

    @property
    def _ttl(self) -> int:
        """Long enough that a bucket cannot expire while still throttling.

        A full refill takes capacity/rate minutes; anything shorter and a
        caller waits for the key to vanish rather than for it to refill, which
        is the same as no limit for anyone patient.
        """
        if self.rate_per_min <= 0:
            return 60
        return max(60, int((self.capacity / (self.rate_per_min / 60.0)) * 2))

    def _redis_key(self, key: str) -> str:
        return f"alppy:ratelimit:{self.name}:{key}"

    def _ensure(self) -> Any:
        if self._script is None:
            import redis

            self._client = redis.Redis.from_url(
                self._url,
                socket_connect_timeout=1,
                socket_timeout=1,
                decode_responses=True,
            )
            self._script = self._client.register_script(_BUCKET_SCRIPT)
        return self._script

    def _run(self, key: str, *, consume: bool) -> float:
        if self.rate_per_min <= 0:
            return 0.0
        try:
            script = self._ensure()
            raw = script(
                keys=[self._redis_key(key)],
                args=[self.rate_per_min / 60.0, self.capacity, 1 if consume else 0, self._ttl],
            )
            return float(raw)
        except Exception as exc:
            # Not `log.exception`: a Redis blip during a lesson would otherwise
            # write a stack trace per request into whatever reads these logs.
            log.warning(
                "ratelimit.redis_unavailable",
                limiter=self.name,
                error=str(exc),
                detail="falling back to this process's own bucket",
            )
            # The script is rebuilt on the next call, so a recovered Redis is
            # picked up without a restart.
            self._script = None
            self._client = None
            return (
                self._fallback.take(key) if consume else self._fallback.peek(key)
            )

    def take(self, key: str, *, now: float | None = None) -> float:
        # `now` is accepted for interface compatibility and ignored: the shared
        # clock has to be Redis's, or two workers refill one bucket twice.
        return self._run(key, consume=True)

    def peek(self, key: str, *, now: float | None = None) -> float:
        return self._run(key, consume=False)

    def reset_key(self, key: str) -> None:
        self._fallback.reset_key(key)
        try:
            self._ensure()
            assert self._client is not None
            self._client.delete(self._redis_key(key))
        except Exception as exc:
            # A failure here leaves a correct password still counted as an
            # attempt, which is a nuisance and not a hole.
            log.warning("ratelimit.reset_failed", limiter=self.name, error=str(exc))

    def reset(self) -> None:
        """Every bucket for this limiter. Tests and the CLI; never a handler."""
        self._fallback.reset()
        try:
            self._ensure()
            assert self._client is not None
            for found in self._client.scan_iter(match=f"alppy:ratelimit:{self.name}:*"):
                self._client.delete(found)
        except Exception as exc:
            log.warning("ratelimit.reset_failed", limiter=self.name, error=str(exc))


def resolve_backend(settings: Settings) -> str:
    """`memory` or `redis`, with `auto` decided by the environment.

    `auto` is the default and means redis on a real deployment, memory
    everywhere else. Local development and the test suite get a limiter that
    needs nothing running; a deployment gets one that survives a second worker.
    """
    if settings.rate_limit_backend != "auto":
        return settings.rate_limit_backend
    return "redis" if settings.env in ("staging", "production") else "memory"


def build_limiter(
    name: str, *, rate_per_min: int, settings: Settings, burst: int | None = None
) -> Limiter:
    if resolve_backend(settings) == "redis":
        return RedisTokenBucketLimiter(
            name=name, rate_per_min=rate_per_min, url=str(settings.redis_url), burst=burst
        )
    return TokenBucketLimiter(rate_per_min=rate_per_min, burst=burst)
