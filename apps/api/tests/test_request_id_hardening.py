"""`X-Request-ID` is caller-controlled and lands in every log line."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from alppy.core.config import get_settings
from alppy.main import REQUEST_ID_HEADER, create_app, frame_ancestors


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def test_a_plain_token_is_kept(client: TestClient) -> None:
    """The header exists so a trace can span the caller's system and ours."""
    response = client.get("/api/v1/health", headers={REQUEST_ID_HEADER: "trace-abc.123_4"})
    assert response.headers[REQUEST_ID_HEADER] == "trace-abc.123_4"


@pytest.mark.parametrize(
    "forged",
    [
        # The one that matters: a newline splits the access line in two, and
        # the second half is whatever the caller wanted the log to say.
        "abc\nhttp.request method=GET path=/admin status=200",
        "abc\r\nX-Injected: yes",
        "a" * 65,
        "",
        "id with spaces",
        "../../etc/passwd",
    ],
)
def test_anything_else_is_replaced(client: TestClient, forged: str) -> None:
    response = client.get("/api/v1/health", headers={REQUEST_ID_HEADER: forged})
    echoed = response.headers[REQUEST_ID_HEADER]
    assert echoed != forged
    assert "\n" not in echoed and "\r" not in echoed
    assert 0 < len(echoed) <= 64


def test_security_headers_are_on_every_response(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    # `frame-ancestors` now NAMES the front ends, because 'self' alone is the
    # API's own origin and the builder is never served from it. The previous
    # assertion — exactly `frame-ancestors 'self'` — was the bug written down:
    # it passed while every sheet preview in the shipped compose arrangement
    # was refused by the browser.
    policy = response.headers["Content-Security-Policy"]
    assert policy.startswith("frame-ancestors 'self'")
    for origin in get_settings().cors_origins:
        assert origin in policy


def test_the_web_origin_may_frame_the_preview() -> None:
    """The preview is framed by the builder, which is a different origin.

    `docker compose up` serves the web app on :3000 and the API on :8000, and
    `next.config.ts` describes the same split for local development. Under
    `frame-ancestors 'self'` the browser blocked the frame and the preview
    panel was blank, with the explanation only in the console.
    """
    settings = get_settings().model_copy(
        update={"cors_origins": ("http://localhost:3000", "https://alppy.example")}
    )
    policy = frame_ancestors(settings)
    assert policy == (
        "frame-ancestors 'self' http://localhost:3000 https://alppy.example"
    )


def test_a_wildcard_origin_never_becomes_a_framing_permission() -> None:
    """CORS may be wildcarded on a laptop; framing must not follow it there.

    `frame-ancestors *` is precisely the clickjacking hole this header exists
    to close, so a `"*"` is dropped rather than translated.
    """
    settings = get_settings().model_copy(
        update={"cors_origins": ("*", "http://localhost:3000")}
    )
    assert frame_ancestors(settings) == "frame-ancestors 'self' http://localhost:3000"
