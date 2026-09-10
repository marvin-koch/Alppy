"""Pydantic schemas — the API contract.

`packages/shared` is generated from the OpenAPI document these produce, so the
frontend builds against this file rather than against assumptions.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from alppy.core.uid import InvalidUidError, parse_uid
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
    MasteryBand,
    ScanStatus,
    SheetTarget,
)
from alppy.sheets.layout import (
    ANSWER_BOX_MAX_LINES,
    DEFAULT_POINTS_CORRECT,
    DEFAULT_POINTS_PENALTY,
    MAX_ITEM_POINTS,
)
from alppy.sheets.layout import MAX_OPTIONS as MAX_MCQ_OPTIONS

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


class SchoolOut(ApiModel):
    id: uuid.UUID
    name: str
    canton: str | None = None
    default_curriculum: CurriculumKind | None = None


class TeacherOut(ApiModel):
    id: uuid.UUID
    email: EmailStr
    first_name: str
    last_name: str
    # The school this SESSION is acting for — not where the account is based
    # (D74). The client switches tenants on this field.
    school_id: uuid.UUID
    # Every staffroom this teacher works in, so the rail can offer the switch.
    schools: list[SchoolOut] = []
    preferences: TeacherPreferences


# ------------------------------------------------------------------ classes
class StudentOut(ApiModel):
    id: uuid.UUID
    uid: str
    number: int
    #: NULL on an anonymised pupil. A client rendering a roster must fall back
    #: to `uid`, which is retained on purpose and is what the paper carries.
    first_name: str | None
    last_name: str | None
    #: When a parent's erasure request was answered. The evidence behind this
    #: pupil is intact; the person is no longer identifiable.
    anonymised_at: datetime | None = None
    #: The class that MINTED `uid` and `number`. A pupil has exactly one, and
    #: it is the one the printed identifier comes from (D69, I-platform-09).
    home_class_code: str = ""
    #: Every class this pupil sits in, home first. A visiting pupil shows two;
    #: without this a roster cannot say why a 9A identifier is on a 7B list.
    class_codes: list[str] = []


class StudentCreate(BaseModel):
    first_name: Annotated[str, Field(min_length=1, max_length=100)]
    last_name: Annotated[str, Field(min_length=1, max_length=100)]
    number: Annotated[int, Field(ge=1, le=99)] | None = None


class RosterCreate(BaseModel):
    """Paste a roster, one student per line. The teacher's real workflow."""

    students: Annotated[list[StudentCreate], Field(min_length=1, max_length=40)]


class ClassTeacherOut(ApiModel):
    """One teacher's footing in one class."""

    teacher_id: uuid.UUID
    first_name: str
    last_name: str
    subject_ids: list[uuid.UUID] = []
    is_head: bool = False


class ColleagueOut(ApiModel):
    """A teacher in the same school, for the branch picker.

    Deliberately no ``email``: a picker has no reason to know colleagues'
    addresses, and ``TeacherOut`` already exists for the signed-in user.
    """

    id: uuid.UUID
    first_name: str
    last_name: str


class ExportEnrolment(ApiModel):
    """One year's enrolment record. A pupil has one per year they were here."""

    student_id: uuid.UUID
    uid: str
    number: int | None
    class_id: uuid.UUID | None
    class_code: str | None
    school_year: str | None
    is_home_class: bool
    valid_from: date | None
    valid_to: date | None


class ExportAttempt(ApiModel):
    """One answer, as it was recorded. The evidence, not the band over it."""

    answered_at: datetime
    exercise_id: uuid.UUID
    competency_codes: list[str] = []
    correct: bool
    score: float
    difficulty: int
    sheet_id: uuid.UUID | None
    sheet_title: str | None


class ExportNote(ApiModel):
    """A misconception note. Free text a teacher or a model wrote ABOUT the
    child, which is the most sensitive thing in the record and the reason the
    export exists as more than a list of marks."""

    created_at: datetime
    subject_id: uuid.UUID
    language: str
    notes: list[str] = []
    based_on_sheet_id: uuid.UUID | None
    approved_at: datetime | None


class StudentExportOut(ApiModel):
    """Everything this establishment holds about one pupil, in one document.

    A parent may ask what is held; a school leaving Alppy has to be able to
    take it. Before this the only way out of the product was the destructive
    one, which is a poor answer to "what do you have on my child".

    Spans every year: the durable identity is `Person`, and `Student` is one
    year's enrolment record (0028). A pupil who repeats a year has two
    enrolments and one continuous record of evidence.

    Mastery snapshots are deliberately NOT here. They are recomputed from the
    attempts below — the score decays, so a snapshot is a photograph of a
    calculation and not an independent fact about the child. Exporting them
    would imply the school holds two things where it holds one.
    """

    generated_at: datetime
    person_id: uuid.UUID
    first_name: str | None
    last_name: str | None
    anonymised_at: datetime | None
    enrolments: list[ExportEnrolment] = []
    attempts: list[ExportAttempt] = []
    notes: list[ExportNote] = []


class SchoolYearOut(ApiModel):
    """One school year of this establishment.

    Every read in this API answers "now" unless told otherwise, which is fine
    until August. `label` is what a teacher recognises ("2026/27"); the two
    dates are what a query needs, and `is_current` is the one the screens
    default to. Without a route to list these there was no way to DISCOVER a
    year id, so `school_year_id` as a filter would have been unaskable
    (audit 02, C3).
    """

    id: uuid.UUID
    label: str
    starts_on: date
    ends_on: date
    is_current: bool


class ClassOut(ApiModel):
    id: uuid.UUID
    code: str
    label: str | None
    #: Which year's group this is. A class code is reused every August, so the
    #: code alone does not identify a group across years.
    school_year_id: uuid.UUID | None = None
    student_count: int = 0
    # The branches THIS CALLER takes here (D73). Not what the class studies —
    # the Branch nav must never render a branch the reader cannot open.
    subject_ids: list[uuid.UUID] = []
    # What the class STUDIES, the superset. Detail route only: branch
    # management is the one screen that needs it.
    declared_subject_ids: list[uuid.UUID] = []
    head_teacher_id: uuid.UUID | None = None
    is_head: bool = False
    # Detail route only — the list route would otherwise fan out one query
    # per class.
    teachers: list[ClassTeacherOut] = []


class SubjectCreate(BaseModel):
    """A new Branch. `key` is the join key, `labels` is what a teacher reads."""

    key: Annotated[str, Field(min_length=2, max_length=50)]
    labels: dict[str, str] = {}


class SubjectUpdate(BaseModel):
    """Only the labels. `key` is what `Competency.subject_key` matches on."""

    labels: dict[str, str]


class ChapterUpdate(BaseModel):
    labels: dict[str, str] | None = None
    position: int | None = None
    # What the Theme CREDITS (`chapter_competency`) — not where it SITS
    # (`primary_competency_id`, resolved per school, D56).
    competency_ids: list[uuid.UUID] | None = None


class ClassUpdate(BaseModel):
    label: str | None = None
    # Refused once the class has pupils: their UIDs were minted from it and
    # are printed (I-platform-09).
    code: Annotated[str, Field(min_length=2, max_length=10)] | None = None


class SchoolCreate(BaseModel):
    """A second establishment, created from the product rather than the seed.

    `default_curriculum` IS settable here and nowhere else: it is resolved into
    every `Chapter.primary_competency_id` the moment the school gets chapters
    (D56), so the one safe time to choose it is before any exist.
    """

    name: Annotated[str, Field(min_length=2, max_length=200)]
    canton: Annotated[str, Field(max_length=2)] | None = None
    default_curriculum: CurriculumKind = CurriculumKind.PER


class SchoolUpdate(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=200)] | None = None
    canton: Annotated[str, Field(max_length=2)] | None = None


class StudentUpdate(BaseModel):
    """Names only. `uid` and `number` are on paper."""

    first_name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    last_name: Annotated[str, Field(min_length=1, max_length=100)] | None = None


class SourceUpdate(BaseModel):
    title: Annotated[str, Field(max_length=200)] | None = None
    language: Annotated[str, Field(max_length=5)] | None = None
    publisher: Annotated[str, Field(max_length=200)] | None = None
    # Unvalidated beyond length on purpose: a teacher copying what is on the
    # cover of a cantonal workbook must not be told their ISBN is malformed.
    isbn: Annotated[str, Field(max_length=20)] | None = None
    url: Annotated[str, Field(max_length=500)] | None = None


class BranchOrder(BaseModel):
    """The class's Branch nav order, as one list.

    Whole-list rather than a move-to-index, because the order is a property of
    the class and a partial update from one co-teacher would silently renumber
    another's branches.
    """

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
    #: The single canonical parent this Theme hangs from in the navigation
    #: tree. NULL only on the per-subject `unfiled` bucket, which is what
    #: keeps it out of the tree and the roll-up.
    primary_competency_id: uuid.UUID | None = None


# ------------------------------------------------------------------ sources
class SourceOut(ApiModel):
    id: uuid.UUID
    # The Branch this book belongs to. Absent until now, which meant no client
    # could tell one branch's shelf from another's — the whole corpus read as
    # one undifferentiated pile.
    subject_id: uuid.UUID
    filename: str
    # What the teacher calls this book; `filename` is what they uploaded.
    title: str | None = None
    publisher: str | None = None
    isbn: str | None = None
    url: str | None = None
    content_type: str
    size_bytes: int
    language: str | None
    page_count: int | None
    status: JobStatus
    error: str | None = None
    notice: str | None = None
    exercise_count: int = 0
    section_count: int = 0
    created_at: datetime


class SourceSectionOut(ApiModel):
    """One chapter of the document, as the document declares it.

    Distinct from `ChapterOut`: that is the teacher's curriculum grouping and an
    exercise reaches one only by competency inference, so it is allowed to be
    null. This one is a fact about the file and is always set, which is why the
    builder filters on it first.
    """

    id: uuid.UUID
    title: str
    label: str | None = None
    page_from: int
    page_to: int
    position: int
    exercise_count: int = 0
    extracted_at: datetime | None = None
    extraction_notice: str | None = None

    @property
    def is_extracted(self) -> bool:
        return self.extracted_at is not None


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
    source_section_id: uuid.UUID | None = None
    source_page: int | None = None
    # The book's own code and title ("NO64", "Les quatre multiplications"),
    # and a picture of the exercise as the page prints it. All three are
    # null for anything a model or a teacher wrote.
    label: str | None = None
    title: str | None = None
    figure_url: str | None = None
    figure_width_mm: float | None = None
    figure_height_mm: float | None = None
    approved_at: datetime | None = None

    @property
    def is_ai_generated(self) -> bool:
        return self.origin is ExerciseOrigin.AI_GENERATED


class ExerciseUpdate(BaseModel):
    """A correction to an extracted or generated exercise.

    Every field a teacher may rewrite carries the same bound its `ExerciseCreate`
    counterpart carries. An edit is not a lesser write than a creation: the row it
    lands in is the row the sheet renderer paginates and the printed grid draws its
    bubbles from, so a statement PATCH may not smuggle in what POST would refuse.
    """

    statement: Annotated[str, Field(min_length=1, max_length=4000)] | None = None
    options: Annotated[list[str], Field(max_length=MAX_MCQ_OPTIONS)] | None = None
    answer_index: int | None = None
    # `answer_bool` and `answer_text` were missing, so a true/false answer and an
    # open question's expected answer — the thing the answer key prints — could
    # be written by extraction and never corrected by the teacher who spotted it.
    answer_bool: bool | None = None
    answer_text: str | None = None
    explanation: str | None = None
    difficulty: Annotated[int, Field(ge=1, le=5)] | None = None
    approved: bool | None = None

    # `type` is deliberately absent. Changing it would leave the answer fields
    # describing a different kind of question (an MCQ keeping `answer_bool`, an
    # open item keeping four options), and the printed grid draws its bubbles
    # from the type. Delete and re-add instead.


class ExerciseCreate(BaseModel):
    """An exercise the teacher wrote in the sheet builder.

    Lands as `ExerciseOrigin.TEACHER`: not a transcription, so it carries no
    source or page, and not a model's proposal, so it wears no accent and needs
    no approval. The teacher approved it by writing it.
    """

    subject_id: uuid.UUID
    type: ExerciseType
    language: Locale
    statement: Annotated[str, Field(min_length=1, max_length=4000)]
    options: Annotated[list[str], Field(max_length=MAX_MCQ_OPTIONS)] | None = None
    answer_index: int | None = None
    answer_bool: bool | None = None
    answer_text: str | None = None
    explanation: str | None = None
    difficulty: Annotated[int, Field(ge=1, le=5)] = 3
    chapter_id: uuid.UUID | None = None
    competency_ids: Annotated[list[uuid.UUID], Field(max_length=10)] = []

    @field_validator("options")
    @classmethod
    def _trim_options(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [o.strip() for o in value if o and o.strip()]
        return cleaned or None

    @model_validator(mode="after")
    def _answer_matches_type(self) -> ExerciseCreate:
        """Reject an answer that does not fit the type, rather than coercing it.

        A silently dropped answer is a sheet whose key is blank for that item,
        discovered by the teacher at the photocopier. `MAX_MCQ_OPTIONS` mirrors
        `sheets.layout.MAX_OPTIONS`: a fifth option would key the answer to a
        bubble that is not printed on the paper.
        """
        if self.type is ExerciseType.MCQ:
            if not self.options or len(self.options) < 2:
                raise ValueError("a multiple-choice exercise needs at least two answers")
            if self.answer_index is None:
                raise ValueError("a multiple-choice exercise needs a correct answer")
            if not 0 <= self.answer_index < len(self.options):
                raise ValueError("the correct answer must be one of the options")
            self.answer_bool = None
        elif self.type is ExerciseType.TRUE_FALSE:
            if self.answer_bool is None:
                raise ValueError("a true/false exercise needs a correct answer")
            self.options, self.answer_index = None, None
        else:  # open — printable, never auto-graded (D13)
            self.options, self.answer_index, self.answer_bool = None, None, None
        return self


class ExerciseFacets(ApiModel):
    """Counts for the filter chips, computed over the *unfiltered-by-type* set.

    The chips have to show what selecting them would give, so these are counted
    with every filter applied except the one each chip controls. A chip reading
    "QCM · 0" is useful; a chip that silently yields nothing is not.
    """

    total: int = 0
    mcq: int = 0
    true_false: int = 0
    open: int = 0


class DetectionListOut(ApiModel):
    """One page of readings from a scanned pile.

    A pile is one page per pupil per sheet page, and each page carries one
    detection per item — twenty-eight copies of a twelve-item sheet is 336
    rows, each with its fill ratios, its bubble boxes and a presigned crop
    URL. The review screen reads them all at once and re-reads them on every
    correction (audit 02, M4).
    """

    items: list[DetectionOut] = []
    total: int = 0
    offset: int = 0
    limit: int = 0


class CompetencyListOut(ApiModel):
    """One page of the curriculum.

    Small today because the seeded PER tree is two levels deep and invented;
    the real one is five levels and a few thousand nodes, and this route is
    what a picker calls (database audit H1).
    """

    items: list[CompetencyOut] = []
    total: int = 0
    offset: int = 0
    limit: int = 0


class ExerciseListOut(ApiModel):
    """One page of exercises.

    `GET /sources/{id}/exercises` used to return every row of a document in a
    single unpaginated array — fine for a 40-exercise worksheet, roughly two
    megabytes of JSON for a textbook, through a Worker proxy, into a list of a
    thousand React rows. Filtering and paging both happen in Postgres now.
    """

    items: list[ExerciseOut] = []
    total: int = 0
    offset: int = 0
    limit: int = 0
    facets: ExerciseFacets = ExerciseFacets()


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
    # The written-answer box under an open item: height in 8 mm lines, any
    # number up to the tallest a page can carry (the builder offers presets as
    # shortcuts), and what is printed inside. Ignored on a bubble item. None
    # means the default; 0 prints no box.
    answer_box_lines: Annotated[int, Field(ge=0, le=ANSWER_BOX_MAX_LINES)] | None = None
    answer_box_fill: AnswerBoxFill | None = None
    # The expected answer for this printing of an open item, optional. Blank
    # or absent means "use the exercise's own answer if it has one, otherwise
    # let the grader work it out". Ignored on a bubble item.
    expected_answer: Annotated[str, Field(max_length=4000)] | None = None
    # This item's own barème. None means "use the sheet's default". Unlike the
    # box and the expected answer, these are NOT ignored on a bubble item — a
    # point value means something on every type, and an `open` item becomes
    # auto-gradeable the moment a vision verdict lands.
    points_correct: Annotated[float, Field(ge=0, le=MAX_ITEM_POINTS)] | None = None
    #: The penalty as a magnitude; the grader applies the sign.
    points_penalty: Annotated[float, Field(ge=0, le=MAX_ITEM_POINTS)] | None = None

    @field_validator("expected_answer")
    @classmethod
    def _trim_expected_answer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class SheetCreate(BaseModel):
    class_id: uuid.UUID
    subject_id: uuid.UUID
    #: The Theme to file this sheet under. Optional at the boundary even though
    #: the column is NOT NULL: omitting it means "not filed yet", and the
    #: service falls back to the subject's `unfiled` chapter rather than
    #: guessing one from the items.
    chapter_id: uuid.UUID | None = None
    title: Annotated[str, Field(min_length=1, max_length=200)]
    language: Locale
    target: SheetTarget = SheetTarget.CLASS
    intent: str | None = None
    items: Annotated[list[SheetItemIn], Field(min_length=1, max_length=64)]
    #: The barème every item falls back to when it sets none of its own.
    default_points_correct: Annotated[float, Field(ge=0, le=MAX_ITEM_POINTS)] = (
        DEFAULT_POINTS_CORRECT
    )
    default_points_penalty: Annotated[float, Field(ge=0, le=MAX_ITEM_POINTS)] = (
        DEFAULT_POINTS_PENALTY
    )


class SheetUpdate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    #: Re-filing a sheet under the right Theme. Needed in practice the moment
    #: the hierarchy ships, when every existing sheet is `unfiled`.
    chapter_id: uuid.UUID | None = None
    #: Capped like `SheetCreate.items`. PATCH replaces the whole list, so an
    #: unbounded one let a caller put a thousand items on a sheet that POST
    #: would have refused at sixty-four — through the same renderer, which
    #: measures every answer box in Chromium.
    #:
    #: No lower bound, deliberately, where POST has one: emptying a sheet is
    #: how a teacher clears a draft, and the render route already refuses to
    #: print one. Refusing the edit as well would make that state unreachable
    #: and break the composer.
    items: Annotated[list[SheetItemIn], Field(max_length=64)] | None = None
    default_points_correct: Annotated[float, Field(ge=0, le=MAX_ITEM_POINTS)] | None = None
    default_points_penalty: Annotated[float, Field(ge=0, le=MAX_ITEM_POINTS)] | None = None


class SheetDraftPreview(BaseModel):
    """A sheet that does not exist yet, rendered so the teacher can see it.

    The builder needs a preview while the teacher is still reordering, and the
    two obvious ways to get one are both wrong. Redrawing the page in React
    duplicates the millimetre geometry that `sheets.layout` owns and that the
    scan detector reads — the previous hand-rolled attempt put the bubbles
    inline instead of on the fixed grid and printed A/B/C/D where the sheet
    prints V/F. Creating a real draft `Sheet` and PATCHing it writes a row plus
    one `SheetInstance` per student on every keystroke, and leaves a junk sheet
    behind whenever the teacher walks away.

    So the draft is posted and rendered, never stored. The response is the same
    markup `GET /sheets/{id}/preview` returns, from the same `SheetData`.
    """

    class_id: uuid.UUID
    subject_id: uuid.UUID
    title: Annotated[str, Field(max_length=200)] = ""
    language: Locale
    items: Annotated[list[SheetItemIn], Field(max_length=64)]
    default_points_correct: Annotated[float, Field(ge=0, le=MAX_ITEM_POINTS)] = (
        DEFAULT_POINTS_CORRECT
    )
    default_points_penalty: Annotated[float, Field(ge=0, le=MAX_ITEM_POINTS)] = (
        DEFAULT_POINTS_PENALTY
    )


class SheetItemOut(ApiModel):
    id: uuid.UUID
    position: int
    statement_override: str | None
    answer_box_lines: int | None = None
    answer_box_fill: AnswerBoxFill | None = None
    expected_answer: str | None = None
    points_correct: float | None = None
    points_penalty: float | None = None
    exercise: ExerciseOut


class SheetInstanceOut(ApiModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_uid: str
    page_count: int | None = None
    #: "Groupe 2 · Fractions équivalentes", printed on this copy.
    group_label: str | None = None
    #: Whether this copy has an approved feedback page in the third document.
    has_feedback: bool = False
    #: Points earned so far, floored at zero, or None when nothing is graded
    #: yet. A per-item score stays signed in the record; only the total floors.
    points_earned: float | None = None
    #: What this copy's own item list is worth in total.
    points_possible: float = 0.0


class SheetOut(ApiModel):
    id: uuid.UUID
    class_id: uuid.UUID
    subject_id: uuid.UUID
    #: Required, mirroring the NOT NULL column. Every sheet has a home.
    chapter_id: uuid.UUID
    title: str
    target: SheetTarget
    language: str
    intent: str | None
    layout_version: str
    default_points_correct: float = DEFAULT_POINTS_CORRECT
    default_points_penalty: float = DEFAULT_POINTS_PENALTY
    items: list[SheetItemOut] = []
    instances: list[SheetInstanceOut] = []
    blank_pdf_url: str | None = None
    answer_key_pdf_url: str | None = None
    #: The per-student feedback pages, as their own document.
    feedback_pdf_url: str | None = None
    #: The common sheet whose corrected results produced this one.
    derived_from_id: uuid.UUID | None = None
    #: Every sheet whose corrected results justified this one, principal
    #: first. `derived_from_id` is entry 0; the rest are the further evidence
    #: the teacher named (D70). Empty on a sheet that answers nothing.
    source_sheet_ids: list[uuid.UUID] = []
    #: The piles photographed against this sheet. There is no `CorrectedSheet`
    #: entity: a corrected sheet IS the confirmed scan plus the attempts it
    #: wrote, so this is the route from a sheet to its corrections.
    scans: list[SheetScanOut] = []
    #: The Competences and Themes this sheet's ITEMS touch — derived from
    #: `SheetItem -> Exercise`, never stored, so they cannot drift from the
    #: items they describe. Distinct from `chapter_id`, which is the one home
    #: Theme the teacher stated (I-sheets-11).
    competency_ids: list[uuid.UUID] = []
    chapter_ids: list[uuid.UUID] = []
    rendered_at: datetime | None = None
    #: When it went to the photocopier. Null means "not yet", and is a
    #: different fact from `rendered_at` being null.
    printed_at: datetime | None = None
    created_at: datetime


# -------------------------------------------------------------------- scans
class DetectionOut(ApiModel):
    id: uuid.UUID
    item_index: int
    sheet_item_id: uuid.UUID | None
    exercise_id: uuid.UUID | None = None
    detected_index: int | None
    detected_bool: bool | None
    confidence: float
    outcome: DetectionOutcome
    fill_ratios: list[float] | None = None
    bubble_boxes: list[dict[str, float]] | None = None
    corrected_at: datetime | None = None
    # What the machine read, kept beside the teacher's override rather than
    # under it, so the review UI can show what was disagreed with.
    machine_index: int | None = None
    machine_outcome: DetectionOutcome | None = None
    machine_confidence: float | None = None
    # The question this reading is graded against, so the teacher reviewing a
    # low-confidence mark can see what was asked instead of a bare "#7".
    number: int | None = None
    statement: str | None = None
    options: list[str] | None = None
    option_letters: str | None = None
    exercise_type: ExerciseType | None = None
    ai_generated: bool = False
    # The correct option, as an index into option_letters. The teacher is
    # adjudicating what the machine read, and "is that what they meant" is a
    # different question from "were they right" — but both are asked of the
    # same row, and the key is already on the answer-key sheet in their hand.
    answer_index: int | None = None
    # A written answer: the box cut from the page, what was read in it, and
    # the verdict — current beside machine, as for the bubbles.
    crop_url: str | None = None
    transcription: str | None = None
    verdict_correct: bool | None = None
    machine_transcription: str | None = None
    machine_verdict_correct: bool | None = None
    vision_model: str | None = None
    answer_text: str | None = None
    # What the machine judged against when no expected answer existed: the
    # answer it worked out itself. Null when the teacher's answer was used.
    reference_answer: str | None = None


class DetectionCorrection(BaseModel):
    """A teacher overriding the machine. Always allowed, always recorded.

    ``le=3`` is the layout's hard ceiling (``MAX_OPTIONS``); the item's own
    option count is checked in the service, which is the only place that knows
    it — a two-bubble true/false item must not accept option 3.

    For a written answer the correction is a verdict and/or a transcription.
    Sending ``verdict_correct: null`` explicitly means "I cannot tell either";
    leaving it out keeps the verdict as it was.
    """

    detected_index: Annotated[int, Field(ge=0, le=3)] | None = None
    verdict_correct: bool | None = None
    transcription: Annotated[str, Field(max_length=4000)] | None = None


class ScanPageOut(ApiModel):
    id: uuid.UUID
    page_index: int
    image_url: str | None = None
    registered: bool
    detected_uid: str | None
    uid_confidence: float | None
    student_id: uuid.UUID | None
    sheet_instance_id: uuid.UUID | None
    # Why this page is not simply one of the copies: it belongs to another
    # class, or the teacher took it out of the pile. Both are shown, and
    # neither blocks confirmation.
    wrong_class: bool = False
    discarded: bool = False
    page_in_copy: int | None = None
    registration_error: str | None = None
    detections: list[DetectionOut] = []


class ScanPageDiscard(BaseModel):
    """Take a page out of the pile, or put it back."""

    discarded: bool = True


class ScanPageAssign(BaseModel):
    """Manual fallback when the printed UID could not be read."""

    student_id: uuid.UUID

    
class SheetScanOut(ApiModel):
    """One pile photographed against a sheet, as the sheet lists it.

    Deliberately not `ScanOut`: that carries every page and every detection,
    and a sheet showing four scans would ship four page lists nobody asked for.
    What a sheet needs is a route back to its corrections and the one word that
    says where each pile got to.
    """

    id: uuid.UUID
    status: ScanStatus
    #: Signed off, reopened, signed off again (D48).
    revised: bool = False
    confirmed_at: datetime | None = None
    reopened_at: datetime | None = None
    created_at: datetime


class ScanOut(ApiModel):
    id: uuid.UUID
    sheet_id: uuid.UUID | None
    original_filename: str
    status: ScanStatus
    error: str | None = None
    # The job registering and detecting this pile. Returned on upload so the
    # review screen can poll it for real per-page progress rather than showing
    # a still-processing scan as a finished empty one.
    job_id: uuid.UUID | None = None
    pages: list[ScanPageOut] = []
    # The confirmation history, as three derived facts rather than a fourth
    # status. `status` still answers "is this pile signed off?"; these answer
    # "has it been signed off before, and was it taken back?" (D48).
    #: Signed off, then reopened, then signed off again.
    revised: bool = False
    #: Non-null once the pile has been reopened at least once, whatever its
    #: status is now.
    reopened_at: datetime | None = None
    confirmed_at: datetime | None = None
    created_at: datetime


class StudentPointsOut(ApiModel):
    """One student's marks. Field names match ``SheetInstanceOut`` on purpose:
    the same two numbers, aggregated one level up."""

    student_id: uuid.UUID
    #: null when nothing has been graded — never rendered as a zero.
    points_earned: float | None = None
    points_possible: float = 0.0


class ClassSheetPointsOut(ApiModel):
    sheet_id: uuid.UUID
    sheet_title: str
    #: Mean of each graded copy's ratio, 0..1. null when no copy is graded.
    average_ratio: float | None = None
    students: list[StudentPointsOut] = []


class ClassPointsOut(ApiModel):
    class_id: uuid.UUID
    #: Totals across every sheet in scope.
    students: list[StudentPointsOut] = []
    sheets: list[ClassSheetPointsOut] = []


class ItemConfidenceOut(ApiModel):
    """How one printed item was read across the class's copies."""

    sheet_item_id: uuid.UUID | None = None
    exercise_id: uuid.UUID | None = None
    number: int | None = None
    statement: str | None = None
    copies_read: int = 0
    low_confidence: int = 0
    ambiguous: int = 0
    corrected: int = 0


class SheetConfidenceOut(ApiModel):
    sheet_id: uuid.UUID
    items: list[ItemConfidenceOut] = []


class StudentSheetItemOut(ApiModel):
    """One question, as one student answered it."""

    position: int
    number: int | None = None
    exercise_id: uuid.UUID
    statement: str
    exercise_type: ExerciseType
    #: Wears the mandarin accent in the breakdown: an AI-written item is the one
    #: to read twice before trusting the mark.
    ai_generated: bool = False
    options: list[str] = []
    #: Already readable: "B. 2/3", "Vrai", or the transcription.
    given: str | None = None
    given_index: int | None = None
    expected: str | None = None
    expected_index: int | None = None
    outcome: DetectionOutcome | None = None
    confidence: float | None = None
    #: null when the item produced no attempt — not the same as wrong.
    correct: bool | None = None
    #: null when ungraded. Never rendered as a zero.
    points_earned: float | None = None
    points_possible: float = 0.0
    crop_url: str | None = None


class StudentSheetOut(ApiModel):
    student: StudentOut
    sheet_id: uuid.UUID
    sheet_title: str
    scan_id: uuid.UUID | None = None
    answered_at: datetime | None = None
    points_earned: float | None = None
    points_possible: float = 0.0
    items: list[StudentSheetItemOut] = []


class ScanUnvalidateResponse(ApiModel):
    """What reopening a pile withdrew, and what it put back."""

    attempts_removed: int
    #: Recomputed from an older pile that is still confirmed. The difference
    #: between removed and rederived is the number of items that now have no
    #: grade at all — which is not the same as a zero.
    attempts_rederived: int
    students_affected: int
    competencies_updated: int


class ScanConfirmResponse(ApiModel):
    attempts_created: int
    students_affected: int
    competencies_updated: int
    # A re-scan of the same pile corrects the record rather than doubling it.
    attempts_superseded: int = 0
    # Items that went in on paper and produced no attempt: two bubbles filled,
    # or free text. Counted rather than dropped in silence.
    items_skipped: int = 0


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


# ------------------------------------------------- the curriculum tree
class TreeMasteryOut(ApiModel):
    """A rolled-up band. The SAME five bands as a matrix cell, deliberately.

    ``roll_up_mastery`` returns a ``MasteryResult`` through the same
    ``band_for`` thresholds, so a Theme or a Branch needs no new colour, no new
    label set and no second reading of DC-colour-08 — the shipped band tokens,
    glyphs and written labels already cover it.

    Two fields do NOT mean at this level what they mean on a cell, and the
    difference is documented in docs/mastery-model.md §6 rather than papered
    over: ``score`` is a weighted mean of the children's already-decayed
    scores, so it is NOT ``accuracy * recency`` here; ``days_until_review`` is
    the earliest of the children's, not a re-derivation.
    """

    score: float
    band: MasteryBand
    attempts_count: int
    provisional: bool
    #: Assessed children over total children — the coverage behind the band.
    #: A Theme can read "acquis" on one competency while two others were never
    #: examined, and the band alone cannot say so.
    assessed_count: int = 0
    child_count: int = 0
    #: The worst band among the assessed children, so a strong aggregate can
    #: still show what is weakest inside it.
    weakest_band: MasteryBand | None = None
    days_until_review: int | None = None
    last_attempt_at: datetime | None = None


class TreeThemeOut(ApiModel):
    chapter_id: uuid.UUID
    key: str
    labels: LocalisedText
    position: int
    sheet_count: int
    #: Every competency this Theme credits — the tagging set, not just the
    #: primary. A student profile groups its competency rows by looking each
    #: one up here, and an exercise legitimately carries a code from the other
    #: curriculum, so the narrower set would drop rows on the floor.
    competency_ids: list[uuid.UUID] = []
    mastery: TreeMasteryOut


class TreeCompetenceOut(ApiModel):
    competency_id: uuid.UUID
    code: str
    labels: LocalisedText
    mastery: TreeMasteryOut
    themes: list[TreeThemeOut] = []


class TreeBranchOut(ApiModel):
    subject_id: uuid.UUID
    subject_key: str
    labels: LocalisedText
    mastery: TreeMasteryOut
    competences: list[TreeCompetenceOut] = []
    #: Sheets filed under this subject's `unfiled` chapter. Never rolled into
    #: `mastery` above, surfaced so the teacher can still find them.
    unfiled_sheet_count: int = 0
    #: Exercises in this Branch that carry NO chapter at all. Distinct from
    #: `unfiled_sheet_count`: that counts sheets nobody filed, this counts
    #: corpus rows the ingest could not tag. The builder needs it to render a
    #: counted "Sans thème" bucket, which is what keeps every exercise
    #: reachable now that Theme is the picker's root.
    unfiled_exercise_count: int = 0


class SheetStudentMastery(ApiModel):
    """One student's band on one sheet."""

    student_id: uuid.UUID
    mastery: TreeMasteryOut


class SheetMasteryOut(ApiModel):
    """How a class did on one sheet, in the product's own five bands.

    `TreeMasteryOut`, not a new shape: a sheet band is the same kind of
    aggregate as a Theme band and carries the same coverage, so it reads and
    prints through the components that already exist (DC-content-07).

    `overall` pools the students the way `pool_by_competency` does — across
    pupils, which is sound — and never across competencies, which is not
    (I-mastery-10).
    """

    sheet_id: uuid.UUID
    competency_ids: list[uuid.UUID] = []
    students: list[SheetStudentMastery] = []
    overall: TreeMasteryOut
    computed_at: datetime


class ClassTreeOut(ApiModel):
    class_id: uuid.UUID
    branches: list[TreeBranchOut] = []
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


class SheetTaken(ApiModel):
    """One sheet a student actually sat, newest first on the profile.

    ``scan_id`` is the pile the marks were read from, so the teacher can get
    from "she did badly here" back to the photograph of her copy in one click.
    """

    sheet_id: uuid.UUID
    title: str
    answered_at: datetime
    attempts_count: int
    correct_count: int
    scan_id: uuid.UUID | None = None
    #: The Theme the sheet is FILED under (`Sheet.chapter_id`) — the one the
    #: teacher stated, not one inferred from the items. The profile groups by
    #: it, so a term reads as a few teaching units rather than a flat list.
    chapter_id: uuid.UUID | None = None
    #: This pupil's band ON THIS SHEET: a roll-up of the sheet's competencies,
    #: never a mean of its items (I-mastery-11). Carried here rather than
    #: fetched per sheet, which would be one request per row.
    mastery: TreeMasteryOut | None = None


class AttemptOut(ApiModel):
    """One graded item behind a matrix cell, with its provenance.

    This is the bottom of the drill-down: a teacher who disagrees with a band
    follows it to the individual answers, and from any answer back to the sheet
    it was printed on and the scan it was read from.
    """

    id: uuid.UUID
    exercise_id: uuid.UUID
    statement: str
    # Marks the item with the mandarin accent in the drill-down: an AI-written
    # exercise is the one a teacher should read twice before trusting the mark.
    origin: ExerciseOrigin
    correct: bool
    difficulty: int
    answered_at: datetime
    sheet_id: uuid.UUID | None = None
    sheet_title: str | None = None
    scan_id: uuid.UUID | None = None
    # The teacher overrode the scanner's reading of this item during review.
    corrected: bool = False


class CompetencyAttemptsOut(ApiModel):
    """The drill-down payload for one (student, competency) cell."""

    student: StudentOut
    competency: CompetencyOut
    score: float
    band: MasteryBand
    provisional: bool
    days_until_review: int | None = None
    attempts: list[AttemptOut] = []


class StudentProfileOut(ApiModel):
    student: StudentOut
    overall_score: float
    strengths: list[CompetencyMastery] = []
    gaps: list[CompetencyMastery] = []
    all_competencies: list[CompetencyMastery] = []
    sheets_taken: int = 0
    sheets: list[SheetTaken] = []


# ----------------------------------------------------------------- adaptive
class AdaptiveProposeRequest(BaseModel):
    class_id: uuid.UUID
    subject_id: uuid.UUID
    student_ids: Annotated[list[uuid.UUID], Field(max_length=40)] = []
    items_per_student: Annotated[int, Field(ge=1, le=16)] = 8
    allow_generation: bool = True
    #: An explicit teacher override. Normally absent: the language of a sheet
    #: follows the source material, not the UI locale, and the server reads it
    #: off the corpus.
    language: Locale | None = None
    #: One shared sheet for the selected students, targeting the union of their
    #: gaps, instead of one sheet each. Kept for the single-group path;
    #: `n_groups` supersedes it and wins when both are given.
    group: bool = False
    #: How many personalised group sheets to build. 1 is one shared sheet for
    #: the whole selection; a value at or above the class size is one sheet per
    #: student. Absent means the per-student path, unchanged.
    n_groups: Annotated[int | None, Field(ge=1, le=40)] = None
    #: The COMMON sheet whose corrected results justify this batch. Recorded on
    #: the sheet as lineage, the sheet feedback is read from — and, when it has
    #: confirmed results, the evidence the plans target.
    source_sheet_id: uuid.UUID | None = None
    #: Ask a model to revise the deterministic partition. Off by default: the
    #: deterministic rule is the one a teacher can state to a parent (D33), and
    #: an invalid or failed model answer falls straight back to it.
    llm_grouping: bool = False


#: Which evidence chose this plan's competencies. Reported because the teacher
#: has to be able to defend the sheet, and "we targeted the sheet you just
#: corrected" and "we targeted the term so far" are different answers.
TargetingBasis = Literal["source_sheet", "mastery", "diagnostic"]


class AdaptiveStudentPlan(ApiModel):
    student_id: uuid.UUID
    student_uid: str
    targeted_competency_ids: list[uuid.UUID]
    #: Where the gaps came from. `diagnostic` means there was no evidence at all
    #: and the plan is a probe, not a diagnosis.
    targeting_basis: TargetingBasis = "mastery"
    #: True when the source sheet was only partly read back — some copies not
    #: scanned, some answers blank or ungraded, some items tagged to no
    #: competency. The plan still stands; it is just built on less than it looks.
    evidence_partial: bool = False
    retrieved: list[ExerciseProposal] = []
    generated: list[ExerciseProposal] = []
    #: Which personalised group this student's copy belongs to, printed on the
    #: page. Absent on the per-student path, where there is no group.
    group_label: str | None = None
    group_index: int | None = None
    #: The teacher may move a student between groups before exporting; the
    #: batch request carries the result, so this is what it edits.
    feedback_id: uuid.UUID | None = None

    @property
    def total_items(self) -> int:
        return len(self.retrieved) + len(self.generated)


class AdaptiveGroupItem(ApiModel):
    """Which students in the group a shared item is actually for."""

    exercise_id: uuid.UUID
    for_student_uids: list[str] = []


class AdaptiveGroupPlan(ApiModel):
    """One item list shared by several students with overlapping gaps."""

    #: "Groupe 2 · Fractions équivalentes". Printed on every copy in the group.
    label: str = ""
    index: int = 1
    student_ids: list[uuid.UUID] = []
    student_uids: list[str] = []
    targeted_competency_ids: list[uuid.UUID] = []
    retrieved: list[ExerciseProposal] = []
    generated: list[ExerciseProposal] = []
    items: list[AdaptiveGroupItem] = []


class AdaptiveGenerationFailure(ApiModel):
    """Generation could not fill a student's sheet, and why.

    A shorter sheet with no explanation is the failure a teacher cannot act on:
    they count fifteen items where they asked for sixteen and have no way to
    tell whether the corpus ran out or the provider fell over.
    """

    student_id: uuid.UUID
    student_uid: str
    #: `provider_error` | `unparsable_response` | `pii_gate` | `incomplete`
    #: | `truncated` (the answer hit the output-token cap — a configuration
    #: cause, which `unparsable_response` would have hidden)
    reason: str
    requested: int
    produced: int = 0
    detail: str | None = None


class AdaptiveProposeResponse(ApiModel):
    plans: list[AdaptiveStudentPlan]
    #: True when a model's partition was accepted. False covers both "not asked
    #: for" and "asked for and rejected", so the screen can say which rule the
    #: groups on it came from.
    grouped_by_model: bool = False
    language: str
    generated_count: int = 0
    needs_approval: bool = True
    #: The single-group path. Kept so the existing screen keeps working.
    group: AdaptiveGroupPlan | None = None
    #: The N-group path. One entry per personalised group, worst first.
    groups: list[AdaptiveGroupPlan] = []
    failures: list[AdaptiveGenerationFailure] = []


class AdaptiveApproveRequest(BaseModel):
    """The only way an AI-generated item becomes printable."""

    exercise_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=400)]


class AdaptiveApproveResponse(ApiModel):
    approved: int
    exercise_ids: list[uuid.UUID] = []


class AdaptiveDiscardRequest(BaseModel):
    exercise_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=400)]


class AdaptiveDiscardResponse(ApiModel):
    discarded: int
    exercise_ids: list[uuid.UUID] = []


class AdaptiveRegenerateRequest(BaseModel):
    exercise_id: uuid.UUID


class AdaptiveRegenerateResponse(ApiModel):
    """The replacement, plus the id it replaced so the UI can swap in place."""

    replaced_exercise_id: uuid.UUID
    proposal: ExerciseProposal


class AdaptiveBatchRequest(BaseModel):
    class_id: uuid.UUID
    subject_id: uuid.UUID
    title: Annotated[str, Field(min_length=1, max_length=200)]
    language: Locale
    #: One plan per pupil, so the bound is a class. Forty is roughly twice
    #: the largest Sek I group, and well under what the batched generator
    #: can be asked for in one call without a provider timing out.
    plans: Annotated[list[AdaptiveStudentPlan], Field(max_length=40)]
    #: The common sheet this batch answers. Stored as `Sheet.derived_from_id`,
    #: which is what makes a teaching unit a chain rather than two loose rows.
    #: When `source_sheet_ids` is given this is its first entry — the two are
    #: one fact reached two ways (D70).
    source_sheet_id: uuid.UUID | None = None
    #: Every sheet whose corrected results justified this batch, principal
    #: first. A reprise may answer a test *and* the worksheets whose gaps it
    #: revisits; `source_sheet_id` alone could only name one of them.
    source_sheet_ids: list[uuid.UUID] | None = None
    #: How many groups the plans were built from. >1 marks the sheet
    #: `SheetTarget.GROUP`, which has been in the enum unused since 0001.
    group_count: int | None = None

    def resolved_source_ids(self) -> list[uuid.UUID]:
        """The lineage, de-duplicated, principal first.

        Accepts either field so an older client keeps working: `source_sheet_id`
        is the principal, and is prepended when the caller sent only it.
        """
        ids = list(self.source_sheet_ids or [])
        if self.source_sheet_id is not None and self.source_sheet_id not in ids:
            ids.insert(0, self.source_sheet_id)
        seen: list[uuid.UUID] = []
        for sid in ids:
            if sid not in seen:
                seen.append(sid)
        return seen


# ------------------------------------------------------- misconception notes
class MisconceptionNoteOut(ApiModel):
    """One student's feedback, as the teacher reviews it before it prints."""

    id: uuid.UUID
    student_id: uuid.UUID
    student_uid: str = ""
    subject_id: uuid.UUID
    based_on_sheet_id: uuid.UUID | None = None
    language: str
    notes: list[str] = []
    competency_ids: list[uuid.UUID] = []
    approved_at: datetime | None = None
    created_at: datetime


class FeedbackApproveRequest(BaseModel):
    """The only way a generated note becomes printable."""

    feedback_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=400)]


class FeedbackApproveResponse(ApiModel):
    approved: int
    feedback_ids: list[uuid.UUID] = []


class FeedbackDiscardRequest(BaseModel):
    feedback_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=400)]


class FeedbackDiscardResponse(ApiModel):
    discarded: int
    feedback_ids: list[uuid.UUID] = []


class FeedbackGenerateRequest(BaseModel):
    """Start the per-student feedback job for one corrected common sheet."""

    class_id: uuid.UUID
    subject_id: uuid.UUID
    source_sheet_id: uuid.UUID
    language: Locale | None = None


# ----------------------------------------------------------------- timeline
class TimelineEventOut(ApiModel):
    """One line of the agenda.

    ``title`` is resolved from the row the event points at when it still
    exists, and falls back to the stored ``summary`` when it does not — an
    event outlives its subject, because deleting a sheet does not un-print it.
    """

    id: uuid.UUID
    kind: EventKind
    occurred_at: datetime
    subject_type: EventSubject
    subject_id: uuid.UUID
    title: str
    class_id: uuid.UUID | None = None
    class_code: str | None = None
    subject_area_id: uuid.UUID | None = None
    detail: dict[str, Any] = {}
    #: False when the row the event describes has since been deleted, so the
    #: agenda can show the line without offering a link that 404s.
    resolved: bool = True


class TimelineFacets(ApiModel):
    """How many events each kind would give under the CURRENT filters.

    Computed with every filter except the kind filter itself: a chip has to
    report what selecting it would give, not what is already selected.
    """

    by_kind: dict[str, int] = {}


class TimelineOut(ApiModel):
    items: list[TimelineEventOut] = []
    total: int = 0
    offset: int = 0
    limit: int = 0
    facets: TimelineFacets = TimelineFacets()


# --------------------------------------------------------------------- jobs
class JobOut(ApiModel):
    id: uuid.UUID
    kind: JobKind
    status: JobStatus
    progress: float
    message: str | None = None
    result: dict[str, Any] | None = None
    #: A code from ``services.job_failure.FAILURE_CODES``, never an exception's
    #: own text: this field is polled by the browser for the length of every
    #: extraction. The diagnostic is in the worker log.
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
