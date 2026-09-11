"""Login, logout, the session, and the teacher's display preferences."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from alppy.api import errors
from alppy.api.deps import (
    DbDep,
    SettingsDep,
    TeacherDep,
    TenantDep,
    clear_failed_logins,
    enforce_login_rate_limit,
    record_failed_login,
)
from alppy.core.security import hash_password, issue_session, needs_rehash, verify_password
from alppy.db import tenancy
from alppy.db.validity import today, valid_on
from alppy.models import Teacher, teacher_school
from alppy.models.enums import Locale
from alppy.schemas import (
    LoginRequest,
    PasswordChangeRequest,
    TeacherOut,
    TeacherPreferences,
)
from alppy.services import class_service, teacher_out

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TeacherOut)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
) -> TeacherOut:
    """Sign in, and set the session cookie.

    Rate limited on failures, per account and per address. This is the only
    unauthenticated endpoint, so it is the only one no teacher-keyed bucket can
    cover — it was previously the one unlimited door in the API. Two things
    stood behind it: a roster of children, reachable by guessing one password,
    and Argon2id, which is expensive *on purpose* and so answers an unlimited
    endpoint with an unlimited bill in CPU.

    The check runs before the hash is verified, so a throttled attempt costs
    nothing; the token is charged only when the attempt fails, so a teacher
    signing in correctly is never throttled by their own success.
    """
    email = payload.email.lower()
    enforce_login_rate_limit(request, email, settings)

    teacher = db.execute(
        select(Teacher).where(Teacher.email == email)
    ).scalar_one_or_none()
    # Verify against a dummy hash when the email is unknown so the response
    # time does not reveal whether an address exists.
    stored = teacher.password_hash if teacher is not None else hash_password("not-a-user")
    if not verify_password(stored, payload.password) or teacher is None:
        record_failed_login(request, email, settings)
        raise errors.unauthorized("invalid email or password")

    clear_failed_logins(email, settings)

    if needs_rehash(teacher.password_hash):
        teacher.password_hash = hash_password(payload.password)
        db.flush()

    token = issue_session(teacher.id, teacher.home_school_id, settings=settings)
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=settings.session_max_age_s,
        httponly=True,
        samesite="lax",
        secure=settings.env in ("staging", "production"),
        path="/",
    )
    db.commit()
    # Bind the tenant before reading the staffroom list, and ONLY after proving
    # the same thing `get_membership` proves.
    #
    # Row-level security is keyed on `app.current_school_id` (D84) and an
    # unbound session sees nothing. So on Postgres this read returned an EMPTY
    # LIST — the `schools` field of every login response was `[]`, in every
    # deployment, while the SQLite suite (which has no policies) saw it full and
    # passed. The web client seeds its `me` cache from this response, so the
    # school switcher came up empty for one render before `invalidateQueries`
    # refetched `/auth/me` and filled it in. Self-healing, and wrong.
    #
    # The `school` policy was written for exactly this moment: its second arm
    # matches on `app.current_teacher_id` against an OPEN `teacher_school` row,
    # which is what keeps a teacher's other staffrooms visible (D74). It needs
    # the GUC set, and login was the one entry point that never set it.
    #
    # This is the SECOND writer of the GUC, after `get_membership`. The rule
    # that there be only one is about never binding without the entitlement
    # check, so the check comes with it: a CURRENT membership of the school the
    # cookie is being minted for, the same predicate `get_membership` uses. A
    # teacher whose home school is no longer theirs binds nothing and gets an
    # empty list — which is the honest answer, and the state they are in.
    current = db.execute(
        select(teacher_school.c.school_id)
        .where(teacher_school.c.teacher_id == teacher.id)
        .where(teacher_school.c.school_id == teacher.home_school_id)
        .where(valid_on(teacher_school, today()))
    ).first()
    schools = []
    if current is not None:
        tenancy.bind(db, school_id=teacher.home_school_id, teacher_id=teacher.id)
        schools = class_service.schools_for_teacher(db, teacher.id)
    return teacher_out(teacher, teacher.home_school_id, schools=schools)


@router.post("/auth/school/{school_id}", response_model=TeacherOut)
def switch_school(
    school_id: uuid.UUID,
    teacher: TeacherDep,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
) -> TeacherOut:
    """Act for another of this teacher's schools from now on.

    Switching a tenant is re-issuing the cookie, not a new kind of session:
    the payload has carried ``{"t": teacher_id, "s": school_id}`` since 0001,
    and since D74 ``get_membership`` is what checks that pair against
    ``teacher_school`` on every request. So this endpoint's whole job is to
    prove the membership once and mint a cookie naming the new school.

    A school the teacher does not work at reads as **missing**, not forbidden —
    the same rule every ownership failure here follows, and the response must
    not confirm that a school it will not open exists.
    """
    schools = class_service.schools_for_teacher(db, teacher.id)
    target = next((s for s in schools if s.id == school_id), None)
    if target is None:
        raise errors.not_found("school", id=str(school_id))

    response.set_cookie(
        settings.session_cookie,
        issue_session(teacher.id, target.id, settings=settings),
        max_age=settings.session_max_age_s,
        httponly=True,
        samesite="lax",
        secure=settings.env in ("staging", "production"),
        path="/",
    )
    return teacher_out(teacher, target.id, schools=schools)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, settings: SettingsDep) -> None:
    response.delete_cookie(settings.session_cookie, path="/")


@router.post("/auth/password", response_model=TeacherOut)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    teacher: TeacherDep,
    tenant: TenantDep,
    db: DbDep,
    settings: SettingsDep,
) -> TeacherOut:
    """Change your own password, knowing the current one (D12).

    The one account operation that is an endpoint, and the reason it can be:
    it needs no e-mail transport — which this product does not have — and no
    role, which this schema does not have either. Creating an account or
    resetting a forgotten password are commands run by somebody with server
    access (`alppy.cli create-teacher`, `set-password`).

    **The current password is verified even though the caller already holds a
    valid session.** The session is the weaker claim: a cookie is what an
    unlocked laptop in a staffroom hands to whoever sits down next, and without
    this check a borrowed two minutes becomes a permanent takeover. Knowing the
    old password is the thing an attacker in that position does not have.

    Rate limited on the same buckets as sign-in, per account and per address,
    because this verifies a password and Argon2id is expensive on purpose —
    otherwise an authenticated session is an unlimited oracle for guessing the
    password that session already implies.

    **It does not sign other sessions out.** There is no server-side session
    store to revoke against: the cookie is signed with the server key and
    carries no password. Stated here rather than discovered, because a teacher
    changing a password they believe is known expects the opposite. The only
    lever that ejects a stolen session is rotating `ALPPY_SECRET_KEY`, which
    ejects everybody in every school — see docs/runbook/rotate-a-secret.md.
    """
    from alppy.services.account_service import AccountError, change_own_password

    email = teacher.email.lower()
    enforce_login_rate_limit(request, email, settings)
    try:
        change_own_password(
            db,
            teacher=teacher,
            current=payload.current_password,
            new=payload.new_password,
        )
    except AccountError as exc:
        # A wrong current password is a failed authentication and is charged
        # like one; the other refusals (same password, too short) are the
        # caller's own value and cost nothing to reject.
        if "current password" in str(exc):
            record_failed_login(request, email, settings)
            raise errors.unauthorized("the current password is not correct") from exc
        raise errors.unprocessable(str(exc)) from exc
    db.commit()
    clear_failed_logins(email, settings)
    return teacher_out(
        teacher, tenant, schools=class_service.schools_for_teacher(db, teacher.id)
    )


@router.get("/auth/me", response_model=TeacherOut)
def me(teacher: TeacherDep, tenant: TenantDep, db: DbDep) -> TeacherOut:
    return teacher_out(
        teacher, tenant, schools=class_service.schools_for_teacher(db, teacher.id)
    )


@router.patch("/teachers/me/preferences", response_model=TeacherOut)
def update_preferences(
    payload: TeacherPreferences, teacher: TeacherDep, tenant: TenantDep, db: DbDep
) -> TeacherOut:
    """The four display switches plus the locale.

    ``None`` is a real value here: "not chosen" means follow the system, which
    is why the request body replaces the whole preference object rather than
    patching field by field.
    """
    teacher.locale = Locale(payload.locale)
    teacher.theme = payload.theme
    teacher.contrast = payload.contrast
    teacher.motion = payload.motion
    teacher.calm = payload.calm
    teacher.discreet = payload.discreet
    db.commit()
    db.refresh(teacher)
    return teacher_out(
        teacher, tenant, schools=class_service.schools_for_teacher(db, teacher.id)
    )
