#!/usr/bin/env python
"""Fail when row-level security is not actually protecting a tenant.

Two questions, and the second is the one that matters:

1. **Coverage.** Every ``SchoolScopedMixin`` table has RLS enabled, FORCED, and
   a policy. A new table added without one fails here.
2. **Behaviour.** Connected as the low-privilege runtime role, with the tenant
   GUC set to school A, can this connection read school B's rows, write into
   school B, or see anything at all with no tenant bound?

Why it exists
-------------
For the same reason ``check-schema-drift.py`` does, and it is the same hole.
The unit suite builds its schema with ``create_all()`` on **SQLite**, which has
no roles, no ``set_config`` and no row-level security. It is therefore
structurally incapable of noticing that a policy was never created, that
``FORCE`` was left off (in which case the owner — alembic, the CLI — is exempt
and the migration looks like it worked), or that ``ALPPY_DATABASE_URL`` was
pointed back at the owning role, which switches the whole mechanism off while
every test stays green.

Usage
-----
    createdb alppy_rls
    ALPPY_ENV=local \
    ALPPY_DISPOSABLE_DATABASE_URL=postgresql+psycopg://owner:pw@localhost:5432/alppy_rls \
        python scripts/check-rls.py

The URL must be the **owner's**. It **drops and recreates the public schema**
of the database it is given, so it refuses to run against one that is not
visibly disposable — see ``alppy.db.disposable``. Note what that guard is for
here in particular: this script wants an owner DSN, and the owner DSN a
developer has to hand is ``ALPPY_ADMIN_DATABASE_URL``, which points at the
database the application is serving. The low-privilege role is created here, so
nothing outside this script has to exist first. Exits 0 when every check
passes, 1 with the failures listed, 2 when it would not accept the database it
was pointed at.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from alppy.db.disposable import NotDisposableError, resolve_disposable_url

try:
    URL = resolve_disposable_url(os.environ)
except NotDisposableError as exc:
    print(exc)
    raise SystemExit(2) from None

# alembic/env.py reads the app's own setting rather than anything passed to it,
# by design — a migration must not be runnable against a URL hard-coded in a
# file. Pointing that setting at the database the guard just approved is how
# the two rules meet.
os.environ["ALPPY_DATABASE_URL"] = URL

#: Created by this script, dropped by nothing — the database is disposable.
APP_ROLE = "alppy_rls_probe"
APP_PASSWORD = "alppy_rls_probe"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    if not ok:
        failures.append(message)


def main() -> int:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from alppy.db.base import SchoolScopedMixin
    from alppy.models import Base

    owner = create_engine(URL)
    with owner.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text(f"DROP ROLE IF EXISTS {APP_ROLE}"))
        conn.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
        conn.execute(text(f"ALTER ROLE {APP_ROLE} NOBYPASSRLS NOSUPERUSER NOCREATEDB"))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
        conn.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
            )
        )

    config = Config(str(ROOT / "apps" / "api" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "apps" / "api" / "alembic"))
    command.upgrade(config, "head")

    with owner.begin() as conn:
        conn.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
        )
        conn.execute(text(f"GRANT EXECUTE ON FUNCTION alppy_job_school(uuid) TO {APP_ROLE}"))

    # --- 1. Coverage ------------------------------------------------------
    scoped = sorted(
        c.__tablename__
        for c in Base.__subclasses__()
        if issubclass(c, SchoolScopedMixin)
    )
    with owner.connect() as conn:
        state = dict(
            conn.execute(
                text(
                    "SELECT relname, (relrowsecurity, relforcerowsecurity) "
                    "FROM pg_class WHERE relkind = 'r'"
                )
            ).all()
        )
        with_policy = {
            row[0]
            for row in conn.execute(text("SELECT DISTINCT tablename FROM pg_policies")).all()
        }
    for table in scoped:
        flags = state.get(table)
        check(flags is not None, f"{table}: table is missing entirely")
        if flags is None:
            continue
        enabled, forced = flags
        check(enabled, f"{table}: row-level security is not enabled")
        check(
            forced,
            f"{table}: RLS is not FORCED, so the table's owner — alembic, the CLI — is exempt",
        )
        check(table in with_policy, f"{table}: RLS is on but no policy exists, so it reads as empty")

    # --- Two schools' worth of rows, written as the owner ------------------
    school_a, school_b = uuid.uuid4(), uuid.uuid4()
    teacher_id = uuid.uuid4()
    ids: dict[str, uuid.UUID] = {}
    with owner.begin() as conn:
        for name, school_id in (("A", school_a), ("B", school_b)):
            conn.execute(
                text("INSERT INTO school (id, name, default_curriculum) VALUES (:i, :n, 'PER')"),
                {"i": school_id, "n": f"School {name}"},
            )
        conn.execute(
            text(
                "INSERT INTO teacher (id, home_school_id, email, password_hash,"
                " first_name, last_name, locale)"
                " VALUES (:i, :s, 'probe@alppy.ch', 'x', 'P', 'R', 'FR')"
            ),
            {"i": teacher_id, "s": school_a},
        )
        conn.execute(
            text(
                "INSERT INTO teacher_school (teacher_id, school_id, valid_from)"
                " VALUES (:t, :s, CURRENT_DATE)"
            ),
            {"t": teacher_id, "s": school_a},
        )
        for name, school_id in (("a", school_a), ("b", school_b)):
            year, klass, student = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            person = uuid.uuid4()
            ids[f"year_{name}"], ids[f"class_{name}"] = year, klass
            ids[f"student_{name}"] = student
            ids[f"person_{name}"] = person
            conn.execute(
                text(
                    "INSERT INTO school_year (id, school_id, label, starts_on, ends_on,"
                    " is_current) VALUES (:i, :s, '2025/26', :f, :t, true)"
                ),
                {"i": year, "s": school_id, "f": date(2025, 8, 1), "t": date(2026, 7, 1)},
            )
            conn.execute(
                text(
                    "INSERT INTO class (id, school_id, school_year_id, head_teacher_id, code)"
                    " VALUES (:i, :s, :y, :t, '7B')"
                ),
                {"i": klass, "s": school_id, "y": year, "t": teacher_id},
            )
            # The durable identity above the year-bound row (0028). Names live
            # here now; `student` is one year of enrolment.
            conn.execute(
                text(
                    "INSERT INTO person (id, school_id, first_name, last_name)"
                    " VALUES (:i, :s, 'Enfant', 'Anonyme')"
                ),
                {"i": person, "s": school_id},
            )
            conn.execute(
                text(
                    "INSERT INTO student (id, school_id, person_id, home_class_id,"
                    " school_year_id, uid, number, first_name, last_name)"
                    " VALUES (:i, :s, :p, :c, :y, '7B_15', 15, 'Enfant', 'Anonyme')"
                ),
                {"i": student, "s": school_id, "p": person, "c": klass, "y": year},
            )
            # `valid_from` is NOT NULL with a CURRENT_DATE default since 0027;
            # named explicitly here so the fixture does not depend on it.
            conn.execute(
                text(
                    "INSERT INTO class_student (class_id, student_id, valid_from)"
                    " VALUES (:c, :s, CURRENT_DATE)"
                ),
                {"c": klass, "s": student},
            )

    # --- 2. Behaviour, as the low-privilege role --------------------------
    app_url = make_url(URL).set(username=APP_ROLE, password=APP_PASSWORD)
    app = create_engine(app_url)

    def as_tenant(conn, school_id: uuid.UUID | None, teacher: uuid.UUID | None = None) -> None:
        conn.execute(
            text("SELECT set_config('app.current_school_id', :s, true),"
                 "       set_config('app.current_teacher_id', :t, true)"),
            {"s": str(school_id) if school_id else "", "t": str(teacher) if teacher else ""},
        )

    with app.connect() as conn:
        # Unset is blind, not omniscient.
        with conn.begin():
            as_tenant(conn, None)
            for table in ("student", "class", "school_year", "class_student"):
                n = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                check(n == 0, f"{table}: {n} row(s) visible with no tenant bound; unset must see nothing")

        # Bound to A, B is invisible — including through the association table
        # that carries no school_id of its own.
        with conn.begin():
            as_tenant(conn, school_a, teacher_id)
            seen = conn.execute(text("SELECT school_id FROM student")).scalars().all()
            check(seen == [school_a], f"student: bound to A but saw {seen}")
            klasses = conn.execute(text("SELECT school_id FROM class")).scalars().all()
            check(klasses == [school_a], f"class: bound to A but saw {klasses}")
            links = conn.execute(text("SELECT class_id FROM class_student")).scalars().all()
            check(
                links == [ids["class_a"]],
                f"class_student: bound to A but saw {links}; the EXISTS policy is not filtering",
            )
            # A teacher sees the schools they work at, and no others (D74).
            schools = conn.execute(text("SELECT id FROM school")).scalars().all()
            check(
                set(schools) == {school_a},
                f"school: bound to A saw {schools}; login and POST /auth/school/id read this",
            )

        # A write INTO another school is refused by WITH CHECK, not silently kept.
        with conn.begin():
            as_tenant(conn, school_a, teacher_id)
            try:
                conn.execute(
                    text(
                        "INSERT INTO school_year (id, school_id, label, starts_on, ends_on,"
                        " is_current) VALUES (:i, :s, 'x', :f, :t, false)"
                    ),
                    {"i": uuid.uuid4(), "s": school_b, "f": date(2025, 8, 1), "t": date(2026, 7, 1)},
                )
            except Exception:
                pass
            else:
                failures.append(
                    "school_year: bound to A, an INSERT naming school B succeeded; "
                    "the policy has USING but no WITH CHECK"
                )

        # An UPDATE cannot move a row out of the tenant either.
        with conn.begin():
            as_tenant(conn, school_a, teacher_id)
            try:
                moved = conn.execute(
                    text("UPDATE student SET school_id = :b WHERE school_id = :a"),
                    {"a": school_a, "b": school_b},
                ).rowcount
            except Exception:
                moved = 0
            check(moved == 0, "student: bound to A, an UPDATE moved a child into school B")

        # The runtime role holds no DDL and no way to switch the mechanism off.
        with conn.begin():
            for statement, what in (
                ("CREATE TABLE rls_probe (id int)", "CREATE TABLE"),
                ("ALTER TABLE student DISABLE ROW LEVEL SECURITY", "disabling RLS"),
                ("ALTER TABLE student NO FORCE ROW LEVEL SECURITY", "un-FORCING RLS"),
            ):
                try:
                    conn.execute(text(statement))
                except Exception:
                    continue
                failures.append(f"the runtime role can run {what}; it must hold DML only")
                break

        with conn.begin():
            bypass = conn.execute(
                text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
            ).scalar_one()
            check(not bypass, "the runtime role has BYPASSRLS; every policy is decoration")

        # The worker's one uuid of escalation: a job id in, a school id out.
        with conn.begin():
            as_tenant(conn, None)
            job = uuid.uuid4()
            with owner.begin() as oconn:
                oconn.execute(
                    text(
                        "INSERT INTO job (id, school_id, kind, status, progress, payload)"
                        " VALUES (:i, :s, 'PROCESS_SCAN', 'QUEUED', 0, '{}'::jsonb)"
                    ),
                    {"i": job, "s": school_b},
                )
            found = conn.execute(
                text("SELECT alppy_job_school(:i)"), {"i": job}
            ).scalar_one_or_none()
            check(
                found == school_b,
                "alppy_job_school did not resolve a job's school with no tenant bound; "
                "the worker cannot start a job it is not yet allowed to read",
            )

            # Resolving the school is only half of it. What the worker actually
            # does next is bind that school and read the job row — the sequence
            # `_bind_job_tenant` then `db.get(Job, ...)` in worker/tasks.py. If
            # the job policy and the function disagreed about which column is
            # the tenant, the lookup above would still succeed and every job
            # would then be reported "not found" by a worker that had just been
            # told exactly where to look.
            blind = conn.execute(
                text("SELECT count(*) FROM job WHERE id = :i"), {"i": job}
            ).scalar_one()
            check(
                blind == 0,
                "an unbound session could already read a job row; the worker's "
                "SECURITY DEFINER lookup exists precisely because it cannot",
            )
            as_tenant(conn, found)
            visible = conn.execute(
                text("SELECT count(*) FROM job WHERE id = :i"), {"i": job}
            ).scalar_one()
            check(
                visible == 1,
                "binding the school alppy_job_school returned did not make the job "
                "row readable; the worker would report every job as not found",
            )

    if not failures:
        print(f"row-level security: {len(scoped)} scoped tables covered, and enforced")
        return 0

    print(f"row-level security: {len(failures)} failure(s)\n")
    for line in failures:
        print(f"  {line}")
    print(
        "\nEach line is a tenant boundary the database is not holding. "
        "Application-level filtering may still be hiding it — that is what this check is for."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
