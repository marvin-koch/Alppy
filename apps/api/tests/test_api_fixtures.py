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
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
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
from alppy.main import create_app  # noqa: E402
from alppy.models import (  # noqa: E402
    Chapter,
    Class,
    Competency,
    Detection,
    Exercise,
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
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "objects")


@pytest.fixture
def settings() -> Settings:
    """A small upload cap so the size-limit test does not allocate 50 MB."""
    return Settings(env="ci", secret_key="test-secret-key", max_upload_mb=1)


@pytest.fixture
def app(db: Session, storage: LocalStorage, settings: Settings) -> FastAPI:
    application = create_app(settings)

    def _db() -> Iterator[Session]:
        yield db

    application.dependency_overrides[deps.get_db] = _db
    application.dependency_overrides[deps.get_object_storage] = lambda: storage
    application.dependency_overrides[deps.get_app_settings] = lambda: settings
    return application


@contextmanager
def make_app_client(
    db: Session, storage: LocalStorage, settings: Settings
) -> Iterator[TestClient]:
    """A client on non-default settings, sharing this test's session.

    The `app`/`client` fixtures bake in the `settings` fixture; a test that has
    to vary one setting (demo mode) needs to build its own without duplicating
    the dependency overrides.
    """
    application = create_app(settings)

    def _db() -> Iterator[Session]:
        yield db

    application.dependency_overrides[deps.get_db] = _db
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

    One helper rather than the same loop in every fixture, because a student is
    now two facts: the home class that minted the uid, and the enrollment rows
    that say where they sit (D69). A fixture that sets only the first builds a
    pupil who exists but is in nobody's class, and the failure surfaces three
    layers away as an empty matrix.
    """
    students: list[Student] = []
    for number, (first, last) in enumerate(names, start=1):
        students.append(
            Student(
                id=uuid.uuid4(),
                school_id=school_id,
                home_class_id=school_class.id,
                school_year_id=school_year_id,
                uid=f"{school_class.code}_{number:02d}",
                number=number,
                first_name=first,
                last_name=last,
            )
        )
    db.add_all(students)
    db.flush()
    db.execute(
        class_student.insert(),
        [{"class_id": school_class.id, "student_id": s.id} for s in students],
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
    db.execute(
        pg_insert(class_teacher_subject)
        .values(class_id=school_class.id, teacher_id=teacher.id, subject_id=subject.id)
        .on_conflict_do_nothing(index_elements=["class_id", "teacher_id", "subject_id"])
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
