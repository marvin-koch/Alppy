"""Exporting a whole class (D36).

`docs/privacy.md` §4 has promised this since it was written — "the mechanism a
school uses to take its data with it, and the mechanism used to satisfy a
data-portability request" — and only the per-pupil route existed. A school of
four hundred children exercised its portability right twenty-four pupils at a
time, by hand.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login


def test_a_class_exports_its_whole_roster(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    response = client.get(f"/api/v1/classes/{tenant.school_class.id}/export")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["class_code"] == tenant.school_class.code
    assert body["student_count"] == len(tenant.students)
    assert len(body["students"]) == len(tenant.students)


def test_each_pupil_is_the_same_shape_the_single_export_returns(
    client: TestClient, tenant: Tenant
) -> None:
    """One shape, one place: the class document and the pupil document cannot
    drift, because the class one is built out of the pupil one."""
    login(client, tenant.teacher.email)
    student = tenant.students[0]

    single = client.get(f"/api/v1/students/{student.id}/export").json()
    whole = client.get(f"/api/v1/classes/{tenant.school_class.id}/export").json()

    mine = next(s for s in whole["students"] if s["person_id"] == single["person_id"])
    # `generated_at` differs by construction; everything else must not.
    del single["generated_at"], mine["generated_at"]
    assert mine == single


def test_the_document_says_which_year_it_describes(
    client: TestClient, tenant: Tenant
) -> None:
    """`7B` does not identify a class across years, and an export somebody has
    to date by hand is an export that gets mis-filed."""
    login(client, tenant.teacher.email)
    body = client.get(f"/api/v1/classes/{tenant.school_class.id}/export").json()
    assert body["school_year"]
    assert body["generated_at"]


def test_another_schools_class_is_not_exportable(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    """404 rather than 403: the response must not confirm the id exists."""
    login(client, tenant.teacher.email)
    response = client.get(f"/api/v1/classes/{other_tenant.school_class.id}/export")
    assert response.status_code == 404


def test_an_unknown_class_is_a_404(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    assert client.get(f"/api/v1/classes/{uuid.uuid4()}/export").status_code == 404


def test_the_export_needs_a_session(client: TestClient, tenant: Tenant) -> None:
    assert (
        client.get(f"/api/v1/classes/{tenant.school_class.id}/export").status_code == 401
    )


def test_a_pupil_who_has_left_is_not_in_the_class_document(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """The roster as it stands, which is what makes this exportable at all.

    A teacher who arrived in March has no standing over a pupil who left in
    October — `ever_shared_student_ids` gates that on the two windows having
    OVERLAPPED — and rather than invent a third access rule inside an export,
    this exports exactly the pupils the caller may already act on. The pupil is
    still exportable individually, under the gate that governs them.

    The membership is ended at the table rather than through `unenrol_student`
    because a pupil cannot leave the class that minted their UID; what is being
    asserted here is the interval, not the product rule on top of it.
    """
    from datetime import timedelta

    from alppy.db.validity import today
    from alppy.models import class_student

    leaver = tenant.students[0]
    db.execute(
        class_student.update()
        .where(class_student.c.class_id == tenant.school_class.id)
        .where(class_student.c.student_id == leaver.id)
        .where(class_student.c.valid_to.is_(None))
        .values(valid_to=today() - timedelta(days=1))
    )
    db.commit()

    login(client, tenant.teacher.email)
    body = client.get(f"/api/v1/classes/{tenant.school_class.id}/export").json()
    assert body["student_count"] == len(tenant.students) - 1
    assert all(s["person_id"] != str(leaver.person_id) for s in body["students"])
