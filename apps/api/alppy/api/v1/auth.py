"""Login, logout, the session, and the teacher's display preferences."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from alppy.api import errors
from alppy.api.deps import DbDep, SettingsDep, TeacherDep, TenantDep
from alppy.core.security import hash_password, issue_session, needs_rehash, verify_password
from alppy.models import Teacher
from alppy.models.enums import Locale
from alppy.schemas import LoginRequest, TeacherOut, TeacherPreferences
from alppy.services import class_service, teacher_out

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TeacherOut)
def login(
    payload: LoginRequest, response: Response, db: DbDep, settings: SettingsDep
) -> TeacherOut:
    teacher = db.execute(
        select(Teacher).where(Teacher.email == payload.email.lower())
    ).scalar_one_or_none()
    # Verify against a dummy hash when the email is unknown so the response
    # time does not reveal whether an address exists.
    stored = teacher.password_hash if teacher is not None else hash_password("not-a-user")
    if not verify_password(stored, payload.password) or teacher is None:
        raise errors.unauthorized("invalid email or password")

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
    return teacher_out(
        teacher,
        teacher.home_school_id,
        schools=class_service.schools_for_teacher(db, teacher.id),
    )


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
    db.commit()
    db.refresh(teacher)
    return teacher_out(
        teacher, tenant, schools=class_service.schools_for_teacher(db, teacher.id)
    )
