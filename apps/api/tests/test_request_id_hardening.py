"""`X-Request-ID` is caller-controlled and lands in every log line."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from alppy.main import REQUEST_ID_HEADER, create_app


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
    assert response.headers["Content-Security-Policy"] == "frame-ancestors 'self'"
