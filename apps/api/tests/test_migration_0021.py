"""The 0021 backfill is behaviour-preserving. Nothing else can prove it.

The unit suite builds its schema with ``create_all()`` (D18), so it never runs
a migration and structurally cannot see a backfill. ``check-schema-drift.py``
runs them all, but only compares the *shape* it ends with — a backfill that
inserted nothing, or the wrong rows, would leave the shape perfect.

What is at stake is the claim in 0021's docstring and in D73: after the
backfill, the widened ``owned_class_ids`` — head teacher **or** any
assignment — selects exactly the classes the old ``Class.teacher_id ==
teacher`` predicate did. If that is wrong, the release silently changes who
can open a roster of named children.

The case that makes it non-trivial is a class with **no declared branches**:
it gets zero backfilled assignments, and is still owned only because of the
head-teacher arm of the union. A pure-assignment rule would make it vanish
from its own teacher's list.

Needs a Postgres with **pgvector** — 0001 creates the extension for
``SourceChunk.embedding``. That is the dev stack's container; a plain local
Postgres will skip.
"""

from __future__ import annotations

import getpass
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from alppy.core.config import get_settings

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CANDIDATES = [
    os.environ.get("ALPPY_TEST_DATABASE_URL"),
    "postgresql+psycopg://alppy:alppy@localhost:5432/postgres",
    f"postgresql+psycopg://{getpass.getuser()}@127.0.0.1:5432/postgres",
]


def _has_pgvector(url: str | None) -> bool:
    """A server that cannot create the extension cannot run 0001."""
    if not url:
        return False
    engine = None
    try:
        engine = sa.create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            found = conn.execute(
                sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
            ).scalar_one_or_none()
            return found is not None
    except Exception:
        return False
    finally:
        if engine is not None:
            engine.dispose()


_SERVER_URL = next((u for u in _CANDIDATES if _has_pgvector(u)), None)

# A skip here used to be invisible: the candidate list below ends in a guessed
# `alppy:alppy@localhost:5432`, which is what CI happens to run, so these tests
# were passing in CI by coincidence rather than by configuration. Any change to
# that server's credentials would have retired the module in silence, green.
# CI now sets ALPPY_REQUIRE_PG_TESTS=1, which makes an unreachable server a
# collection error instead — loud, and naming the variable to set.
def _require_or_skip(server_url: str | None, what: str) -> None:
    if server_url is not None or os.environ.get("ALPPY_REQUIRE_PG_TESTS") != "1":
        return
    raise RuntimeError(
        f"ALPPY_REQUIRE_PG_TESTS=1 but no Postgres with pgvector was reachable, so "
        f"{what} cannot run. Set ALPPY_TEST_DATABASE_URL to a server (not a "
        f"database — one is created per run), or unset ALPPY_REQUIRE_PG_TESTS to "
        f"allow the skip."
    )


_require_or_skip(_SERVER_URL, "migration 0021")

pytestmark = pytest.mark.skipif(
    _SERVER_URL is None,
    reason=(
        "needs a Postgres with pgvector (migration 0001 creates the "
        "extension). Run `docker compose up postgres`, or set "
        "ALPPY_TEST_DATABASE_URL."
    ),
)


@pytest.fixture
def db_url() -> Iterator[str]:
    """A database of this test's own, dropped afterwards.

    Never the developer's: this fixture runs `downgrade` as well as
    `upgrade`, and the drift script's habit of dropping the public schema is
    exactly the accident worth designing out.
    """
    assert _SERVER_URL is not None
    name = f"alppy_mig_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(_SERVER_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = _SERVER_URL.rsplit("/", 1)[0] + f"/{name}"
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"
                ),
                {"n": name},
            )
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


@contextmanager
def _alembic(url: str) -> Iterator[Config]:
    """An Alembic config pointed at ``url``.

    ``alembic/env.py`` deliberately ignores ``sqlalchemy.url`` and always reads
    ``get_settings().database_url``, so that a migration can never be run
    against a URL hard-coded in a file. That is the right rule and this test
    does not weaken it — it sets the environment the rule reads, and puts it
    back afterwards, so nothing later in the session inherits a throwaway
    database.
    """
    previous = os.environ.get("ALPPY_DATABASE_URL")
    os.environ["ALPPY_DATABASE_URL"] = url
    get_settings.cache_clear()
    cfg = Config(os.path.join(_HERE, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_HERE, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    try:
        yield cfg
    finally:
        if previous is None:
            os.environ.pop("ALPPY_DATABASE_URL", None)
        else:
            os.environ["ALPPY_DATABASE_URL"] = previous
        get_settings.cache_clear()


def _seed_at_0020(conn: sa.Connection) -> dict[str, uuid.UUID]:
    """A world in the OLD shape, written in SQL so it survives the rename.

    Three classes, chosen for what they prove:

    * ``5A`` — Martin's, two declared branches. The ordinary case.
    * ``5B`` — Martin's, **no declared branches**. Gets no backfilled
      assignment, and is the reason ownership is a union.
    * ``6A`` — Lambert's. Must not become Martin's.
    """
    ids = {k: uuid.uuid4() for k in ("school", "martin", "lambert", "year", "5A", "5B", "6A", "fr", "ma")}
    conn.execute(
        sa.text("INSERT INTO school (id, name, canton, default_curriculum, created_at, updated_at)"
                " VALUES (:i, 'CO de Sion', 'VS', 'PER', now(), now())"),
        {"i": ids["school"]},
    )
    for key, email in (("martin", "martin@example.ch"), ("lambert", "lambert@example.ch")):
        conn.execute(
            sa.text(
                "INSERT INTO teacher (id, school_id, email, password_hash, first_name,"
                " last_name, locale, created_at, updated_at)"
                " VALUES (:i, :s, :e, 'x', 'A', :n, 'FR', now(), now())"
            ),
            {"i": ids[key], "s": ids["school"], "e": email, "n": key},
        )
    conn.execute(
        sa.text("INSERT INTO school_year (id, school_id, label, starts_on, ends_on, is_current,"
                " created_at, updated_at)"
                " VALUES (:i, :s, '2026/27', '2026-08-01', '2027-07-31', true, now(), now())"),
        {"i": ids["year"], "s": ids["school"]},
    )
    for code, owner in (("5A", "martin"), ("5B", "martin"), ("6A", "lambert")):
        conn.execute(
            sa.text("INSERT INTO class (id, school_id, school_year_id, teacher_id, code,"
                    " created_at, updated_at)"
                    " VALUES (:i, :s, :y, :t, :c, now(), now())"),
            {"i": ids[code], "s": ids["school"], "y": ids["year"], "t": ids[owner], "c": code},
        )
    for key, subject_key in (("fr", "french"), ("ma", "maths")):
        conn.execute(
            sa.text("INSERT INTO subject (id, school_id, key, labels, created_at, updated_at)"
                    " VALUES (:i, :s, :k, '{}'::jsonb, now(), now())"),
            {"i": ids[key], "s": ids["school"], "k": subject_key},
        )
    for pos, key in enumerate(("fr", "ma")):
        conn.execute(
            sa.text("INSERT INTO class_subject (class_id, subject_id, position)"
                    " VALUES (:c, :s, :p)"),
            {"c": ids["5A"], "s": ids[key], "p": pos},
        )
    # 6A studies French too, so Lambert gets a backfilled assignment of his own.
    conn.execute(
        sa.text("INSERT INTO class_subject (class_id, subject_id, position) VALUES (:c, :s, 0)"),
        {"c": ids["6A"], "s": ids["fr"]},
    )
    return ids


def _owned_the_old_way(conn: sa.Connection, teacher_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        conn.execute(
            sa.text("SELECT id FROM class WHERE teacher_id = :t"), {"t": teacher_id}
        ).scalars()
    )


def _owned_the_new_way(conn: sa.Connection, teacher_id: uuid.UUID) -> set[uuid.UUID]:
    """The widened predicate, spelled in SQL rather than imported.

    Deliberately not ``enrollment.owned_class_ids``: this test must fail if
    the *migration* is wrong, not merely agree with whatever the service
    currently does. Spelling it twice is the point.
    """
    return set(
        conn.execute(
            sa.text(
                "SELECT id FROM class WHERE head_teacher_id = :t"
                " UNION"
                " SELECT class_id FROM class_teacher_subject WHERE teacher_id = :t"
            ),
            {"t": teacher_id},
        ).scalars()
    )


def test_the_backfill_preserves_exactly_who_owned_what(db_url: str) -> None:
    engine = sa.create_engine(db_url)
    with _alembic(db_url) as cfg:
      try:
        command.upgrade(cfg, "0020")
        with engine.begin() as conn:
            ids = _seed_at_0020(conn)
            before = {
                "martin": _owned_the_old_way(conn, ids["martin"]),
                "lambert": _owned_the_old_way(conn, ids["lambert"]),
            }
        assert before["martin"] == {ids["5A"], ids["5B"]}
        assert before["lambert"] == {ids["6A"]}

        command.upgrade(cfg, "0021")

        with engine.connect() as conn:
            after = {
                "martin": _owned_the_new_way(conn, ids["martin"]),
                "lambert": _owned_the_new_way(conn, ids["lambert"]),
            }
        assert after == before, "0021 changed who owns which class"
      finally:
        engine.dispose()


def test_a_class_with_no_branches_is_still_owned_by_its_head_teacher(db_url: str) -> None:
    """The union's reason to exist.

    5B declares nothing, so it gets no assignment row. Under a
    pure-assignment ownership rule it would disappear from Martin's list the
    moment 0021 ran — a class of named children, gone, with no error anywhere.
    """
    engine = sa.create_engine(db_url)
    with _alembic(db_url) as cfg:
      try:
        command.upgrade(cfg, "0020")
        with engine.begin() as conn:
            ids = _seed_at_0020(conn)
        command.upgrade(cfg, "0021")

        with engine.connect() as conn:
            assignments = conn.execute(
                sa.text("SELECT count(*) FROM class_teacher_subject WHERE class_id = :c"),
                {"c": ids["5B"]},
            ).scalar_one()
            assert assignments == 0
            assert ids["5B"] in _owned_the_new_way(conn, ids["martin"])
      finally:
        engine.dispose()


def test_the_backfill_records_one_assignment_per_declared_branch(db_url: str) -> None:
    engine = sa.create_engine(db_url)
    with _alembic(db_url) as cfg:
      try:
        command.upgrade(cfg, "0020")
        with engine.begin() as conn:
            ids = _seed_at_0020(conn)
        command.upgrade(cfg, "0021")

        with engine.connect() as conn:
            rows = set(
                conn.execute(
                    sa.text("SELECT class_id, teacher_id, subject_id FROM class_teacher_subject")
                ).all()
            )
            assert rows == {
                (ids["5A"], ids["martin"], ids["fr"]),
                (ids["5A"], ids["martin"], ids["ma"]),
                (ids["6A"], ids["lambert"], ids["fr"]),
            }
            # The date of the thing described, not of the backfill run.
            same = conn.execute(
                sa.text(
                    "SELECT count(*) FROM class_teacher_subject a JOIN class c"
                    " ON c.id = a.class_id WHERE a.assigned_at <> c.created_at"
                )
            ).scalar_one()
            assert same == 0
      finally:
        engine.dispose()


def test_every_teacher_becomes_a_member_of_their_own_school(db_url: str) -> None:
    """Why no live cookie is logged out by this deploy.

    A session carries ``{"t": teacher_id, "s": school_id}`` and, after 0021,
    ``get_membership`` checks that pair against ``teacher_school``. The
    backfill is what makes every pair already in flight still resolve.
    """
    engine = sa.create_engine(db_url)
    with _alembic(db_url) as cfg:
      try:
        command.upgrade(cfg, "0020")
        with engine.begin() as conn:
            ids = _seed_at_0020(conn)
        command.upgrade(cfg, "0021")

        with engine.connect() as conn:
            rows = set(
                conn.execute(sa.text("SELECT teacher_id, school_id FROM teacher_school")).all()
            )
            assert rows == {
                (ids["martin"], ids["school"]),
                (ids["lambert"], ids["school"]),
            }
            # The column that stayed still answers where the account is based.
            homes = conn.execute(
                sa.text("SELECT count(*) FROM teacher WHERE home_school_id = :s"),
                {"s": ids["school"]},
            ).scalar_one()
            assert homes == 2
      finally:
        engine.dispose()


def test_downgrade_restores_the_old_column_and_constraint_names(db_url: str) -> None:
    engine = sa.create_engine(db_url)
    with _alembic(db_url) as cfg:
      try:
        command.upgrade(cfg, "0021")
        command.downgrade(cfg, "0020")

        insp = sa.inspect(engine)
        class_cols = {c["name"] for c in insp.get_columns("class")}
        assert "teacher_id" in class_cols and "head_teacher_id" not in class_cols
        teacher_cols = {c["name"] for c in insp.get_columns("teacher")}
        assert "school_id" in teacher_cols and "home_school_id" not in teacher_cols
        assert "class_teacher_subject" not in insp.get_table_names()
        assert "teacher_school" not in insp.get_table_names()
        assert "fk_class_teacher_id_teacher" in {
            fk["name"] for fk in insp.get_foreign_keys("class")
        }
      finally:
        engine.dispose()
