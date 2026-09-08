"""The free-text grader D13 promised.

``grading.py`` dispatches on exercise type and shipped ``open`` mapped to a
stub that always answered ``NOT_GRADEABLE``: printed, never auto-graded. This
module is the grader that replaces it, and it arrives through the public seam
``register_grader`` exactly as the docstring there said one would.

It interprets a verdict, it does not form one. The vision model has already
compared the transcription with the expected answer inside its prompt; what
lands here is that verdict, the teacher's correction of it, or the absence of
either — and the absence is never turned into a score.
"""

from __future__ import annotations

from alppy.models.enums import DetectionOutcome, ExerciseType
from alppy.scan.grading import (
    AnswerKey,
    DetectedAnswer,
    GradedItem,
    register_grader,
    ungradeable,
)


def grade_open_vision(key: AnswerKey, detected: DetectedAnswer) -> GradedItem:
    if detected.outcome is DetectionOutcome.PENDING:
        # Still with the grader, or abandoned by a grader that died. Either
        # way there is no verdict, and a missing verdict is not a zero.
        return ungradeable(DetectionOutcome.PENDING, detected.confidence, "awaiting the vision grader")
    if detected.outcome is DetectionOutcome.BLANK:
        # As for a bubble: the student saw the item and wrote nothing. That
        # counts, at zero.
        return GradedItem(
            correct=False,
            score=0.0,
            gradeable=True,
            outcome=DetectionOutcome.BLANK,
            confidence=detected.confidence,
            reason="nothing written in the box",
        )
    if detected.verdict_correct is None:
        return ungradeable(
            DetectionOutcome.NOT_GRADEABLE,
            detected.confidence,
            "no verdict on this written answer",
        )
    return GradedItem(
        correct=detected.verdict_correct,
        score=1.0 if detected.verdict_correct else 0.0,
        gradeable=True,
        outcome=detected.outcome,
        confidence=detected.confidence,
        reason=(
            "written answer matched the expected answer"
            if detected.verdict_correct
            else "written answer did not match the expected answer"
        ),
    )


def install() -> None:
    """Replace the stub. Idempotent: registering twice installs the same
    function twice."""
    register_grader(ExerciseType.OPEN, grade_open_vision)


__all__ = ["grade_open_vision", "install"]
