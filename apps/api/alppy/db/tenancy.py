"""The tenant a database session is entitled to read.

Tenancy used to be entirely application-level: every query carried its own
``.where(school_id == ...)``, and a query that forgot one was an unbounded
cross-school read with nothing underneath it. Since D84 there is something
underneath it — row-level security, keyed on two session variables this module
is the only writer of:

``app.current_school_id``   the tenant. Every school-scoped table's policy
                            compares its ``school_id`` against it.
``app.current_teacher_id``  the account. Needed by exactly one policy — the
                            one on ``school``, which has to let a teacher see
                            the *other* schools they work at so that logging
                            in, ``/auth/me`` and ``POST /auth/school/{id}``
                            still answer (D74).

Both are set with ``set_config(..., is_local => true)``, which is scoped to the
**transaction**. That is what makes the value safe under a connection pool: it
cannot outlive the request and be inherited by the next one to check out the
same connection. It also means it has to be re-applied on every transaction,
not once per request — services commit mid-request — which is what the
``after_begin`` listener below is for.

Unset is not "see everything", it is "see nothing": the policies read
``nullif(current_setting(..., true), '')::uuid``, which is NULL when nothing has
been bound, and a comparison against NULL admits no rows. A session that never
resolved a membership is therefore blind rather than omniscient.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

GUC_SCHOOL: Final = "app.current_school_id"
GUC_TEACHER: Final = "app.current_teacher_id"

_APPLY: Final = text(
    "SELECT set_config(:school_key, :school_id, true),"
    "       set_config(:teacher_key, :teacher_id, true)"
)


class TenantSession(Session):
    """A session that knows which school it may read.

    The tenant is deliberately **not** a constructor argument: at the moment a
    request's session is opened nobody knows the answer yet, because resolving
    it means reading ``teacher_school`` — which needs a session. So the session
    starts blind and ``bind_tenant`` is called by ``deps.get_membership`` once
    the cookie has been proved against the membership table, in the one place
    that check already lives (I-platform-14).

    A handler that takes ``DbDep`` without ``TenantDep`` or ``ScopeDep`` never
    gets that call, and its session stays blind. That is the intended
    behaviour and not an oversight: the failure mode of a forgotten tenant is
    now an empty result, not another school's roster.
    """

    school_id: uuid.UUID | None = None
    teacher_id: uuid.UUID | None = None

    def bind_tenant(self, *, school_id: uuid.UUID, teacher_id: uuid.UUID | None = None) -> None:
        """Name the tenant this session acts for, from now until it closes."""
        bind(self, school_id=school_id, teacher_id=teacher_id)


def bind(
    session: Session, *, school_id: uuid.UUID, teacher_id: uuid.UUID | None = None
) -> None:
    """Bind a tenant onto any session.

    Takes a plain ``Session`` rather than a ``TenantSession`` because the HTTP
    tests substitute a SQLite session for the real one, and the dependency that
    calls this must not have to know which it was handed. A plain ``Session``
    on Postgres would miss the ``after_begin`` re-bind and go blind after its
    first commit — an empty read, never a cross-tenant one, so the degradation
    is in the safe direction.
    """
    session.school_id = school_id  # type: ignore[attr-defined]  # plain Session, see above
    session.teacher_id = teacher_id  # type: ignore[attr-defined]  # plain Session, see above
    # `connection()` starts the transaction if one is not open yet, which also
    # fires `after_begin`. If one IS open — and by this point one usually is,
    # since resolving the membership just read two tables — that listener has
    # already run with nothing to say, so apply it here too.
    apply_tenant(session, session.connection())


def apply_tenant(session: Session, connection: Connection) -> None:
    """Push the session's tenant onto this transaction.

    A no-op off Postgres: the unit suite builds its schema on SQLite, which has
    neither ``set_config`` nor row-level security. Nothing there is protected by
    this — see ``scripts/check-rls.py``, which is where the policies are
    actually exercised, for the same reason ``check-schema-drift.py`` exists.
    """
    if connection.dialect.name != "postgresql":
        return
    school_id = getattr(session, "school_id", None)
    teacher_id = getattr(session, "teacher_id", None)
    connection.execute(
        _APPLY,
        {
            "school_key": GUC_SCHOOL,
            "school_id": str(school_id) if school_id else "",
            "teacher_key": GUC_TEACHER,
            "teacher_id": str(teacher_id) if teacher_id else "",
        },
    )


@event.listens_for(TenantSession, "after_begin")
def _rebind_on_begin(session: Session, _transaction: Any, connection: Connection) -> None:
    """Re-apply the tenant every time a transaction opens.

    ``set_config(..., true)`` dies with its transaction, and a request commits
    several times on its way through a service. Binding once at the start of
    the request would leave every statement after the first commit running with
    the GUC unset — which, being fail-closed, would read as "this teacher's
    school suddenly has no classes in it".
    """
    if getattr(session, "school_id", None) is None:
        return
    apply_tenant(session, connection)


__all__ = ["GUC_SCHOOL", "GUC_TEACHER", "TenantSession", "apply_tenant", "bind"]
