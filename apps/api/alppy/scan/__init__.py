"""Scan registration, mark detection and grading."""

from alppy.scan.detector import PageResult, process_page
from alppy.scan.grading import (
    AnswerKey,
    DetectedAnswer,
    GradedItem,
    ItemGrader,
    grade_item,
    grade_sheet,
    grader_for,
    register_grader,
)

__all__ = [
    "AnswerKey",
    "DetectedAnswer",
    "GradedItem",
    "ItemGrader",
    "PageResult",
    "grade_item",
    "grade_sheet",
    "grader_for",
    "process_page",
    "register_grader",
]
