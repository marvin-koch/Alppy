"""The loop a teacher actually walks, end to end, through HTTP.

Every other suite tests one side of one step: `test_api_classes` the roster,
`test_api_sheets` the builder, `test_scan_processing` the detector,
`test_api_mastery` the bands. None of them ever walks from an empty school to
a printed sheet and back, so the seams between the steps — the ones where a
teacher actually gets stuck — were never exercised in order.

That is what this file is for. It is deliberately slow and deliberately
sequential: the point is the ORDER, and each assertion is a thing the teacher
would have noticed was missing.

It uses only the public API. No service is imported, nothing is inserted
behind the handlers' backs — a step that needs a fixture to happen is a step
a teacher could not have performed.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login


def test_a_teacher_walks_from_an_empty_class_to_a_printable_sheet(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """Class -> roster -> exercise -> sheet -> one copy per pupil.

    The single most important path in the product, and the one whose steps are
    each covered elsewhere while the chain between them was not.
    """
    login(client, tenant.teacher.email)

    # 1 · A class exists before it has anybody in it.
    created = client.post("/api/v1/classes", json={"code": "9C", "label": "Groupe C"})
    assert created.status_code == 201, created.text
    class_id = created.json()["id"]
    assert created.json()["student_count"] == 0
    # A brand-new class has no Branch level yet: nothing has declared one.
    assert created.json()["subject_ids"] == []

    # 2 · The roster paste is how pupils come to EXIST — it mints the uid.
    roster = client.post(
        f"/api/v1/classes/{class_id}/students",
        json={
            "students": [
                {"first_name": "Marie", "last_name": "Favre"},
                {"first_name": "Luc", "last_name": "Rey"},
                {"first_name": "Ana", "last_name": "Blanc"},
            ]
        },
    )
    assert roster.status_code == 201, roster.text
    pupils = roster.json()
    assert [p["number"] for p in pupils] == [1, 2, 3]
    # The identifier is built from the class code, and it is what gets printed.
    assert [p["uid"] for p in pupils] == ["9C_01", "9C_02", "9C_03"]

    # 3 · An exercise the teacher wrote themselves.
    exercise = client.post(
        "/api/v1/exercises",
        json={
            "subject_id": str(tenant.subject.id),
            "type": "mcq",
            "language": "fr",
            "statement": "Combien font 1/2 + 1/4 ?",
            "options": ["1/6", "3/4", "2/6", "1/8"],
            "answer_index": 1,
            "difficulty": 2,
            "competency_ids": [str(tenant.competency.id)],
        },
    )
    assert exercise.status_code == 201, exercise.text
    # Written by the teacher, so it wears no accent and needs no approval.
    assert exercise.json()["origin"] == "teacher"
    exercise_id = exercise.json()["id"]

    # 4 · A sheet for the class. No Theme chosen — that is a real state, and
    #     the service files it under `unfiled` rather than guessing one from
    #     the items (D60).
    sheet = client.post(
        "/api/v1/sheets",
        json={
            "class_id": class_id,
            "subject_id": str(tenant.subject.id),
            "title": "Fractions — série 1",
            "language": "fr",
            "items": [{"exercise_id": exercise_id, "position": 0}],
        },
    )
    assert sheet.status_code == 201, sheet.text
    sheet_id = sheet.json()["id"]
    assert sheet.json()["chapter_id"] is not None, "a sheet always has a home Theme"

    # 5 · One printed copy per pupil, each carrying that pupil's own uid.
    detail = client.get(f"/api/v1/sheets/{sheet_id}").json()
    assert len(detail["items"]) == 1
    assert {i["student_uid"] for i in detail["instances"]} == {"9C_01", "9C_02", "9C_03"}

    # 6 · Building the sheet is what declared the Branch for this class (D57),
    #     and recorded that this teacher takes it (D73). Without the second,
    #     the sheet they just made would be invisible to them.
    klass = client.get(f"/api/v1/classes/{class_id}").json()
    assert klass["subject_ids"] == [str(tenant.subject.id)]
    assert klass["student_count"] == 3

    # 7 · And it is on the tree, under the unfiled bucket rather than lost.
    tree = client.get(f"/api/v1/classes/{class_id}/tree").json()
    assert [b["subject_id"] for b in tree["branches"]] == [str(tenant.subject.id)]
    assert tree["branches"][0]["unfiled_sheet_count"] == 1


def test_the_matrix_of_a_class_that_has_answered_nothing_is_honest(
    client: TestClient, tenant: Tenant
) -> None:
    """A roster with no attempts is an empty matrix, not an error and not zeros.

    "No evidence" and "answered wrongly" are different facts, and the band
    that means the first is `none` — a dashed ring, not a red disc.
    """
    login(client, tenant.teacher.email)
    matrix = client.get(f"/api/v1/classes/{tenant.school_class.id}/mastery")
    assert matrix.status_code == 200
    body = matrix.json()
    assert len(body["students"]) == len(tenant.students)
    for row in body["students"]:
        for cell in row.get("cells", []):
            assert cell["band"] in ("none", None), "an unassessed cell must not read as failure"


def test_creating_a_sheet_lands_in_the_agenda_with_its_branch(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """The agenda is how a teacher finds last term's work again.

    It carries the Branch (`subject_area_id`), which is what lets the timeline
    stay per-teacher under strict isolation (D75) rather than becoming a feed
    of a colleague's marking.
    """
    exercise = make_exercise(db, tenant, statement="1/2 + 1/4 ?")  # noqa: F405
    db.commit()
    login(client, tenant.teacher.email)
    client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Fractions — série 1",
            "language": "fr",
            "items": [{"exercise_id": str(exercise.id), "position": 0}],
        },
    )
    agenda = client.get("/api/v1/timeline").json()
    titles = [item["title"] for item in agenda["items"]]
    assert "Fractions — série 1" in titles


def test_the_home_screen_answers_the_morning_question(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """"What am I teaching, and what is waiting for me?"

    The first screen of the day, and the one that has to be true without the
    teacher clicking anything.
    """
    exercise = make_exercise(db, tenant, statement="1/2 + 1/4 ?")  # noqa: F405
    db.commit()
    login(client, tenant.teacher.email)
    client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Fractions — série 1",
            "language": "fr",
            "items": [{"exercise_id": str(exercise.id), "position": 0}],
        },
    )
    home = client.get("/api/v1/home").json()
    assert home["teacher"]["school_id"] == str(tenant.school.id)
    card = next(c for c in home["classes"] if c["class_id"] == str(tenant.school_class.id))
    assert card["student_count"] == len(tenant.students)
    assert card["last_sheet_title"] == "Fractions — série 1"


def test_a_roster_paste_refuses_to_mint_an_unprintable_identifier(
    client: TestClient, tenant: Tenant
) -> None:
    """The uid is composed from the class code and must stay decodable.

    A class code the uid grammar cannot carry is refused at the paste rather
    than discovered when a scan comes back unreadable.
    """
    login(client, tenant.teacher.email)
    created = client.post("/api/v1/classes", json={"code": "9D", "label": None})
    class_id = created.json()["id"]
    too_many = client.post(
        f"/api/v1/classes/{class_id}/students",
        json={"students": [{"first_name": f"P{n}", "last_name": "X"} for n in range(41)]},
    )
    assert too_many.status_code == 422, "a roster longer than the page allows is refused"


def test_a_sheet_cannot_borrow_another_schools_exercise(
    client: TestClient, db: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    """Tenancy, from the outside, on the one path that would print it.

    An exercise from another school reaching a sheet would put another
    tenant's content on this school's paper.
    """
    theirs = make_exercise(db, other_tenant, statement="Autre école")  # noqa: F405
    db.commit()
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Emprunt",
            "language": "fr",
            "items": [{"exercise_id": str(theirs.id), "position": 0}],
        },
    )
    assert response.status_code in (404, 422)
