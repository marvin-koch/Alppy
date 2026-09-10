"""What the SCHEMA enforces — not what a service remembers to check.

Not one feature's tests: this is the whole data model's load-bearing rules, in
one place. Every unique constraint, every CHECK, and every foreign key whose
``ondelete`` was chosen rather than defaulted. When a future change makes one
of them convenient to drop, the failure here says which promise is being
broken and to whom.

The rest of the suite builds its tables with ``create_all()`` on SQLite (D18),
which does not turn on ``PRAGMA foreign_keys``. Every rule in this file —
composite foreign keys, ``ON DELETE RESTRICT``, ``ON CONFLICT DO NOTHING`` —
is therefore invisible there: a test asserting them on the default engine
would pass while proving nothing. So these run on **Postgres**, in a database
they create and drop themselves.

They are the counterpart to ``scripts/check-schema-drift.py``: that proves the
migration reproduces the models, this proves the models mean what their
comments claim. Between them, ``class_teacher_subject`` cannot quietly lose the
constraint that makes it safe to skip ``school_id``.

Set ``ALPPY_TEST_DATABASE_URL`` to point at a server (not a database — one is
created per run). Without it the module skips, so ``pytest -q`` stays fast.
"""

from __future__ import annotations

import getpass
import os
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from alppy.core.security import hash_password
from alppy.db.base import Base
from alppy.models import (
    Class,
    Person,
    School,
    SchoolYear,
    Student,
    Subject,
    Teacher,
    class_subject,
    class_teacher_subject,
    teacher_school,
)
from alppy.models.enums import Locale

# What the per-test TRUNCATE resets. Every table these tests write to, plus
# the ones that cascade from them; `create_all` builds the whole model
# regardless, so a new table only needs adding here if a test touches it.
_TABLE_NAMES = (
    "school",
    "teacher",
    "teacher_school",
    "school_year",
    "subject",
    "competency",
    "class",
    "student",
    "class_subject",
    "class_student",
    "class_teacher_subject",
    "chapter",
    "chapter_competency",
    "source",
    "exercise",
    "exercise_competency",
    "sheet",
    "sheet_item",
    "sheet_instance",
    "attempt",
)
_TABLES = Base.metadata.tables

# Only the SERVER is reused — every run creates its own database and drops it
# again, so a failing test can never leave rows in a database somebody is
# developing against. Candidates in order: an explicit override, the dev
# stack's container, then a local Postgres under the current user.
_CANDIDATES = [
    os.environ.get("ALPPY_TEST_DATABASE_URL"),
    "postgresql+psycopg://alppy:alppy@localhost:5432/postgres",
    f"postgresql+psycopg://{getpass.getuser()}@127.0.0.1:5432/postgres",
]


def _reachable(url: str | None) -> bool:
    """Reachable AND able to create pgvector.

    The whole model is created here, and ``SourceChunk.embedding`` is a
    ``vector(1024)``. Building a partial schema instead would mean choosing
    which constraints matter, which is the decision this file exists to stop
    anyone making.
    """
    if not url:
        return False
    engine = None
    try:
        engine = sa.create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            return (
                conn.execute(
                    sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
                ).scalar_one_or_none()
                is not None
            )
    except Exception:
        return False
    finally:
        if engine is not None:
            engine.dispose()


_SERVER_URL = next((u for u in _CANDIDATES if _reachable(u)), None)


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


_require_or_skip(_SERVER_URL, "the schema's constraints")

pytestmark = pytest.mark.skipif(
    _SERVER_URL is None,
    reason=(
        "needs a Postgres with pgvector: these assert constraints SQLite does "
        "not enforce. Run `docker compose up postgres`, or set "
        "ALPPY_TEST_DATABASE_URL."
    ),
)


@pytest.fixture(scope="module")
def pg_session_factory() -> Iterator[sessionmaker[Session]]:
    """A throwaway database, built from the models, dropped afterwards."""
    assert _SERVER_URL is not None  # guarded by pytestmark
    name = f"alppy_schema_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(_SERVER_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))

    url = _SERVER_URL.rsplit("/", 1)[0] + f"/{name}"
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        # The WHOLE model, not a chosen subset: a constraint nobody selected
        # is a constraint nobody notices losing.
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()
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


@pytest.fixture
def db(pg_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = pg_session_factory()
    try:
        yield session
    finally:
        session.rollback()
        # Each test starts from an empty database rather than from whatever the
        # last one left. Truncating beats per-test transactions here because
        # several of these tests deliberately provoke an IntegrityError, which
        # aborts the surrounding transaction.
        session.execute(
            sa.text(
                f"TRUNCATE {', '.join(chr(34) + n + chr(34) for n in _TABLE_NAMES)} "
                "RESTART IDENTITY CASCADE"
            )
        )
        session.commit()
        session.close()


# --------------------------------------------------------------------------
# A small world: one school, two teachers, one class, two subjects.
# --------------------------------------------------------------------------
class World:
    def __init__(self, db: Session) -> None:
        self.school = School(id=uuid.uuid4(), name="CO de Sion", canton="VS")
        db.add(self.school)
        db.flush()
        self.martin = self._teacher(db, "martin@example.ch", "Martin")
        self.lambert = self._teacher(db, "lambert@example.ch", "Lambert")
        self.year = SchoolYear(
            id=uuid.uuid4(),
            school_id=self.school.id,
            label="2026/27",
            starts_on=sa.Date().python_type(2026, 8, 1),
            ends_on=sa.Date().python_type(2027, 7, 31),
            is_current=True,
        )
        db.add(self.year)
        db.flush()
        self.klass = Class(
            id=uuid.uuid4(),
            school_id=self.school.id,
            school_year_id=self.year.id,
            head_teacher_id=self.martin.id,
            code="5A",
        )
        self.french = Subject(id=uuid.uuid4(), school_id=self.school.id, key="french", labels={})
        self.maths = Subject(id=uuid.uuid4(), school_id=self.school.id, key="maths", labels={})
        self.history = Subject(id=uuid.uuid4(), school_id=self.school.id, key="history", labels={})
        db.add_all([self.klass, self.french, self.maths, self.history])
        db.flush()

    def _teacher(self, db: Session, email: str, last: str) -> Teacher:
        row = Teacher(
            id=uuid.uuid4(),
            home_school_id=self.school.id,
            email=email,
            password_hash=hash_password("x"),
            first_name="A",
            last_name=last,
            locale=Locale.FR,
        )
        db.add(row)
        db.flush()
        db.execute(
            pg_insert(teacher_school)
            .values(teacher_id=row.id, school_id=self.school.id)
            .on_conflict_do_nothing()
        )
        return row

    def declare(self, db: Session, subject: Subject, position: int = 0) -> None:
        db.execute(
            pg_insert(class_subject)
            .values(class_id=self.klass.id, subject_id=subject.id, position=position)
            .on_conflict_do_nothing()
        )

    def assign(self, db: Session, teacher: Teacher, subject: Subject) -> None:
        db.execute(
            pg_insert(class_teacher_subject)
            .values(class_id=self.klass.id, teacher_id=teacher.id, subject_id=subject.id)
            .on_conflict_do_nothing()
        )


@pytest.fixture
def world(db: Session) -> World:
    w = World(db)
    db.commit()
    return w


# --------------------------------------------------------------------------
# class_teacher_subject
# --------------------------------------------------------------------------
def test_a_branch_the_class_does_not_study_cannot_be_assigned(db: Session, world: World) -> None:
    """The composite FK, and the reason the table can skip `school_id`.

    Without it, "Mme Martin teaches history in 5A" would be recordable in a
    class that does not study history, and `class_subject` would stop being
    the superset the Branch nav is entitled to trust.
    """
    with pytest.raises(IntegrityError):
        world.assign(db, world.martin, world.history)
        db.flush()


def test_the_same_teacher_holds_two_branches_in_one_class(db: Session, world: World) -> None:
    """The whole feature, at the schema level (the spec's Example 4)."""
    world.declare(db, world.french, 0)
    world.declare(db, world.maths, 1)
    world.assign(db, world.martin, world.french)
    world.assign(db, world.martin, world.maths)
    db.commit()

    held = set(
        db.execute(
            sa.select(class_teacher_subject.c.subject_id).where(
                class_teacher_subject.c.teacher_id == world.martin.id
            )
        ).scalars()
    )
    assert held == {world.french.id, world.maths.id}


def test_two_teachers_hold_different_branches_in_one_class(db: Session, world: World) -> None:
    world.declare(db, world.french, 0)
    world.declare(db, world.history, 1)
    world.assign(db, world.martin, world.french)
    world.assign(db, world.lambert, world.history)
    db.commit()

    rows = db.execute(
        sa.select(class_teacher_subject.c.teacher_id, class_teacher_subject.c.subject_id)
    ).all()
    assert set(rows) == {
        (world.martin.id, world.french.id),
        (world.lambert.id, world.history.id),
    }


def test_assigning_the_same_branch_twice_is_a_no_op(db: Session, world: World) -> None:
    """`ON CONFLICT DO NOTHING` over the composite PK.

    Two colleagues added at once must not race into a duplicate-key error on
    an ordinary action — the same posture `declare_subject` and `enroll` take.
    """
    world.declare(db, world.french, 0)
    world.assign(db, world.martin, world.french)
    world.assign(db, world.martin, world.french)
    db.commit()

    assert db.execute(sa.select(sa.func.count()).select_from(class_teacher_subject)).scalar_one() == 1


def test_undeclaring_a_branch_takes_its_assignments_with_it(db: Session, world: World) -> None:
    """CASCADE on the composite FK: no assignment can outlive its declaration."""
    world.declare(db, world.french, 0)
    world.assign(db, world.martin, world.french)
    db.commit()

    db.execute(sa.delete(class_subject).where(class_subject.c.subject_id == world.french.id))
    db.commit()

    assert db.execute(sa.select(sa.func.count()).select_from(class_teacher_subject)).scalar_one() == 0


def test_a_teacher_holding_an_assignment_cannot_be_deleted(db: Session, world: World) -> None:
    """RESTRICT, not the module's usual CASCADE.

    Cascading here would strip a class of an owner silently. With the head
    teacher also RESTRICT, a class can never end up as a roster of named
    children that nobody can open.
    """
    world.declare(db, world.french, 0)
    world.assign(db, world.lambert, world.french)
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(sa.delete(Teacher.__table__).where(Teacher.id == world.lambert.id))
        db.flush()


def test_a_head_teacher_cannot_be_deleted(db: Session, world: World) -> None:
    """`Class.head_teacher_id` kept its RESTRICT through the rename."""
    with pytest.raises(IntegrityError):
        db.execute(sa.delete(Teacher.__table__).where(Teacher.id == world.martin.id))
        db.flush()


# --------------------------------------------------------------------------
# teacher_school
# --------------------------------------------------------------------------
def test_a_teacher_works_at_two_schools(db: Session, world: World) -> None:
    other = School(id=uuid.uuid4(), name="OS Chur", canton="GR")
    db.add(other)
    db.flush()
    db.execute(
        pg_insert(teacher_school)
        .values(teacher_id=world.martin.id, school_id=other.id)
        .on_conflict_do_nothing()
    )
    db.commit()

    schools = set(
        db.execute(
            sa.select(teacher_school.c.school_id).where(
                teacher_school.c.teacher_id == world.martin.id
            )
        ).scalars()
    )
    assert schools == {world.school.id, other.id}
    # The column that stayed still answers a different question.
    assert world.martin.home_school_id == world.school.id


def test_deleting_a_school_takes_its_memberships_but_not_the_teacher(
    db: Session, world: World
) -> None:
    other = School(id=uuid.uuid4(), name="OS Chur", canton="GR")
    db.add(other)
    db.flush()
    db.execute(pg_insert(teacher_school).values(teacher_id=world.martin.id, school_id=other.id))
    db.commit()

    db.execute(sa.delete(School.__table__).where(School.id == other.id))
    db.commit()

    assert db.get(Teacher, world.martin.id) is not None
    remaining = set(
        db.execute(
            sa.select(teacher_school.c.school_id).where(
                teacher_school.c.teacher_id == world.martin.id
            )
        ).scalars()
    )
    assert remaining == {world.school.id}


def test_one_email_is_one_account_across_schools(db: Session, world: World) -> None:
    """`uq_teacher_email` stays global.

    One human, one account, several schools — a per-school email would mean
    two password hashes and two preference sets for one person, and `login`
    looks up by email alone.
    """
    other = School(id=uuid.uuid4(), name="OS Chur", canton="GR")
    db.add(other)
    db.flush()
    with pytest.raises(IntegrityError):
        db.add(
            Teacher(
                id=uuid.uuid4(),
                home_school_id=other.id,
                email=world.martin.email,
                password_hash=hash_password("x"),
                first_name="A",
                last_name="Martin",
                locale=Locale.FR,
            )
        )
        db.flush()


def test_a_uid_is_unique_per_school_and_year_with_two_schools_present(
    db: Session, world: World
) -> None:
    """The multi-school claim, checked rather than asserted in prose.

    `SchoolYear` is itself school-scoped, so two schools hold distinct year
    rows and therefore distinct UID namespaces: 5A_1 may exist in both Sion
    and Chur, and may not exist twice in either.
    """
    other = School(id=uuid.uuid4(), name="OS Chur", canton="GR")
    db.add(other)
    db.flush()
    other_year = SchoolYear(
        id=uuid.uuid4(),
        school_id=other.id,
        label="2026/27",
        starts_on=sa.Date().python_type(2026, 8, 1),
        ends_on=sa.Date().python_type(2027, 7, 31),
        is_current=True,
    )
    other_teacher = Teacher(
        id=uuid.uuid4(),
        home_school_id=other.id,
        email="chur@example.ch",
        password_hash=hash_password("x"),
        first_name="A",
        last_name="Blanc",
        locale=Locale.FR,
    )
    db.add_all([other_year, other_teacher])
    db.flush()
    other_class = Class(
        id=uuid.uuid4(),
        school_id=other.id,
        school_year_id=other_year.id,
        head_teacher_id=other_teacher.id,
        code="5A",
    )
    db.add(other_class)
    db.flush()

    def pupil(school_id: uuid.UUID, year_id: uuid.UUID, class_id: uuid.UUID) -> Student:
        # The person is per school: two schools holding "5A_1" hold two
        # different children, which is the claim this test is checking.
        person = Person(
            id=uuid.uuid4(),
            school_id=school_id,
            first_name="Marie",
            last_name="Favre",
        )
        db.add(person)
        db.flush()
        return Student(
            id=uuid.uuid4(),
            school_id=school_id,
            person_id=person.id,
            school_year_id=year_id,
            home_class_id=class_id,
            uid="5A_1",
            number=1,
            first_name="Marie",
            last_name="Favre",
        )

    # The same UID in two schools is fine — different namespaces.
    db.add(pupil(world.school.id, world.year.id, world.klass.id))
    db.add(pupil(other.id, other_year.id, other_class.id))
    db.commit()

    # Twice in one school and year is not.
    with pytest.raises(IntegrityError):
        db.add(pupil(world.school.id, world.year.id, world.klass.id))
        db.flush()


# --------------------------------------------------------------------------
# The names the drift gate compares
# --------------------------------------------------------------------------
def test_the_renamed_constraints_carry_their_new_names(
    pg_session_factory: sessionmaker[Session],
) -> None:
    """A rename keeps the OLD constraint names unless they are respelled.

    `check-schema-drift.py` compares names, not just shapes, so a migration
    that renamed the column and left `fk_class_teacher_id_teacher` behind
    would fail CI for a reason that reads like a mystery. Pin the names here,
    where the failure says what it means.
    """
    session = pg_session_factory()
    try:
        insp = sa.inspect(session.get_bind())
        class_fks = {fk["name"] for fk in insp.get_foreign_keys("class")}
        assert "fk_class_head_teacher_id_teacher" in class_fks
        assert "fk_class_teacher_id_teacher" not in class_fks

        teacher_fks = {fk["name"] for fk in insp.get_foreign_keys("teacher")}
        assert "fk_teacher_home_school_id_school" in teacher_fks

        cts_fks = {fk["name"] for fk in insp.get_foreign_keys("class_teacher_subject")}
        assert "fk_class_teacher_subject_class_subject" in cts_fks

        indexes = {ix["name"] for ix in insp.get_indexes("class_teacher_subject")}
        assert "ix_class_teacher_subject_teacher" in indexes
        assert "ix_teacher_school_school" in {ix["name"] for ix in insp.get_indexes("teacher_school")}
    finally:
        session.close()


# --------------------------------------------------------------------------
# The rest of the model. Not this feature's rules — the schema's.
#
# Each of these is a promise some other part of the product leans on, and each
# has a failure symptom a reviewer can picture. They live here rather than in
# the behaviour suite because SQLite would let every one of them through.
# --------------------------------------------------------------------------
def test_a_class_code_is_unique_within_a_school_year(db: Session, world: World) -> None:
    """`uq_class_code`. Two 7Bs in one year make a printed UID ambiguous."""
    with pytest.raises(IntegrityError):
        db.add(
            Class(
                id=uuid.uuid4(),
                school_id=world.school.id,
                school_year_id=world.year.id,
                head_teacher_id=world.lambert.id,
                code=world.klass.code,
            )
        )
        db.flush()


def test_a_pupil_number_must_be_positive(db: Session, world: World) -> None:
    """`number_positive`. The number is half of the UID printed on paper."""
    with pytest.raises(IntegrityError):
        db.add(
            Student(
                id=uuid.uuid4(),
                school_id=world.school.id,
                school_year_id=world.year.id,
                home_class_id=world.klass.id,
                uid="5A_0",
                number=0,
                first_name="X",
                last_name="Y",
            )
        )
        db.flush()


def test_a_class_that_is_someones_home_cannot_be_deleted(db: Session, world: World) -> None:
    """`Student.home_class_id` RESTRICT — the D69 rule, at the schema.

    Deleting a class used to delete its students, and `attempt`,
    `mastery_snapshot` and `sheet_instance` all cascade from there: a term of
    evidence gone for a child who also sat in another class.
    """
    person = Person(
        id=uuid.uuid4(),
        school_id=world.school.id,
        first_name="Marie",
        last_name="Favre",
    )
    db.add(person)
    db.flush()
    db.add(
        Student(
            id=uuid.uuid4(),
            school_id=world.school.id,
            person_id=person.id,
            school_year_id=world.year.id,
            home_class_id=world.klass.id,
            uid="5A_1",
            number=1,
            first_name="Marie",
            last_name="Favre",
        )
    )
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(sa.delete(Class.__table__).where(Class.id == world.klass.id))
        db.flush()


def test_unenrolling_removes_the_row_and_nothing_else(db: Session, world: World) -> None:
    """`class_student` CASCADEs both ends — the row is only the FACT of it.

    Deleting an enrollment must leave the pupil, their UID and their evidence
    untouched; that is what makes "unenrolling is not deleting" true rather
    than merely intended.
    """
    _person = Person(
        id=uuid.uuid4(),
        school_id=world.school.id,
        first_name="Luc",
        last_name="Rey",
    )
    db.add(_person)
    db.flush()
    student = Student(
        id=uuid.uuid4(),
        school_id=world.school.id,
        person_id=_person.id,
        school_year_id=world.year.id,
        home_class_id=world.klass.id,
        uid="5A_2",
        number=2,
        first_name="Luc",
        last_name="Rey",
    )
    db.add(student)
    db.flush()
    db.execute(
        pg_insert(_TABLES["class_student"]).values(
            class_id=world.klass.id, student_id=student.id
        )
    )
    db.commit()

    db.execute(
        sa.delete(_TABLES["class_student"]).where(
            _TABLES["class_student"].c.student_id == student.id
        )
    )
    db.commit()

    assert db.get(Student, student.id) is not None


def test_a_competency_code_is_unique_within_a_curriculum(db: Session, world: World) -> None:
    """`uq_competency_code`. LP21 and PER may both define "MSN 31"."""
    competency = _TABLES["competency"]
    common = {"labels": {"fr": "Nombres"}, "cycle": 3, "subject_key": "maths"}
    db.execute(
        pg_insert(competency).values(
            id=uuid.uuid4(), curriculum="PER", code="MSN 31", **common
        )
    )
    # The same code in the OTHER curriculum is fine.
    db.execute(
        pg_insert(competency).values(
            id=uuid.uuid4(), curriculum="LP21", code="MSN 31", **common
        )
    )
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(
            pg_insert(competency).values(
                id=uuid.uuid4(), curriculum="PER", code="MSN 31", **common
            )
        )
        db.flush()


def test_a_chapter_key_is_unique_per_school_and_subject(db: Session, world: World) -> None:
    """`uq_chapter_key` — what makes the `unfiled` bucket a singleton.

    Two `unfiled` chapters in one branch and sheets nobody filed would split
    across them, so half of them would stop being findable.
    """
    chapter = _TABLES["chapter"]
    row = {
        "school_id": world.school.id,
        "subject_id": world.french.id,
        "key": "unfiled",
        "labels": {},
        "position": 999,
    }
    db.execute(pg_insert(chapter).values(id=uuid.uuid4(), **row))
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(pg_insert(chapter).values(id=uuid.uuid4(), **row))
        db.flush()


def test_an_exercise_difficulty_stays_between_one_and_five(db: Session, world: World) -> None:
    """`difficulty_range`. Targeting reads it as a weight, not a free number."""
    with pytest.raises(IntegrityError):
        db.execute(
            pg_insert(_TABLES["exercise"]).values(
                id=uuid.uuid4(),
                school_id=world.school.id,
                subject_id=world.french.id,
                type="OPEN",
                origin="TEACHER",
                language="fr",
                statement="x",
                difficulty=6,
            )
        )
        db.flush()


def test_deleting_a_pupil_takes_their_evidence_with_them(db: Session, world: World) -> None:
    """The cascade behind the one operation allowed to destroy evidence.

    `data-model.md` §6: `SheetInstance` cascades from `Student`, and since 0028
    `Attempt`, `MasterySnapshot`, `MasteryBranchSnapshot` and
    `MisconceptionNote` cascade from `Person` instead. The API-level test can
    only show the pupil is gone — SQLite does not enforce foreign keys (D18),
    so the cascade is invisible there and a green assertion would mean nothing.
    Here it is real.

    **What 0028 changed, and why this test now deletes two rows.** Deleting the
    year-bound `Student` alone no longer destroys the evidence — it cannot, or
    a pupil's record would vanish every August. Erasure is deleting the PERSON,
    which cascades to every year of enrolment and through them to everything
    else. `nouns_service.delete_student` does exactly this: it removes the
    student, then the person once no other year still refers to them. A version
    of this test that deleted only the student would go green while destroying
    nothing, which is the failure it exists to catch.

    The mirror of `test_a_class_that_is_someones_home_cannot_be_deleted`:
    deleting a CLASS must refuse, deleting a PERSON must cascade. Those two
    facts are one decision, and they are easy to reverse by accident.
    """
    _person = Person(
        id=uuid.uuid4(),
        school_id=world.school.id,
        first_name="Marie",
        last_name="Favre",
    )
    db.add(_person)
    db.flush()
    student = Student(
        id=uuid.uuid4(),
        school_id=world.school.id,
        person_id=_person.id,
        school_year_id=world.year.id,
        home_class_id=world.klass.id,
        uid="5A_9",
        number=9,
        first_name="Marie",
        last_name="Favre",
    )
    db.add(student)
    db.flush()
    snapshot = _TABLES["mastery_snapshot"]
    competency = _TABLES["competency"]
    db.execute(
        pg_insert(competency).values(
            id=(cid := uuid.uuid4()), curriculum="PER", code="MSN 32",
            labels={"fr": "Nombres"}, cycle=3, subject_key="maths",
        )
    )
    db.execute(
        pg_insert(snapshot).values(
            id=uuid.uuid4(), school_id=world.school.id, person_id=student.person_id,
            competency_id=cid, computed_at=sa.func.now(), score=0.8, band="SOLID",
        )
    )
    db.commit()

    person_id = student.person_id
    # Deleting the enrolment record first, the way `delete_student` does: the
    # snapshot must survive THIS, and die with the person below.
    db.execute(sa.delete(Student.__table__).where(Student.id == student.id))
    db.commit()
    assert db.execute(
        sa.select(sa.func.count())
        .select_from(snapshot)
        .where(snapshot.c.person_id == person_id)
    ).scalar_one() == 1, "a year's enrolment is not the pupil"

    db.execute(sa.delete(Person.__table__).where(Person.id == person_id))
    db.commit()

    assert db.execute(
        sa.select(sa.func.count())
        .select_from(snapshot)
        .where(snapshot.c.person_id == person_id)
    ).scalar_one() == 0


# --------------------------------------------------------------------------
# The sheet, the copy and the mark
#
# These are the rules the printed loop leans on. Each is a CHECK or a UNIQUE
# that SQLite ignores entirely, so the behaviour suite has never seen one of
# them fire.
# --------------------------------------------------------------------------
def _subject_and_chapter(db: Session, world: World) -> tuple[uuid.UUID, uuid.UUID]:
    chapter_id = uuid.uuid4()
    db.execute(
        pg_insert(_TABLES["chapter"]).values(
            id=chapter_id, school_id=world.school.id, subject_id=world.french.id,
            key="fractions", labels={}, position=0,
        )
    )
    return world.french.id, chapter_id


def _sheet(db: Session, world: World, **over: object) -> uuid.UUID:
    subject_id, chapter_id = _subject_and_chapter(db, world)
    sheet_id = uuid.uuid4()
    values = {
        "id": sheet_id, "school_id": world.school.id, "class_id": world.klass.id,
        "subject_id": subject_id, "chapter_id": chapter_id, "title": "Fractions",
        "target": "CLASS", "language": "FR", "layout_version": "v1",
        "default_points_correct": 1.0, "default_points_penalty": 0.0,
    }
    values.update(over)
    db.execute(pg_insert(_TABLES["sheet"]).values(**values))
    return sheet_id


def _exercise(db: Session, world: World) -> uuid.UUID:
    exercise_id = uuid.uuid4()
    db.execute(
        pg_insert(_TABLES["exercise"]).values(
            id=exercise_id, school_id=world.school.id, subject_id=world.french.id,
            type="MCQ", origin="TEACHER", language="fr", statement="1/2 + 1/4 ?",
            difficulty=3,
        )
    )
    return exercise_id


def test_a_sheets_points_stay_inside_the_bareme(db: Session, world: World) -> None:
    """`ck_sheet_default_points_correct` — 0..20.

    The barème is a teacher's own number, but an unbounded one turns a typo
    ("100" for "1.00") into a sheet total nothing downstream expects.
    """
    with pytest.raises(IntegrityError):
        _sheet(db, world, default_points_correct=25.0)
        db.flush()


def test_a_penalty_is_stored_as_a_magnitude(db: Session, world: World) -> None:
    """The columns hold a magnitude; `scan.grading.score_for` applies the sign.

    That is the whole reason 0.25 and -0.25 cannot come to mean two different
    things, and a negative penalty here would reopen it.
    """
    with pytest.raises(IntegrityError):
        _sheet(db, world, default_points_penalty=-0.25)
        db.flush()


def test_two_items_cannot_share_a_position_on_one_sheet(
    db: Session, world: World
) -> None:
    """`uq_sheet_item_position`. Position IS the printed order.

    Two items at position 3 makes the paper's numbering ambiguous, and the
    detector reads items by index.
    """
    sheet_id = _sheet(db, world)
    exercise_id = _exercise(db, world)
    db.commit()
    item = _TABLES["sheet_item"]
    common = {"school_id": world.school.id, "sheet_id": sheet_id, "exercise_id": exercise_id}
    db.execute(pg_insert(item).values(id=uuid.uuid4(), position=0, **common))
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(pg_insert(item).values(id=uuid.uuid4(), position=0, **common))
        db.flush()


def test_an_answer_box_cannot_be_taller_than_the_page_allows(
    db: Session, world: World
) -> None:
    """`answer_box_lines` 0..14 — 0 means "no box", 14 is the page's ceiling.

    A box taller than the ceiling would print past `ITEMS_BOTTOM_MM`, and the
    crop that the scanner takes from it is refused outside that band
    (DC-print-10).
    """
    sheet_id = _sheet(db, world)
    exercise_id = _exercise(db, world)
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(
            pg_insert(_TABLES["sheet_item"]).values(
                id=uuid.uuid4(), school_id=world.school.id, sheet_id=sheet_id,
                exercise_id=exercise_id, position=1, answer_box_lines=20,
            )
        )
        db.flush()


def test_a_pupil_gets_one_printed_copy_per_sheet(db: Session, world: World) -> None:
    """`uq_instance_student`. An instance IS one printed copy.

    Two for the same pupil means two papers carrying the same UID, and the
    scan path would have no way to say which pile a page came from.
    """
    _person = Person(
        id=uuid.uuid4(),
        school_id=world.school.id,
        first_name="Luc",
        last_name="Rey",
    )
    db.add(_person)
    db.flush()
    student = Student(
        id=uuid.uuid4(), school_id=world.school.id,
        person_id=_person.id, school_year_id=world.year.id,
        home_class_id=world.klass.id, uid="5A_3", number=3,
        first_name="Luc", last_name="Rey",
    )
    db.add(student)
    sheet_id = _sheet(db, world)
    db.commit()
    inst = _TABLES["sheet_instance"]
    common = {
        "school_id": world.school.id, "sheet_id": sheet_id, "student_id": student.id,
        "student_uid": student.uid, "item_plan": [], "page_count": 1,
    }
    db.execute(pg_insert(inst).values(id=uuid.uuid4(), **common))
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(pg_insert(inst).values(id=uuid.uuid4(), **common))
        db.flush()


def test_a_sheet_cannot_be_deleted_while_it_has_been_printed(
    db: Session, world: World
) -> None:
    """`Sheet.chapter_id` is RESTRICT the other way round: the CHAPTER is what
    a sheet protects. Deleting the chapter under a live sheet is refused.

    Without it, a term of worksheets would leave the tree the moment somebody
    tidied up a Theme.
    """
    subject_id, chapter_id = _subject_and_chapter(db, world)
    db.execute(
        pg_insert(_TABLES["sheet"]).values(
            id=uuid.uuid4(), school_id=world.school.id, class_id=world.klass.id,
            subject_id=subject_id, chapter_id=chapter_id, title="Fractions",
            target="CLASS", language="FR", layout_version="v1",
            default_points_correct=1.0, default_points_penalty=0.0,
        )
    )
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(sa.delete(_TABLES["chapter"]).where(_TABLES["chapter"].c.id == chapter_id))
        db.flush()


def test_one_attempt_per_pupil_per_exercise_per_sheet(db: Session, world: World) -> None:
    """`uq_attempt_student_exercise_sheet`.

    Confirming a pile twice must not double a child's evidence — the mastery
    model weights by count, so a duplicate silently doubles that item's pull.
    """
    _person = Person(
        id=uuid.uuid4(),
        school_id=world.school.id,
        first_name="Ana",
        last_name="Blanc",
    )
    db.add(_person)
    db.flush()
    student = Student(
        id=uuid.uuid4(), school_id=world.school.id,
        person_id=_person.id, school_year_id=world.year.id,
        home_class_id=world.klass.id, uid="5A_4", number=4,
        first_name="Ana", last_name="Blanc",
    )
    db.add(student)
    sheet_id = _sheet(db, world)
    exercise_id = _exercise(db, world)
    db.commit()
    attempt = _TABLES["attempt"]
    common = {
        "school_id": world.school.id, "person_id": student.person_id,
        "exercise_id": exercise_id, "sheet_id": sheet_id,
        "correct": True, "score": 1.0, "answered_at": sa.func.now(),
    }
    db.execute(pg_insert(attempt).values(id=uuid.uuid4(), **common))
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(pg_insert(attempt).values(id=uuid.uuid4(), **common))
        db.flush()


def test_an_exercise_on_a_printed_sheet_cannot_be_deleted(
    db: Session, world: World
) -> None:
    """`SheetItem.exercise_id` is RESTRICT.

    The paper already carries the statement; deleting the row it came from
    would leave a printed item whose meaning nothing in the database knows.
    """
    sheet_id = _sheet(db, world)
    exercise_id = _exercise(db, world)
    db.execute(
        pg_insert(_TABLES["sheet_item"]).values(
            id=uuid.uuid4(), school_id=world.school.id, sheet_id=sheet_id,
            exercise_id=exercise_id, position=0,
        )
    )
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(sa.delete(_TABLES["exercise"]).where(_TABLES["exercise"].c.id == exercise_id))
        db.flush()


def test_a_mastery_score_is_a_unit_interval(db: Session, world: World) -> None:
    """`score_unit_interval`. The band thresholds are read against 0..1.

    A stored 85 (a percentage that lost its division) would read as `solid`
    forever and never decay.
    """
    _person = Person(
        id=uuid.uuid4(),
        school_id=world.school.id,
        first_name="Eva",
        last_name="Roth",
    )
    db.add(_person)
    db.flush()
    student = Student(
        id=uuid.uuid4(), school_id=world.school.id,
        person_id=_person.id, school_year_id=world.year.id,
        home_class_id=world.klass.id, uid="5A_5", number=5,
        first_name="Eva", last_name="Roth",
    )
    db.add(student)
    db.flush()
    cid = uuid.uuid4()
    db.execute(
        pg_insert(_TABLES["competency"]).values(
            id=cid, curriculum="PER", code="MSN 33", labels={}, cycle=3, subject_key="maths",
        )
    )
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(
            pg_insert(_TABLES["mastery_snapshot"]).values(
                id=uuid.uuid4(), school_id=world.school.id, person_id=student.person_id,
                competency_id=cid, computed_at=sa.func.now(), score=85.0, band="SOLID",
            )
        )
        db.flush()
