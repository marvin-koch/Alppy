"""Sheet CRUD, instance binding, and the guarded collaborator imports."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_chapter, make_exercise

from alppy.models import UNFILED_CHAPTER_KEY, Chapter, Subject, class_subject
from alppy.sheets.layout import LAYOUT_VERSION


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


def test_an_open_item_carries_the_teachers_expected_answer(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The answer is per sheet item and optional. An MCQ item never keeps one:
    its answer is the bubble, and a stray text would print on the key."""
    from alppy.models.enums import ExerciseType

    written = make_exercise(db, tenant, statement="Calcule 3/4 + 1/8.", kind=ExerciseType.OPEN, answer_index=None)
    bubbles = make_exercise(db, tenant, statement="1/2 + 1/4 ?")
    login(client, tenant.teacher.email)

    payload = _sheet_payload(tenant, [str(written.id), str(bubbles.id)])
    payload["items"] = [
        {"exercise_id": str(written.id), "position": 0, "expected_answer": "  7/8 "},
        {"exercise_id": str(bubbles.id), "position": 1, "expected_answer": "B"},
    ]
    response = client.post("/api/v1/sheets", json=payload)
    assert response.status_code == 201, response.text
    items = response.json()["items"]
    assert items[0]["expected_answer"] == "7/8"
    assert items[1]["expected_answer"] is None

    # Blank means "none given", not an empty string the grader would judge against.
    payload["items"][0]["expected_answer"] = "   "
    response = client.patch(f"/api/v1/sheets/{response.json()['id']}", json={"items": payload["items"]})
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["expected_answer"] is None


def test_a_box_may_be_any_height_up_to_the_pages_ceiling(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    from alppy.models.enums import ExerciseType
    from alppy.sheets.layout import ANSWER_BOX_MAX_LINES

    written = make_exercise(db, tenant, statement="Explique.", kind=ExerciseType.OPEN, answer_index=None)
    login(client, tenant.teacher.email)

    def create(lines: int):  # type: ignore[no-untyped-def]
        payload = _sheet_payload(tenant, [str(written.id)])
        payload["items"] = [{"exercise_id": str(written.id), "position": 0, "answer_box_lines": lines}]
        return client.post("/api/v1/sheets", json=payload)

    assert create(7).status_code == 201, "not a preset, still a box a page can carry"
    assert create(ANSWER_BOX_MAX_LINES).json()["items"][0]["answer_box_lines"] == ANSWER_BOX_MAX_LINES
    assert create(ANSWER_BOX_MAX_LINES + 1).status_code == 422
    assert create(-1).status_code == 422


def test_the_barème_is_a_sheet_default_with_per_item_overrides(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    a = make_exercise(db, tenant, statement="a")
    b = make_exercise(db, tenant, statement="b")
    login(client, tenant.teacher.email)

    payload = _sheet_payload(tenant, [str(a.id), str(b.id)])
    payload["default_points_correct"] = 1.0
    payload["default_points_penalty"] = 0.25
    payload["items"] = [
        {"exercise_id": str(a.id), "position": 0},
        {"exercise_id": str(b.id), "position": 1, "points_correct": 3.0, "points_penalty": 0.0},
    ]
    response = client.post("/api/v1/sheets", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["default_points_correct"] == 1.0
    assert body["default_points_penalty"] == 0.25
    # No override means NULL, not a copy of the default: the item follows the
    # sheet, so changing the sheet's barème moves it.
    assert body["items"][0]["points_correct"] is None
    assert body["items"][1]["points_correct"] == 3.0
    assert body["items"][1]["points_penalty"] == 0.0


def test_points_survive_on_every_exercise_type(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Unlike `expected_answer`, which an MCQ never keeps. A point value means
    something on every type, and a written item becomes auto-gradeable the
    moment a vision verdict lands — a column that had to be un-gated later is
    worse than one that was never gated."""
    from alppy.models.enums import ExerciseType

    written = make_exercise(
        db, tenant, statement="Explique.", kind=ExerciseType.OPEN, answer_index=None
    )
    login(client, tenant.teacher.email)
    payload = _sheet_payload(tenant, [str(written.id)])
    payload["items"] = [{"exercise_id": str(written.id), "position": 0, "points_correct": 3.0}]
    response = client.post("/api/v1/sheets", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["items"][0]["points_correct"] == 3.0


def test_a_barème_outside_the_ceiling_is_refused(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    from alppy.sheets.layout import MAX_ITEM_POINTS

    a = make_exercise(db, tenant, statement="a")
    login(client, tenant.teacher.email)

    def create(**item_fields: object):  # type: ignore[no-untyped-def]
        payload = _sheet_payload(tenant, [str(a.id)])
        payload["items"] = [{"exercise_id": str(a.id), "position": 0, **item_fields}]
        return client.post("/api/v1/sheets", json=payload)

    assert create(points_correct=MAX_ITEM_POINTS).status_code == 201
    assert create(points_correct=MAX_ITEM_POINTS + 1).status_code == 422
    # The penalty is a magnitude. A teacher who types a minus sign means the
    # same thing as one who does not, and guessing which would double it.
    assert create(points_penalty=-0.25).status_code == 422


def test_editing_the_barème_invalidates_the_rendered_pdf(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The paper prints what each item is worth, so a barème edit makes the
    rendered PDF wrong in a way the teacher cannot see by looking at the app."""
    a = make_exercise(db, tenant, statement="a")
    login(client, tenant.teacher.email)
    sheet_id = client.post(
        "/api/v1/sheets", json=_sheet_payload(tenant, [str(a.id)])
    ).json()["id"]

    from alppy.models import Sheet

    sheet = db.get(Sheet, uuid.UUID(sheet_id))
    assert sheet is not None
    sheet.blank_pdf_key = "sheets/x/v1/blank.pdf"
    sheet.rendered_at = datetime.now(UTC)
    db.commit()

    response = client.patch(
        f"/api/v1/sheets/{sheet_id}", json={"default_points_penalty": 1.0}
    )
    assert response.status_code == 200, response.text
    assert response.json()["rendered_at"] is None
    assert response.json()["default_points_penalty"] == 1.0


def test_a_sheet_title_is_bounded_on_the_way_in_however_it_arrives(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """`Sheet.title` is `String(200)`, and `SheetUpdate` used to say nothing.

    A creation was refused at the boundary with a 422 the builder can show
    beside the field; a rename of the same sheet went straight at the column,
    where the failure is a 500 at best and a silent truncation at worst.
    """
    a = make_exercise(db, tenant, statement="a")
    login(client, tenant.teacher.email)
    sheet_id = client.post(
        "/api/v1/sheets", json=_sheet_payload(tenant, [str(a.id)])
    ).json()["id"]

    too_long = "R" * 201
    assert client.post(
        "/api/v1/sheets", json={**_sheet_payload(tenant, [str(a.id)]), "title": too_long}
    ).status_code == 422
    assert (
        client.patch(f"/api/v1/sheets/{sheet_id}", json={"title": too_long}).status_code == 422
    )
    assert client.patch(f"/api/v1/sheets/{sheet_id}", json={"title": ""}).status_code == 422


# --- filing a sheet under a Theme ----------------------------------------
def test_a_sheet_created_without_a_theme_lands_in_unfiled(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Omitting `chapter_id` says "not filed yet", and that is a real answer.

    The alternative — inferring a Theme from the items' own inferred
    `Exercise.chapter_id` — would promote a guess into a teacher-facing filing
    the teacher never confirmed.
    """
    exercise = make_exercise(db, tenant, statement="1/2 + 1/4 ?")
    login(client, tenant.teacher.email)

    response = client.post("/api/v1/sheets", json=_sheet_payload(tenant, [str(exercise.id)]))
    assert response.status_code == 201

    chapter = db.get(Chapter, uuid.UUID(response.json()["chapter_id"]))
    assert chapter is not None
    assert chapter.key == UNFILED_CHAPTER_KEY
    # Excluded from the tree and the roll-up by the NULL, not by the key.
    assert chapter.primary_competency_id is None


def test_a_sheet_can_be_filed_under_a_theme_of_its_own_subject(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    exercise = make_exercise(db, tenant, statement="1/2 + 1/4 ?")
    chapter = make_chapter(db, tenant, key="fractions", competencies=[tenant.competency])
    login(client, tenant.teacher.email)

    payload = _sheet_payload(tenant, [str(exercise.id)]) | {"chapter_id": str(chapter.id)}
    response = client.post("/api/v1/sheets", json=payload)
    assert response.status_code == 201
    assert response.json()["chapter_id"] == str(chapter.id)


def test_a_theme_from_another_subject_is_refused(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """A Theme in another Branch would file the sheet where the tree cannot
    show it, so it is a caller bug rather than a valid state."""
    exercise = make_exercise(db, tenant, statement="1/2 + 1/4 ?")
    other_subject = Subject(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        key="german",
        labels={"fr": "Allemand", "de": "Deutsch", "en": "German"},
    )
    db.add(other_subject)
    db.flush()
    foreign = Chapter(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        subject_id=other_subject.id,
        key="deklination",
        labels={"fr": "d", "de": "d", "en": "d"},
        position=0,
    )
    db.add(foreign)
    db.commit()
    login(client, tenant.teacher.email)

    payload = _sheet_payload(tenant, [str(exercise.id)]) | {"chapter_id": str(foreign.id)}
    response = client.post("/api/v1/sheets", json=payload)
    assert response.status_code == 422


def test_a_sheet_can_be_refiled_after_the_fact(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The path that matters the day this ships, when everything is unfiled."""
    exercise = make_exercise(db, tenant, statement="1/2 + 1/4 ?")
    chapter = make_chapter(db, tenant, key="fractions", competencies=[tenant.competency])
    login(client, tenant.teacher.email)

    created = client.post("/api/v1/sheets", json=_sheet_payload(tenant, [str(exercise.id)]))
    sheet_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/sheets/{sheet_id}", json={"chapter_id": str(chapter.id)}
    )
    assert response.status_code == 200
    assert response.json()["chapter_id"] == str(chapter.id)


def test_creating_a_sheet_declares_the_branch_for_the_class(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The Branch level of the navigation is kept populated from here.

    Asserted against `class_subject` rather than against sheets, so it would
    still fail if the read quietly went back to deriving from sheets.

    The fixture already declares the teacher's own branch — that is what being
    assigned to teach it means (D73) — so what is proved here is that building
    a sheet keeps the table current and never duplicates a row.
    """
    exercise = make_exercise(db, tenant, statement="1/2 + 1/4 ?")
    login(client, tenant.teacher.email)
    expected = (tenant.school_class.id, tenant.subject.id, 0)
    assert [(r.class_id, r.subject_id, r.position) for r in db.execute(select(class_subject))] == [
        expected
    ]

    client.post("/api/v1/sheets", json=_sheet_payload(tenant, [str(exercise.id)]))

    rows = db.execute(select(class_subject)).all()
    assert [(r.class_id, r.subject_id, r.position) for r in rows] == [expected]

    # A second sheet in the same Branch must not add a second row.
    client.post("/api/v1/sheets", json=_sheet_payload(tenant, [str(exercise.id)]))
    assert len(db.execute(select(class_subject)).all()) == 1


# --------------------------------------------------------------------------
# Derived coverage (D71) and sheet-level mastery (D72)
# --------------------------------------------------------------------------
def test_a_sheets_coverage_is_derived_from_its_items(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """No `sheet_competency` table — the items are the only source of truth."""
    tagged = make_exercise(db, tenant, statement="tagged")
    untagged = make_exercise(db, tenant, statement="untagged", with_competency=False)
    login(client, tenant.teacher.email)

    created = client.post(
        "/api/v1/sheets", json=_sheet_payload(tenant, [str(tagged.id), str(untagged.id)])
    )
    assert created.status_code == 201
    assert created.json()["competency_ids"] == [str(tenant.competency.id)]


def test_a_sheets_coverage_follows_an_item_edit(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The reason it is derived: a stored set would go stale here."""
    tagged = make_exercise(db, tenant, statement="tagged")
    untagged = make_exercise(db, tenant, statement="untagged", with_competency=False)
    login(client, tenant.teacher.email)

    created = client.post("/api/v1/sheets", json=_sheet_payload(tenant, [str(tagged.id)]))
    sheet_id = created.json()["id"]
    assert created.json()["competency_ids"] == [str(tenant.competency.id)]

    patched = client.patch(
        f"/api/v1/sheets/{sheet_id}",
        json={"items": [{"exercise_id": str(untagged.id), "position": 0}]},
    )
    assert patched.status_code == 200
    assert patched.json()["competency_ids"] == []


def test_a_sheet_reports_a_band_per_student_and_one_for_the_class(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    exercise = make_exercise(db, tenant, statement="fractions")
    login(client, tenant.teacher.email)
    created = client.post("/api/v1/sheets", json=_sheet_payload(tenant, [str(exercise.id)]))
    sheet_id = created.json()["id"]

    response = client.get(f"/api/v1/sheets/{sheet_id}/mastery")
    assert response.status_code == 200
    body = response.json()

    assert body["competency_ids"] == [str(tenant.competency.id)]
    assert {s["student_id"] for s in body["students"]} == {str(s.id) for s in tenant.students}

    # Nobody has sat it yet, so every band is `none` — never-assessed is a
    # band, not a zero, at this altitude too (I-mastery-03).
    assert {s["mastery"]["band"] for s in body["students"]} == {"none"}
    assert body["overall"]["band"] == "none"
    # And the coverage travels with it (DC-content-07).
    assert body["overall"]["child_count"] == 1
    assert body["overall"]["assessed_count"] == 0


def test_a_sheet_band_ignores_the_bareme(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """I-mastery-08 at the new altitude: a marking scheme must not move a band."""
    from alppy.models import Attempt, Sheet

    exercise = make_exercise(db, tenant, statement="fractions")
    login(client, tenant.teacher.email)
    created = client.post("/api/v1/sheets", json=_sheet_payload(tenant, [str(exercise.id)]))
    sheet_id = uuid.UUID(created.json()["id"])

    db.add(
        Attempt(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            student_id=tenant.students[0].id,
            exercise_id=exercise.id,
            sheet_id=sheet_id,
            correct=True,
            score=0.0,  # a barème of nothing...
            difficulty=3,
            answered_at=datetime.now(UTC),
        )
    )
    db.commit()

    body = client.get(f"/api/v1/sheets/{sheet_id}/mastery").json()
    theirs = next(
        s for s in body["students"] if s["student_id"] == str(tenant.students[0].id)
    )
    # ...still a correct answer, so still a solid band.
    assert theirs["mastery"]["band"] == "solid"
    assert theirs["mastery"]["assessed_count"] == 1
    assert db.get(Sheet, sheet_id) is not None
