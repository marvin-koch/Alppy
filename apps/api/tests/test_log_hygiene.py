"""No log line identifies a pupil (D33).

The database is designed to hold children's names and is protected accordingly.
Logs are not: they go to stdout, get picked up by whatever aggregates them, and
live under a retention policy that is not this repository's. So the rule is that
a pupil is never identifiable in one — and it was being broken by the plainest
line in the app, the access log, because a request path in this product
routinely carries a student's primary key.

There was no test asserting any of this, which is why it went unnoticed.
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.testclient import TestClient
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login

from alppy.core.logging import scrub_path

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


# --- the scrubber -----------------------------------------------------------


def test_a_student_key_does_not_survive_a_path() -> None:
    student, klass = uuid.uuid4(), uuid.uuid4()
    path = f"/api/v1/classes/{klass}/students/{student}/mastery"
    assert scrub_path(path) == "/api/v1/classes/{id}/students/{id}/mastery"


def test_the_route_survives() -> None:
    """The diagnostic value of the line is which route was slow or failed. A
    scrubber that took that too would be turned off within a week."""
    scrubbed = scrub_path(f"/api/v1/scans/{uuid.uuid4()}/confirm")
    assert scrubbed == "/api/v1/scans/{id}/confirm"


def test_a_printed_uid_is_scrubbed_too() -> None:
    """`7B_15` is not a database key, and it is the identifier the entire scan
    path is keyed on — trivially re-identifiable by anyone holding the roster,
    which is the definition that matters."""
    assert scrub_path("/api/v1/students/7B_15/sheets") == "/api/v1/students/{uid}/sheets"


def test_an_object_key_keeps_its_shape_and_loses_its_ids() -> None:
    key = "scans/" + uuid.uuid4().hex + "/" + uuid.uuid4().hex + "/page-000.png"
    assert scrub_path(key) == "scans/{id}/{id}/page-000.png"


def test_a_path_with_nothing_to_hide_is_unchanged() -> None:
    for path in ("/api/v1/health", "/api/v1/classes", "/api/v1/auth/login"):
        assert scrub_path(path) == path


def test_scrubbing_is_idempotent() -> None:
    """It runs on a path that may already have been through it."""
    once = scrub_path(f"/api/v1/students/{uuid.uuid4()}")
    assert scrub_path(once) == once


# --- the line the app actually writes ---------------------------------------


def test_no_identifier_reaches_the_access_log(
    client: TestClient, tenant: Tenant, capsys: pytest.CaptureFixture[str]
) -> None:
    """The end-to-end claim, made against a real request to a real route that
    carries a pupil's key.

    Asserted on the raw captured stream rather than on parsed JSON, because the
    renderer differs between a development run and a deployment — and the claim
    ("this id does not appear in what we printed") has to hold for both.
    """
    login(client, tenant.teacher.email)
    student = tenant.students[0]
    capsys.readouterr()  # discard the login's own lines

    client.get(f"/api/v1/classes/{tenant.school_class.id}/students/{student.id}/mastery")

    captured = capsys.readouterr().out
    assert "http.request" in captured, "the access line was not emitted at all"
    assert str(student.id) not in captured
    assert str(tenant.school_class.id) not in captured
    assert not UUID_RE.search(captured), UUID_RE.search(captured)
    assert "{id}" in captured


def test_a_pupils_name_never_reaches_a_log_line(
    client: TestClient, tenant: Tenant, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stronger claim, and the one a school would ask about. Names live in
    request BODIES and responses, neither of which is logged — this is what
    keeps that true rather than incidental."""
    login(client, tenant.teacher.email)
    capsys.readouterr()

    client.get(f"/api/v1/classes/{tenant.school_class.id}/students")

    captured = capsys.readouterr().out
    for student in tenant.students:
        assert student.first_name not in captured
        assert student.last_name not in captured
