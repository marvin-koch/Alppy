"""The erasure log (audit 07, `runbook/restore-from-backup.md` §4).

A backup window is also the window in which an erasure is not really complete:
restore to the 1st after erasing on the 3rd and the child is back — name,
attempts, handwriting — with a request that was honoured and then quietly
undone. Re-applying erasures after a restore needs a record of them, and a
record kept in the database being restored is a record the restore takes away.

So it goes to stdout, where it lands wherever logs are aggregated. These tests
are what keep it emitted, and keep it free of the name it just removed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login


def _erasure_lines(captured: str) -> list[str]:
    return [line for line in captured.splitlines() if "privacy.erasure" in line]


def test_anonymising_writes_an_erasure_line(
    client: TestClient, tenant: Tenant, capsys: pytest.CaptureFixture[str]
) -> None:
    login(client, tenant.teacher.email)
    student = tenant.students[0]
    capsys.readouterr()

    response = client.post(
        f"/api/v1/students/{student.id}/anonymise", json={"confirm": student.uid}
    )
    assert response.status_code == 200, response.text

    lines = _erasure_lines(capsys.readouterr().out)
    assert len(lines) == 1
    assert "anonymise" in lines[0]
    assert str(student.person_id) in lines[0]


def test_deleting_writes_an_erasure_line(
    client: TestClient, tenant: Tenant, capsys: pytest.CaptureFixture[str]
) -> None:
    """The case that matters most: after a restore the rows are back in full,
    and nothing in the restored database records that they were meant to go."""
    login(client, tenant.teacher.email)
    student = tenant.students[0]
    person_id = student.person_id
    capsys.readouterr()

    response = client.request(
        "DELETE",
        f"/api/v1/students/{student.id}",
        json={"confirm": student.uid},
    )
    assert response.status_code in (200, 204), response.text

    lines = _erasure_lines(capsys.readouterr().out)
    assert len(lines) == 1
    assert "delete" in lines[0]
    assert str(person_id) in lines[0]


def test_the_erasure_line_never_carries_the_name(
    client: TestClient, tenant: Tenant, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole point of the row is to say WHICH pupil to re-erase. The name
    is the thing that was just removed, and writing it into a log that outlives
    the database would undo the erasure in the one place nobody looks."""
    login(client, tenant.teacher.email)
    student = tenant.students[0]
    first, last = student.first_name, student.last_name
    assert first and last
    capsys.readouterr()

    client.post(f"/api/v1/students/{student.id}/anonymise", json={"confirm": student.uid})

    line = _erasure_lines(capsys.readouterr().out)[0]
    assert first not in line
    assert last not in line


def test_a_refused_erasure_writes_nothing(
    client: TestClient, tenant: Tenant, capsys: pytest.CaptureFixture[str]
) -> None:
    """A wrong confirmation is not an erasure, and a log that recorded it would
    put a pupil on the re-erase list who was never erased."""
    login(client, tenant.teacher.email)
    student = tenant.students[0]
    capsys.readouterr()

    response = client.post(
        f"/api/v1/students/{student.id}/anonymise", json={"confirm": "WRONG_1"}
    )
    assert response.status_code == 422
    assert _erasure_lines(capsys.readouterr().out) == []


def test_answering_the_same_request_twice_is_not_two_erasures(
    client: TestClient, tenant: Tenant, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second request for the same child is the same request. It still logs —
    the re-erase list wants the fact, not the count — but the stamp on the
    record does not move, which is what somebody already shown it relies on."""
    login(client, tenant.teacher.email)
    student = tenant.students[0]

    first = client.post(
        f"/api/v1/students/{student.id}/anonymise", json={"confirm": student.uid}
    )
    stamp = first.json()["anonymised_at"]
    capsys.readouterr()

    again = client.post(
        f"/api/v1/students/{student.id}/anonymise", json={"confirm": student.uid}
    )
    assert again.json()["anonymised_at"] == stamp
    assert len(_erasure_lines(capsys.readouterr().out)) == 1
