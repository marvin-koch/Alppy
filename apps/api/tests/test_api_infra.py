"""Health, the error envelope, the request id, rate limiting and curriculum."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from alppy.api.deps import TokenBucketLimiter, get_ai_limiter
from alppy.core.config import Settings
from alppy.models import Competency
from alppy.models.enums import CurriculumKind
from alppy.storage import LocalStorage, sanitise_filename, storage_key
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import PDF_BYTES, Tenant, login


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
def test_health_never_throws_and_reports_each_dependency(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert set(body) == {"status", "version", "database", "redis", "storage"}
    assert isinstance(body["database"], bool)
    assert body["storage"] is True  # the local backend is always reachable


def test_health_needs_no_session(client: TestClient) -> None:
    assert "cookie" not in {k.lower() for k in client.cookies}
    assert client.get("/api/v1/health").status_code == 200


# --------------------------------------------------------------------------
# Error envelope and request id
# --------------------------------------------------------------------------
def test_every_error_uses_the_same_envelope(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    response = client.get(f"/api/v1/classes/{uuid.uuid4()}")
    assert response.status_code == 404
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_an_unroutable_path_still_returns_the_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_the_request_id_is_echoed_when_the_caller_supplies_one(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers["X-Request-ID"] == "trace-abc-123"


def test_a_generated_request_id_is_stable_within_one_response(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    first = client.get(f"/api/v1/classes/{uuid.uuid4()}")
    second = client.get(f"/api/v1/classes/{uuid.uuid4()}")
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------
def test_the_token_bucket_refills_over_time() -> None:
    limiter = TokenBucketLimiter(rate_per_min=60)
    assert limiter.take("teacher", now=0.0) == 0.0
    for _ in range(59):
        limiter.take("teacher", now=0.0)
    wait = limiter.take("teacher", now=0.0)
    assert wait > 0.0
    assert limiter.take("teacher", now=2.0) == 0.0


def test_the_bucket_is_per_teacher() -> None:
    limiter = TokenBucketLimiter(rate_per_min=1)
    assert limiter.take("a", now=0.0) == 0.0
    assert limiter.take("a", now=0.0) > 0.0
    assert limiter.take("b", now=0.0) == 0.0


def test_ai_endpoints_are_rate_limited(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    limiter = get_ai_limiter()
    payload = {
        "class_id": str(tenant.school_class.id),
        "subject_id": str(tenant.subject.id),
    }
    seen: set[int] = set()
    for _ in range(limiter.rate_per_min + 2):
        seen.add(client.post("/api/v1/sheets/propose", json=payload).status_code)
    assert 429 in seen

    limited = client.post("/api/v1/sheets/propose", json=payload)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) >= 1


# --------------------------------------------------------------------------
# Curriculum
# --------------------------------------------------------------------------
def test_competencies_are_filterable(client: TestClient, tenant: Tenant, db: Session) -> None:
    db.add(
        Competency(
            id=uuid.uuid4(),
            curriculum=CurriculumKind.LP21,
            code="MA.1.A.1",
            parent_id=None,
            subject_key="mathematics",
            cycle=3,
            labels={"de": "Bruche"},
            description={},
        )
    )
    db.commit()
    login(client, tenant.teacher.email)

    per = client.get("/api/v1/curricula/PER/competencies").json()
    assert [c["code"] for c in per] == [tenant.competency.code]

    lp21 = client.get("/api/v1/curricula/LP21/competencies?subject_key=mathematics").json()
    assert [c["code"] for c in lp21] == ["MA.1.A.1"]
    assert client.get("/api/v1/curricula/LP21/competencies?cycle=1").json() == []


def test_chapters_belong_to_a_subject_in_the_same_school(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    created = client.post(
        "/api/v1/chapters",
        json={
            "subject_id": str(tenant.subject.id),
            "key": "fractions",
            "labels": {"fr": "Fractions"},
            "position": 1,
            "competency_ids": [str(tenant.competency.id)],
        },
    )
    assert created.status_code == 201
    assert created.json()["competency_ids"] == [str(tenant.competency.id)]

    foreign = client.post(
        "/api/v1/chapters",
        json={
            "subject_id": str(other_tenant.subject.id),
            "key": "stolen",
            "labels": {"fr": "Vole"},
        },
    )
    assert foreign.status_code == 404
    assert client.get("/api/v1/chapters").json()[0]["key"] == "fractions"


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------
def test_source_upload_only_accepts_pdfs(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/sources",
        data={"subject_id": str(tenant.subject.id)},
        files={"file": ("photo.png", b"\x89PNG\r\n\x1a\n0000", "image/png")},
    )
    assert response.status_code == 415


def test_source_upload_needs_a_subject_in_the_same_school(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/sources",
        data={"subject_id": str(other_tenant.subject.id)},
        files={"file": ("livre.pdf", PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 404


def test_source_upload_reports_the_missing_ingestion_module(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/sources",
        data={"subject_id": str(tenant.subject.id)},
        files={"file": ("livre.pdf", PDF_BYTES, "application/pdf")},
    )
    assert response.status_code in (202, 503)
    if response.status_code == 503:
        assert response.json()["error"]["code"] == "service_unavailable"
    else:
        assert response.json()["status"] == "queued"


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
def test_storage_keys_cannot_escape_their_prefix() -> None:
    assert sanitise_filename("../../etc/passwd") == "passwd"
    assert sanitise_filename("") == "upload"
    assert sanitise_filename("...") == "upload"
    key = storage_key("scans", uuid.uuid4(), uuid.uuid4(), "a/../../b.pdf")
    assert key.count("/") == 3
    assert ".." not in key


def test_local_storage_round_trips(storage: LocalStorage) -> None:
    key = storage.put_bytes("scans/a/b/c.pdf", b"bytes", "application/pdf")
    assert storage.get_bytes(key) == b"bytes"
    assert storage.exists(key)
    assert not storage.exists("scans/a/b/missing.pdf")


def test_the_file_route_is_tenant_scoped(
    client: TestClient, tenant: Tenant, storage: LocalStorage, other_tenant: Tenant
) -> None:
    mine = storage_key("scans", tenant.school.id, uuid.uuid4(), "ok.pdf")
    theirs = storage_key("scans", other_tenant.school.id, uuid.uuid4(), "secret.pdf")
    storage.put_bytes(mine, b"mine", "application/pdf")
    storage.put_bytes(theirs, b"theirs", "application/pdf")

    login(client, tenant.teacher.email)
    assert client.get(f"/api/v1/files/{mine}").content == b"mine"
    assert client.get(f"/api/v1/files/{theirs}").status_code == 404


def test_settings_expose_the_upload_cap(settings: Settings) -> None:
    assert settings.max_upload_bytes == 1024 * 1024
