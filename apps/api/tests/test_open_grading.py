"""The free-text grader: a verdict becomes a score, and nothing else does."""

from __future__ import annotations

from alppy.models.enums import DetectionOutcome, ExerciseType
from alppy.scan import grading
from alppy.scan.grading import AnswerKey, DetectedAnswer, grade_item, grader_for
from alppy.scan.open_grading import grade_open_vision, install

OPEN = AnswerKey(type=ExerciseType.OPEN)


def test_importing_the_scan_package_installs_the_grader() -> None:
    assert grader_for(ExerciseType.OPEN) is grade_open_vision
    install()
    install()
    assert grader_for(ExerciseType.OPEN) is grade_open_vision


def test_a_verdict_is_a_score() -> None:
    right = DetectedAnswer(outcome=DetectionOutcome.DETECTED, confidence=0.9, verdict_correct=True)
    wrong = DetectedAnswer(outcome=DetectionOutcome.DETECTED, confidence=0.9, verdict_correct=False)
    assert grade_item(OPEN, right).correct and grade_item(OPEN, right).score == 1.0
    assert not grade_item(OPEN, wrong).correct and grade_item(OPEN, wrong).score == 0.0
    assert grade_item(OPEN, right).gradeable and grade_item(OPEN, wrong).gradeable


def test_a_low_confidence_verdict_still_grades_and_keeps_its_confidence() -> None:
    shaky = DetectedAnswer(
        outcome=DetectionOutcome.LOW_CONFIDENCE, confidence=0.4, verdict_correct=True
    )
    g = grade_item(OPEN, shaky)
    assert g.gradeable and g.correct and g.confidence == 0.4


def test_a_teacher_correction_grades_on_the_teachers_verdict() -> None:
    corrected = DetectedAnswer(
        outcome=DetectionOutcome.CORRECTED, confidence=1.0, verdict_correct=False,
        transcription="7/9",
    )
    g = grade_item(OPEN, corrected)
    assert g.gradeable and not g.correct


def test_a_blank_box_counts_at_zero() -> None:
    g = grade_item(OPEN, DetectedAnswer(outcome=DetectionOutcome.BLANK, confidence=0.98))
    assert g.gradeable and not g.correct and g.outcome is DetectionOutcome.BLANK


def test_no_verdict_is_not_a_zero() -> None:
    for outcome in (
        DetectionOutcome.PENDING,
        DetectionOutcome.NOT_GRADEABLE,
        DetectionOutcome.DETECTED,
        DetectionOutcome.CORRECTED,
    ):
        g = grade_item(OPEN, DetectedAnswer(outcome=outcome, confidence=0.9))
        assert not g.gradeable, outcome
        assert g.score == 0.0 and not g.correct


def test_the_stub_alone_grades_nothing() -> None:
    """``grading.py`` imported on its own still refuses a written answer."""
    g = grading._grade_open(OPEN, DetectedAnswer(outcome=DetectionOutcome.DETECTED, verdict_correct=True))
    assert not g.gradeable
