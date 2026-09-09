"""Two teachers, one class, different branches — through the API.

The scenario is the spec's own and the reason D73 exists: **5A, where Mme
Martin takes maths and M. Lambert takes history.** Until now the schema could
say "Martin owns 5A" and, separately, "5A studies maths and history", which is
indistinguishable from "Martin owns 5A and teaches everything in it". A second
teacher on the same class was not expressible at all.

These go through the HTTP surface rather than the services, because the thing
worth pinning is what a teacher actually sees. They are the integration layer
over ``test_schema_constraints.py`` (what the database enforces) and
``test_migration_0021.py`` (that the backfill changed nobody's ownership).

**Two grains, and every test here is about which one applies** (D73):

    class-grained   may I know this class and these children exist?
    pair-grained    may I see this teaching artefact and this evidence?

The pair-grained half of the product — sheets, piles, bands — lands with the
isolation pass; what is proved here is the ownership union, the branch nav,
and the two carve-outs that are deliberately class-grained and must stay so.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, assign_branch, login, make_subject


@pytest.fixture
def history(db: Session, tenant: Tenant) -> object:
    """A second Branch in the same school, for the colleague to take."""
    return make_subject(db, tenant.school, "history")


@pytest.fixture
def co_taught(db: Session, tenant: Tenant, colleague: Tenant, history: object) -> Tenant:
    """5A as the spec describes it.

    ``tenant.teacher`` is the head teacher and takes the class's original
    subject; ``colleague.teacher`` takes history in the *same* class while
    keeping their own class elsewhere.
    """
    assign_branch(db, tenant.school_class, tenant.teacher, tenant.subject, position=0)
    assign_branch(db, tenant.school_class, colleague.teacher, history, position=1)  # type: ignore[arg-type]
    db.commit()
    return colleague


# --------------------------------------------------------------------------
# Ownership is a union: head teacher OR an assignment
# --------------------------------------------------------------------------
def test_a_co_teacher_can_open_the_class_they_hold_a_branch_in(
    client: TestClient, tenant: Tenant, co_taught: Tenant
) -> None:
    login(client, co_taught.teacher.email)
    response = client.get(f"/api/v1/classes/{tenant.school_class.id}")
    assert response.status_code == 200
    assert response.json()["code"] == tenant.school_class.code


def test_a_colleague_with_no_assignment_still_reads_as_missing(
    client: TestClient, tenant: Tenant, colleague: Tenant
) -> None:
    """The boundary, paired beside the widening on purpose (D69's habit).

    A widening is only meaningful next to the case it did NOT widen: without
    this test, ``owned_class_ids`` could return every class in the school and
    the test above would still pass.
    """
    login(client, colleague.teacher.email)
    response = client.get(f"/api/v1/classes/{tenant.school_class.id}")
    assert response.status_code == 404


def test_a_co_taught_class_appears_in_both_teachers_lists(
    client: TestClient, tenant: Tenant, co_taught: Tenant
) -> None:
    for teacher in (tenant.teacher, co_taught.teacher):
        login(client, teacher.email)
        listed = {row["id"] for row in client.get("/api/v1/classes").json()}
        assert str(tenant.school_class.id) in listed


def test_removing_an_assignment_leaves_the_head_teacher_owning_the_class(
    client: TestClient, db: Session, tenant: Tenant, co_taught: Tenant
) -> None:
    """The union arm that the migration's empty-branch case also depends on.

    A class whose every assignment is gone is still its head teacher's — it
    must not become a roster of named children nobody can open.
    """
    from alppy.models import class_teacher_subject

    db.execute(class_teacher_subject.delete())
    db.commit()

    login(client, tenant.teacher.email)
    assert client.get(f"/api/v1/classes/{tenant.school_class.id}").status_code == 200
    login(client, co_taught.teacher.email)
    assert client.get(f"/api/v1/classes/{tenant.school_class.id}").status_code == 404


# --------------------------------------------------------------------------
# The Branch nav is per teacher; its ORDER is per class
# --------------------------------------------------------------------------
def test_each_teacher_sees_only_the_branches_they_take(
    client: TestClient, tenant: Tenant, co_taught: Tenant, history: object
) -> None:
    login(client, tenant.teacher.email)
    mine = client.get(f"/api/v1/classes/{tenant.school_class.id}").json()["subject_ids"]
    assert mine == [str(tenant.subject.id)]

    login(client, co_taught.teacher.email)
    theirs = client.get(f"/api/v1/classes/{tenant.school_class.id}").json()["subject_ids"]
    assert theirs == [str(history.id)]  # type: ignore[attr-defined]


def test_the_tree_shows_a_teacher_their_own_branches(
    client: TestClient, tenant: Tenant, co_taught: Tenant, history: object
) -> None:
    """`class_tree` walks the taught set, not everything the class studies.

    Otherwise the maths teacher opens 5A and finds a history Branch whose
    Themes, sheets and bands are all somebody else's work.
    """
    login(client, tenant.teacher.email)
    mine = client.get(f"/api/v1/classes/{tenant.school_class.id}/tree").json()
    assert [b["subject_id"] for b in mine["branches"]] == [str(tenant.subject.id)]

    login(client, co_taught.teacher.email)
    theirs = client.get(f"/api/v1/classes/{tenant.school_class.id}/tree").json()
    assert [b["subject_id"] for b in theirs["branches"]] == [str(history.id)]  # type: ignore[attr-defined]


def test_a_head_teacher_who_teaches_nothing_gets_a_roster_and_an_empty_tree(
    client: TestClient, db: Session, tenant: Tenant, co_taught: Tenant
) -> None:
    """An empty tree is the honest answer, not a 404.

    The maître de classe runs the roster whether or not they teach the group,
    so the class must open — with nothing in it.
    """
    from alppy.models import class_teacher_subject

    db.execute(
        class_teacher_subject.delete().where(
            class_teacher_subject.c.teacher_id == tenant.teacher.id
        )
    )
    db.commit()

    login(client, tenant.teacher.email)
    tree = client.get(f"/api/v1/classes/{tenant.school_class.id}/tree")
    assert tree.status_code == 200
    assert tree.json()["branches"] == []
    roster = client.get(f"/api/v1/classes/{tenant.school_class.id}/students")
    assert roster.status_code == 200
    assert len(roster.json()) == len(tenant.students)


# --------------------------------------------------------------------------
# The carve-outs: a child is a child
# --------------------------------------------------------------------------
def test_both_teachers_see_the_same_roster(
    client: TestClient, tenant: Tenant, co_taught: Tenant
) -> None:
    """Class-grained, deliberately.

    Names and UIDs are what a co-teacher already knows by standing in the
    room. Narrowing the roster per branch would mean the history teacher
    could not take a register.
    """
    seen = []
    for teacher in (tenant.teacher, co_taught.teacher):
        login(client, teacher.email)
        response = client.get(f"/api/v1/classes/{tenant.school_class.id}/students")
        assert response.status_code == 200
        seen.append({row["uid"] for row in response.json()})
    assert seen[0] == seen[1]


def test_a_co_taught_childs_profile_opens_for_both_teachers(
    client: TestClient, tenant: Tenant, co_taught: Tenant
) -> None:
    """`_owned_student` stays class-grained — this is D69's widening.

    Narrowed by branch, a child the history teacher actually teaches would
    404 for them, which is the regression D69's whole entry is about.
    """
    student = tenant.students[0]
    for teacher in (tenant.teacher, co_taught.teacher):
        login(client, teacher.email)
        response = client.get(f"/api/v1/students/{student.id}/mastery")
        assert response.status_code == 200, teacher.email


def test_a_teacher_outside_the_class_still_cannot_read_its_children(
    client: TestClient, tenant: Tenant, colleague: Tenant
) -> None:
    login(client, colleague.teacher.email)
    response = client.get(f"/api/v1/students/{tenant.students[0].id}/mastery")
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Tenancy still holds above all of it
# --------------------------------------------------------------------------
def test_an_assignment_never_reaches_across_schools(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    """A teacher from another school is not made an owner by anything here.

    The table carries no ``school_id`` because every read joins a class that
    is already filtered — this is the test that the shortcut is safe.
    """
    login(client, other_tenant.teacher.email)
    assert client.get(f"/api/v1/classes/{tenant.school_class.id}").status_code == 404
    assert str(tenant.school_class.id) not in {
        row["id"] for row in client.get("/api/v1/classes").json()
    }


def test_a_session_for_a_school_the_teacher_left_is_refused(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """The membership check in ``get_membership``, from the outside.

    The cookie signature stays valid — what changed is that the pair it names
    is no longer a membership. A teacher who has left must stop reading the
    school, without anyone having to remember to invalidate a cookie.
    """
    from alppy.models import teacher_school

    login(client, tenant.teacher.email)
    assert client.get("/api/v1/auth/me").status_code == 200

    db.execute(
        teacher_school.delete().where(teacher_school.c.teacher_id == tenant.teacher.id)
    )
    db.commit()

    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_reports_the_school_the_session_is_acting_for(
    client: TestClient, tenant: Tenant
) -> None:
    """Not ``home_school_id``.

    The client switches tenants on this field, so reporting where the account
    is based would have every screen describe the wrong school the moment
    somebody worked at two (I-platform-14).
    """
    login(client, tenant.teacher.email)
    body = client.get("/api/v1/auth/me").json()
    assert body["school_id"] == str(tenant.school.id)
    assert uuid.UUID(body["school_id"]) == tenant.teacher.home_school_id


# --------------------------------------------------------------------------
# Pair-grained: what a teacher MAKES and MARKS
#
# The tests above are about who may open a class. These are about what they
# find inside it, and they are the ones strict isolation is for.
# --------------------------------------------------------------------------
def _make_sheet(client: TestClient, klass: object, subject_id: str, exercise_id: str, title: str) -> str:
    response = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(klass.id),  # type: ignore[attr-defined]
            "subject_id": subject_id,
            "title": title,
            "language": "fr",
            "items": [{"exercise_id": exercise_id, "position": 0}],
        },
    )
    assert response.status_code in (200, 201), response.text
    return str(response.json()["id"])


@pytest.fixture
def two_sheets(
    client: TestClient, db: Session, tenant: Tenant, co_taught: Tenant, history: object
) -> tuple[str, str]:
    """One sheet per teacher, in the same class, in different branches."""
    exercise = make_exercise(db, tenant, statement="1/2 + 1/4 ?")  # noqa: F405
    db.commit()

    login(client, tenant.teacher.email)
    mine = _make_sheet(
        client, tenant.school_class, str(tenant.subject.id), str(exercise.id), "Fractions"
    )
    login(client, co_taught.teacher.email)
    theirs = _make_sheet(
        client, tenant.school_class, str(history.id), str(exercise.id), "1848"  # type: ignore[attr-defined]
    )
    return mine, theirs


def test_a_colleagues_sheet_in_a_shared_class_is_not_listed(
    client: TestClient, tenant: Tenant, co_taught: Tenant, two_sheets: tuple[str, str]
) -> None:
    mine, theirs = two_sheets

    login(client, tenant.teacher.email)
    listed = {row["id"] for row in client.get("/api/v1/sheets").json()}
    assert mine in listed and theirs not in listed

    login(client, co_taught.teacher.email)
    listed = {row["id"] for row in client.get("/api/v1/sheets").json()}
    assert theirs in listed and mine not in listed


def test_a_colleagues_sheet_reads_as_missing_not_forbidden(
    client: TestClient, tenant: Tenant, two_sheets: tuple[str, str]
) -> None:
    """404, not 403 — the response must not confirm the id exists.

    Every ownership failure in this codebase is a 404; a 403 here would be the
    first, and would tell a colleague exactly what they are not allowed to see.
    """
    _, theirs = two_sheets
    login(client, tenant.teacher.email)
    assert client.get(f"/api/v1/sheets/{theirs}").status_code == 404


def test_a_teacher_can_still_open_their_own_sheet(
    client: TestClient, tenant: Tenant, two_sheets: tuple[str, str]
) -> None:
    """The boundary's other side. Without it, isolation could be a blanket 404."""
    mine, _ = two_sheets
    login(client, tenant.teacher.email)
    assert client.get(f"/api/v1/sheets/{mine}").status_code == 200


def test_building_a_sheet_records_the_branch_the_builder_teaches(
    client: TestClient, db: Session, tenant: Tenant, co_taught: Tenant, history: object
) -> None:
    """`declare_subject` writes both facts, and this is why.

    A teacher who built a sheet in a branch nobody had recorded them teaching
    would immediately lose it: the branch would not be in their tree, and the
    sheet would not be in their list. The sheet they just made would be gone.
    """
    from alppy.models import class_teacher_subject

    exercise = make_exercise(db, tenant, statement="Qui?")  # noqa: F405
    db.commit()

    login(client, co_taught.teacher.email)
    sheet_id = _make_sheet(
        client, tenant.school_class, str(history.id), str(exercise.id), "1848"  # type: ignore[attr-defined]
    )

    held = set(
        db.execute(
            class_teacher_subject.select().where(
                class_teacher_subject.c.teacher_id == co_taught.teacher.id
            )
        ).all()
    )
    assert (tenant.school_class.id, co_taught.teacher.id, history.id) in {  # type: ignore[attr-defined]
        (r.class_id, r.teacher_id, r.subject_id) for r in held
    }
    assert client.get(f"/api/v1/sheets/{sheet_id}").status_code == 200


def test_a_colleagues_sheet_cannot_be_attached_to_a_pile(
    client: TestClient, tenant: Tenant, two_sheets: tuple[str, str]
) -> None:
    """What closes the scan lifecycle hazard structurally.

    An unmatched pile is uploader-only. If a teacher could attach a sheet they
    do not teach, the pile would become visible to that sheet's owner and
    vanish from the uploader's list mid-workflow. They cannot, because the
    attach resolves the sheet through the pair-grained `get_sheet`.
    """
    _, theirs = two_sheets
    login(client, tenant.teacher.email)
    response = client.get(f"/api/v1/sheets/{theirs}")
    assert response.status_code == 404


def test_the_agenda_shows_a_teacher_only_their_own_branchs_events(
    client: TestClient, tenant: Tenant, co_taught: Tenant, two_sheets: tuple[str, str]
) -> None:
    """Class-level events stay shared; branch events do not.

    "Fractions" and "1848" both happened in 5A. Each teacher should see their
    own in the agenda and not the other's, or the timeline becomes a feed of a
    colleague's marking.
    """
    login(client, tenant.teacher.email)
    mine = " ".join(e["title"] for e in client.get("/api/v1/timeline").json()["items"])
    assert "Fractions" in mine and "1848" not in mine

    login(client, co_taught.teacher.email)
    theirs = " ".join(e["title"] for e in client.get("/api/v1/timeline").json()["items"])
    assert "1848" in theirs and "Fractions" not in theirs


def test_the_home_card_counts_only_what_this_teacher_teaches(
    client: TestClient, tenant: Tenant, co_taught: Tenant, two_sheets: tuple[str, str]
) -> None:
    """"Last sheet" must not be a colleague's.

    The home card is the first thing a teacher reads in the morning; a history
    sheet appearing on it because the two share a class is noise that looks
    like their own work.
    """
    login(client, tenant.teacher.email)
    cards = {c["class_id"]: c for c in client.get("/api/v1/home").json()["classes"]}
    card = cards[str(tenant.school_class.id)]
    assert card["last_sheet_title"] == "Fractions"

    login(client, co_taught.teacher.email)
    cards = {c["class_id"]: c for c in client.get("/api/v1/home").json()["classes"]}
    assert cards[str(tenant.school_class.id)]["last_sheet_title"] == "1848"


# --------------------------------------------------------------------------
# The endpoints D57 deferred (D75)
# --------------------------------------------------------------------------
def test_a_teacher_can_be_given_a_branch_in_a_class(
    client: TestClient, tenant: Tenant, colleague: Tenant, history: object
) -> None:
    """The whole feature, through the API, from nothing."""
    login(client, tenant.teacher.email)
    response = client.post(
        f"/api/v1/classes/{tenant.school_class.id}"
        f"/teachers/{colleague.teacher.id}/branches/{history.id}"  # type: ignore[attr-defined]
    )
    assert response.status_code == 201
    holders = {r["teacher_id"]: r for r in response.json()}
    assert holders[str(colleague.teacher.id)]["subject_ids"] == [str(history.id)]  # type: ignore[attr-defined]

    # And it is real: the colleague can now open the class.
    login(client, colleague.teacher.email)
    assert client.get(f"/api/v1/classes/{tenant.school_class.id}").status_code == 200


def test_assigning_a_branch_twice_is_not_an_error(
    client: TestClient, tenant: Tenant, colleague: Tenant, history: object
) -> None:
    login(client, tenant.teacher.email)
    path = (
        f"/api/v1/classes/{tenant.school_class.id}"
        f"/teachers/{colleague.teacher.id}/branches/{history.id}"  # type: ignore[attr-defined]
    )
    first = client.post(path)
    second = client.post(path)
    assert first.status_code == 201 and second.status_code == 201
    holders = {r["teacher_id"]: r for r in second.json()}
    assert holders[str(colleague.teacher.id)]["subject_ids"] == [str(history.id)]  # type: ignore[attr-defined]


def test_unassigning_a_branch_that_is_not_there_is_a_no_op(
    client: TestClient, tenant: Tenant, colleague: Tenant, history: object
) -> None:
    """A no-op, not a 500 — the caller's intent is already satisfied."""
    login(client, tenant.teacher.email)
    response = client.delete(
        f"/api/v1/classes/{tenant.school_class.id}"
        f"/teachers/{colleague.teacher.id}/branches/{history.id}"  # type: ignore[attr-defined]
    )
    assert response.status_code == 200


def test_unassigning_takes_the_branch_away_without_touching_the_sheets(
    client: TestClient, db: Session, tenant: Tenant, co_taught: Tenant, history: object
) -> None:
    """Unassigning is not deleting.

    The sheet survives; it simply stops being visible to that teacher. Losing
    a branch assignment must never destroy a term of worksheets.
    """
    from alppy.models import Sheet

    exercise = make_exercise(db, tenant, statement="Qui?")  # noqa: F405
    db.commit()
    login(client, co_taught.teacher.email)
    sheet_id = _make_sheet(
        client, tenant.school_class, str(history.id), str(exercise.id), "1848"  # type: ignore[attr-defined]
    )
    assert client.get(f"/api/v1/sheets/{sheet_id}").status_code == 200

    login(client, tenant.teacher.email)
    client.delete(
        f"/api/v1/classes/{tenant.school_class.id}"
        f"/teachers/{co_taught.teacher.id}/branches/{history.id}"  # type: ignore[attr-defined]
    )

    login(client, co_taught.teacher.email)
    assert client.get(f"/api/v1/sheets/{sheet_id}").status_code == 404
    assert db.get(Sheet, uuid.UUID(sheet_id)) is not None


def test_a_teacher_from_another_school_cannot_be_assigned(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, history: object
) -> None:
    """I-platform-12, and the reason the table can carry no `school_id`."""
    login(client, tenant.teacher.email)
    response = client.post(
        f"/api/v1/classes/{tenant.school_class.id}"
        f"/teachers/{other_tenant.teacher.id}/branches/{history.id}"  # type: ignore[attr-defined]
    )
    assert response.status_code == 404


def test_assigning_into_a_class_you_have_no_footing_in_is_missing(
    client: TestClient, tenant: Tenant, colleague: Tenant, history: object
) -> None:
    login(client, colleague.teacher.email)
    response = client.post(
        f"/api/v1/classes/{tenant.school_class.id}"
        f"/teachers/{colleague.teacher.id}/branches/{history.id}"  # type: ignore[attr-defined]
    )
    assert response.status_code == 404


def test_the_class_screen_separates_what_it_studies_from_what_you_take(
    client: TestClient, tenant: Tenant, co_taught: Tenant, history: object
) -> None:
    """`subject_ids` is mine, `declared_subject_ids` is the class's.

    Redefining the first would make the Branch nav silently per-viewer; making
    it the class's would render branches the reader cannot open. Two facts,
    two fields.
    """
    login(client, tenant.teacher.email)
    body = client.get(f"/api/v1/classes/{tenant.school_class.id}").json()
    assert body["subject_ids"] == [str(tenant.subject.id)]
    assert set(body["declared_subject_ids"]) == {str(tenant.subject.id), str(history.id)}  # type: ignore[attr-defined]
    assert body["is_head"] is True

    login(client, co_taught.teacher.email)
    body = client.get(f"/api/v1/classes/{tenant.school_class.id}").json()
    assert body["subject_ids"] == [str(history.id)]  # type: ignore[attr-defined]
    assert body["is_head"] is False


def test_the_head_teacher_is_listed_even_when_they_take_nothing(
    client: TestClient, db: Session, tenant: Tenant, co_taught: Tenant
) -> None:
    """A class always has an owner, and the screen must say who."""
    from alppy.models import class_teacher_subject

    db.execute(
        class_teacher_subject.delete().where(
            class_teacher_subject.c.teacher_id == tenant.teacher.id
        )
    )
    db.commit()

    login(client, tenant.teacher.email)
    rows = {r["teacher_id"]: r for r in client.get(
        f"/api/v1/classes/{tenant.school_class.id}/teachers"
    ).json()}
    head = rows[str(tenant.teacher.id)]
    assert head["is_head"] is True and head["subject_ids"] == []


def test_a_branch_still_holding_sheets_cannot_be_undeclared(
    client: TestClient, db: Session, tenant: Tenant, two_sheets: tuple[str, str]
) -> None:
    """A conflict with a count, not a cascade.

    Removing the branch from a settings screen must not be a way to throw away
    the term's worksheets.
    """
    login(client, tenant.teacher.email)
    response = client.delete(
        f"/api/v1/classes/{tenant.school_class.id}/subjects/{tenant.subject.id}"
    )
    assert response.status_code == 409
    assert response.json()["error"]["details"]["sheet_count"] == "1"
    # Its own code, because the screen has to say HOW MANY sheets stand in the
    # way. Under the generic `conflict` the teacher was told only "no longer
    # possible in the current state", which names nothing and suggests nothing.
    assert response.json()["error"]["code"] == "branch_holds_sheets"


def test_reordering_branches_keeps_the_ones_you_did_not_name(
    client: TestClient, tenant: Tenant, co_taught: Tenant, history: object
) -> None:
    """Order is the CLASS's, so a partial list must not renumber a colleague's.

    Mme Martin can only see maths; reordering from her screen must leave
    history in the list rather than dropping it.
    """
    login(client, tenant.teacher.email)
    response = client.put(
        f"/api/v1/classes/{tenant.school_class.id}/subjects",
        json={"subject_ids": [str(tenant.subject.id)]},
    )
    assert response.status_code == 200
    assert response.json()["declared_subject_ids"] == [
        str(tenant.subject.id),
        str(history.id),  # type: ignore[attr-defined]
    ]


def test_the_colleague_list_carries_no_email(
    client: TestClient, tenant: Tenant, colleague: Tenant
) -> None:
    """A branch picker has no reason to know addresses."""
    login(client, tenant.teacher.email)
    rows = client.get("/api/v1/colleagues").json()
    assert {r["id"] for r in rows} >= {str(tenant.teacher.id), str(colleague.teacher.id)}
    assert all("email" not in r for r in rows)


# --------------------------------------------------------------------------
# One teacher, several staffrooms (D74)
#
# The schema landed with the assignment work; these are about a teacher
# actually moving between them, which is the part a cookie has to survive.
# --------------------------------------------------------------------------
@pytest.fixture
def second_school(db: Session, tenant: Tenant) -> object:
    """Another school Camille also works at, with a class of its own."""
    from alppy.models import Class, School, SchoolYear
    from alppy.services import class_service

    school = School(id=uuid.uuid4(), name="Oberstufe Chur", canton="GR")
    db.add(school)
    db.flush()
    year = SchoolYear(
        id=uuid.uuid4(),
        school_id=school.id,
        label="2026/27",
        starts_on=date(2026, 8, 1),
        ends_on=date(2027, 7, 31),
        is_current=True,
    )
    db.add(year)
    db.flush()
    klass = Class(
        id=uuid.uuid4(),
        school_id=school.id,
        school_year_id=year.id,
        head_teacher_id=tenant.teacher.id,
        code="10A",
    )
    db.add(klass)
    class_service.join_school(db, tenant.teacher.id, school.id)
    db.commit()
    return school


def test_me_lists_every_staffroom_the_teacher_works_in(
    client: TestClient, tenant: Tenant, second_school: object
) -> None:
    login(client, tenant.teacher.email)
    body = client.get("/api/v1/auth/me").json()
    assert {s["id"] for s in body["schools"]} == {
        str(tenant.school.id),
        str(second_school.id),  # type: ignore[attr-defined]
    }
    # And it still says which one this session is acting for.
    assert body["school_id"] == str(tenant.school.id)


def test_switching_school_changes_which_classes_exist(
    client: TestClient, tenant: Tenant, second_school: object
) -> None:
    """The whole point: the same account, a different tenant.

    Every service query already filters on `scope.school_id`; switching is
    re-issuing the cookie, so this is the test that the tenant really moved
    rather than the payload merely saying so.
    """
    login(client, tenant.teacher.email)
    before = {row["code"] for row in client.get("/api/v1/classes").json()}
    assert tenant.school_class.code in before and "10A" not in before

    switched = client.post(f"/api/v1/auth/school/{second_school.id}")  # type: ignore[attr-defined]
    assert switched.status_code == 200
    assert switched.json()["school_id"] == str(second_school.id)  # type: ignore[attr-defined]

    after = {row["code"] for row in client.get("/api/v1/classes").json()}
    assert after == {"10A"}


def test_a_school_the_teacher_does_not_work_at_reads_as_missing(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    """404, not 403 — the response must not confirm the school exists."""
    login(client, tenant.teacher.email)
    response = client.post(f"/api/v1/auth/school/{other_tenant.school.id}")
    assert response.status_code == 404
    # And the session did not move.
    assert client.get("/api/v1/auth/me").json()["school_id"] == str(tenant.school.id)


def test_switching_back_restores_the_first_school(
    client: TestClient, tenant: Tenant, second_school: object
) -> None:
    login(client, tenant.teacher.email)
    client.post(f"/api/v1/auth/school/{second_school.id}")  # type: ignore[attr-defined]
    client.post(f"/api/v1/auth/school/{tenant.school.id}")
    assert {row["code"] for row in client.get("/api/v1/classes").json()} == {
        tenant.school_class.code
    }
