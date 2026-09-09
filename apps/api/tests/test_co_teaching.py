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
