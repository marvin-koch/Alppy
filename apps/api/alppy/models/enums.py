"""Domain enumerations shared by models, schemas and the grading pipeline."""

from __future__ import annotations

from enum import StrEnum


class Locale(StrEnum):
    FR = "fr"
    DE = "de"
    EN = "en"


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


class SheetTarget(StrEnum):
    CLASS = "class"
    STUDENT = "student"
    GROUP = "group"


class SheetKind(StrEnum):
    BLANK = "blank"
    ANSWER_KEY = "answer_key"


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
    GENERATE_ADAPTIVE = "generate_adaptive"


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
    NOT_GRADEABLE = "not_gradeable"  # free-text; printed, never auto-graded
