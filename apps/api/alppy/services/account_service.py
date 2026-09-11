"""Creating a teacher, and changing their password (D12).

There was **no way to create an account**. Not an endpoint, not a command,
nothing: `api/v1/auth.py` has five routes and none of them provisions anybody.
The only path that has ever minted a teacher is `alppy.cli seed`, which creates
the *demo* teacher with a password that is a constant in this repository and
refuses to run against a real deployment. So onboarding an establishment meant
writing SQL by hand, and so did resetting a password for a teacher locked out
before a lesson.

**Why this is a CLI and not a REST resource.** Two reasons, and the first is
the honest one:

1. **There is no e-mail.** No transport exists in this product — no password
   reset, no invitation, no notification. A self-service "reset my password"
   endpoint without e-mail is either useless or a way to take over an account by
   knowing an address. Until e-mail exists, provisioning is an act performed by
   somebody with server access, and pretending otherwise would be worse than
   saying so.
2. **There are no roles.** Membership of a school *is* the permission model
   (D85): every teacher in a staffroom can see the staffroom. An
   "administrator" who may create accounts is a concept this schema does not
   have, and inventing one here — rather than in the data model, deliberately —
   would put an authorisation decision in a service module.

The one thing a teacher CAN do for themselves is change their own password,
knowing the current one. That needs no e-mail and no role, so it is an endpoint
(`POST /auth/password`) and not a command.

**A membership is an interval.** `grant_school` and `revoke_school` are thin
wrappers over `class_service.join_school`/`leave_school`, which is where the
refusals live — a staffroom cannot be emptied, and a head teacher cannot be
removed from a class that still names them.
"""

from __future__ import annotations

import secrets
import string
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.core.logging import get_logger
from alppy.core.security import hash_password, verify_password
from alppy.models import School, Teacher, teacher_school
from alppy.models.enums import Locale
from alppy.services import class_service

log = get_logger(__name__)

#: Minimum length for a password anybody sets by hand.
#:
#: 12, not the 8 `LoginRequest` accepts. That 8 is a bound on what may be
#: *submitted* — it has to keep admitting whatever already exists — and this is
#: the floor for something being created now, where there is no legacy to
#: accommodate. No composition rules: they push people towards `Passw0rd!` and
#: every current guideline says length is what matters.
MIN_PASSWORD_LENGTH = 12

#: Alphabet for a generated password. Unambiguous on purpose — no `O`/`0`,
#: `l`/`1`/`I` — because this is read off a terminal and typed into a phone by
#: somebody who has been handed it on paper.
_ALPHABET = (
    "".join(c for c in string.ascii_lowercase if c not in "l")
    + "".join(c for c in string.ascii_uppercase if c not in "IO")
    + "".join(c for c in string.digits if c not in "01")
)


class AccountError(Exception):
    """A refusal a person reading a terminal has to act on.

    Carries prose, unlike the API's error types, because the only reader is an
    operator at a shell — nothing here crosses to a browser.
    """


@dataclass(frozen=True, slots=True)
class CreatedTeacher:
    teacher: Teacher
    #: Set only when the password was GENERATED. Printed once and never stored
    #: in recoverable form; `password_hash` is Argon2id.
    generated_password: str | None


def generate_password(length: int = 20) -> str:
    """A password nobody has to invent.

    `secrets`, not `random`. 20 characters of this alphabet is ~103 bits, which
    is far past anything that matters and costs nothing — the teacher changes it
    or they do not, and if they do not, this is what stands behind their roster.
    """
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def _check_password(raw: str) -> None:
    if len(raw) < MIN_PASSWORD_LENGTH:
        raise AccountError(
            f"a password must be at least {MIN_PASSWORD_LENGTH} characters; "
            "leave it out and one will be generated"
        )


def find_school(db: Session, *, name_or_id: str) -> School:
    """By id, or by exact name. Ambiguity is refused, never guessed."""
    try:
        school = db.get(School, uuid.UUID(name_or_id))
    except ValueError:
        school = None
    if school is not None:
        return school

    matches = list(db.execute(select(School).where(School.name == name_or_id)).scalars())
    if not matches:
        raise AccountError(f"no school called {name_or_id!r}; `list-schools` shows them all")
    if len(matches) > 1:
        raise AccountError(
            f"{len(matches)} schools are called {name_or_id!r}; name one by its id instead"
        )
    return matches[0]


def find_teacher(db: Session, *, email: str) -> Teacher:
    teacher = db.execute(
        select(Teacher).where(Teacher.email == email.lower())
    ).scalar_one_or_none()
    if teacher is None:
        raise AccountError(f"no teacher with the address {email!r}")
    return teacher


def create_teacher(
    db: Session,
    *,
    email: str,
    first_name: str,
    last_name: str,
    school: School,
    password: str | None = None,
    locale: Locale = Locale.FR,
) -> CreatedTeacher:
    """Create an account and put it in a staffroom, in one act.

    Both halves, always. A teacher row without a `teacher_school` membership
    holds a valid cookie and can act on nothing — `get_membership` checks the
    pair — which presents as a teacher who signs in successfully and then finds
    an empty product. That silent half-state is the reason this is one function
    and not two commands.
    """
    email = email.lower().strip()
    if not email or "@" not in email:
        raise AccountError(f"{email!r} is not an e-mail address")

    existing = db.execute(select(Teacher).where(Teacher.email == email)).scalar_one_or_none()
    if existing is not None:
        raise AccountError(
            f"{email} already exists. To add them to another staffroom use "
            "`grant-school`; to reset their password use `set-password`"
        )

    generated: str | None = None
    if password is None:
        generated = generate_password()
        password = generated
    else:
        _check_password(password)

    teacher = Teacher(
        id=uuid.uuid4(),
        home_school_id=school.id,
        email=email,
        password_hash=hash_password(password),
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        locale=locale,
    )
    db.add(teacher)
    db.flush()
    class_service.join_school(db, teacher.id, school.id)

    # The address is deliberately absent: this line goes to whatever aggregates
    # stdout, and an e-mail address is personal data about the teacher (D33).
    log.info("account.created", teacher_id=str(teacher.id), school_id=str(school.id))
    return CreatedTeacher(teacher=teacher, generated_password=generated)


def set_password(db: Session, *, teacher: Teacher, password: str | None = None) -> str | None:
    """Set a teacher's password. Returns the generated one, or None.

    **Every live session survives.** The cookie is signed with the server key
    and carries no password, so changing one does not sign anybody out — which
    is exactly wrong when the reason for the change is that somebody else knows
    it. There is no server-side session store to revoke against, so the only
    lever is the signing key, and turning that means ejecting every teacher in
    every school. Say so where it is read: `runbook/rotate-a-secret.md`.
    """
    generated: str | None = None
    if password is None:
        generated = generate_password()
        password = generated
    else:
        _check_password(password)
    teacher.password_hash = hash_password(password)
    db.flush()
    log.info("account.password_set", teacher_id=str(teacher.id))
    return generated


def change_own_password(
    db: Session, *, teacher: Teacher, current: str, new: str
) -> None:
    """A teacher changing their own password, knowing the old one.

    The one account operation that needs neither e-mail nor a role, which is
    why it is the one that is an endpoint. Verifying the current password is
    what stops a borrowed unlocked laptop becoming a permanent takeover.
    """
    if not verify_password(teacher.password_hash, current):
        raise AccountError("the current password is not correct")
    if new == current:
        raise AccountError("the new password is the same as the current one")
    _check_password(new)
    teacher.password_hash = hash_password(new)
    db.flush()
    log.info("account.password_changed", teacher_id=str(teacher.id))


def grant_school(db: Session, *, teacher: Teacher, school: School) -> None:
    """Add a teacher to a staffroom. Idempotent; re-joining is supported."""
    class_service.join_school(db, teacher.id, school.id)
    log.info("account.granted", teacher_id=str(teacher.id), school_id=str(school.id))


def revoke_school(db: Session, *, teacher: Teacher, school: School) -> None:
    """End a membership as of today. An UPDATE, never a DELETE.

    `class_service.leave_school` holds the two refusals — a staffroom cannot be
    emptied, and a teacher who is still head of a class cannot be removed — and
    both raise the API's `conflict`, which reads perfectly well at a shell.
    """
    class_service.leave_school(db, teacher.id, school.id)
    log.info("account.revoked", teacher_id=str(teacher.id), school_id=str(school.id))


@dataclass(frozen=True, slots=True)
class TeacherRow:
    """One line of `list-teachers`. No password material, ever."""

    teacher_id: uuid.UUID
    email: str
    name: str
    home_school: str
    current_schools: tuple[str, ...]


def list_teachers(db: Session, *, school: School | None = None) -> list[TeacherRow]:
    """Every teacher, or every teacher in one staffroom.

    Cross-school by design — it runs as the owner, from a shell, to answer
    "which account is this" before acting on it. That is precisely the question
    the tenant boundary refuses to answer inside a request, and precisely why
    this is not an endpoint.
    """
    from alppy.db.validity import today, valid_on

    stmt = select(Teacher).order_by(Teacher.last_name, Teacher.first_name)
    if school is not None:
        stmt = stmt.join(
            teacher_school, teacher_school.c.teacher_id == Teacher.id
        ).where(
            teacher_school.c.school_id == school.id,
            valid_on(teacher_school, today()),
        )

    rows: list[TeacherRow] = []
    schools = {s.id: s.name for s in db.execute(select(School)).scalars()}
    for teacher in db.execute(stmt).scalars():
        current = db.execute(
            select(teacher_school.c.school_id)
            .where(teacher_school.c.teacher_id == teacher.id)
            .where(valid_on(teacher_school, today()))
        ).scalars()
        rows.append(
            TeacherRow(
                teacher_id=teacher.id,
                email=teacher.email,
                name=f"{teacher.first_name} {teacher.last_name}",
                home_school=schools.get(teacher.home_school_id, "?"),
                current_schools=tuple(
                    sorted(schools.get(sid, "?") for sid in current)
                ),
            )
        )
    return rows
