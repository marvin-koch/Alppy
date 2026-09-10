"""Domain enumerations shared by models, schemas and the grading pipeline."""

from __future__ import annotations

from enum import StrEnum


class Locale(StrEnum):
    FR = "fr"
    DE = "de"
    EN = "en"


class ClassKind(StrEnum):
    """Which of the two things a ``Class`` row is.

    Both are classes and both hold a roster; the difference is what the roster
    *means*. A homeroom is the group a pupil BELONGS to — the one that minted
    their UID, whose maître de classe is accountable for them. A course group
    is one they are TAUGHT in: usually one branch, usually assembled across
    several homerooms (a Vaud niveau-2 maths group, a support group).

    NULL — not a member of this enum — is the third state and the default: the
    school has not declared. It is not a synonym for ``HOMEROOM``, and 0026
    says why.
    """

    HOMEROOM = "homeroom"
    COURSE = "course"


class CurriculumKind(StrEnum):
    """Both Swiss curricula are first-class; neither is the default."""

    LP21 = "LP21"  # German-speaking cantons
    PER = "PER"  # Plan d'etudes romand


class ExerciseType(StrEnum):
    MCQ = "mcq"
    TRUE_FALSE = "true_false"
    OPEN = "open"  # printable, never auto-graded in the MVP

    @property
    def is_auto_gradable(self) -> bool:
        return self is not ExerciseType.OPEN


class ExerciseOrigin(StrEnum):
    TEXTBOOK = "textbook"
    AI_GENERATED = "ai_generated"  # the one feature wearing the mandarin accent
    TEACHER = "teacher"
    """Written by the teacher in the sheet builder.

    Neither a transcription nor a proposal, so it is neither of the other two.
    Filing it under ``TEXTBOOK`` would claim a provenance it does not have — a
    source filename and a page the teacher could check against the book on the
    desk — and filing it under ``AI_GENERATED`` would put the mandarin accent on
    a sentence a human wrote, which is the one thing that accent must never
    mean. It needs no approval gate: the teacher approved it by writing it."""


class AnswerBoxFill(StrEnum):
    """What is printed inside a written-answer box, under the student's ink.

    Every fill prints lighter than pen so the crop step can suppress it by
    luminance; the border and the corner ticks are removed by geometry."""

    LINED = "lined"  # a guide line every 8 mm
    GRID = "grid"  # the 5 mm square of a Swiss maths notebook
    BLANK = "blank"  # nothing but the border


class SheetTarget(StrEnum):
    CLASS = "class"
    STUDENT = "student"
    GROUP = "group"


class SheetKind(StrEnum):
    BLANK = "blank"
    ANSWER_KEY = "answer_key"
    #: The per-student feedback pages. Its OWN document, never extra pages
    #: inside a copy: the detector counts a copy's pages by re-paginating its
    #: items, so a page the renderer adds and that count does not know about
    #: rotates every later page onto the wrong item list.
    FEEDBACK = "feedback"


class MasteryBand(StrEnum):
    """The ordered domain scale. Order is meaningful: BAND_ORDER below."""

    SOLID = "solid"
    OK = "ok"
    WEAK = "weak"
    FADING = "fading"
    NONE = "none"


BAND_ORDER: tuple[MasteryBand, ...] = (
    MasteryBand.SOLID,
    MasteryBand.OK,
    MasteryBand.WEAK,
    MasteryBand.FADING,
    MasteryBand.NONE,
)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobKind(StrEnum):
    INGEST_SOURCE = "ingest_source"
    EXTRACT_SECTION = "extract_section"
    RENDER_SHEET = "render_sheet"
    PROCESS_SCAN = "process_scan"
    #: Builds the proposal: targeting, retrieval, and the model calls that fill
    #: the shortfall. Separate from GENERATE_ADAPTIVE, which despite its name
    #: only *renders* an already-approved batch to PDF.
    PROPOSE_ADAPTIVE = "propose_adaptive"
    GENERATE_ADAPTIVE = "generate_adaptive"
    GENERATE_FEEDBACK = "generate_feedback"
    #: The vision grader over a scan's written answers. Chained after
    #: PROCESS_SCAN by the worker so the review opens as soon as the marks are
    #: read, and grades arrive while the teacher is already looking.
    GRADE_OPEN_ANSWERS = "grade_open_answers"


class ScanStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class DetectionOutcome(StrEnum):
    """How a single item's answer was arrived at — the audit trail matters."""

    DETECTED = "detected"          # the pipeline read it confidently
    LOW_CONFIDENCE = "low_confidence"  # surfaced to the teacher first
    BLANK = "blank"                # no mark found
    MULTIPLE = "multiple"          # more than one bubble filled
    CORRECTED = "corrected"        # teacher overrode the detection
    NOT_GRADEABLE = "not_gradeable"  # free-text with no verdict: printed, not auto-graded
    PENDING = "pending"            # a written answer cropped, awaiting the vision grader


class EventKind(StrEnum):
    """What happened, in the teacher's vocabulary rather than the schema's.

    An append-only log rather than a column per lifecycle moment. `updated_at`
    cannot answer "when was this confirmed" — it is overwritten by the next
    edit to the row, whatever that edit was — and two of the moments a teacher
    most wants back (a sheet printed, a pile confirmed) had no timestamp at all.

    The names are what a teacher would say happened, because they are read back
    as a sentence in the agenda, not as a status field.
    """

    SOURCE_IMPORTED = "source_imported"
    CHAPTER_READ = "chapter_read"
    SHEET_CREATED = "sheet_created"
    SHEET_RENDERED = "sheet_rendered"
    SHEET_PRINTED = "sheet_printed"
    SCAN_UPLOADED = "scan_uploaded"
    SCAN_CONFIRMED = "scan_confirmed"
    #: A confirmed pile put back into review. The counterpart of
    #: SCAN_CONFIRMED, and the reason the agenda can show that a set of grades
    #: was withdrawn rather than silently changing underneath the teacher.
    SCAN_REOPENED = "scan_reopened"
    ADAPTIVE_PROPOSED = "adaptive_proposed"
    ADAPTIVE_EXPORTED = "adaptive_exported"
    FEEDBACK_WRITTEN = "feedback_written"
    FEEDBACK_APPROVED = "feedback_approved"


class EventSubject(StrEnum):
    """Which row the event is about, so the agenda can link back to it."""

    SOURCE = "source"
    SHEET = "sheet"
    SCAN = "scan"
    CLASS = "class"
