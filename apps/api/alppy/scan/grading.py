"""Grading.

The MVP auto-grades MCQ and true/false only. Free-text is explicitly out of
scope — but the shape here is what makes adding it later a plug-in rather than
a rewrite: ``grade_item`` dispatches on exercise type, and every type that has
no automatic grader returns ``NOT_GRADEABLE`` instead of guessing. A future
free-text grader registers itself in ``_GRADERS`` and nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from alppy.models.enums import DetectionOutcome, ExerciseType


@dataclass(frozen=True, slots=True)
class AnswerKey:
    """What the correct answer is, as printed on the answer-key sheet."""

    type: ExerciseType
    answer_index: int | None = None
    answer_bool: bool | None = None
    option_count: int = 0


@dataclass(frozen=True, slots=True)
class DetectedAnswer:
    """What the scan pipeline believes the student marked."""

    outcome: DetectionOutcome
    index: int | None = None
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class GradedItem:
    correct: bool
    score: float
    gradeable: bool
    outcome: DetectionOutcome
    confidence: float
    reason: str


class ItemGrader(Protocol):
    def __call__(self, key: AnswerKey, detected: DetectedAnswer) -> GradedItem: ...


def _ungradeable(outcome: DetectionOutcome, confidence: float, reason: str) -> GradedItem:
    return GradedItem(
        correct=False,
        score=0.0,
        gradeable=False,
        outcome=outcome,
        confidence=confidence,
        reason=reason,
    )


def _grade_choice(key: AnswerKey, detected: DetectedAnswer, expected: int | None) -> GradedItem:
    """Shared logic for the two bubble-based types."""
    if detected.outcome is DetectionOutcome.BLANK:
        # A blank answer is a wrong answer, not a missing one: the student saw
        # the item and left it. It counts, at zero.
        return GradedItem(
            correct=False,
            score=0.0,
            gradeable=True,
            outcome=DetectionOutcome.BLANK,
            confidence=detected.confidence,
            reason="no mark detected",
        )
    if detected.outcome is DetectionOutcome.MULTIPLE:
        # Two bubbles filled is ambiguous. We never guess; the teacher decides.
        return _ungradeable(
            DetectionOutcome.MULTIPLE, detected.confidence, "more than one bubble marked"
        )
    if detected.index is None:
        return _ungradeable(detected.outcome, detected.confidence, "no answer index")
    if expected is None:
        return _ungradeable(
            DetectionOutcome.NOT_GRADEABLE, detected.confidence, "exercise has no answer key"
        )

    correct = detected.index == expected
    return GradedItem(
        correct=correct,
        score=1.0 if correct else 0.0,
        gradeable=True,
        outcome=detected.outcome,
        confidence=detected.confidence,
        reason="matched answer key" if correct else "did not match answer key",
    )


def _grade_mcq(key: AnswerKey, detected: DetectedAnswer) -> GradedItem:
    return _grade_choice(key, detected, key.answer_index)


def _grade_true_false(key: AnswerKey, detected: DetectedAnswer) -> GradedItem:
    # Bubble 0 is "true", bubble 1 is "false". The printed glyph changes with
    # the sheet language (V/F, R/F, T/F); the positions never do.
    expected = None if key.answer_bool is None else (0 if key.answer_bool else 1)
    return _grade_choice(key, detected, expected)


def _grade_open(key: AnswerKey, detected: DetectedAnswer) -> GradedItem:
    """Free-text is printed and never auto-graded. This is the extension point."""
    return _ungradeable(
        DetectionOutcome.NOT_GRADEABLE,
        detected.confidence,
        "free-text grading is out of scope for the MVP",
    )


_GRADERS: dict[ExerciseType, ItemGrader] = {
    ExerciseType.MCQ: _grade_mcq,
    ExerciseType.TRUE_FALSE: _grade_true_false,
    ExerciseType.OPEN: _grade_open,
}


def grade_item(key: AnswerKey, detected: DetectedAnswer) -> GradedItem:
    """Grade one item. Never raises: an unknown type is simply not gradeable."""
    grader = _GRADERS.get(key.type)
    if grader is None:  # pragma: no cover - defensive
        return _ungradeable(DetectionOutcome.NOT_GRADEABLE, detected.confidence, "unknown type")
    return grader(key, detected)


def grade_sheet(
    keys: list[AnswerKey], detections: list[DetectedAnswer]
) -> list[GradedItem]:
    """Grade a whole sheet. Lengths must match — the caller pairs by item index."""
    if len(keys) != len(detections):
        raise ValueError(
            f"key/detection length mismatch: {len(keys)} keys vs {len(detections)} detections"
        )
    return [grade_item(k, d) for k, d in zip(keys, detections, strict=True)]
