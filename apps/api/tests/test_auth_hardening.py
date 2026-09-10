"""Sign-in throttling and session expiry — the two auth properties nothing pinned.

`test_api_auth.py` covers the happy path and a tampered cookie. Two things it
did not:

* **The login endpoint had no rate limit at all.** Every other expensive door
  in the API is behind a bucket keyed on a teacher id, which is exactly what a
  caller who has not signed in does not have — so the one unauthenticated
  endpoint was the one unlimited endpoint. Behind it: a roster of children,
  reachable by guessing one password, and Argon2id, which is costly by design
  and therefore turns an unlimited endpoint into an unlimited CPU bill.

* **Session expiry was never exercised.** `read_session` honours
  `session_max_age_s` through `itsdangerous`, but no test made a token old, so
  a session that never actually expired would have looked exactly like this.

Integration-level where it matters: the throttling tests drive the real HTTP
endpoint through `TestClient` with the real limiter and the real Argon2id
verification, not a mocked one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import PASSWORD, Tenant, make_app_client

from alppy.api import deps
from alppy.core.config import Settings
from alppy.core.security import SESSION_SALT, issue_session, read_session
from alppy.storage import LocalStorage

WRONG = "definitely-not-the-password"


def _attempt(client: TestClient, email: str, password: str = WRONG) -> int:
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    ).status_code


# --------------------------------------------------------------------------
# Throttling a failing account
# --------------------------------------------------------------------------
def test_repeated_wrong_passwords_are_eventually_refused(
    client: TestClient, tenant: Tenant, settings: Settings
) -> None:
    """The point of the whole exercise: guessing a teacher's password must not
    be something you can do at request speed."""
    email = tenant.teacher.email
    limit = settings.login_rate_limit_per_min

    for _ in range(limit):
        assert _attempt(client, email) == 401

    throttled = client.post(
        "/api/v1/auth/login", json={"email": email, "password": WRONG}
    )
    assert throttled.status_code == 429
    body = throttled.json()
    assert body["error"]["code"] == "rate_limited"
    # The client has to be able to back off correctly rather than hammering.
    assert body["error"]["details"]["retry_after_s"] >= 1


def test_a_throttled_attempt_does_not_verify_the_password(
    client: TestClient, tenant: Tenant, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DoS half of the fix.

    Argon2id is deliberately slow. If the limiter ran after the hash, a
    throttled endpoint would still burn a full verification per request and the
    429 would be decoration — the attacker would have achieved the CPU
    exhaustion anyway.
    """
    for _ in range(settings.login_rate_limit_per_min):
        _attempt(client, tenant.teacher.email)

    verified = False

    def _spy(*_args: object, **_kw: object) -> bool:
        nonlocal verified
        verified = True
        return False

    monkeypatch.setattr("alppy.api.v1.auth.verify_password", _spy)
    assert _attempt(client, tenant.teacher.email) == 429
    assert not verified


def test_the_correct_password_still_works_below_the_limit(
    client: TestClient, tenant: Tenant, settings: Settings
) -> None:
    """A teacher who fumbles their password twice and then gets it right must
    not be locked out — the common case by far."""
    for _ in range(settings.login_rate_limit_per_min - 1):
        assert _attempt(client, tenant.teacher.email) == 401

    ok = client.post(
        "/api/v1/auth/login", json={"email": tenant.teacher.email, "password": PASSWORD}
    )
    assert ok.status_code == 200


def test_a_success_clears_the_accounts_failures(
    client: TestClient, tenant: Tenant, settings: Settings
) -> None:
    """Otherwise a teacher who mistypes four times, signs in, signs out and
    mistypes once more is locked out of their own account for a minute."""
    email = tenant.teacher.email
    for _ in range(settings.login_rate_limit_per_min - 1):
        _attempt(client, email)

    assert client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    ).status_code == 200

    # The budget is fresh, so the next wrong password is a 401 and not a 429.
    assert _attempt(client, email) == 401


def test_a_successful_sign_in_is_never_throttled_by_its_own_repetition(
    client: TestClient, tenant: Tenant, settings: Settings
) -> None:
    """Only failures are charged. A shared classroom machine signing the same
    teacher in over and over is normal use, not an attack."""
    for _ in range(settings.login_rate_limit_per_min * 3):
        assert client.post(
            "/api/v1/auth/login",
            json={"email": tenant.teacher.email, "password": PASSWORD},
        ).status_code == 200


def test_throttling_one_account_does_not_throttle_another(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, settings: Settings
) -> None:
    """The account bucket is per account. If it were global, one attacker would
    take down sign-in for every school on the deployment."""
    for _ in range(settings.login_rate_limit_per_min + 2):
        _attempt(client, tenant.teacher.email)

    assert client.post(
        "/api/v1/auth/login",
        json={"email": other_tenant.teacher.email, "password": PASSWORD},
    ).status_code == 200


def test_an_unknown_email_is_throttled_the_same_way(
    client: TestClient, tenant: Tenant, settings: Settings
) -> None:
    """The endpoint must not become an account oracle in a second way: if only
    real accounts were throttled, the status code would say which addresses
    exist even though the message does not."""
    for _ in range(settings.login_rate_limit_per_min):
        assert _attempt(client, "nobody@example.org") == 401
    assert _attempt(client, "nobody@example.org") == 429


def test_the_address_bucket_bounds_stuffing_across_many_accounts(
    db: Session, storage: LocalStorage, tenant: Tenant
) -> None:
    """Per-account limits alone do not stop one source trying one password
    against a thousand addresses — each account stays under its own budget
    while the box pays for every Argon2id call."""
    settings = Settings(
        env="ci",
        secret_key="test-secret-key",
        max_upload_mb=1,
        login_rate_limit_per_min=50,  # deliberately not the binding constraint
        login_ip_rate_limit_per_min=4,
    )
    deps.get_login_limiter(settings).reset()
    deps.get_login_ip_limiter(settings).reset()
    try:
        with make_app_client(db, storage, settings) as client:
            for i in range(4):
                assert _attempt(client, f"victim{i}@example.org") == 401
            # A fifth address, same source: the address bucket is what stops it.
            assert _attempt(client, "victim4@example.org") == 429
    finally:
        deps.get_login_limiter(settings).reset()
        deps.get_login_ip_limiter(settings).reset()


# --------------------------------------------------------------------------
# The client address the bucket keys on
# --------------------------------------------------------------------------
class _FakeRequest:
    def __init__(self, host: str | None, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})() if host else None


def test_a_forwarded_header_is_ignored_when_no_proxy_is_configured() -> None:
    """`X-Forwarded-For` is written by whoever is talking to us. Trusting it at
    zero hops would let one client mint a fresh bucket per request by varying a
    header — the limiter would be there and do nothing."""
    settings = Settings(env="ci", secret_key="test-secret-key", trusted_proxy_hops=0)
    request = _FakeRequest("10.0.0.9", {"x-forwarded-for": "1.2.3.4"})
    assert deps.client_ip(request, settings) == "10.0.0.9"  # type: ignore[arg-type]


def test_one_configured_hop_reads_the_address_the_proxy_appended() -> None:
    settings = Settings(env="ci", secret_key="test-secret-key", trusted_proxy_hops=1)
    request = _FakeRequest("10.0.0.9", {"x-forwarded-for": "spoofed, 203.0.113.7"})
    # The rightmost entry is the one our own proxy wrote; everything to its
    # left is the client's text.
    assert deps.client_ip(request, settings) == "203.0.113.7"  # type: ignore[arg-type]


def test_a_short_forwarded_chain_falls_back_to_the_socket() -> None:
    """Fewer entries than configured hops means the header did not come through
    our proxy. Taking the leftmost anyway would read attacker-supplied text."""
    settings = Settings(env="ci", secret_key="test-secret-key", trusted_proxy_hops=2)
    request = _FakeRequest("10.0.0.9", {"x-forwarded-for": "1.2.3.4"})
    assert deps.client_ip(request, settings) == "10.0.0.9"  # type: ignore[arg-type]


def test_a_missing_client_is_named_rather_than_crashing() -> None:
    settings = Settings(env="ci", secret_key="test-secret-key")
    assert deps.client_ip(_FakeRequest(None), settings) == "unknown"  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The bucket itself
# --------------------------------------------------------------------------
def test_peek_reports_the_wait_without_consuming_a_token() -> None:
    """A peek that consumed would charge the request that is about to succeed;
    a peek that refilled would let a caller poll their way past the limit."""
    limiter = deps.TokenBucketLimiter(rate_per_min=60)
    assert limiter.peek("k", now=0.0) == 0.0  # unseen key: nothing owed
    for i in range(60):
        assert limiter.take("k", now=0.0) == 0.0, i
    first = limiter.peek("k", now=0.0)
    assert first > 0.0
    assert limiter.peek("k", now=0.0) == first  # idempotent


def test_a_bucket_refills_over_time() -> None:
    limiter = deps.TokenBucketLimiter(rate_per_min=60)
    for _ in range(60):
        limiter.take("k", now=0.0)
    assert limiter.peek("k", now=0.0) > 0.0
    # 60/min is one per second.
    assert limiter.peek("k", now=1.5) == 0.0


def test_reset_key_forgets_one_account_and_leaves_the_others() -> None:
    limiter = deps.TokenBucketLimiter(rate_per_min=1)
    limiter.take("a", now=0.0)
    limiter.take("b", now=0.0)
    limiter.reset_key("a")
    assert limiter.peek("a", now=0.0) == 0.0
    assert limiter.peek("b", now=0.0) > 0.0


def test_a_rate_of_zero_disables_the_bucket() -> None:
    """The escape hatch has to actually open: a deployment that sets 0 must not
    be throttled at some other rate."""
    limiter = deps.TokenBucketLimiter(rate_per_min=0)
    for _ in range(1000):
        assert limiter.take("k") == 0.0
    assert limiter.peek("k") == 0.0


# --------------------------------------------------------------------------
# Session expiry
# --------------------------------------------------------------------------
def test_a_fresh_session_reads_back(settings: Settings, tenant: Tenant) -> None:
    token = issue_session(tenant.teacher.id, tenant.school.id, settings=settings)
    session = read_session(token, settings=settings)
    assert session is not None
    assert session.teacher_id == tenant.teacher.id
    assert session.school_id == tenant.school.id


def test_a_session_older_than_the_maximum_age_is_refused(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`session_max_age_s` is honoured, not merely configured.

    A session that never expires is invisible until it matters: a cookie copied
    off a shared staffroom machine in September would still open a roster in
    June. The token is correctly signed throughout — only its AGE is at issue,
    which is what separates this from the tampered-cookie test.

    Ageing is done by moving `itsdangerous`'s clock forward at read time rather
    than by sleeping, so the test costs nothing and pins the real window.
    """
    import itsdangerous.timed

    settings = Settings(env="ci", secret_key="test-secret-key", session_max_age_s=3600)
    token = issue_session(tenant.teacher.id, tenant.school.id, settings=settings)
    assert read_session(token, settings=settings) is not None

    real = itsdangerous.timed.TimestampSigner.get_timestamp
    monkeypatch.setattr(
        itsdangerous.timed.TimestampSigner,
        "get_timestamp",
        lambda self: int(real(self)) + 3601,
    )
    assert read_session(token, settings=settings) is None


def test_a_session_inside_the_window_still_reads(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half: the window is a window, not a hair trigger. An hour-long
    session must survive fifty-nine minutes, or every teacher is signed out
    mid-lesson."""
    import itsdangerous.timed

    settings = Settings(env="ci", secret_key="test-secret-key", session_max_age_s=3600)
    token = issue_session(tenant.teacher.id, tenant.school.id, settings=settings)

    real = itsdangerous.timed.TimestampSigner.get_timestamp
    monkeypatch.setattr(
        itsdangerous.timed.TimestampSigner,
        "get_timestamp",
        lambda self: int(real(self)) + 3540,
    )
    assert read_session(token, settings=settings) is not None


def test_an_expired_cookie_does_not_open_a_session(
    db: Session, storage: LocalStorage, tenant: Tenant
) -> None:
    """End to end through HTTP: the API refuses an aged cookie, it does not
    merely fail to mint one."""
    settings = Settings(
        env="ci", secret_key="test-secret-key", max_upload_mb=1, session_max_age_s=0
    )
    with make_app_client(db, storage, settings) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": tenant.teacher.email, "password": PASSWORD},
        )
        assert response.status_code == 200
        # `session_max_age_s = 0` means every token is already too old.
        assert client.get("/api/v1/auth/me").status_code == 401


def test_a_session_signed_with_another_key_is_refused(tenant: Tenant) -> None:
    """The cookie is the whole of our authentication, so a deployment that
    rotates `ALPPY_SECRET_KEY` must invalidate every outstanding session."""
    issued = Settings(env="ci", secret_key="the-old-key")
    rotated = Settings(env="ci", secret_key="the-new-key")
    token = issue_session(tenant.teacher.id, tenant.school.id, settings=issued)
    assert read_session(token, settings=rotated) is None


def test_a_session_carrying_a_malformed_payload_is_refused(tenant: Tenant) -> None:
    """Correctly signed but structurally wrong — what a rolled-back payload
    change looks like. It must read as "no session", never as a partial one."""
    settings = Settings(env="ci", secret_key="test-secret-key")
    serializer = URLSafeTimedSerializer(settings.secret_key, salt=SESSION_SALT)
    for payload in (["not", "a", "dict"], {"t": "not-a-uuid", "s": str(tenant.school.id)}, {}):
        assert read_session(serializer.dumps(payload), settings=settings) is None


def test_a_session_never_carries_anything_identifying_a_student(
    tenant: Tenant, settings: Settings
) -> None:
    """The cookie is readable by anyone holding it. It carries two uuids."""
    session = read_session(
        issue_session(tenant.teacher.id, tenant.school.id, settings=settings),
        settings=settings,
    )
    assert session is not None
    assert set(vars(type(session)).get("__slots__", ())) <= {"teacher_id", "school_id"}
