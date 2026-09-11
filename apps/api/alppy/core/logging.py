"""Structured logging with a request id bound to every line.

**Nothing written here identifies a pupil.** That is a rule about logs, not
only about the database, and it was being broken by the access line: the API
logs `request.url.path`, and a request path in this product routinely carries a
student's primary key —
`/api/v1/classes/{class}/students/{student}/mastery`. Those lines go to
whatever aggregates stdout, under a retention policy that is not this
repository's, and they are the one place a pupil is identified in plain text
outside the tables designed to hold them (audit 07, D33).

`scrub_path` is the fix and it is deliberately a *structural* replacement
rather than a redaction of known-sensitive segments: a path is matched on shape,
so a route added next year is covered without anybody remembering. What survives
is the route — which is the whole diagnostic value of the line — and what goes
is the row.
"""

from __future__ import annotations

import logging
import re
import sys
import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

#: A UUID in any of the forms this API produces or accepts.
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

#: A student UID as printed on a sheet (`7B_15`). Not a database key, but it is
#: the identifier the whole scan path is keyed on and it is trivially
#: re-identifiable by anybody holding the roster — which is the definition that
#: matters here.
_UID_RE = re.compile(r"(?<=/)[0-9]{1,2}[A-Za-z]{1,3}_[0-9]{1,4}(?=/|$)")

#: A stored object key: `<kind>/<school_id>/<entity_id>/<name>`.
_OPAQUE_SEGMENT_RE = re.compile(r"(?<=/)[0-9a-fA-F]{24,}(?=/|$)")


def scrub_path(path: str) -> str:
    """The route, without the row.

    `/api/v1/classes/6f6.../students/2b1.../mastery`
      -> `/api/v1/classes/{id}/students/{id}/mastery`

    Kept here rather than at the one call site because every logger in the
    process can reach it, and because the next person to log a path should find
    this before they find the problem.
    """
    path = _UUID_RE.sub("{id}", path)
    path = _UID_RE.sub("{uid}", path)
    return _OPAQUE_SEGMENT_RE.sub("{id}", path)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def _add_request_id(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Bind the request id onto every line, so one request is greppable."""
    event_dict["request_id"] = request_id_var.get()
    return event_dict


def configure_logging(*, debug: bool = False) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_request_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            (
                structlog.dev.ConsoleRenderer()
                if debug
                else structlog.processors.JSONRenderer()
            ),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
