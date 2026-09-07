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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
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


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Iterator[None]:
    deps.get_ai_limiter().reset()
    yield
    deps.get_ai_limiter().reset()


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------
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
        school_id=school.id,
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

    school_class = Class(
        id=uuid.uuid4(),
        school_id=school.id,
        school_year_id=year.id,
        teacher_id=teacher.id,
        code=class_code,
        label="Groupe A",
    )
    db.add(school_class)
    db.flush()

    students: list[Student] = []
    for number, (first, last) in enumerate(student_names or [("Lea", "Roth")], start=1):
        student = Student(
            id=uuid.uuid4(),
            school_id=school.id,
            class_id=school_class.id,
            school_year_id=year.id,
            uid=f"{class_code}_{number:02d}",
            number=number,
            first_name=first,
            last_name=last,
        )
        students.append(student)
    db.add_all(students)

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
) -> Chapter:
    """A chapter grouping competencies, so the matrix filter has something to
    narrow to."""
    chapter = Chapter(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        subject_id=tenant.subject.id,
        key=key,
        labels={"fr": key, "de": key, "en": key},
        position=position,
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
        school_id=host.school.id,
        email=email,
        password_hash=hash_password(PASSWORD),
        first_name="Beatrice",
        last_name="Blanc",
        locale=Locale.FR,
    )
    db.add(teacher)
    db.flush()

    school_class = Class(
        id=uuid.uuid4(),
        school_id=host.school.id,
        school_year_id=host.school_class.school_year_id,
        teacher_id=teacher.id,
        code=class_code,
        label="Groupe B",
    )
    db.add(school_class)
    db.flush()

    students: list[Student] = []
    for number, (first, last) in enumerate(student_names or [("Marc", "Dupont")], start=1):
        students.append(
            Student(
                id=uuid.uuid4(),
                school_id=host.school.id,
                class_id=school_class.id,
                school_year_id=host.school_class.school_year_id,
                uid=f"{class_code}_{number:02d}",
                number=number,
                first_name=first,
                last_name=last,
            )
        )
    db.add_all(students)
    db.flush()
    db.commit()
    return Tenant(
        school=host.school,
        teacher=teacher,
        subject=host.subject,
        school_class=school_class,
        students=students,
        competency=host.competency,
    )


@pytest.fixture
def colleague(db: Session, tenant: Tenant) -> Tenant:
    """Another teacher in the SAME school as ``tenant``."""
    return make_colleague(db, tenant)
