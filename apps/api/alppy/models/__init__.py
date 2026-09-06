"""SQLAlchemy models for Alppy.

Tenancy: every domain table carries ``school_id``. A teacher belongs to exactly
one school, and every read path filters on the school resolved from the session.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from alppy.core.config import get_settings
from alppy.db.base import Base, SchoolScopedMixin, TimestampMixin
from alppy.models.enums import (
    CurriculumKind,
    DetectionOutcome,
    ExerciseOrigin,
    ExerciseType,
    JobKind,
    JobStatus,
    Locale,
    MasteryBand,
    ScanStatus,
    SheetKind,
    SheetTarget,
)

_EMBED_DIM = get_settings().embedding_dim


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _fk(target: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> Any:
    return mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        index=True,
    )


# --------------------------------------------------------------------------
# Tenancy
# --------------------------------------------------------------------------
class School(Base, TimestampMixin):
    __tablename__ = "school"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    canton: Mapped[str | None] = mapped_column(String(2))
    default_curriculum: Mapped[CurriculumKind] = mapped_column(
        Enum(CurriculumKind, name="curriculum_kind"), default=CurriculumKind.PER
    )

    teachers: Mapped[list[Teacher]] = relationship(back_populates="school")


class Teacher(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "teacher"
    __table_args__ = (UniqueConstraint("email", name="uq_teacher_email"),)

    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # The four display switches from DESIGN.md §8, persisted per teacher.
    # NULL means "not chosen" — which is a distinct state from light or dark.
    locale: Mapped[Locale] = mapped_column(
        Enum(Locale, name="locale"), default=Locale.FR, nullable=False
    )
    theme: Mapped[str | None] = mapped_column(String(10))  # None | light | dark
    contrast: Mapped[str | None] = mapped_column(String(10))  # None | high
    motion: Mapped[str | None] = mapped_column(String(10))  # None | off
    calm: Mapped[str | None] = mapped_column(String(10))  # None | on

    school: Mapped[School] = relationship(back_populates="teachers")


class SchoolYear(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "school_year"

    id: Mapped[uuid.UUID] = _pk()
    label: Mapped[str] = mapped_column(String(20), nullable=False)  # "2025/26"
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Subject(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "subject"

    id: Mapped[uuid.UUID] = _pk()
    key: Mapped[str] = mapped_column(String(50), nullable=False)  # "mathematics"
    labels: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)


class Class(Base, TimestampMixin, SchoolScopedMixin):
    """A teaching group. ``code`` is the Swiss short form, e.g. "7B"."""

    __tablename__ = "class"
    __table_args__ = (
        UniqueConstraint("school_id", "school_year_id", "code", name="uq_class_code"),
    )

    id: Mapped[uuid.UUID] = _pk()
    school_year_id: Mapped[uuid.UUID] = _fk("school_year.id")
    teacher_id: Mapped[uuid.UUID] = _fk("teacher.id", ondelete="RESTRICT")
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))

    students: Mapped[list[Student]] = relationship(
        back_populates="school_class", cascade="all, delete-orphan"
    )


class Student(Base, TimestampMixin, SchoolScopedMixin):
    """Names are stored but NEVER required by any AI feature.

    ``uid`` (e.g. "7B_15") is the only identifier that leaves the database
    toward a model provider or onto a printed sheet. See docs/privacy.md.
    """

    __tablename__ = "student"
    __table_args__ = (
        UniqueConstraint("school_id", "school_year_id", "uid", name="uq_student_uid"),
        CheckConstraint("number > 0", name="number_positive"),
    )

    id: Mapped[uuid.UUID] = _pk()
    class_id: Mapped[uuid.UUID] = _fk("class.id")
    school_year_id: Mapped[uuid.UUID] = _fk("school_year.id")
    uid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    school_class: Mapped[Class] = relationship(back_populates="students")


# --------------------------------------------------------------------------
# Curriculum
# --------------------------------------------------------------------------
class Competency(Base, TimestampMixin):
    """Hierarchical, curriculum-coded. LP21 and PER coexist in one table.

    Not school-scoped: official curriculum data is shared reference data.
    """

    __tablename__ = "competency"
    __table_args__ = (
        UniqueConstraint("curriculum", "code", name="uq_competency_code"),
        Index("ix_competency_subject_cycle", "subject_key", "cycle"),
    )

    id: Mapped[uuid.UUID] = _pk()
    curriculum: Mapped[CurriculumKind] = mapped_column(
        Enum(CurriculumKind, name="curriculum_kind"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("competency.id", ondelete="SET NULL")
    )
    subject_key: Mapped[str] = mapped_column(String(50), nullable=False)
    cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    labels: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    description: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)

    children: Mapped[list[Competency]] = relationship()


chapter_competency = Table(
    "chapter_competency",
    Base.metadata,
    Column("chapter_id", PgUUID(as_uuid=True), ForeignKey("chapter.id", ondelete="CASCADE"), primary_key=True),
    Column("competency_id", PgUUID(as_uuid=True), ForeignKey("competency.id", ondelete="CASCADE"), primary_key=True),
)

exercise_competency = Table(
    "exercise_competency",
    Base.metadata,
    Column("exercise_id", PgUUID(as_uuid=True), ForeignKey("exercise.id", ondelete="CASCADE"), primary_key=True),
    Column("competency_id", PgUUID(as_uuid=True), ForeignKey("competency.id", ondelete="CASCADE"), primary_key=True),
)


class Chapter(Base, TimestampMixin, SchoolScopedMixin):
    """The teacher's textbook-oriented grouping, mapped to competencies."""

    __tablename__ = "chapter"

    id: Mapped[uuid.UUID] = _pk()
    subject_id: Mapped[uuid.UUID] = _fk("subject.id")
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    labels: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    competencies: Mapped[list[Competency]] = relationship(secondary=chapter_competency)


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------
class Source(Base, TimestampMixin, SchoolScopedMixin):
    """An uploaded textbook / workbook PDF. Never redistributed by Alppy."""

    __tablename__ = "source"

    id: Mapped[uuid.UUID] = _pk()
    subject_id: Mapped[uuid.UUID] = _fk("subject.id")
    uploaded_by_id: Mapped[uuid.UUID] = _fk("teacher.id", ondelete="SET NULL", nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    language: Mapped[str | None] = mapped_column(String(5))
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), default=JobStatus.QUEUED, nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text)
    notice: Mapped[str | None] = mapped_column(Text)
    """A truthful caveat on an otherwise *successful* ingest.

    ``error`` explains a failure; this explains a success that is narrower than
    it looks — extraction skipped because no model is configured, or only the
    first N chunks scanned on a very long book. Without it the teacher reads a
    green tick and assumes the whole book was indexed for exercises."""

    chunks: Mapped[list[SourceChunk]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class SourceChunk(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "source_chunk"
    __table_args__ = (Index("ix_source_chunk_source_page", "source_id", "page"),)

    id: Mapped[uuid.UUID] = _pk()
    source_id: Mapped[uuid.UUID] = _fk("source.id")
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(Vector(_EMBED_DIM))

    source: Mapped[Source] = relationship(back_populates="chunks")


class Exercise(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "exercise"
    __table_args__ = (
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty_range"),
        Index("ix_exercise_subject_origin", "subject_id", "origin"),
    )

    id: Mapped[uuid.UUID] = _pk()
    subject_id: Mapped[uuid.UUID] = _fk("subject.id")
    chapter_id: Mapped[uuid.UUID | None] = _fk("chapter.id", nullable=True, ondelete="SET NULL")
    source_id: Mapped[uuid.UUID | None] = _fk("source.id", nullable=True, ondelete="SET NULL")
    source_chunk_id: Mapped[uuid.UUID | None] = _fk(
        "source_chunk.id", nullable=True, ondelete="SET NULL"
    )
    source_page: Mapped[int | None] = mapped_column(Integer)

    type: Mapped[ExerciseType] = mapped_column(
        Enum(ExerciseType, name="exercise_type"), nullable=False
    )
    origin: Mapped[ExerciseOrigin] = mapped_column(
        Enum(ExerciseOrigin, name="exercise_origin"),
        default=ExerciseOrigin.TEXTBOOK,
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str] | None] = mapped_column(JSONB)
    answer_index: Mapped[int | None] = mapped_column(Integer)
    answer_bool: Mapped[bool | None] = mapped_column(Boolean)
    answer_text: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    # AI-generated exercises are never printed without teacher approval.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    competencies: Mapped[list[Competency]] = relationship(secondary=exercise_competency)

    @property
    def option_count(self) -> int:
        """How many bubbles this item gets on the printed answer grid."""
        if self.type is ExerciseType.TRUE_FALSE:
            return 2
        if self.type is ExerciseType.MCQ:
            return len(self.options or [])
        return 0  # open: printed, no bubbles, never auto-graded


class ExerciseVariant(Base, TimestampMixin, SchoolScopedMixin):
    """A per-student generated version of an exercise (F4)."""

    __tablename__ = "exercise_variant"

    id: Mapped[uuid.UUID] = _pk()
    exercise_id: Mapped[uuid.UUID] = _fk("exercise.id")
    student_id: Mapped[uuid.UUID | None] = _fk("student.id", nullable=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str] | None] = mapped_column(JSONB)
    answer_index: Mapped[int | None] = mapped_column(Integer)
    answer_bool: Mapped[bool | None] = mapped_column(Boolean)
    explanation: Mapped[str | None] = mapped_column(Text)
    generation_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


# --------------------------------------------------------------------------
# Sheets
# --------------------------------------------------------------------------
class Sheet(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "sheet"

    id: Mapped[uuid.UUID] = _pk()
    class_id: Mapped[uuid.UUID] = _fk("class.id")
    subject_id: Mapped[uuid.UUID] = _fk("subject.id")
    created_by_id: Mapped[uuid.UUID] = _fk("teacher.id", ondelete="SET NULL", nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    target: Mapped[SheetTarget] = mapped_column(
        Enum(SheetTarget, name="sheet_target"), default=SheetTarget.CLASS, nullable=False
    )
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    intent: Mapped[str | None] = mapped_column(Text)

    # The print layout and the scan detector are versioned together. A scan is
    # always registered against the layout the sheet was printed with.
    layout_version: Mapped[str] = mapped_column(String(10), default="v1", nullable=False)

    blank_pdf_key: Mapped[str | None] = mapped_column(String(500))
    answer_key_pdf_key: Mapped[str | None] = mapped_column(String(500))
    rendered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[SheetItem]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", order_by="SheetItem.position"
    )
    instances: Mapped[list[SheetInstance]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan"
    )


class SheetItem(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "sheet_item"
    __table_args__ = (UniqueConstraint("sheet_id", "position", name="uq_sheet_item_position"),)

    id: Mapped[uuid.UUID] = _pk()
    sheet_id: Mapped[uuid.UUID] = _fk("sheet.id")
    exercise_id: Mapped[uuid.UUID] = _fk("exercise.id", ondelete="RESTRICT")
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # The teacher may edit the printed wording without mutating the corpus.
    statement_override: Mapped[str | None] = mapped_column(Text)

    sheet: Mapped[Sheet] = relationship(back_populates="items")
    exercise: Mapped[Exercise] = relationship()


class SheetInstance(Base, TimestampMixin, SchoolScopedMixin):
    """One printed sheet bound to one student UID.

    For a differentiated batch each instance has its own item list (via
    ``item_plan``), which is why a class export is not simply N copies.
    """

    __tablename__ = "sheet_instance"
    __table_args__ = (UniqueConstraint("sheet_id", "student_id", name="uq_instance_student"),)

    id: Mapped[uuid.UUID] = _pk()
    sheet_id: Mapped[uuid.UUID] = _fk("sheet.id")
    student_id: Mapped[uuid.UUID] = _fk("student.id")
    student_uid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # [{exercise_id, variant_id|null, position}] — resolved at render time.
    item_plan: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    page_count: Mapped[int | None] = mapped_column(Integer)

    sheet: Mapped[Sheet] = relationship(back_populates="instances")


# --------------------------------------------------------------------------
# Scan and grading
# --------------------------------------------------------------------------
class Scan(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "scan"

    id: Mapped[uuid.UUID] = _pk()
    sheet_id: Mapped[uuid.UUID | None] = _fk("sheet.id", nullable=True, ondelete="SET NULL")
    uploaded_by_id: Mapped[uuid.UUID] = _fk("teacher.id", ondelete="SET NULL", nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scan_status"), default=ScanStatus.UPLOADED, nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text)

    pages: Mapped[list[ScanPage]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", order_by="ScanPage.page_index"
    )


class ScanPage(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "scan_page"

    id: Mapped[uuid.UUID] = _pk()
    scan_id: Mapped[uuid.UUID] = _fk("scan.id")
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    image_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # Filled once the four fiducials are located and the page is deskewed.
    registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    registration_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    detected_uid: Mapped[str | None] = mapped_column(String(20), index=True)
    uid_confidence: Mapped[float | None] = mapped_column(Float)
    student_id: Mapped[uuid.UUID | None] = _fk("student.id", nullable=True, ondelete="SET NULL")
    sheet_instance_id: Mapped[uuid.UUID | None] = _fk(
        "sheet_instance.id", nullable=True, ondelete="SET NULL"
    )

    scan: Mapped[Scan] = relationship(back_populates="pages")
    detections: Mapped[list[Detection]] = relationship(
        back_populates="page", cascade="all, delete-orphan"
    )


class Detection(Base, TimestampMixin, SchoolScopedMixin):
    """One item's reading on one scanned page, before the teacher confirms."""

    __tablename__ = "detection"

    id: Mapped[uuid.UUID] = _pk()
    scan_page_id: Mapped[uuid.UUID] = _fk("scan_page.id")
    sheet_item_id: Mapped[uuid.UUID | None] = _fk(
        "sheet_item.id", nullable=True, ondelete="SET NULL"
    )
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_index: Mapped[int | None] = mapped_column(Integer)
    detected_bool: Mapped[bool | None] = mapped_column(Boolean)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    outcome: Mapped[DetectionOutcome] = mapped_column(
        Enum(DetectionOutcome, name="detection_outcome"), nullable=False
    )
    # Per-bubble fill ratios, kept so the review overlay can explain itself.
    fill_ratios: Mapped[list[float] | None] = mapped_column(JSONB)
    # Normalised [0,1] frame coords so the overlay scales to any rendered size.
    bubble_boxes: Mapped[list[dict[str, float]] | None] = mapped_column(JSONB)
    corrected_by_id: Mapped[uuid.UUID | None] = _fk(
        "teacher.id", nullable=True, ondelete="SET NULL"
    )
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    page: Mapped[ScanPage] = relationship(back_populates="detections")


class Attempt(Base, TimestampMixin, SchoolScopedMixin):
    """A graded result: one student, one exercise, one confirmed sheet."""

    __tablename__ = "attempt"
    __table_args__ = (
        Index("ix_attempt_student_answered", "student_id", "answered_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = _fk("student.id")
    exercise_id: Mapped[uuid.UUID] = _fk("exercise.id", ondelete="RESTRICT")
    sheet_id: Mapped[uuid.UUID | None] = _fk("sheet.id", nullable=True, ondelete="SET NULL")
    sheet_instance_id: Mapped[uuid.UUID | None] = _fk(
        "sheet_instance.id", nullable=True, ondelete="SET NULL"
    )
    detection_id: Mapped[uuid.UUID | None] = _fk(
        "detection.id", nullable=True, ondelete="SET NULL"
    )
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MasterySnapshot(Base, TimestampMixin, SchoolScopedMixin):
    """student x competency x time. Recomputed after every confirmed scan."""

    __tablename__ = "mastery_snapshot"
    __table_args__ = (
        Index("ix_mastery_student_competency", "student_id", "competency_id", "computed_at"),
        CheckConstraint("score >= 0 AND score <= 1", name="score_unit_interval"),
    )

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = _fk("student.id")
    competency_id: Mapped[uuid.UUID] = _fk("competency.id")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[MasteryBand] = mapped_column(
        Enum(MasteryBand, name="mastery_band"), nullable=False
    )
    attempts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------
class ModelCall(Base, TimestampMixin, SchoolScopedMixin):
    """Audit log of every model call. Contains NO student PII by construction.

    ``prompt_sha256`` lets us prove which prompt ran without storing content.
    """

    __tablename__ = "model_call"

    id: Mapped[uuid.UUID] = _pk()
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    purpose: Mapped[str] = mapped_column(String(60), nullable=False)
    prompt_name: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_estimate_chf: Mapped[float | None] = mapped_column(Float)
    ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class Job(Base, TimestampMixin, SchoolScopedMixin):
    """Background work. Request handlers never block on a model call."""

    __tablename__ = "job"

    id: Mapped[uuid.UUID] = _pk()
    kind: Mapped[JobKind] = mapped_column(Enum(JobKind, name="job_kind"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), default=JobStatus.QUEUED, nullable=False
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    message: Mapped[str | None] = mapped_column(String(300))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = [
    "Attempt",
    "Base",
    "Chapter",
    "Class",
    "Competency",
    "Detection",
    "Exercise",
    "ExerciseVariant",
    "Job",
    "MasterySnapshot",
    "ModelCall",
    "Scan",
    "ScanPage",
    "School",
    "SchoolYear",
    "Sheet",
    "SheetInstance",
    "SheetItem",
    "SheetKind",
    "Source",
    "SourceChunk",
    "Student",
    "Subject",
    "Teacher",
    "chapter_competency",
    "exercise_competency",
]
