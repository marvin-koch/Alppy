"""What an error tracker is allowed to send (D8).

The integration is inert until a DSN is set, so the part worth testing is the
part that would matter the day one is: a default-configured tracker sends the
request body, and on this API that body is transcriptions of what a named child
wrote, presigned links to photographs of their handwriting, roster names, or a
password. The rest of the system keeps all of that out of logs; a tracker on
its defaults would put it in a vendor dashboard instead, quietly, under a
retention window somebody else chose.

`before_send` is a pure function precisely so this can be checked without an
SDK, a DSN or a network.
"""

from __future__ import annotations

from typing import Any

from alppy.core.config import Settings
from alppy.core.observability import before_send, configure


def _event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "request": {
            "url": "https://api.alppy.ch/api/v1/scans/abc/confirm",
            "method": "POST",
            "query_string": "crop_url=https%3A%2F%2Fbucket%2Fcrops%2Fsigned",
            "data": {"detections": [{"transcription": "Lea a écrit trois quarts"}]},
            "cookies": {"alppy_session": "a-valid-signed-cookie"},
            "headers": {
                "Cookie": "alppy_session=a-valid-signed-cookie",
                "Authorization": "Bearer something",
                "X-Alppy-Health-Token": "s3cret",
                "User-Agent": "Mozilla/5.0",
                "X-Request-ID": "abc123",
            },
        },
    }
    event.update(overrides)
    return event


def test_the_request_body_never_leaves() -> None:
    """The single most important line. A scan confirmation's body carries what
    the model read off a named child's paper."""
    sent = before_send(_event())
    assert "data" not in sent["request"]


def test_the_session_cookie_never_leaves() -> None:
    """It is the whole of authentication: a cookie in a dashboard is an account."""
    sent = before_send(_event())
    assert "cookies" not in sent["request"]
    header_names = {name.lower() for name in sent["request"]["headers"]}
    assert "cookie" not in header_names
    assert "authorization" not in header_names
    assert "x-alppy-health-token" not in header_names


def test_the_useful_headers_survive() -> None:
    """A scrub that took everything would make the tracker useless, and a
    useless tracker gets loosened rather than kept."""
    sent = before_send(_event())
    assert sent["request"]["headers"]["User-Agent"] == "Mozilla/5.0"
    assert sent["request"]["headers"]["X-Request-ID"] == "abc123"


def test_the_query_string_goes_and_the_path_stays() -> None:
    """The path is how a failure is located. The query string is where a
    presigned crop URL ends up."""
    sent = before_send(_event())
    assert sent["request"]["query_string"] == "[redacted]"
    assert "/api/v1/scans/" in sent["request"]["url"]


def test_a_transcription_in_context_is_redacted_however_deep() -> None:
    """An SDK attaches its own context, and a scan handler's locals are full of
    exactly the values the PII gate exists to keep out of anything durable."""
    sent = before_send(
        _event(
            extra={
                "detection": {
                    "id": "abc",
                    "transcription": "Lea a écrit trois quarts",
                    "nested": [{"crop_key": "crops/school/abc.png"}],
                }
            }
        )
    )
    assert sent["extra"]["detection"]["transcription"] == "[redacted]"
    assert sent["extra"]["detection"]["nested"][0]["crop_key"] == "[redacted]"
    assert sent["extra"]["detection"]["id"] == "abc"


def test_a_pathological_structure_does_not_become_the_outage() -> None:
    """Bounded depth: the event is a structure the SDK built, not one we
    control, and error reporting must never be the thing that fails."""
    deep: dict[str, Any] = {"password": "x"}
    for _ in range(50):
        deep = {"level": deep}
    assert before_send(_event(extra=deep)) is not None


def test_an_event_with_no_request_is_handled() -> None:
    """A worker job's failure has no request at all."""
    assert before_send({"extra": {"job": "process_scan"}})["extra"]["job"] == "process_scan"


# --- installation -----------------------------------------------------------


def test_nothing_is_installed_without_a_dsn() -> None:
    assert configure(Settings(_env_file=None)) is False


def test_a_dsn_without_the_sdk_warns_rather_than_crashing(
    monkeypatch: object,
) -> None:
    """An observability integration that can stop the API from starting has
    made reliability worse, not better."""
    import builtins

    real_import = builtins.__import__

    def _no_sentry(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sentry_sdk":
            raise ImportError("no module named sentry_sdk")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_sentry)  # type: ignore[attr-defined]
    settings = Settings(_env_file=None, sentry_dsn="https://key@example.ingest.sentry.io/1")
    assert configure(settings) is False


def test_traces_are_sampled_rather_than_complete() -> None:
    """A scan pipeline is hundreds of spans, and what is missing here is error
    reporting, not an APM product."""
    rate = Settings(_env_file=None).sentry_traces_sample_rate
    assert 0.0 < rate <= 0.2
