"""Scan registration, mark detection and grading.

Importing the package installs the free-text grader over the ``open`` stub in
``grading``: every caller reaches grading through this package, so the seam is
closed the moment anything asks to grade.
"""

from alppy.scan import open_grading
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

open_grading.install()

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
