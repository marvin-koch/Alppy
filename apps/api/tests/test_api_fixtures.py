"""Shared fixtures for the HTTP-layer tests.

The suite runs against SQLite so it needs neither Postgres nor MinIO. Two
Postgres-specific column types have to be taught a SQLite spelling for
``create_all`` to work — ``JSONB`` and pgvector's ``Vector``. That translation
lives here, in test code, and never in ``alppy/models``: production is Postgres,
and the models must say so.

Other ``test_api_*`` modules pull these fixtures in with
``from test_api_fixtures import *``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, object_session, sessionmaker
from sqlalchemy.pool import StaticPool


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type: Any, _compiler: Any, **_kw: Any) -> str:
    return "JSON"


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(_type: Any, _compiler: Any, **_kw: Any) -> str:
    return "TEXT"


from alppy.api import deps  # noqa: E402
from alppy.api.deps import Scope  # noqa: E402
from alppy.core.config import Settings  # noqa: E402
from alppy.core.security import hash_password  # noqa: E402
from alppy.db.base import Base  # noqa: E402
from alppy.db.validity import today  # noqa: E402
from alppy.main import create_app  # noqa: E402
from alppy.models import (  # noqa: E402
    Chapter,
    Class,
    Competency,
    Detection,
    Exercise,
    Person,
    Scan,
    ScanPage,
    School,
    SchoolYear,
    Sheet,
    Student,
    Subject,
    Teacher,
    class_student,
    class_subject,
    class_teacher_subject,
)
from alppy.models.enums import (  # noqa: E402
    CurriculumKind,
    DetectionOutcome,
    ExerciseOrigin,
    ExerciseType,
    Locale,
    ScanStatus,
    SheetTarget,
)
from alppy.services import class_service  # noqa: E402
from alppy.storage import LocalStorage  # noqa: E402

PASSWORD = "correct-horse-battery"
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


class Tenant:
    """One school with a teacher, a subject, a class and a roster."""

    def __init__(
        self,
        school: School,
        teacher: Teacher,
        subject: Subject,
        school_class: Class,
        students: list[Student],
        competency: Competency,
    ) -> None:
        self.school = school
        self.teacher = teacher
        self.subject = subject
        self.school_class = school_class
        self.students = students
        self.competency = competency

    @property
    def unfiled_chapter_id(self) -> uuid.UUID:
        """The subject's `unfiled` Theme.

        ``Sheet.chapter_id`` is NOT NULL, so a fixture that builds a Sheet row
        directly needs a chapter. Resolved lazily through the same service the
        product uses, so the fixture cannot drift from it.
        """
        from alppy.services.chapter_service import ensure_unfiled_chapter

        session = object_session(self.subject)
        assert session is not None
        return ensure_unfiled_chapter(
            session, school_id=self.school.id, subject_id=self.subject.id
        ).id

    @property
    def scope(self) -> Scope:
        """What a request from this teacher resolves to.

        Class-derived reads take a ``Scope`` (school + owner), not a bare
        ``school_id`` — see decisions-log D23.
        """
        return Scope(school_id=self.school.id, teacher_id=self.teacher.id)


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    # pysqlite opens its own implicit transactions and never emits BEGIN, which
    # leaves SAVEPOINT unusable — and SAVEPOINT is what gives each request its
    # own rollback boundary below. Take the driver's transaction handling away
    # and emit BEGIN ourselves: the recipe SQLAlchemy documents for pysqlite.
    @event.listens_for(eng, "connect")
    def _no_implicit_begin(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(eng, "begin")
    def _explicit_begin(conn: Connection) -> None:
        conn.exec_driver_sql("BEGIN")

    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    """One connection, one outer transaction, rolled back when the test ends.

    Every session in a test — the test's own and one per request — is bound to
    this connection, so they see one another's committed work and none of it
    outlives the test. The in-memory database is on a ``StaticPool``, so this
    is the only connection there is: sessions cannot be kept apart by giving
    them one each, which is why the boundary below is a SAVEPOINT.
    """
    conn = engine.connect()
    outer = conn.begin()
    try:
        yield conn
    finally:
        if outer.is_active:
            outer.rollback()
        conn.close()


@pytest.fixture
def session_factory(connection: Connection) -> sessionmaker[Session]:
    """Sessions whose ``commit()`` lands in a SAVEPOINT, not on the database.

    ``create_savepoint`` is what makes a forgotten ``commit()`` visible. A
    request session that commits releases its savepoint and its writes stand;
    one that closes without committing rolls its savepoint back and its writes
    are gone — which is what production does, where ``get_db`` closes the
    session in a ``finally`` and ``Session.close()`` rolls back an open
    transaction (``api/deps.py``).

    The suite used to hand every request *the test's own session* and never
    close it, so a missing ``commit()`` was structurally invisible to all of
    it — the same shape of blind spot as ``create_all()`` versus migrations
    (audit 02, H1).
    """
    return sessionmaker(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """The session a test seeds through, and NOT the one handlers run on."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def reread(session_factory: sessionmaker[Session]) -> Iterator[Callable[[], Session]]:
    """Open a session with an empty identity map.

    ``db.get(Model, id)`` answers from the identity map without touching the
    database, so it returns the object a handler mutated in memory whether or
    not the row was ever written. Asserting that a write *landed* means reading
    it back through a session that has never seen it.
    """
    opened: list[Session] = []

    def _open() -> Session:
        session = session_factory()
        opened.append(session)
        return session

    try:
        yield _open
    finally:
        for session in opened:
            session.close()


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "objects")


@pytest.fixture
def settings() -> Settings:
    """A small upload cap so the size-limit test does not allocate 50 MB."""
    return Settings(env="ci", secret_key="test-secret-key", max_upload_mb=1)


@pytest.fixture
def request_sessions() -> list[Session]:
    """Every session a request opened, in order.

    A request no longer runs on the test's session, so anything a test wants to
    assert about the session a *handler* held — the tenant GUC bound onto it,
    above all — has to be asserted about this, not about ``db``.
    """
    return []


def _request_session(
    factory: sessionmaker[Session],
    opened: list[Session] | None = None,
) -> Callable[[], Iterator[Session]]:
    """A fresh session per request, closed when the request ends.

    The shape ``get_db`` has in production. Closing is the whole point: it is
    what turns a handler that flushed but never committed into a rolled-back
    write that the next assertion can see.
    """

    def _db() -> Iterator[Session]:
        session = factory()
        if opened is not None:
            opened.append(session)
        try:
            yield session
        finally:
            session.close()

    return _db


@pytest.fixture
def app(
    session_factory: sessionmaker[Session],
    storage: LocalStorage,
    settings: Settings,
    request_sessions: list[Session],
) -> FastAPI:
    application = create_app(settings)
    application.dependency_overrides[deps.get_db] = _request_session(
        session_factory, request_sessions
    )
    application.dependency_overrides[deps.get_object_storage] = lambda: storage
    application.dependency_overrides[deps.get_app_settings] = lambda: settings
    return application


@contextmanager
def make_app_client(
    session_factory: sessionmaker[Session],
    storage: LocalStorage,
    settings: Settings,
) -> Iterator[TestClient]:
    """A client on non-default settings, on this test's transaction.

    The `app`/`client` fixtures bake in the `settings` fixture; a test that has
    to vary one setting (demo mode) needs to build its own without duplicating
    the dependency overrides. It takes the factory rather than a session for
    the same reason ``app`` does: a request gets its own session and closes it.
    """
    application = create_app(settings)
    application.dependency_overrides[deps.get_db] = _request_session(session_factory)
    application.dependency_overrides[deps.get_object_storage] = lambda: storage
    application.dependency_overrides[deps.get_app_settings] = lambda: settings
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------
def seat_students(
    db: Session,
    *,
    school_id: uuid.UUID,
    school_year_id: uuid.UUID,
    school_class: Class,
    names: list[tuple[str, str]],
) -> list[Student]:
    """Build a roster and seat it, the way ``class_service.add_students`` does.

    One helper rather than the same loop in every fixture, because a pupil is
    now THREE facts: the durable ``Person`` their evidence hangs off (D87), the
    home class that minted the uid, and the enrollment rows that say where they
    sit (D69). A fixture that sets only the second builds a pupil who exists
    but is in nobody's class, and the failure surfaces three layers away as an
    empty matrix; one that skips the first cannot hold an attempt at all.
    """
    students: list[Student] = []
    people: list[Person] = []
    for number, (first, last) in enumerate(names, start=1):
        person = Person(
            id=uuid.uuid4(), school_id=school_id, first_name=first, last_name=last
        )
        people.append(person)
        students.append(
            Student(
                id=uuid.uuid4(),
                school_id=school_id,
                person_id=person.id,
                home_class_id=school_class.id,
                school_year_id=school_year_id,
                uid=f"{school_class.code}_{number:02d}",
                number=number,
                first_name=first,
                last_name=last,
            )
        )
    db.add_all(people)
    db.flush()
    db.add_all(students)
    db.flush()
    db.execute(
        class_student.insert(),
        [
            {"class_id": school_class.id, "student_id": s.id, "valid_from": today()}
            for s in students
        ],
    )
    return students


def make_tenant(
    db: Session,
    *,
    name: str,
    email: str,
    class_code: str,
    student_names: list[tuple[str, str]] | None = None,
    competency_code: str = "MSN.11",
) -> Tenant:
    school = School(id=uuid.uuid4(), name=name, canton="VD")
    db.add(school)
    db.flush()

    teacher = Teacher(
        id=uuid.uuid4(),
        home_school_id=school.id,
        email=email,
        password_hash=hash_password(PASSWORD),
        first_name="Anne",
        last_name="Muller",
        locale=Locale.FR,
    )
    year = SchoolYear(
        id=uuid.uuid4(),
        school_id=school.id,
        label="2026/27",
        starts_on=datetime(2026, 8, 1).date(),
        ends_on=datetime(2027, 7, 31).date(),
        is_current=True,
    )
    subject = Subject(
        id=uuid.uuid4(),
        school_id=school.id,
        key="mathematics",
        labels={"fr": "Mathematiques", "de": "Mathematik", "en": "Mathematics"},
    )
    db.add_all([teacher, year, subject])
    db.flush()
    class_service.join_school(db, teacher.id, school.id)

    school_class = Class(
        id=uuid.uuid4(),
        school_id=school.id,
        school_year_id=year.id,
        head_teacher_id=teacher.id,
        code=class_code,
        label="Groupe A",
    )
    db.add(school_class)
    db.flush()
    # The teacher TAKES this branch here, not merely owns the class. That is
    # the state migration 0021's backfill produces for every existing class,
    # and a fixture that skipped it would build a head teacher whose own
    # sheets are invisible to them (D73).
    assign_branch(db, school_class, teacher, subject)

    students = seat_students(
        db,
        school_id=school.id,
        school_year_id=year.id,
        school_class=school_class,
        names=list(student_names or [("Lea", "Roth")]),
    )

    competency = db.query(Competency).filter(Competency.code == competency_code).one_or_none()
    if competency is None:
        competency = Competency(
            id=uuid.uuid4(),
            curriculum=CurriculumKind.PER,
            code=competency_code,
            parent_id=None,
            subject_key="mathematics",
            cycle=3,
            labels={"fr": "Fractions", "en": "Fractions"},
            description={},
        )
        db.add(competency)
    db.flush()
    db.commit()

    return Tenant(school, teacher, subject, school_class, students, competency)


def make_exercise(
    db: Session,
    tenant: Tenant,
    *,
    statement: str,
    kind: ExerciseType = ExerciseType.MCQ,
    answer_index: int | None = 1,
    answer_bool: bool | None = None,
    difficulty: int = 3,
    with_competency: bool = True,
) -> Exercise:
    exercise = Exercise(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        subject_id=tenant.subject.id,
        type=kind,
        origin=ExerciseOrigin.TEXTBOOK,
        language="fr",
        statement=statement,
        options=["A", "B", "C", "D"] if kind is ExerciseType.MCQ else None,
        answer_index=answer_index,
        answer_bool=answer_bool,
        difficulty=difficulty,
    )
    if with_competency:
        exercise.competencies = [tenant.competency]
    db.add(exercise)
    db.flush()
    db.commit()
    return exercise


@pytest.fixture
def tenant(db: Session) -> Tenant:
    return make_tenant(
        db,
        name="College des Alpes",
        email="anne@alpes.ch",
        class_code="7B",
        student_names=[("Lea", "Roth"), ("Noah", "Berger"), ("Mia", "Keller")],
    )


@pytest.fixture
def other_tenant(db: Session) -> Tenant:
    return make_tenant(
        db,
        name="Ecole du Lac",
        email="marc@lac.ch",
        class_code="9A",
        student_names=[("Tim", "Frei")],
        competency_code="MSN.22",
    )


def login(client: TestClient, email: str, password: str = PASSWORD) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def signed_in(client: TestClient, tenant: Tenant) -> Tenant:
    login(client, tenant.teacher.email)
    return tenant


def days_before(days: float) -> datetime:
    return NOW - timedelta(days=days)


PDF_BYTES = b"%PDF-1.7\n" + b"0" * 512
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 256


def make_chapter(
    db: Session,
    tenant: Tenant,
    *,
    key: str,
    competencies: list[Competency],
    position: int = 0,
    primary_competency: Competency | None = None,
) -> Chapter:
    """A chapter grouping competencies, so the matrix filter has something to
    narrow to.

    ``primary_competency`` is the canonical parent the navigation tree hangs
    this Theme from. Defaults to the first tagged competency: a chapter with no
    primary is the `unfiled` bucket, which the tree deliberately excludes, and
    a fixture that silently produced one would make tree tests assert on an
    empty tree for the wrong reason.
    """
    primary = primary_competency or (competencies[0] if competencies else None)
    chapter = Chapter(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        subject_id=tenant.subject.id,
        key=key,
        labels={"fr": key, "de": key, "en": key},
        position=position,
        primary_competency_id=primary.id if primary is not None else None,
    )
    chapter.competencies = competencies
    db.add(chapter)
    db.flush()
    db.commit()
    return chapter


def make_paper_trail(
    db: Session, tenant: Tenant, exercise: Exercise, student: Student
) -> tuple[Sheet, Scan, Detection]:
    """A sheet, a scan of it, and one teacher-corrected detection.

    The drill-down promises a route from a mark back to the paper it came from,
    which needs the whole chain to exist: attempt -> detection -> page -> scan,
    and attempt -> sheet.
    """
    sheet = Sheet(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        class_id=tenant.school_class.id,
        subject_id=tenant.subject.id,
        chapter_id=tenant.unfiled_chapter_id,
        title="Fractions, controle 1",
        target=SheetTarget.CLASS,
        language="fr",
        layout_version="v1",
    )
    scan = Scan(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        sheet_id=sheet.id,
        original_filename="copies.pdf",
        storage_key="scans/copies.pdf",
        status=ScanStatus.CONFIRMED,
    )
    db.add_all([sheet, scan])
    db.flush()

    page = ScanPage(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        scan_id=scan.id,
        page_index=0,
        image_key="scans/page-000.png",
        registered=True,
        student_id=student.id,
    )
    db.add(page)
    db.flush()

    detection = Detection(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        scan_page_id=page.id,
        exercise_id=exercise.id,
        item_index=0,
        detected_index=1,
        confidence=0.4,
        outcome=DetectionOutcome.CORRECTED,
    )
    db.add(detection)
    db.flush()
    db.commit()
    return sheet, scan, detection


def make_colleague(
    db: Session,
    host: Tenant,
    *,
    email: str = "beatrice@alpes.ch",
    class_code: str = "7C",
    student_names: list[tuple[str, str]] | None = None,
) -> Tenant:
    """A second teacher **inside an existing school**, with their own class.

    Every other fixture pair in this suite is two different *schools*, so the
    only isolation the suite could ever see was the tenant boundary. The
    boundary that actually leaked was the one inside a school: a colleague
    could list and open another teacher's class, roster and mastery. This
    fixture is what makes that testable (decisions-log D23).
    """
    teacher = Teacher(
        id=uuid.uuid4(),
        home_school_id=host.school.id,
        email=email,
        password_hash=hash_password(PASSWORD),
        first_name="Beatrice",
        last_name="Blanc",
        locale=Locale.FR,
    )
    db.add(teacher)
    db.flush()
    class_service.join_school(db, teacher.id, host.school.id)

    school_class = Class(
        id=uuid.uuid4(),
        school_id=host.school.id,
        school_year_id=host.school_class.school_year_id,
        head_teacher_id=teacher.id,
        code=class_code,
        label="Groupe B",
    )
    db.add(school_class)
    db.flush()
    assign_branch(db, school_class, teacher, host.subject)

    students = seat_students(
        db,
        school_id=host.school.id,
        school_year_id=host.school_class.school_year_id,
        school_class=school_class,
        names=list(student_names or [("Marc", "Dupont")]),
    )
    db.commit()
    return Tenant(
        school=host.school,
        teacher=teacher,
        subject=host.subject,
        school_class=school_class,
        students=students,
        competency=host.competency,
    )


def assign_branch(
    db: Session,
    school_class: Class,
    teacher: Teacher,
    subject: Subject,
    *,
    position: int = 0,
) -> None:
    """Record that ``teacher`` takes ``subject`` in ``school_class``.

    Writes BOTH facts, in order, because they are two facts and the second
    has a composite FK onto the first: `class_subject` is what the class
    studies, `class_teacher_subject` is who teaches it (D73).

    A fixture that set only one of them would build a state the product
    cannot reach — a branch in the nav that nobody teaches, or an assignment
    to a branch the class does not study — and the failure would surface
    three layers away as an empty tree. Same reason `seat_students` exists
    rather than tests inserting `class_student` rows by hand.
    """
    db.execute(
        pg_insert(class_subject)
        .values(class_id=school_class.id, subject_id=subject.id, position=position)
        .on_conflict_do_nothing(index_elements=["class_id", "subject_id"])
    )
    # `valid_from` and the partial unique index are 0027's: the plain triple is
    # no longer unique on its own, so the conflict target has to name the
    # PARTIAL index — predicate included — or Postgres matches no index at all.
    db.execute(
        pg_insert(class_teacher_subject)
        .values(
            class_id=school_class.id,
            teacher_id=teacher.id,
            subject_id=subject.id,
            valid_from=today(),
        )
        .on_conflict_do_nothing(
            index_elements=["class_id", "teacher_id", "subject_id"],
            index_where=text("valid_to IS NULL"),
        )
    )
    db.flush()


def make_subject(db: Session, school: School, key: str) -> Subject:
    row = Subject(id=uuid.uuid4(), school_id=school.id, key=key, labels={"fr": key})
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def colleague(db: Session, tenant: Tenant) -> Tenant:
    """Another teacher in the SAME school as ``tenant``."""
    return make_colleague(db, tenant)
