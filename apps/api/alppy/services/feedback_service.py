"""Per-student misconception notes, written from a corrected common sheet (F4).

What this is for
----------------
A teacher runs a common sheet, scans it back, confirms the grades, and asks for
differentiated sheets. The differentiated sheet says what to practise next; it
does not say *why the child got it wrong*. This module writes that, once per
student, from the answers they actually gave.

Grounded, or nothing
--------------------
``adaptive_feedback`` is in ``providers.TRANSCRIPTION_PURPOSES``, so an
ungrounded provider returns an empty payload rather than inventing content. That
is deliberate and it is a stronger requirement than the one on generated
exercises: a wrong exercise is a bad question a teacher can reject on sight, a
wrong misconception is a claim about how a named child thinks, printed and put
in that child's hands. A student with no note is a student who reads no note;
a student with an invented one is told something false about themselves.

Where the wrong answer comes from
---------------------------------
``Attempt`` records *whether* the answer was right, never what it was. What the
student actually marked lives on ``Detection.detected_index`` /
``detected_bool``, reachable through ``Attempt.detection_id``. An attempt with
no detection, or one whose reading was never trustworthy
(``LOW_CONFIDENCE``, ``MULTIPLE``, ``BLANK``), is skipped: there is no
distractor to explain, and guessing which one they chose is exactly the
fabrication the grounding rule exists to prevent.

Privacy
-------
The prompt carries ``to_ref(student.uid)`` — "7B_15" — never a name, and the
mistake block is ``scrub``-ed before it goes in, because a textbook statement
may well name a pupil who is in this class. ``assert_no_pii`` inside
``AiClient.complete`` stays armed as the proof.

Approval
--------
Every note is written with ``approved_at = None`` and cannot be printed until a
teacher stamps it, enforced by ``services.approval`` at the same two doors as a
generated exercise: batch creation and render.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.ai.audit import flush as flush_ai_log
from alppy.ai.client import AiClient, load_prompt, parse_json_response
from alppy.ai.scrub import scrub, to_ref
from alppy.core.logging import get_logger
from alppy.models import Attempt, Detection, Exercise, MisconceptionNote, Student
from alppy.models.enums import DetectionOutcome, ExerciseType

log = get_logger(__name__)

MAX_NOTES = 3
"""Three misconceptions is what a student can act on in one sitting. A page
listing eight things you do wrong is not feedback, it is a verdict."""

MAX_MISTAKES = 6
"""How many wrong answers are shown to the model. Enough to spot a pattern,
few enough that the prompt stays a page."""

GENERATION_TEMPERATURE = 0.4
"""Lower than exercise generation. This text is about a real child's real
answers; invention is the failure mode, not dullness."""

#: Readings the pipeline never resolved confidently enough to explain.
UNTRUSTWORTHY = frozenset(
    {DetectionOutcome.LOW_CONFIDENCE, DetectionOutcome.MULTIPLE, DetectionOutcome.BLANK}
)


class FeedbackGenerationError(RuntimeError):
    """The model did not return a usable note for a student who needed one."""


class GeneratedFeedbackIn(BaseModel):
    """What a generated note must look like before it becomes a row.

    ``extra="forbid"`` for the same reason the exercise schema forbids it: a
    model that invents a field has not understood the schema, and quietly
    dropping the field is how a plausible-but-wrong claim reaches paper.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    notes: list[str] = Field(min_length=1, max_length=MAX_NOTES)

    def cleaned(self) -> list[str]:
        """Non-empty, de-duplicated, each short enough to print."""
        out: list[str] = []
        seen: set[str] = set()
        for note in self.notes:
            text = " ".join(note.split())
            if not 12 <= len(text) <= 400:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
        if not out:
            raise ValueError("no usable note in the response")
        return out


@dataclass(frozen=True, slots=True)
class Mistake:
    """One wrong answer, with what the student marked and what was right."""

    statement: str
    given: str
    expected: str
    competency_id: uuid.UUID | None


def _option_text(exercise: Exercise, index: int | None, *, language: str) -> str:
    """The printed wording of one option, as the student saw it."""
    if index is None:
        return "—"
    if exercise.type is ExerciseType.TRUE_FALSE:
        # layout.tf_letters fixes the convention: index 0 is the true glyph.
        true_word = {"fr": "vrai", "de": "richtig"}.get(language, "true")
        false_word = {"fr": "faux", "de": "falsch"}.get(language, "false")
        return true_word if index == 0 else false_word
    options = exercise.options or []
    if 0 <= index < len(options):
        return str(options[index])
    return "—"


def _given_index(detection: Detection, exercise: Exercise) -> int | None:
    if exercise.type is ExerciseType.TRUE_FALSE:
        if detection.detected_bool is None:
            return None
        return 0 if detection.detected_bool else 1
    return detection.detected_index


def _expected_index(exercise: Exercise) -> int | None:
    if exercise.type is ExerciseType.TRUE_FALSE:
        if exercise.answer_bool is None:
            return None
        return 0 if exercise.answer_bool else 1
    return exercise.answer_index


def wrong_attempts(
    db: Session,
    *,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    sheet_id: uuid.UUID,
    limit: int = MAX_MISTAKES,
) -> list[Mistake]:
    """The student's explainable wrong answers on one sheet, oldest item first.

    "Explainable" is the whole filter: we must be able to say what they marked.
    An attempt with no detection row, or one the detector never resolved, is
    dropped rather than guessed at.
    """
    rows = db.execute(
        select(Attempt, Exercise, Detection)
        .join(Exercise, Exercise.id == Attempt.exercise_id)
        .outerjoin(Detection, Detection.id == Attempt.detection_id)
        .where(
            Attempt.school_id == school_id,
            Attempt.student_id == student_id,
            Attempt.sheet_id == sheet_id,
            Attempt.correct.is_(False),
        )
        .order_by(Attempt.answered_at.asc())
    ).all()

    mistakes: list[Mistake] = []
    for _attempt, exercise, detection in rows:
        if detection is None or detection.outcome in UNTRUSTWORTHY:
            continue
        given = _given_index(detection, exercise)
        expected = _expected_index(exercise)
        if given is None or expected is None or given == expected:
            continue
        mistakes.append(
            Mistake(
                statement=exercise.statement,
                given=_option_text(exercise, given, language=exercise.language),
                expected=_option_text(exercise, expected, language=exercise.language),
                competency_id=(
                    exercise.competencies[0].id if exercise.competencies else None
                ),
            )
        )
        if len(mistakes) >= limit:
            break
    return mistakes


def _format_mistakes(mistakes: Sequence[Mistake], *, roster_names: Sequence[str]) -> str:
    """The prompt's mistake block, scrubbed.

    Scrubbed rather than merely asserted over, for the reason recorded in
    decisions-log D10: Swiss textbook prose is full of Léa, Noah and Emma, who
    are also in the class, and asserting alone means a corpus that happens to
    name a pupil silently kills feedback for that student.
    """
    names = list(roster_names)
    lines: list[str] = []
    for i, m in enumerate(mistakes, start=1):
        statement = " ".join(scrub(m.statement, names=names).split())
        lines.append(
            f"{i}. {statement}\n"
            f"   Réponse de l'élève : {scrub(m.given, names=names)}\n"
            f"   Réponse correcte : {scrub(m.expected, names=names)}"
        )
    return "\n".join(lines)


def generate_for_student(
    db: Session,
    *,
    school_id: uuid.UUID,
    student: Student,
    subject_id: uuid.UUID,
    source_sheet_id: uuid.UUID,
    language: str,
    roster_names: list[str],
    ai: AiClient,
) -> MisconceptionNote | None:
    """One note for one student, or ``None`` when there is nothing to explain.

    A clean paper costs no model call and produces no row: a student who got
    everything right does not need to be told what they misunderstood, and a
    note invented for them would be the clearest possible proof that the text
    is not grounded.
    """
    mistakes = wrong_attempts(
        db, school_id=school_id, student_id=student.id, sheet_id=source_sheet_id
    )
    if not mistakes:
        return None

    prompt = load_prompt("generate_feedback")
    values = {
        "language": language,
        "student_ref": str(to_ref(student.uid)),
        "mistakes": _format_mistakes(mistakes, roster_names=roster_names),
        "max_notes": str(MAX_NOTES),
    }

    response, record = ai.complete(
        prompt=prompt,
        purpose="adaptive_feedback",
        values=values,
        student_names=roster_names,
        temperature=GENERATION_TEMPERATURE,
    )
    flush_ai_log(db, school_id=school_id, ai=ai)

    try:
        payload = parse_json_response(response.text)
        parsed = GeneratedFeedbackIn.model_validate(payload)
        notes = parsed.cleaned()
    except (ValidationError, ValueError, TypeError) as exc:
        # An ungrounded provider answers `{"notes": []}` here, and so does a
        # model that had nothing to say. Neither is an error worth failing the
        # batch over: the student simply gets no feedback page.
        log.info(
            "feedback.unusable",
            student_uid=student.uid,
            reason=type(exc).__name__,
        )
        return None

    competency_ids = [str(m.competency_id) for m in mistakes if m.competency_id is not None]
    note = MisconceptionNote(
        id=uuid.uuid4(),
        school_id=school_id,
        student_id=student.id,
        subject_id=subject_id,
        based_on_sheet_id=source_sheet_id,
        language=language,
        notes=notes,
        competency_ids=sorted(set(competency_ids)),
        approved_at=None,
        generation_meta={
            "prompt": f"{prompt.name}.{prompt.version}",
            "model": record.model,
            "student_ref": str(to_ref(student.uid)),
            "mistakes_considered": len(mistakes),
        },
    )
    db.add(note)
    db.flush()
    return note


def latest_for_students(
    db: Session,
    *,
    school_id: uuid.UUID,
    student_ids: Sequence[uuid.UUID],
    source_sheet_id: uuid.UUID,
) -> dict[uuid.UUID, MisconceptionNote]:
    """The newest live note per student for one common sheet."""
    if not student_ids:
        return {}
    rows = db.scalars(
        select(MisconceptionNote)
        .where(
            MisconceptionNote.school_id == school_id,
            MisconceptionNote.student_id.in_(list(student_ids)),
            MisconceptionNote.based_on_sheet_id == source_sheet_id,
            MisconceptionNote.discarded_at.is_(None),
        )
        .order_by(MisconceptionNote.created_at.desc())
    )
    newest: dict[uuid.UUID, MisconceptionNote] = {}
    for row in rows:
        newest.setdefault(row.student_id, row)
    return newest


def generate_for_sheet(
    db: Session,
    *,
    school_id: uuid.UUID,
    source_sheet_id: uuid.UUID,
    subject_id: uuid.UUID,
    students: Sequence[Student],
    language: str,
    ai: AiClient,
    on_progress: Any = None,
) -> list[MisconceptionNote]:
    """One note per student who has something to be told, for the worker.

    This is job work rather than request work by the rule in CLAUDE.md: it is
    one model call per student, and a class of twenty inside a request handler
    is a timeout with a half-written batch behind it.
    """
    roster_names = _roster_names(students)
    written: list[MisconceptionNote] = []
    total = max(1, len(students))
    for i, student in enumerate(students):
        note = generate_for_student(
            db,
            school_id=school_id,
            student=student,
            subject_id=subject_id,
            source_sheet_id=source_sheet_id,
            language=language,
            roster_names=roster_names,
            ai=ai,
        )
        if note is not None:
            written.append(note)
        if on_progress is not None:
            on_progress((i + 1) / total, f"{i + 1} / {len(students)}")
    db.flush()
    return written


def _roster_names(students: Sequence[Student]) -> list[str]:
    """Every name the gate must refuse to let through, longest first."""
    names: set[str] = set()
    for s in students:
        for part in (s.first_name, s.last_name):
            if part and part.strip():
                names.add(part.strip())
    return sorted(names, key=len, reverse=True)


__all__ = [
    "MAX_NOTES",
    "FeedbackGenerationError",
    "GeneratedFeedbackIn",
    "Mistake",
    "generate_for_sheet",
    "generate_for_student",
    "latest_for_students",
    "wrong_attempts",
]
