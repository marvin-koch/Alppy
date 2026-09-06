"""Pydantic schemas — the API contract.

`packages/shared` is generated from the OpenAPI document these produce, so the
frontend builds against this file rather than against assumptions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from alppy.core.uid import InvalidUidError, parse_uid
from alppy.models.enums import (
    CurriculumKind,
    DetectionOutcome,
    ExerciseOrigin,
    ExerciseType,
    JobKind,
    JobStatus,
    MasteryBand,
    ScanStatus,
    SheetTarget,
)

Locale = Literal["fr", "de", "en"]
LocalisedText = dict[str, str]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# --------------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=200)]


class TeacherPreferences(ApiModel):
    """The four display switches. None is a real value: "not chosen" differs
    from "light", because not chosen means follow the system."""

    locale: Locale = "fr"
    theme: Literal["light", "dark"] | None = None
    contrast: Literal["high"] | None = None
    motion: Literal["off"] | None = None
    calm: Literal["on"] | None = None


class TeacherOut(ApiModel):
    id: uuid.UUID
    email: EmailStr
    first_name: str
    last_name: str
    school_id: uuid.UUID
    preferences: TeacherPreferences


# ------------------------------------------------------------------ classes
class StudentOut(ApiModel):
    id: uuid.UUID
    uid: str
    number: int
    first_name: str
    last_name: str


class StudentCreate(BaseModel):
    first_name: Annotated[str, Field(min_length=1, max_length=100)]
    last_name: Annotated[str, Field(min_length=1, max_length=100)]
    number: Annotated[int, Field(ge=1, le=99)] | None = None


class RosterCreate(BaseModel):
    """Paste a roster, one student per line. The teacher's real workflow."""

    students: Annotated[list[StudentCreate], Field(min_length=1, max_length=40)]


class ClassOut(ApiModel):
    id: uuid.UUID
    code: str
    label: str | None
    student_count: int = 0
    subject_ids: list[uuid.UUID] = []


class ClassCreate(BaseModel):
    code: Annotated[str, Field(min_length=2, max_length=10)]
    label: str | None = None
    school_year_id: uuid.UUID | None = None

    @field_validator("code")
    @classmethod
    def _valid_code(cls, v: str) -> str:
        from alppy.core.uid import is_valid_class_code

        if not is_valid_class_code(v):
            raise ValueError("class code must look like 7B or 11AB")
        return v.strip().upper()


class SubjectOut(ApiModel):
    id: uuid.UUID
    key: str
    labels: LocalisedText


# --------------------------------------------------------------- curriculum
class CompetencyOut(ApiModel):
    id: uuid.UUID
    curriculum: CurriculumKind
    code: str
    parent_id: uuid.UUID | None
    subject_key: str
    cycle: int
    labels: LocalisedText
    description: LocalisedText = {}


class ChapterOut(ApiModel):
    id: uuid.UUID
    key: str
    labels: LocalisedText
    position: int
    competency_ids: list[uuid.UUID] = []


# ------------------------------------------------------------------ sources
class SourceOut(ApiModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    language: str | None
    page_count: int | None
    status: JobStatus
    error: str | None = None
    notice: str | None = None
    exercise_count: int = 0
    created_at: datetime


# ---------------------------------------------------------------- exercises
class ExerciseOut(ApiModel):
    id: uuid.UUID
    type: ExerciseType
    origin: ExerciseOrigin
    language: str
    statement: str
    options: list[str] | None = None
    answer_index: int | None = None
    answer_bool: bool | None = None
    answer_text: str | None = None
    explanation: str | None = None
    difficulty: int
    chapter_id: uuid.UUID | None = None
    competency_ids: list[uuid.UUID] = []
    source_id: uuid.UUID | None = None
    source_page: int | None = None
    approved_at: datetime | None = None

    @property
    def is_ai_generated(self) -> bool:
        return self.origin is ExerciseOrigin.AI_GENERATED


class ExerciseUpdate(BaseModel):
    statement: str | None = None
    options: list[str] | None = None
    answer_index: int | None = None
    answer_bool: bool | None = None
    explanation: str | None = None
    difficulty: Annotated[int, Field(ge=1, le=5)] | None = None
    approved: bool | None = None


class Provenance(ApiModel):
    """Where a proposal came from. The teacher audits this, so it must be
    specific enough to check against the book on the desk."""

    source_id: uuid.UUID | None = None
    source_filename: str | None = None
    page: int | None = None
    excerpt: str | None = None
    similarity: float | None = None
    reason: str


class ExerciseProposal(ApiModel):
    exercise: ExerciseOut
    score: float
    provenance: Provenance


# ------------------------------------------------------------------- sheets
class SheetProposeRequest(BaseModel):
    class_id: uuid.UUID
    subject_id: uuid.UUID
    chapter_ids: Annotated[list[uuid.UUID], Field(max_length=20)] = []
    intent: Annotated[str, Field(max_length=500)] | None = None
    count: Annotated[int, Field(ge=1, le=32)] = 12
    language: Locale | None = None
    difficulty: Annotated[int, Field(ge=1, le=5)] | None = None


class SheetProposeResponse(ApiModel):
    proposals: list[ExerciseProposal]
    language: str


class SheetItemIn(BaseModel):
    exercise_id: uuid.UUID
    position: int
    statement_override: str | None = None


class SheetCreate(BaseModel):
    class_id: uuid.UUID
    subject_id: uuid.UUID
    title: Annotated[str, Field(min_length=1, max_length=200)]
    language: Locale
    target: SheetTarget = SheetTarget.CLASS
    intent: str | None = None
    items: Annotated[list[SheetItemIn], Field(min_length=1, max_length=64)]


class SheetUpdate(BaseModel):
    title: str | None = None
    items: list[SheetItemIn] | None = None


class SheetItemOut(ApiModel):
    id: uuid.UUID
    position: int
    statement_override: str | None
    exercise: ExerciseOut


class SheetInstanceOut(ApiModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_uid: str
    page_count: int | None = None


class SheetOut(ApiModel):
    id: uuid.UUID
    class_id: uuid.UUID
    subject_id: uuid.UUID
    title: str
    target: SheetTarget
    language: str
    intent: str | None
    layout_version: str
    items: list[SheetItemOut] = []
    instances: list[SheetInstanceOut] = []
    blank_pdf_url: str | None = None
    answer_key_pdf_url: str | None = None
    rendered_at: datetime | None = None
    created_at: datetime


# -------------------------------------------------------------------- scans
class DetectionOut(ApiModel):
    id: uuid.UUID
    item_index: int
    sheet_item_id: uuid.UUID | None
    detected_index: int | None
    detected_bool: bool | None
    confidence: float
    outcome: DetectionOutcome
    fill_ratios: list[float] | None = None
    bubble_boxes: list[dict[str, float]] | None = None
    corrected_at: datetime | None = None


class DetectionCorrection(BaseModel):
    """A teacher overriding the machine. Always allowed, always recorded."""

    detected_index: Annotated[int, Field(ge=0, le=3)] | None = None


class ScanPageOut(ApiModel):
    id: uuid.UUID
    page_index: int
    image_url: str | None = None
    registered: bool
    detected_uid: str | None
    uid_confidence: float | None
    student_id: uuid.UUID | None
    sheet_instance_id: uuid.UUID | None
    detections: list[DetectionOut] = []


class ScanPageAssign(BaseModel):
    """Manual fallback when the printed UID could not be read."""

    student_id: uuid.UUID

    
class ScanOut(ApiModel):
    id: uuid.UUID
    sheet_id: uuid.UUID | None
    original_filename: str
    status: ScanStatus
    error: str | None = None
    pages: list[ScanPageOut] = []
    created_at: datetime


class ScanConfirmResponse(ApiModel):
    attempts_created: int
    students_affected: int
    competencies_updated: int


# ------------------------------------------------------------------ mastery
class MasteryCell(ApiModel):
    student_id: uuid.UUID
    competency_id: uuid.UUID
    score: float
    band: MasteryBand
    attempts_count: int
    provisional: bool
    days_until_review: int | None = None
    last_attempt_at: datetime | None = None


class MasteryMatrixOut(ApiModel):
    class_id: uuid.UUID
    students: list[StudentOut]
    competencies: list[CompetencyOut]
    cells: list[MasteryCell]
    computed_at: datetime


class MasteryPoint(ApiModel):
    at: datetime
    score: float
    band: MasteryBand


class CompetencyMastery(ApiModel):
    competency: CompetencyOut
    score: float
    band: MasteryBand
    attempts_count: int
    provisional: bool
    days_until_review: int | None = None
    history: list[MasteryPoint] = []


class StudentProfileOut(ApiModel):
    student: StudentOut
    overall_score: float
    strengths: list[CompetencyMastery] = []
    gaps: list[CompetencyMastery] = []
    all_competencies: list[CompetencyMastery] = []
    sheets_taken: int = 0


# ----------------------------------------------------------------- adaptive
class AdaptiveProposeRequest(BaseModel):
    class_id: uuid.UUID
    subject_id: uuid.UUID
    student_ids: Annotated[list[uuid.UUID], Field(max_length=40)] = []
    items_per_student: Annotated[int, Field(ge=1, le=16)] = 8
    allow_generation: bool = True
    language: Locale | None = None


class AdaptiveStudentPlan(ApiModel):
    student_id: uuid.UUID
    student_uid: str
    targeted_competency_ids: list[uuid.UUID]
    retrieved: list[ExerciseProposal] = []
    generated: list[ExerciseProposal] = []

    @property
    def total_items(self) -> int:
        return len(self.retrieved) + len(self.generated)


class AdaptiveProposeResponse(ApiModel):
    plans: list[AdaptiveStudentPlan]
    language: str
    generated_count: int = 0
    needs_approval: bool = True


class AdaptiveBatchRequest(BaseModel):
    class_id: uuid.UUID
    subject_id: uuid.UUID
    title: Annotated[str, Field(min_length=1, max_length=200)]
    language: Locale
    plans: list[AdaptiveStudentPlan]


# --------------------------------------------------------------------- jobs
class JobOut(ApiModel):
    id: uuid.UUID
    kind: JobKind
    status: JobStatus
    progress: float
    message: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


# --------------------------------------------------------------------- home
class ClassSummary(ApiModel):
    class_id: uuid.UUID
    code: str
    label: str | None
    student_count: int
    last_sheet_title: str | None = None
    last_sheet_at: datetime | None = None
    pending_scans: int = 0
    students_needing_attention: int = 0
    band_counts: dict[str, int] = {}


class HomeOut(ApiModel):
    teacher: TeacherOut
    subjects: list[SubjectOut]
    classes: list[ClassSummary]


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: bool
    redis: bool
    storage: bool


def validate_uid(value: str) -> str:
    try:
        return parse_uid(value).uid
    except InvalidUidError as exc:
        raise ValueError(str(exc)) from exc
