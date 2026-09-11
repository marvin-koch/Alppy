"""Creating a teacher, and changing a password (D12).

There was no way to do either. `api/v1/auth.py` has five routes and none of them
provisions anybody; the only account-minting path in the product was
`alppy.cli seed`, which creates the *demo* teacher with a password that is a
constant in this repository and refuses to run against a real deployment. So
onboarding an establishment — and unlocking a teacher five minutes before a
lesson — both meant hand-written SQL.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import PASSWORD, Tenant, login

from alppy.core.security import verify_password
from alppy.models import Class
from alppy.models.enums import Locale
from alppy.services.account_service import (
    MIN_PASSWORD_LENGTH,
    AccountError,
    change_own_password,
    create_teacher,
    find_school,
    find_teacher,
    generate_password,
    grant_school,
    list_teachers,
    revoke_school,
    set_password,
)

# --- generating a password --------------------------------------------------


def test_a_generated_password_is_long_and_unambiguous() -> None:
    """It is read off a terminal and typed into a phone by somebody who was
    handed it on paper, so `O`/`0` and `l`/`1`/`I` are not in the alphabet."""
    password = generate_password()
    assert len(password) >= 20
    assert not set(password) & set("O0lI1")


def test_two_generated_passwords_differ() -> None:
    assert generate_password() != generate_password()


# --- creating ---------------------------------------------------------------


def test_creating_a_teacher_also_puts_them_in_the_staffroom(
    db: Session, tenant: Tenant
) -> None:
    """Both halves, always. A teacher row with no `teacher_school` membership
    holds a valid cookie and can act on nothing — which presents as signing in
    successfully and then finding an empty product."""
    created = create_teacher(
        db,
        email="Noemie.Favre@alpes.ch",
        first_name="Noemie",
        last_name="Favre",
        school=tenant.school,
    )
    db.flush()

    assert created.teacher.email == "noemie.favre@alpes.ch"  # normalised
    assert created.generated_password is not None
    assert verify_password(created.teacher.password_hash, created.generated_password)

    staffroom = {row.email for row in list_teachers(db, school=tenant.school)}
    assert "noemie.favre@alpes.ch" in staffroom


def test_the_password_is_never_stored_in_recoverable_form(
    db: Session, tenant: Tenant
) -> None:
    created = create_teacher(
        db, email="a@b.ch", first_name="A", last_name="B", school=tenant.school
    )
    assert created.generated_password not in created.teacher.password_hash
    assert created.teacher.password_hash.startswith("$argon2")


def test_a_supplied_password_must_clear_the_floor(db: Session, tenant: Tenant) -> None:
    with pytest.raises(AccountError, match=str(MIN_PASSWORD_LENGTH)):
        create_teacher(
            db,
            email="short@alpes.ch",
            first_name="S",
            last_name="P",
            school=tenant.school,
            password="short",
        )


def test_a_duplicate_address_is_refused_with_the_command_to_use_instead(
    db: Session, tenant: Tenant
) -> None:
    """The commonest mistake is reaching for `create-teacher` when the account
    exists and needs a second staffroom or a new password."""
    with pytest.raises(AccountError) as caught:
        create_teacher(
            db,
            email=tenant.teacher.email,
            first_name="X",
            last_name="Y",
            school=tenant.school,
        )
    assert "grant-school" in str(caught.value)
    assert "set-password" in str(caught.value)


def test_a_non_address_is_refused(db: Session, tenant: Tenant) -> None:
    with pytest.raises(AccountError):
        create_teacher(
            db, email="not-an-address", first_name="A", last_name="B", school=tenant.school
        )


def test_the_new_teacher_can_actually_sign_in(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """The end-to-end claim. Everything above is machinery; this is the point."""
    created = create_teacher(
        db,
        email="new@alpes.ch",
        first_name="New",
        last_name="Teacher",
        school=tenant.school,
    )
    password = created.generated_password
    assert password is not None
    db.commit()

    response = client.post(
        "/api/v1/auth/login", json={"email": "new@alpes.ch", "password": password}
    )
    assert response.status_code == 200, response.text
    assert response.json()["school_id"] == str(tenant.school.id)


# --- finding ----------------------------------------------------------------


def test_a_school_is_found_by_id_or_by_exact_name(db: Session, tenant: Tenant) -> None:
    assert find_school(db, name_or_id=str(tenant.school.id)).id == tenant.school.id
    assert find_school(db, name_or_id=tenant.school.name).id == tenant.school.id


def test_an_unknown_school_says_how_to_list_them(db: Session) -> None:
    with pytest.raises(AccountError, match="list-schools"):
        find_school(db, name_or_id="Ecole Imaginaire")


def test_an_unknown_teacher_is_refused_rather_than_created(db: Session) -> None:
    with pytest.raises(AccountError):
        find_teacher(db, email="nobody@alpes.ch")


# --- resetting --------------------------------------------------------------


def test_set_password_replaces_the_hash(db: Session, tenant: Tenant) -> None:
    before = tenant.teacher.password_hash
    generated = set_password(db, teacher=tenant.teacher)
    assert generated is not None
    assert tenant.teacher.password_hash != before
    assert verify_password(tenant.teacher.password_hash, generated)


def test_a_reset_does_not_sign_anybody_out(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """Stated in a test because it is the opposite of what a teacher resetting
    a password they believe is known would expect. The cookie is signed with the
    server key and carries no password; there is no session store to revoke
    against. The only lever is rotating ALPPY_SECRET_KEY, which ejects every
    teacher in every school."""
    login(client, tenant.teacher.email)
    set_password(db, teacher=tenant.teacher, password="a-completely-new-one")
    db.commit()

    assert client.get("/api/v1/auth/me").status_code == 200


# --- staffrooms -------------------------------------------------------------


def test_granting_and_revoking_a_staffroom(
    db: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    grant_school(db, teacher=tenant.teacher, school=other_tenant.school)
    db.flush()
    rows = {r.email: r for r in list_teachers(db)}
    assert other_tenant.school.name in rows[tenant.teacher.email].current_schools

    revoke_school(db, teacher=tenant.teacher, school=other_tenant.school)
    db.flush()
    rows = {r.email: r for r in list_teachers(db)}
    assert other_tenant.school.name not in rows[tenant.teacher.email].current_schools


def test_revoking_keeps_the_row(db: Session, tenant: Tenant, other_tenant: Tenant) -> None:
    """An UPDATE, never a DELETE: "they were here from August to February" is
    what justifies every grade they recorded."""
    from alppy.models import teacher_school

    grant_school(db, teacher=tenant.teacher, school=other_tenant.school)
    db.flush()
    revoke_school(db, teacher=tenant.teacher, school=other_tenant.school)
    db.flush()

    rows = db.execute(
        teacher_school.select()
        .where(teacher_school.c.teacher_id == tenant.teacher.id)
        .where(teacher_school.c.school_id == other_tenant.school.id)
    ).all()
    assert rows, "the membership row was deleted rather than ended"
    assert rows[-1].valid_to is not None


def test_the_last_teacher_cannot_be_removed(db: Session, tenant: Tenant) -> None:
    """A school with nobody in it has nobody who can add anyone — membership is
    the only permission there is — so it is unreachable forever, roster and all."""
    from alppy.api.errors import ApiError

    # Hand the classes over first, so the head-teacher refusal is not what fires.
    for klass in db.query(Class).filter(Class.school_id == tenant.school.id):
        klass.head_teacher_id = None
    with pytest.raises(ApiError) as caught:
        revoke_school(db, teacher=tenant.teacher, school=tenant.school)
    assert caught.value.code == "school_last_teacher"


# --- listing ----------------------------------------------------------------


def test_listing_never_exposes_password_material(db: Session, tenant: Tenant) -> None:
    row = list_teachers(db)[0]
    assert not hasattr(row, "password_hash")
    assert "argon2" not in repr(row)


def test_listing_can_be_scoped_to_one_staffroom(
    db: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    here = {r.email for r in list_teachers(db, school=tenant.school)}
    assert tenant.teacher.email in here
    assert other_tenant.teacher.email not in here


# --- a teacher changing their own password ----------------------------------


def test_changing_your_own_password_requires_the_current_one(
    db: Session, tenant: Tenant
) -> None:
    """The session is the weaker claim: a cookie is what an unlocked laptop in
    a staffroom hands to whoever sits down next."""
    with pytest.raises(AccountError, match="current password"):
        change_own_password(
            db, teacher=tenant.teacher, current="wrong", new="a-long-enough-new-one"
        )


def test_the_endpoint_changes_the_password(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": "a-long-enough-new-one"},
    )
    assert response.status_code == 200, response.text

    client.post("/api/v1/auth/logout")
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": tenant.teacher.email, "password": "a-long-enough-new-one"},
        ).status_code
        == 200
    )


def test_the_endpoint_refuses_a_wrong_current_password(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/auth/password",
        json={"current_password": "not-the-one", "new_password": "a-long-enough-new-one"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_the_endpoint_refuses_reusing_the_current_password(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": PASSWORD},
    )
    assert response.status_code in (400, 422)


def test_the_endpoint_enforces_the_new_password_floor(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": "short1234"},
    )
    assert response.status_code == 422


def test_the_endpoint_needs_a_session(client: TestClient) -> None:
    assert (
        client.post(
            "/api/v1/auth/password",
            json={"current_password": "whatever1", "new_password": "a-long-enough-new-one"},
        ).status_code
        == 401
    )


def test_a_created_teacher_gets_the_default_locale(db: Session, tenant: Tenant) -> None:
    created = create_teacher(
        db, email="fr@alpes.ch", first_name="F", last_name="R", school=tenant.school
    )
    assert created.teacher.locale is Locale.FR
