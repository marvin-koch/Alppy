"""Password hashing and the signed session cookie.

Two deliberately small primitives:

* Argon2id for passwords. The parameters are argon2-cffi's defaults, which are
  the OWASP-recommended ones; ``needs_rehash`` lets us migrate them later
  without a password reset.
* An ``itsdangerous`` timed signature for the session. No server-side session
  store: the cookie carries the teacher id and the school id, signed, so a
  request handler can resolve the tenant without a round trip — and a tampered
  cookie fails the signature rather than silently selecting another school.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from alppy.core.config import Settings, get_settings

SESSION_SALT: Final = "alppy.session.v1"

_hasher = PasswordHasher()


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(password_hash: str, raw: str) -> bool:
    """Constant-time-ish verification that never raises for a bad password."""
    try:
        return _hasher.verify(password_hash, raw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:  # pragma: no cover - defensive
        return True


@dataclass(frozen=True, slots=True)
class SessionData:
    """What the cookie carries. Never anything that identifies a student."""

    teacher_id: uuid.UUID
    school_id: uuid.UUID


def _serializer(settings: Settings | None = None) -> URLSafeTimedSerializer:
    s = settings or get_settings()
    return URLSafeTimedSerializer(s.secret_key, salt=SESSION_SALT)


def issue_session(
    teacher_id: uuid.UUID, school_id: uuid.UUID, *, settings: Settings | None = None
) -> str:
    payload: dict[str, str] = {"t": str(teacher_id), "s": str(school_id)}
    return _serializer(settings).dumps(payload)


def read_session(token: str, *, settings: Settings | None = None) -> SessionData | None:
    """Return the session, or ``None`` for anything we cannot fully trust."""
    s = settings or get_settings()
    try:
        raw: Any = _serializer(s).loads(token, max_age=s.session_max_age_s)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return SessionData(
            teacher_id=uuid.UUID(str(raw["t"])), school_id=uuid.UUID(str(raw["s"]))
        )
    except (KeyError, ValueError):
        return None
