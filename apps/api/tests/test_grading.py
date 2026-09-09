"""Grading. A written answer is graded on a verdict and on nothing else; the tests
pin that boundary in place."""

from __future__ import annotations

import pytest

from alppy.models.enums import DetectionOutcome, ExerciseType
from alppy.scan.grading import AnswerKey, DetectedAnswer, grade_item, grade_sheet

MCQ = AnswerKey(type=ExerciseType.MCQ, answer_index=2, option_count=4)
TF_TRUE = AnswerKey(type=ExerciseType.TRUE_FALSE, answer_bool=True, option_count=2)
TF_FALSE = AnswerKey(type=ExerciseType.TRUE_FALSE, answer_bool=False, option_count=2)
OPEN = AnswerKey(type=ExerciseType.OPEN)


def detected(index: int | None, conf: float = 0.95) -> DetectedAnswer:
    return DetectedAnswer(outcome=DetectionOutcome.DETECTED, index=index, confidence=conf)


def test_correct_mcq() -> None:
    g = grade_item(MCQ, detected(2))
    assert g.correct and g.gradeable and g.score == 1.0


def test_wrong_mcq() -> None:
    g = grade_item(MCQ, detected(0))
    assert not g.correct and g.gradeable and g.score == 0.0


def test_true_false_maps_bubble_zero_to_true() -> None:
    """Bubble 0 is 'true' and bubble 1 is 'false' whatever glyph is printed
    (V/F, R/F, T/F). The positions are the contract, not the letters."""
    assert grade_item(TF_TRUE, detected(0)).correct
    assert not grade_item(TF_TRUE, detected(1)).correct
    assert grade_item(TF_FALSE, detected(1)).correct
    assert not grade_item(TF_FALSE, detected(0)).correct


def test_blank_counts_as_wrong_but_gradeable() -> None:
    """The student saw the item and left it. That is information, worth zero —
    not a hole in the data."""
    g = grade_item(MCQ, DetectedAnswer(outcome=DetectionOutcome.BLANK, confidence=0.4))
    assert g.gradeable
    assert not g.correct
    assert g.score == 0.0


def test_multiple_marks_are_never_guessed() -> None:
    """Two filled bubbles is ambiguous; guessing could score a child wrongly."""
    g = grade_item(MCQ, DetectedAnswer(outcome=DetectionOutcome.MULTIPLE, confidence=0.2))
    assert not g.gradeable
    assert g.outcome is DetectionOutcome.MULTIPLE


def test_free_text_without_a_verdict_is_never_auto_graded() -> None:
    """A written answer is graded only on a verdict — the vision model's or
    the teacher's. A reading with none, whatever its confidence claims, is
    not a score, and a bubble index means nothing for a box."""
    g = grade_item(OPEN, detected(0))
    assert not g.gradeable
    assert g.outcome is DetectionOutcome.NOT_GRADEABLE
    pending = DetectedAnswer(outcome=DetectionOutcome.PENDING, confidence=0.0)
    assert not grade_item(OPEN, pending).gradeable
    assert grade_item(OPEN, pending).outcome is DetectionOutcome.PENDING


def test_missing_answer_key_is_not_gradeable() -> None:
    keyless = AnswerKey(type=ExerciseType.MCQ, answer_index=None, option_count=4)
    assert not grade_item(keyless, detected(1)).gradeable


def test_low_confidence_still_grades_but_keeps_its_confidence() -> None:
    """A low-confidence reading is graded provisionally; the review UI surfaces
    it first, and the teacher confirms before anything reaches the mastery model."""
    g = grade_item(MCQ, DetectedAnswer(outcome=DetectionOutcome.LOW_CONFIDENCE, index=2, confidence=0.4))
    assert g.correct
    assert g.confidence == 0.4


def test_grade_sheet_pairs_by_position() -> None:
    keys = [MCQ, TF_TRUE, OPEN]
    dets = [detected(2), detected(1), detected(None)]
    results = grade_sheet(keys, dets)
    assert [r.correct for r in results] == [True, False, False]
    assert [r.gradeable for r in results] == [True, True, False]


def test_grade_sheet_rejects_a_length_mismatch() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        grade_sheet([MCQ], [detected(0), detected(1)])


# ---------------------------------------------------------------- the barème
# The teacher's scale reaches the grader on the AnswerKey. Every test above
# builds a key without one and still asserts 1.0/0.0, which is the point of the
# defaults: a caller that knows nothing about a barème grades as it always did.

SCALED = AnswerKey(type=ExerciseType.MCQ, answer_index=2, option_count=4, points_correct=2.5)
PENALISED = AnswerKey(type=ExerciseType.MCQ, answer_index=2, option_count=4, penalty=0.5)


def test_a_correct_answer_earns_what_the_teacher_set() -> None:
    assert grade_item(SCALED, detected(2)).score == 2.5


def test_a_wrong_answer_costs_the_penalty_and_the_grader_applies_the_sign() -> None:
    g = grade_item(PENALISED, detected(0))
    assert not g.correct and g.gradeable
    # The key carries 0.5, a magnitude. Only the score is signed.
    assert PENALISED.penalty == 0.5
    assert g.score == -0.5


def test_a_blank_is_never_penalised_however_large_the_penalty() -> None:
    """D5: a blank is a graded zero. The student saw the item and left it, and
    that is information — it is not the same act as answering wrongly, so it
    cannot cost what answering wrongly costs."""
    key = AnswerKey(type=ExerciseType.MCQ, answer_index=2, option_count=4, penalty=5.0)
    g = grade_item(key, DetectedAnswer(outcome=DetectionOutcome.BLANK, confidence=0.4))
    assert g.gradeable and not g.correct
    assert g.score == 0.0


def test_an_ambiguous_answer_is_not_penalised_either() -> None:
    """Two bubbles filled is a question for the teacher, not a wrong answer.
    It produces no attempt at all, so no barème applies to it."""
    key = AnswerKey(type=ExerciseType.MCQ, answer_index=2, option_count=4, penalty=5.0)
    g = grade_item(key, DetectedAnswer(outcome=DetectionOutcome.MULTIPLE, confidence=0.3))
    assert not g.gradeable
    assert g.score == 0.0


def test_true_false_carries_the_barème_too() -> None:
    key = AnswerKey(
        type=ExerciseType.TRUE_FALSE,
        answer_bool=True,
        option_count=2,
        points_correct=2.0,
        penalty=1.0,
    )
    assert grade_item(key, detected(0)).score == 2.0
    assert grade_item(key, detected(1)).score == -1.0


def test_zero_points_is_a_real_choice_not_an_absent_one() -> None:
    """An item worth nothing — a warm-up the teacher does not want counted."""
    key = AnswerKey(type=ExerciseType.MCQ, answer_index=2, option_count=4, points_correct=0.0)
    g = grade_item(key, detected(2))
    assert g.correct and g.gradeable and g.score == 0.0
