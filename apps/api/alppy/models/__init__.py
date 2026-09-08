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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from alppy.core.config import get_settings
from alppy.db.base import Base, SchoolScopedMixin, TimestampMixin
from alppy.models.enums import (
    AnswerBoxFill,
    CurriculumKind,
    DetectionOutcome,
    EventKind,
    EventSubject,
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
    sections: Mapped[list[SourceSection]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        order_by="SourceSection.position",
    )


class SourceSection(Base, TimestampMixin, SchoolScopedMixin):
    """A chapter of the uploaded document, as the document itself declares it.

    This is deliberately *not* ``Chapter``. A ``Chapter`` is the teacher's own
    grouping, mapped to curriculum competencies, and an exercise reaches one
    only by inference (``ingest.pipeline._chapter_for`` picks the chapter whose
    competencies overlap most, and returns ``None`` when the model tagged none).
    That inference needs three things to hold at once — the teacher has created
    chapters, those chapters carry competency codes, and the extraction tagged
    the item — so on a real textbook a large minority of rows end up untagged
    and unreachable by a chapter filter.

    A section is a fact about the file: "4 · Les fractions, p. 112–131". It
    needs no setup, it cannot be null for an exercise that came from a page, and
    it is how a teacher actually navigates a 400-page book. Both axes are
    offered in the builder; this one is the primary.

    ``extracted_at`` is the on-demand marker: ingestion maps every section and
    indexes every chunk, but a section's exercises are transcribed by the model
    only when a teacher first opens it. A book nobody teaches from costs nothing.
    """

    __tablename__ = "source_section"
    __table_args__ = (
        UniqueConstraint("source_id", "position", name="uq_source_section_position"),
        Index("ix_source_section_source", "source_id", "position"),
    )

    id: Mapped[uuid.UUID] = _pk()
    source_id: Mapped[uuid.UUID] = _fk("source.id")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # The number the book prints ("4"), when one was found. Not the position:
    # a preface or an un-numbered appendix has a position but no label.
    label: Mapped[str | None] = mapped_column(String(20))
    page_from: Mapped[int] = mapped_column(Integer, nullable=False)
    page_to: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When the model last read this section for exercises. ``None`` means
    indexed and searchable but never transcribed — the state the builder offers
    an "Extract" button for."""

    extraction_notice: Mapped[str | None] = mapped_column(Text)
    """A truthful caveat on an otherwise successful extraction of *this*
    section, mirroring ``Source.notice`` at section scale (no model configured,
    or the per-section chunk ceiling was hit)."""

    source: Mapped[Source] = relationship(back_populates="sections")


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
        # The builder's hot query: one section, ordered as the book prints it.
        Index("ix_exercise_source_section", "source_section_id", "source_page"),
        # Created in migration 0004 and declared nowhere until now, so
        # autogenerate proposed dropping it on every run. Partial on purpose:
        # the discarded rows are a small tail of the table, and the only query
        # that wants them is "what has this teacher already rejected for this
        # subject", which the next generation run asks so it does not offer the
        # same item twice.
        Index(
            "ix_exercise_discarded",
            "subject_id",
            postgresql_where=text("discarded_at IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    subject_id: Mapped[uuid.UUID] = _fk("subject.id")
    chapter_id: Mapped[uuid.UUID | None] = _fk("chapter.id", nullable=True, ondelete="SET NULL")
    source_id: Mapped[uuid.UUID | None] = _fk("source.id", nullable=True, ondelete="SET NULL")
    source_chunk_id: Mapped[uuid.UUID | None] = _fk(
        "source_chunk.id", nullable=True, ondelete="SET NULL"
    )
    # The book's own chapter. Always set for an extracted exercise — the
    # unrecognised tail of a document gets a catch-all section rather than a
    # NULL, so no exercise is invisible to the builder's primary filter.
    source_section_id: Mapped[uuid.UUID | None] = _fk(
        "source_section.id", nullable=True, ondelete="SET NULL"
    )
    source_page: Mapped[int | None] = mapped_column(Integer)
    # The book's own code and title for the exercise ("NO64", "Les quatre
    # multiplications"). Set by the region detector; NULL for anything a model
    # or a teacher wrote. This is how a teacher recognises an exercise, so the
    # builder shows it and the search matches it.
    label: Mapped[str | None] = mapped_column(String(16))
    title: Mapped[str | None] = mapped_column(String(200))
    # A crop of the page, exactly as printed: the figure, the table, the
    # fractions the text layer cannot carry. Stored in object storage under
    # ``figures/<school>/<source>/…``; the sheet prints it in place of the
    # statement and paginates on its physical size, which is why the size is
    # kept here in millimetres rather than re-read from the image.
    figure_key: Mapped[str | None] = mapped_column(String(500))
    figure_width_mm: Mapped[float | None] = mapped_column(Float)
    figure_height_mm: Mapped[float | None] = mapped_column(Float)

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
    # A generated item the teacher threw away. Kept rather than deleted so the
    # next adaptive run knows not to propose it again (and so any Attempt that
    # already points at it still resolves).
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    competencies: Mapped[list[Competency]] = relationship(secondary=exercise_competency)

    @property
    def option_count(self) -> int:
        """How many bubbles this item gets on the printed answer grid."""
        if self.type is ExerciseType.TRUE_FALSE:
            return 2
        if self.type is ExerciseType.MCQ:
            # Capped at the grid width: the sheet only ever draws MAX_OPTIONS
            # bubbles, so claiming more would key an answer to a bubble that is
            # not on the paper. `sheets.pagination.Item.option_count` caps the
            # same way; the two must agree.
            from alppy.sheets.layout import MAX_OPTIONS

            return min(len(self.options or []), MAX_OPTIONS)
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

    # The COMMON sheet whose corrected scan produced this one. NULL on every
    # sheet that is not an adaptive descendant. A teaching unit is a chain of
    # these: one common sheet, then the differentiated sheets its results
    # justify. Nothing else records that a sheet answers another one — without
    # it the two are just two rows with adjacent dates.
    derived_from_id: Mapped[uuid.UUID | None] = _fk(
        "sheet.id", ondelete="SET NULL", nullable=True
    )

    # The print layout and the scan detector are versioned together. A scan is
    # always registered against the layout the sheet was printed with.
    layout_version: Mapped[str] = mapped_column(String(10), default="v1", nullable=False)

    blank_pdf_key: Mapped[str | None] = mapped_column(String(500))
    answer_key_pdf_key: Mapped[str | None] = mapped_column(String(500))
    # The feedback pages, as their OWN document. Deliberately not extra pages
    # inside the copy: the detector counts a copy's pages by re-paginating its
    # items (`scan_processing._copies_by_uid`), so a page the renderer adds and
    # that count does not know about shifts `seen[uid] % len(printed_pages)`
    # and grades page 2 against page 1's questions. A separate document cannot
    # do that, whatever happens to the feedback afterwards.
    feedback_pdf_key: Mapped[str | None] = mapped_column(String(500))
    rendered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[SheetItem]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", order_by="SheetItem.position"
    )
    instances: Mapped[list[SheetInstance]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan"
    )


class SheetItem(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "sheet_item"
    __table_args__ = (
        UniqueConstraint("sheet_id", "position", name="uq_sheet_item_position"),
        # The four presets the builder offers. A value outside them would print
        # a box the pagination estimate never reserved.
        CheckConstraint(
            "answer_box_lines IS NULL OR answer_box_lines IN (0, 3, 5, 8, 12)",
            name="ck_sheet_item_answer_box_lines",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    sheet_id: Mapped[uuid.UUID] = _fk("sheet.id")
    exercise_id: Mapped[uuid.UUID] = _fk("exercise.id", ondelete="RESTRICT")
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # The teacher may edit the printed wording without mutating the corpus.
    statement_override: Mapped[str | None] = mapped_column(Text)
    # The written-answer box under an `open` item: its height in 8 mm lines
    # (3, 5, 8 or 12; 0 prints none) and what is printed inside it. Per sheet item, not per
    # exercise, for the same reason as the wording: the same exercise may want
    # three lines on a quiz and twelve on a test. NULL means the default, and
    # both are meaningless on an MCQ or a true/false item.
    answer_box_lines: Mapped[int | None] = mapped_column(Integer)
    answer_box_fill: Mapped[AnswerBoxFill | None] = mapped_column(
        Enum(AnswerBoxFill, name="answer_box_fill")
    )

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

    # Which personalised group this copy belongs to, as a printable label
    # ("Groupe 2 · Fractions équivalentes"). A label rather than a foreign key
    # to a group entity: the grouping is recomputed from mastery every time the
    # teacher asks, so a stored group would be stale the moment the next scan
    # lands, and nothing downstream — mastery, attempts, scans — needs to know
    # a copy belonged to one.
    group_label: Mapped[str | None] = mapped_column(String(60))

    # This student's misconception note, bound when the batch is created.
    feedback_id: Mapped[uuid.UUID | None] = _fk(
        "misconception_note.id", ondelete="SET NULL", nullable=True
    )

    sheet: Mapped[Sheet] = relationship(back_populates="instances")
    feedback: Mapped[MisconceptionNote | None] = relationship()



class AnswerBoxPlacement(Base, TimestampMixin, SchoolScopedMixin):
    """Where one written-answer box actually printed, in page millimetres.

    Measured from the rendered document — never recomputed from the rows. A
    bubble sits at a coordinate the layout fixes, so the detector can derive it
    from the item index alone; a box sits under a statement whose height the
    browser decides, so the only honest source of its position is the render
    that went to the printer. Written wholesale when a sheet is rendered and
    replaced on every re-render, so an exercise edited after the pile was
    printed cannot move the rectangle the scanner crops.

    Keyed the way a detection is resolved: the student's UID, which page of
    their copy, and the page-local item index.
    """

    __tablename__ = "answer_box_placement"
    __table_args__ = (
        UniqueConstraint(
            "sheet_id", "student_uid", "copy_page", "item_index",
            name="uq_answer_box_placement_slot",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    sheet_id: Mapped[uuid.UUID] = _fk("sheet.id")
    exercise_id: Mapped[uuid.UUID | None] = _fk(
        "exercise.id", nullable=True, ondelete="SET NULL"
    )
    student_uid: Mapped[str] = mapped_column(String(20), nullable=False)
    #: 1-based, the student's own folio — the same number the page footer prints.
    copy_page: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Page-local, 0..15 — what ``Detection.item_index`` carries.
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    box_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    box_fill: Mapped[AnswerBoxFill] = mapped_column(
        Enum(AnswerBoxFill, name="answer_box_fill"), nullable=False
    )
    x_mm: Mapped[float] = mapped_column(Float, nullable=False)
    y_mm: Mapped[float] = mapped_column(Float, nullable=False)
    w_mm: Mapped[float] = mapped_column(Float, nullable=False)
    h_mm: Mapped[float] = mapped_column(Float, nullable=False)
    layout_version: Mapped[str] = mapped_column(String(10), nullable=False)

class MisconceptionNote(Base, TimestampMixin, SchoolScopedMixin):
    """What one student got wrong on one common sheet, written for the student.

    A synthesis over several attempts rather than a fact about one, which is
    why it is not a column on ``Attempt``: "you subtract in the wrong order"
    is read off three wrong answers, and hanging it on an arbitrary one of them
    would make the other two look unexplained.

    It is not an ``ExerciseVariant`` either. That models a per-student rewrite
    of a *question*; this is prose about the student, addressed to them, with
    no question of its own.

    ``approved_at`` mirrors ``Exercise.approved_at`` and is enforced by the same
    module (`services.approval`). An unreviewed generated exercise is a bad
    question a teacher can spot on the page; an unreviewed generated note is a
    claim about how a named child thinks, handed to that child. The second
    needs the gate at least as much as the first.
    """

    __tablename__ = "misconception_note"
    __table_args__ = (
        Index("ix_misconception_note_student_sheet", "student_id", "based_on_sheet_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = _fk("student.id")
    subject_id: Mapped[uuid.UUID] = _fk("subject.id")
    # The common sheet the wrong answers came from. SET NULL rather than
    # CASCADE: deleting the sheet must not silently delete the explanation of
    # what a child misunderstood.
    based_on_sheet_id: Mapped[uuid.UUID | None] = _fk(
        "sheet.id", ondelete="SET NULL", nullable=True
    )
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    # ["...", "..."] — one sentence group per misconception, printed in order.
    notes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    competency_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    student: Mapped[Student] = relationship()


class Event(Base, TimestampMixin, SchoolScopedMixin):
    """One thing that happened, append-only — the spine of the agenda.

    Why a log rather than more columns
    ----------------------------------
    Every row already carries ``created_at``/``updated_at``, and neither can
    answer the questions a teacher actually asks of a term. ``updated_at`` is
    overwritten by whatever edit came last, so it cannot say when a pile was
    confirmed; and two of the moments that matter most — a sheet going to the
    photocopier, a scan being confirmed — left no trace anywhere. Adding a
    column per moment would mean a migration every time the product learns a
    new verb, and would still not give one query that returns them in order.

    Append-only, deliberately. An event is a record that something happened; it
    is never corrected, only followed by another event. That is what makes the
    agenda trustworthy enough to answer "what did I actually do in March".

    ``occurred_at`` is separate from ``created_at`` because they are not always
    the same: a scan confirmed on Sunday evening carries the lesson's date, and
    a backfilled event carries the date of the thing it describes rather than
    the date the backfill ran.
    """

    __tablename__ = "event"
    __table_args__ = (
        # The agenda's only query: this school, newest first.
        Index("ix_event_school_occurred", "school_id", "occurred_at"),
        Index("ix_event_subject", "subject_type", "subject_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    kind: Mapped[EventKind] = mapped_column(Enum(EventKind, name="event_kind"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Who did it. SET NULL: the record of the lesson outlives the account.
    actor_id: Mapped[uuid.UUID | None] = _fk("teacher.id", ondelete="SET NULL", nullable=True)
    subject_type: Mapped[EventSubject] = mapped_column(
        Enum(EventSubject, name="event_subject"), nullable=False
    )
    #: Deliberately NOT a foreign key. The log must outlive what it describes —
    #: a deleted sheet does not un-happen — and one column cannot point at four
    #: different tables. The agenda resolves the title itself and degrades to
    #: the stored summary when the row is gone.
    subject_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID | None] = _fk("class.id", ondelete="CASCADE", nullable=True)
    subject_area_id: Mapped[uuid.UUID | None] = _fk(
        "subject.id", ondelete="SET NULL", nullable=True
    )
    #: What to show when the subject row no longer exists. Never PII: a sheet
    #: title, a filename, a chapter — never a student name.
    summary: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    #: Counts the agenda shows inline (pages, copies, exercises). No free text.
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


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
    # A phone upload is one file per copy: the teacher selects 28 photos and
    # expects ONE review session, not 28. Every uploaded file is stored, in the
    # order it was selected, and the pages of all of them concatenate into this
    # scan. ``storage_key`` stays as the first file so old rows keep working.
    storage_keys: Mapped[list[str] | None] = mapped_column(JSONB)
    # Set once from the sheet the pile was printed from, so a page is always
    # registered against the layout it was printed with (never the current one).
    layout_version: Mapped[str | None] = mapped_column(String(10))
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
    # The UID decoded to a real student who is not in this sheet's class: last
    # week's pile got shuffled into this one. Not an error, but never silently
    # part of this sheet either.
    wrong_class: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # A cover sheet, a lens-cap frame, a page re-shot later. Discarded pages are
    # kept for audit and ignored by confirmation, so one bad photo cannot hold
    # a whole class set hostage.
    discarded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Which page of that student's copy this is, resolved from the decoded UID.
    page_in_copy: Mapped[int | None] = mapped_column(Integer)

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
    # The exercise this reading is graded against, resolved from the copy the
    # page belongs to. Stored rather than derived: a differentiated copy prints
    # its own item list, so "item 3 of the sheet" is not "item 3 of this paper".
    exercise_id: Mapped[uuid.UUID | None] = _fk(
        "exercise.id", nullable=True, ondelete="SET NULL"
    )
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # The number printed beside the statement AND beside the grid row, counting
    # across the whole copy. item_index restarts at 0 on every physical page, so
    # it is not what the student's paper says next to the question.
    printed_number: Mapped[int | None] = mapped_column(Integer)
    detected_index: Mapped[int | None] = mapped_column(Integer)
    detected_bool: Mapped[bool | None] = mapped_column(Boolean)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    outcome: Mapped[DetectionOutcome] = mapped_column(
        Enum(DetectionOutcome, name="detection_outcome"), nullable=False
    )
    # What the MACHINE read, written once and never updated. A teacher override
    # goes into detected_*/outcome/confidence above; these three keep the
    # reading it replaced, because "the teacher disagreed with the scanner" is
    # the fact worth auditing and it is unrecoverable once overwritten.
    machine_index: Mapped[int | None] = mapped_column(Integer)
    machine_outcome: Mapped[DetectionOutcome | None] = mapped_column(
        Enum(DetectionOutcome, name="detection_outcome")
    )
    machine_confidence: Mapped[float | None] = mapped_column(Float)
    # Per-bubble fill ratios, kept so the review overlay can explain itself.
    fill_ratios: Mapped[list[float] | None] = mapped_column(JSONB)
    # Normalised [0,1] frame coords so the overlay scales to any rendered size.
    bubble_boxes: Mapped[list[dict[str, float]] | None] = mapped_column(JSONB)
    # A written answer. ``crop_key`` is the box cut from the registered page
    # with the printed furniture removed, stored beside the page image. The
    # transcription and the verdict follow the same split as the bubbles: the
    # current value the teacher may overwrite, and the machine's, written once.
    crop_key: Mapped[str | None] = mapped_column(String(500))
    transcription: Mapped[str | None] = mapped_column(Text)
    machine_transcription: Mapped[str | None] = mapped_column(Text)
    verdict_correct: Mapped[bool | None] = mapped_column(Boolean)
    machine_verdict_correct: Mapped[bool | None] = mapped_column(Boolean)
    # Which model read it, for the audit trail; never the prompt or the image.
    vision_model: Mapped[str | None] = mapped_column(String(80))
    corrected_by_id: Mapped[uuid.UUID | None] = _fk(
        "teacher.id", nullable=True, ondelete="SET NULL"
    )
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    page: Mapped[ScanPage] = relationship(back_populates="detections")
    # selectin, not joined: the review screen loads every detection of a scan at
    # once, so one extra query beats a row per detection.
    exercise: Mapped[Exercise | None] = relationship(lazy="selectin")


class Attempt(Base, TimestampMixin, SchoolScopedMixin):
    """A graded result: one student, one exercise, one confirmed sheet."""

    __tablename__ = "attempt"
    __table_args__ = (
        Index("ix_attempt_student_answered", "student_id", "answered_at"),
        # Re-scanning a pile must correct the record, not double it: mastery is
        # a weighted mean over attempts, so a duplicate silently doubles one
        # lesson's weight against every other. confirm_scan supersedes rather
        # than inserts; this is the backstop that makes that a guarantee.
        UniqueConstraint(
            "student_id", "exercise_id", "sheet_id", name="uq_attempt_student_exercise_sheet"
        ),
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
    "AnswerBoxPlacement",
    "Attempt",
    "Base",
    "Chapter",
    "Class",
    "Competency",
    "Detection",
    "Event",
    "Exercise",
    "ExerciseVariant",
    "Job",
    "MasterySnapshot",
    "MisconceptionNote",
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
