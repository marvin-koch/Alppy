"""Per-student misconception notes.

The three properties that matter here are all about *not* writing something:
a note must be grounded in a real wrong answer, must never be written for a
student who has nothing to be told, and must never print unapproved.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, make_exercise, make_paper_trail

from alppy.ai.base import ChatRequest, ChatResponse
from alppy.ai.client import AiClient
from alppy.models import Attempt, Detection, MisconceptionNote, Student
from alppy.models.enums import DetectionOutcome, ExerciseType
from alppy.services import feedback_service

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


class _GroundedProvider:
    """Echoes back two notes, and records what it was asked."""

    name = "stub"
    grounded = True

    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            text=(
                '{"notes": ["Tu appliques les operations de gauche a droite : '
                'la multiplication passe avant l addition.", '
                '"Verifie en soulignant les multiplications d abord."]}'
            ),
            model="stub",
        )


def _client(provider: object) -> AiClient:
    client = AiClient()
    client._chat = provider  # type: ignore[assignment]  # test double, as elsewhere in this suite
    return client


def _wrong_attempt(
    db: Session,
    tenant: Tenant,
    student: Student,
    *,
    statement: str = "Combien font 3 + 4 x 2 ?",
    outcome: DetectionOutcome = DetectionOutcome.DETECTED,
    detected_index: int | None = 2,
) -> tuple[object, Detection]:
    """One exercise the student answered wrongly, with the paper behind it."""
    exercise = make_exercise(db, tenant, statement=statement, answer_index=1)
    sheet, _scan, detection = make_paper_trail(db, tenant, exercise, student)
    detection.outcome = outcome
    detection.detected_index = detected_index
    db.add(
        Attempt(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            person_id=student.person_id,
            exercise_id=exercise.id,
            sheet_id=sheet.id,
            detection_id=detection.id,
            correct=False,
            score=0.0,
            difficulty=3,
            answered_at=NOW,
        )
    )
    db.flush()
    return sheet, detection


# --------------------------------------------------------------------------
# 1 · Nothing to explain costs nothing
# --------------------------------------------------------------------------
def test_a_clean_paper_produces_no_note_and_no_model_call(
    db: Session, tenant: Tenant
) -> None:
    """A student who got everything right must not be told what they got wrong."""
    student = tenant.students[0]
    exercise = make_exercise(db, tenant, statement="Combien font 2 + 2 ?")
    sheet, _scan, detection = make_paper_trail(db, tenant, exercise, student)
    db.add(
        Attempt(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            person_id=student.person_id,
            exercise_id=exercise.id,
            sheet_id=sheet.id,
            detection_id=detection.id,
            correct=True,
            score=1.0,
            difficulty=3,
            answered_at=NOW,
        )
    )
    db.flush()

    provider = _GroundedProvider()
    note = feedback_service.generate_for_student(
        db,
        school_id=tenant.school.id,
        student=student,
        subject_id=tenant.subject.id,
        source_sheet_id=sheet.id,
        language="fr",
        roster_names=[],
        ai=_client(provider),
    )

    assert note is None
    assert provider.requests == [], "a clean paper must not reach a provider"
    assert db.query(MisconceptionNote).count() == 0


# --------------------------------------------------------------------------
# 2 · Only an answer we can actually read is explained
# --------------------------------------------------------------------------
def test_an_unreadable_detection_is_never_guessed_at(db: Session, tenant: Tenant) -> None:
    """LOW_CONFIDENCE means the pipeline does not know what the child marked.

    Explaining a distractor we did not read would be inventing the very thing
    the note claims to have observed.
    """
    student = tenant.students[0]
    sheet, _detection = _wrong_attempt(
        db, tenant, student, outcome=DetectionOutcome.LOW_CONFIDENCE
    )

    mistakes = feedback_service.wrong_attempts(
        db, school_id=tenant.school.id, person_id=student.person_id, sheet_id=sheet.id
    )
    assert mistakes == []


def test_a_wrong_answer_carries_what_was_marked_and_what_was_right(
    db: Session, tenant: Tenant
) -> None:
    student = tenant.students[0]
    sheet, _detection = _wrong_attempt(db, tenant, student)

    mistakes = feedback_service.wrong_attempts(
        db, school_id=tenant.school.id, person_id=student.person_id, sheet_id=sheet.id
    )
    assert len(mistakes) == 1
    assert mistakes[0].given == "C", "index 2 of A/B/C/D"
    assert mistakes[0].expected == "B", "index 1 of A/B/C/D"


# --------------------------------------------------------------------------
# 3 · A written note is unapproved, and carries no name
# --------------------------------------------------------------------------
def test_a_note_is_written_unapproved_and_names_nobody(db: Session, tenant: Tenant) -> None:
    student = tenant.students[0]
    sheet, _detection = _wrong_attempt(db, tenant, student)
    provider = _GroundedProvider()

    note = feedback_service.generate_for_student(
        db,
        school_id=tenant.school.id,
        student=student,
        subject_id=tenant.subject.id,
        source_sheet_id=sheet.id,
        language="fr",
        roster_names=[student.first_name, student.last_name],
        ai=_client(provider),
    )

    assert note is not None
    assert note.approved_at is None, "nothing generated may print unreviewed"
    assert note.based_on_sheet_id == sheet.id
    assert len(note.notes) == 2

    sent = provider.requests[0].system + provider.requests[0].user
    assert student.first_name not in sent
    assert student.last_name not in sent
    assert student.uid in sent, "the UID is the only identifier that leaves"


# --------------------------------------------------------------------------
# 4 · An ungrounded provider writes nothing at all
# --------------------------------------------------------------------------
def test_the_offline_provider_writes_no_note(db: Session, tenant: Tenant) -> None:
    """`adaptive_feedback` is a grounded-only purpose.

    The echo provider cannot read the prompt, so any 'misconception' it
    produced would be fiction with a real child's UID attached. An empty page
    is the honest outcome.
    """
    student = tenant.students[0]
    sheet, _detection = _wrong_attempt(db, tenant, student)

    note = feedback_service.generate_for_student(
        db,
        school_id=tenant.school.id,
        student=student,
        subject_id=tenant.subject.id,
        source_sheet_id=sheet.id,
        language="fr",
        roster_names=[],
        ai=AiClient(),  # the offline EchoChatProvider
    )

    assert note is None
    assert db.query(MisconceptionNote).count() == 0


# --------------------------------------------------------------------------
# 5 · The response schema refuses what would reach paper
# --------------------------------------------------------------------------
def test_an_empty_or_padded_response_is_rejected() -> None:
    with pytest.raises(ValidationError):
        feedback_service.GeneratedFeedbackIn.model_validate({"notes": []})
    with pytest.raises(ValidationError):
        # A model that invents a field has not understood the schema.
        feedback_service.GeneratedFeedbackIn.model_validate(
            {"notes": ["Tu confonds les priorites."], "grade": "D"}
        )
    with pytest.raises(ValueError):
        feedback_service.GeneratedFeedbackIn.model_validate({"notes": ["court"]}).cleaned()


def test_true_false_reports_the_word_the_student_saw(db: Session, tenant: Tenant) -> None:
    """index 0 is the true glyph, fixed by layout.tf_letters."""
    student = tenant.students[0]
    exercise = make_exercise(
        db,
        tenant,
        statement="Un carre est un rectangle.",
        kind=ExerciseType.TRUE_FALSE,
        answer_index=None,
        answer_bool=True,
    )
    sheet, _scan, detection = make_paper_trail(db, tenant, exercise, student)
    detection.outcome = DetectionOutcome.DETECTED
    detection.detected_index = None
    detection.detected_bool = False
    db.add(
        Attempt(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            person_id=student.person_id,
            exercise_id=exercise.id,
            sheet_id=sheet.id,
            detection_id=detection.id,
            correct=False,
            score=0.0,
            difficulty=3,
            answered_at=NOW,
        )
    )
    db.flush()

    mistakes = feedback_service.wrong_attempts(
        db, school_id=tenant.school.id, person_id=student.person_id, sheet_id=sheet.id
    )
    assert len(mistakes) == 1
    assert mistakes[0].given == "faux"
    assert mistakes[0].expected == "vrai"
