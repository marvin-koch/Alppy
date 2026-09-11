"""Error tracking, wired and inert (D8).

There is no error tracker, no metrics backend, no alerting and no uptime
monitoring. Failures here cluster between 08:00 and 17:00 on school days, and a
failure during a lesson is unrecoverable *for that lesson* — so the gap between
"it broke" and "somebody knows" is the gap that matters most, and today the
only path is a teacher mentioning it afterwards.

**What this module is.** The integration, complete, and switched off: with no
`ALPPY_SENTRY_DSN` it does nothing at all. The account is a human act; the
wiring is not, and there is no reason for them to wait for each other.

**Why the SDK is an optional dependency.** The default image does not carry it,
so a deployment that has not chosen a vendor installs nothing extra, and the
absence is reported once at startup rather than crashing anything.

────────────────────────────────────────────────────────────────────────────
**The configuration below is the load-bearing part, not the boilerplate.**
────────────────────────────────────────────────────────────────────────────

A default-configured error tracker sends the request body with the event. On
this API that body is, variously, a scan confirmation carrying transcriptions
of what a named child wrote, a crop URL that is a presigned link to a
photograph of their handwriting, a roster import, a teacher's password. The
rest of the system is careful to keep exactly that out of logs — the PII gate
raises rather than redacting, `Job.error` holds a code and never prose, the
access log is swept — and a tracker left on its defaults would undo all of it
through a vendor's dashboard, quietly, and with a retention window somebody
else chose.

So: `send_default_pii=False`, no request bodies, no cookies, no headers that
could carry the session, and a `before_send` that drops anything that slipped
through. Session replay is not enabled at all — it is a recording of a screen
that shows children's names and marks.
"""

from __future__ import annotations

from typing import Any

from alppy.core.config import Settings
from alppy.core.logging import get_logger

log = get_logger(__name__)

#: Header names never sent with an event. `cookie` carries the session, and
#: `authorization`/`x-alppy-health-token` are credentials in their own right.
_DROP_HEADERS = frozenset(
    {"cookie", "set-cookie", "authorization", "x-alppy-health-token", "x-api-key"}
)

#: Keys in any structured payload that must not travel. Not a redaction
#: strategy — the request body is dropped wholesale — but a second line for the
#: places an SDK attaches its own context.
_DROP_KEYS = frozenset(
    {
        "first_name",
        "last_name",
        "student_name",
        "transcription",
        "machine_transcription",
        "crop_url",
        "crop_key",
        "download_url",
        "password",
        "secret",
        "token",
    }
)


def _scrub(value: Any, depth: int = 0) -> Any:
    """Replace anything under a suspicious key, however deep it is nested.

    Bounded depth on purpose: an event is a structure the SDK built, not one we
    control, and a cyclic or pathological one must not turn error reporting
    into the outage.
    """
    if depth > 6:
        return value
    if isinstance(value, dict):
        return {
            key: ("[redacted]" if str(key).lower() in _DROP_KEYS else _scrub(item, depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item, depth + 1) for item in value]
    return value


def before_send(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """The last thing that touches an event before it leaves the process.

    Pure, and exported, so the rule can be tested without an SDK, a DSN or a
    network — which is the only way a rule like this stays true.
    """
    request = event.get("request")
    if isinstance(request, dict):
        # The body, wholesale. On this API it is transcriptions, crop URLs,
        # roster names and passwords, depending on the route.
        request.pop("data", None)
        request.pop("cookies", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                name: value
                for name, value in headers.items()
                if name.lower() not in _DROP_HEADERS
            }
        # A student id lives in the path and a presigned crop URL can live in
        # the query string. The path is worth keeping — it is how a failure is
        # located — the query string is not.
        url = request.get("query_string")
        if url:
            request["query_string"] = "[redacted]"

    for section in ("extra", "contexts", "tags"):
        if section in event:
            event[section] = _scrub(event[section])
    return event


def configure(settings: Settings, *, release: str | None = None) -> bool:
    """Install the error tracker. Returns whether it was actually installed.

    Never raises. An observability integration that can stop the API from
    starting has made reliability worse, not better.
    """
    dsn = settings.sentry_dsn
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log.warning(
            "observability.sdk_missing",
            detail=(
                "ALPPY_SENTRY_DSN is set but sentry-sdk is not installed; "
                'install the "observability" extra or unset the DSN'
            ),
        )
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=settings.env,
            release=release,
            # Never. This is the switch that would attach usernames, IP
            # addresses and request bodies to every event.
            send_default_pii=False,
            max_request_body_size="never",
            # Sampled, not everything: a scan pipeline is hundreds of spans and
            # the point here is errors, not a performance product.
            traces_sample_rate=settings.sentry_traces_sample_rate,
            before_send=before_send,
            # Session replay is deliberately absent rather than set to 0: it is
            # a recording of a screen showing children's names and their marks,
            # and a default that can be raised by editing one number is a
            # different thing from an integration that never had it.
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("observability.init_failed", error=type(exc).__name__, detail=str(exc))
        return False

    log.info("observability.enabled", environment=settings.env, release=release)
    return True
