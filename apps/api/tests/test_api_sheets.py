"""Sheet CRUD, instance binding, and the guarded collaborator imports."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from alppy.sheets.layout import LAYOUT_VERSION
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise


def _sheet_payload(tenant: Tenant, exercise_ids: list[str]) -> dict[str, object]:
    return {
        "class_id": str(tenant.school_class.id),
        "subject_id": str(tenant.subject.id),
        "title": "Fractions — serie 1",
        "language": "fr",
        "items": [
            {"exercise_id": eid, "position": index} for index, eid in enumerate(exercise_ids)
        ],
    }


def test_create_sheet_binds_one_instance_per_student(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    a = make_exercise(db, tenant, statement="1/2 + 1/4 ?")
    b = make_exercise(db, tenant, statement="3/5 de 40 ?")
    login(client, tenant.teacher.email)

    response = client.post("/api/v1/sheets", json=_sheet_payload(tenant, [str(a.id), str(b.id)]))
    assert response.status_code == 201
    body = response.json()

    assert body["layout_version"] == LAYOUT_VERSION
    assert [i["position"] for i in body["items"]] == [0, 1]
    assert body["items"][0]["exercise"]["statement"] == "1/2 + 1/4 ?"
    assert {i["student_uid"] for i in body["instances"]} == {"7B_01", "7B_02", "7B_03"}
    assert body["blank_pdf_url"] is None


def test_sheet_items_must_have_distinct_positions(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    a = make_exercise(db, tenant, statement="a")
    b = make_exercise(db, tenant, statement="b")
    login(client, tenant.teacher.email)

    payload = _sheet_payload(tenant, [str(a.id), str(b.id)])
    payload["items"] = [
        {"exercise_id": str(a.id), "position": 0},
        {"exercise_id": str(b.id), "position": 0},
    ]
    response = client.post("/api/v1/sheets", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unprocessable"


def test_patching_a_sheet_replaces_items_and_invalidates_the_render(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    a = make_exercise(db, tenant, statement="a")
    b = make_exercise(db, tenant, statement="b")
    login(client, tenant.teacher.email)
    sheet_id = client.post(
        "/api/v1/sheets", json=_sheet_payload(tenant, [str(a.id), str(b.id)])
    ).json()["id"]

    response = client.patch(
        f"/api/v1/sheets/{sheet_id}",
        json={
            "title": "Fractions — revision",
            "items": [{"exercise_id": str(b.id), "position": 0}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Fractions — revision"
    assert [i["exercise"]["id"] for i in body["items"]] == [str(b.id)]
    assert body["rendered_at"] is None


def test_get_and_list_sheets(client: TestClient, tenant: Tenant, db: Session) -> None:
    a = make_exercise(db, tenant, statement="a")
    login(client, tenant.teacher.email)
    sheet_id = client.post("/api/v1/sheets", json=_sheet_payload(tenant, [str(a.id)])).json()["id"]

    assert client.get(f"/api/v1/sheets/{sheet_id}").status_code == 200
    listed = client.get(f"/api/v1/sheets?class_id={tenant.school_class.id}").json()
    assert [s["id"] for s in listed] == [sheet_id]


def test_propose_is_unavailable_until_retrieval_ships(
    client: TestClient, tenant: Tenant
) -> None:
    """The API must boot and serve everything else without the RAG module."""
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/sheets/propose",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "count": 8,
        },
    )
    assert response.status_code in (200, 503)
    if response.status_code == 503:
        assert response.json()["error"]["code"] == "service_unavailable"


def test_render_refuses_an_empty_sheet(client: TestClient, tenant: Tenant, db: Session) -> None:
    a = make_exercise(db, tenant, statement="a")
    login(client, tenant.teacher.email)
    sheet_id = client.post("/api/v1/sheets", json=_sheet_payload(tenant, [str(a.id)])).json()["id"]
    client.patch(f"/api/v1/sheets/{sheet_id}", json={"items": []})

    response = client.post(f"/api/v1/sheets/{sheet_id}/render")
    assert response.status_code in (422, 503)


def test_render_queues_a_job_or_reports_the_renderer_missing(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    a = make_exercise(db, tenant, statement="a")
    login(client, tenant.teacher.email)
    sheet_id = client.post("/api/v1/sheets", json=_sheet_payload(tenant, [str(a.id)])).json()["id"]

    response = client.post(f"/api/v1/sheets/{sheet_id}/render")
    if response.status_code == 202:
        job = response.json()
        assert job["kind"] == "render_sheet"
        assert job["status"] == "queued"
        assert client.get(f"/api/v1/jobs/{job['id']}").status_code == 200
    else:
        assert response.status_code == 503
