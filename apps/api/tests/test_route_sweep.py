"""Every route, swept: no session answers 401, another school's id answers 404.

The suite has around thirty-five authorization tests over a hand-picked subset
of ninety-six route/method pairs. Hand-picked is the problem, not thirty-five:
the routes nobody thought to pick are exactly the ones nobody thought about,
and a route added next month is covered only if somebody remembers. A
``NameError`` in a handler body reached this branch twice — once found by an
audit, and again three weeks later, because nothing had been added that would
notice the second one.

So this module does not pick. It asks the application what routes it has and
sweeps all of them, which makes the interesting object the **allow-list**: a
route that answers something other than 401 without a session has to be named
in ``PUBLIC``, by a person, with a reason. That converts "we forgot to check"
into a line somebody had to write and justify in review.

Three things keep the sweep honest, and each exists because its absence would
be invisible:

* **The route list is taken from ``published_app.openapi()``**, not from ``app.routes``.
  This FastAPI version nests included routers inside ``_IncludedRouter``
  objects, so the obvious ``for route in app.routes`` yields four entries, none
  of them an ``APIRoute`` — a sweep written that way passes by testing nothing.
* **``test_the_sweep_actually_swept_something``** pins a floor under the route
  count and names routes that must be in it. A refactor that empties the list
  fails here rather than going quietly green.
* **The skip lists are asserted against**, so they cannot grow without the
  same deliberate justification the allow-list needs.

Request bodies are synthesized from each route's own OpenAPI schema rather
than hand-written per route. A hand-written map is a second place to remember
things, which is the failure this module exists to remove; generating from the
schema means a route added next month gets a plausible body for free. Where
the synthesized body is wrong enough that the route answers 422 before it ever
looks at the id, the route is listed in ``BODY_NOT_SYNTHESIZABLE`` with the
reason — not silently dropped.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise, make_paper_trail

# NOT `import app`: `test_api_fixtures` exports an `app` *fixture*, and a
# module-level name of the same name shadows it for every test in the file —
# which fails as `fixture 'app' not found` on all 149 of them at once.
from alppy.main import app as published_app
from alppy.models import Job, ScanPage, Source, SourceSection
from alppy.models.enums import JobKind, JobStatus

# --- The route list --------------------------------------------------------


def _routes() -> list[tuple[str, str]]:
    """Every (method, path) the application actually publishes.

    From the OpenAPI document because that is the contract the web client is
    generated against, and because it is stable across the FastAPI internals
    that changed shape under ``app.routes``.
    """
    spec = published_app.openapi()
    return sorted(
        (method.upper(), path)
        for path, operations in spec["paths"].items()
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"}
    )


ROUTES = _routes()

#: Routes that answer without a session, on purpose. Every entry is a decision.
PUBLIC: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/health"): "the readiness probe; a load balancer has no cookie",
    ("GET", "/api/v1/health/live"): "the liveness probe, same",
    ("GET", "/api/v1/health/detail"): (
        "the component breakdown, for an operator rather than a probe; open in "
        "local and ci, and gated on ALPPY_HEALTH_DETAIL_TOKEN everywhere else "
        "(D35) — see test_deployment_guards"
    ),
    ("POST", "/api/v1/auth/login"): "how a session is obtained in the first place",
    ("POST", "/api/v1/auth/logout"): (
        "clearing a cookie must work when the cookie is already invalid, or a "
        "teacher with an expired session can never reach a clean state"
    ),
}

#: Routes whose body cannot be synthesized well enough from its schema to reach
#: the handler. Each one answers 422 at validation instead of 404 at lookup, so
#: the tenancy claim is untested HERE and must be made somewhere else.
BODY_NOT_SYNTHESIZABLE: dict[tuple[str, str], str] = {}

#: Routes that take a path parameter which is not a tenant-scoped id, so
#: "another school's value" is not a thing that exists for them.
NOT_TENANT_SCOPED: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/curricula/{kind}/competencies"): (
        "`kind` is a curriculum (PER, LP21), not a row: the competency "
        "catalogue is shared by every school by design (D56)"
    ),
}


# --- Synthesizing a request body from its own schema -----------------------


def _deref(schema: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        ref = schema["$ref"].removeprefix("#/")
        target: Any = spec
        for part in ref.split("/"):
            target = target[part]
        schema = target
    return schema


def _example(schema: dict[str, Any], spec: dict[str, Any], ids: dict[str, str], name: str = "") -> Any:
    """A minimal value satisfying ``schema``.

    Ids are drawn from ``ids`` by property name, so a body that names a class
    names the *other school's* class — the sweep tests the body as an IDOR
    surface too, not only the path.
    """
    schema = _deref(schema, spec)

    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            options = [o for o in schema[key] if _deref(o, spec).get("type") != "null"]
            if not options:
                return None
            return _example(options[0], spec, ids, name)

    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]

    kind = schema.get("type")
    if kind == "object":
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        return {
            prop: _example(properties[prop], spec, ids, prop)
            for prop in required
            if prop in properties
        }
    if kind == "array":
        if schema.get("minItems", 0) == 0 and "items" not in schema:
            return []
        return [_example(schema.get("items", {}), spec, ids, name)]
    if kind == "integer":
        return int(schema.get("minimum", 1))
    if kind == "number":
        return float(schema.get("minimum", 1))
    if kind == "boolean":
        return False
    if kind == "string":
        fmt = schema.get("format")
        # By property name first. `confirm` is the reason: DELETE /students and
        # /students/{id}/anonymise take the pupil's own uid typed back
        # (`StudentConfirmation`), so a generic "x" is rejected at validation and
        # the two most destructive routes in the product would be swept without
        # ever reaching their tenancy check. Naming the foreign pupil's real uid
        # is what makes those two cases mean something.
        if name in ids:
            return ids[name]
        if fmt == "uuid" or name.endswith("_id"):
            return ids.get(name, str(uuid.uuid4()))
        if fmt == "date":
            return "2026-09-01"
        if fmt == "date-time":
            return "2026-09-01T08:00:00Z"
        if fmt == "email":
            return "eve@attacker.example"
        minimum = int(schema.get("minLength", 1) or 1)
        return "x" * max(minimum, 1)
    # A schema with no type at all accepts anything; an empty object is the
    # least surprising thing to send.
    return {}


def _body_for(method: str, path: str, ids: dict[str, str]) -> dict[str, Any] | None:
    spec = published_app.openapi()
    operation = spec["paths"][path][method.lower()]
    request_body = operation.get("requestBody")
    if not request_body:
        return None
    content = request_body.get("content", {})
    if "application/json" not in content:
        return None  # multipart: handled by the caller
    return _example(content["application/json"]["schema"], spec, ids)


def _is_multipart(method: str, path: str) -> bool:
    operation = published_app.openapi()["paths"][path][method.lower()]
    content = (operation.get("requestBody") or {}).get("content", {})
    return "multipart/form-data" in content


def _call(
    client: TestClient, method: str, path: str, ids: dict[str, str]
) -> Any:
    """Issue ``method path`` with every path parameter filled from ``ids``."""
    url = re.sub(r"\{([^}]+)\}", lambda m: ids.get(m.group(1), str(uuid.uuid4())), path)
    if _is_multipart(method, path):
        return client.request(
            method, url, files={"files": ("copies.pdf", b"%PDF-1.7\n" + b"0" * 512, "application/pdf")}
        )
    body = _body_for(method, path, ids)
    if body is None:
        return client.request(method, url)
    return client.request(method, url, json=body)


# --- The two sweeps --------------------------------------------------------


def test_the_sweep_actually_swept_something() -> None:
    """A sweep that enumerates nothing passes every assertion it makes.

    ``app.routes`` yields four non-API entries on this FastAPI version, so this
    is not a hypothetical failure — it is the one the first draft had.
    """
    assert len(ROUTES) >= 90, f"only {len(ROUTES)} routes found; the enumeration broke"
    for expected in (
        ("GET", "/api/v1/classes/{class_id}"),
        ("POST", "/api/v1/adaptive/feedback/generate"),
        ("POST", "/api/v1/scans/{scan_id}/confirm"),
        ("DELETE", "/api/v1/students/{student_id}"),
    ):
        assert expected in ROUTES, f"{expected} vanished from the route list"


@pytest.mark.parametrize(
    ("method", "path"),
    [r for r in ROUTES if r not in PUBLIC],
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_every_route_refuses_a_request_with_no_session(
    client: TestClient, foreign_ids: dict[str, str], method: str, path: str
) -> None:
    """No cookie, no answer — and 401, never 403 or 422.

    422 would mean validation ran before authentication, which leaks the shape
    of a body to anyone who asks. 200 would mean the route forgot its
    dependency entirely.
    """
    response = _call(client, method, path, foreign_ids)
    assert response.status_code == 401, (
        f"{method} {path} answered {response.status_code} with no session. "
        f"If that is deliberate, add it to PUBLIC with a reason."
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        r
        for r in ROUTES
        if "{" in r[1]
        and r not in PUBLIC
        and r not in NOT_TENANT_SCOPED
        and r not in BODY_NOT_SYNTHESIZABLE
    ],
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_every_route_answers_a_foreign_id_as_missing(
    client: TestClient,
    tenant: Tenant,
    other_tenant: Tenant,
    foreign_ids: dict[str, str],
    method: str,
    path: str,
) -> None:
    """Signed into one school, every id belongs to the other one.

    404 and not 403: a 403 confirms the row exists, which is itself the leak
    (the module docstring of test_api_tenancy.py says the same thing about the
    subset it covers by hand).
    """
    login(client, tenant.teacher.email)
    response = _call(client, method, path, foreign_ids)
    assert response.status_code == 404, (
        f"{method} {path} answered {response.status_code} for another school's "
        f"id; expected 404. Body: {response.text[:300]}"
    )


# --- The skip lists cannot grow quietly ------------------------------------


def test_the_allow_lists_are_the_size_they_were_argued_to_be() -> None:
    """Pinning the counts is what makes adding to one a visible act.

    A reviewer who sees this number change knows to go and read the reason that
    was written next to the new entry. Without it, the cheapest way past a
    failing sweep is to add a line, and the cheapest way is the one that gets
    taken at 18:00 on a Friday.
    """
    assert len(PUBLIC) == 5, "a route became public — is that intended?"
    assert len(NOT_TENANT_SCOPED) == 1, "a route stopped being tenant-scoped — why?"
    assert len(BODY_NOT_SYNTHESIZABLE) == 0, (
        "a route can no longer be reached generically; its tenancy claim now "
        "needs a hand-written test somewhere else"
    )
    for entry, reason in {**PUBLIC, **NOT_TENANT_SCOPED, **BODY_NOT_SYNTHESIZABLE}.items():
        assert entry in ROUTES, f"{entry} is listed but no longer exists — stale entry"
        assert len(reason) > 20, f"{entry} needs a real reason, not {reason!r}"


# --- The foreign world -----------------------------------------------------


@pytest.fixture
def foreign_ids(db: Session, other_tenant: Tenant) -> dict[str, str]:
    """One id per path-parameter name, every one belonging to the OTHER school.

    Built as real rows rather than random UUIDs wherever a fixture can make
    one: a random UUID proves only that a missing row 404s, which is the easy
    half. A real row in another school is what an IDOR actually looks like.
    """
    exercise = make_exercise(db, other_tenant, statement="3/4 - 1/4 ?")
    sheet, scan, detection = make_paper_trail(
        db, other_tenant, exercise, other_tenant.students[0]
    )
    page = db.query(ScanPage).filter(ScanPage.scan_id == scan.id).one()

    source = Source(
        id=uuid.uuid4(),
        school_id=other_tenant.school.id,
        subject_id=other_tenant.subject.id,
        uploaded_by_id=other_tenant.teacher.id,
        filename="manuel.pdf",
        storage_key=f"sources/{other_tenant.school.id}/{uuid.uuid4()}/manuel.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        sha256="0" * 64,
        status=JobStatus.SUCCEEDED,
    )
    db.add(source)
    db.flush()

    section = SourceSection(
        id=uuid.uuid4(),
        school_id=other_tenant.school.id,
        source_id=source.id,
        title="Fractions",
        label="1",
        page_from=1,
        page_to=4,
        position=0,
    )
    job = Job(
        id=uuid.uuid4(),
        school_id=other_tenant.school.id,
        kind=JobKind.PROCESS_SCAN,
        status=JobStatus.SUCCEEDED,
        progress=1.0,
        payload={"scan_id": str(scan.id)},
    )
    db.add_all([section, job])
    db.flush()
    db.commit()

    return {
        # Not a path parameter: the body field `StudentConfirmation.confirm`,
        # which must be a well-formed uid belonging to the pupil being acted on.
        "confirm": other_tenant.students[0].uid,
        "chapter_id": str(other_tenant.unfiled_chapter_id),
        "class_id": str(other_tenant.school_class.id),
        "competency_id": str(other_tenant.competency.id),
        "detection_id": str(detection.id),
        "exercise_id": str(exercise.id),
        "job_id": str(job.id),
        "key": source.storage_key,
        "kind": "PER",
        "page_id": str(page.id),
        "scan_id": str(scan.id),
        "school_id": str(other_tenant.school.id),
        "section_id": str(section.id),
        "sheet_id": str(sheet.id),
        "source_id": str(source.id),
        "student_id": str(other_tenant.students[0].id),
        "subject_id": str(other_tenant.subject.id),
        "teacher_id": str(other_tenant.teacher.id),
    }
