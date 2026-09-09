"""Read-only reports over grades that already exist.

Two views the teacher had no way to get: what a class scored, and which printed
item the scanner struggled with. Both are pure reads, computed fresh from
``Attempt`` and ``Detection`` rows exactly as the mastery matrix is — nothing
here is stored, so nothing here can disagree with the rows it summarises.

They are deliberately separate from ``/mastery``: a band is decayed competency
evidence, a score is what the teacher's barème says the paper was worth. The
two answer different questions and must not be read off one another.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from alppy.api.deps import DbDep, ScopeDep, StorageDep
from alppy.schemas import ClassPointsOut, SheetConfidenceOut, StudentSheetOut
from alppy.services import class_points_out, sheet_confidence_out, student_sheet_out
from alppy.services import results_service as results_svc
from alppy.services import scan_service as scan_svc
from alppy.services import sheet_service as sheet_svc

router = APIRouter(tags=["reports"])


@router.get("/classes/{class_id}/points", response_model=ClassPointsOut)
def class_points(
    class_id: uuid.UUID,
    scope: ScopeDep,
    db: DbDep,
    subject_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ClassPointsOut:
    """What this class scored, per student and per sheet.

    ``points_earned`` is null, never 0, for a student with nothing graded yet —
    a term with two of five sheets marked must not read as three failures.
    """
    report = sheet_svc.class_points_totals(db, scope, class_id, subject_id=subject_id)
    return class_points_out(class_id, report)


@router.get("/sheets/{sheet_id}/confidence", response_model=SheetConfidenceOut)
def sheet_confidence(sheet_id: uuid.UUID, scope: ScopeDep, db: DbDep) -> SheetConfidenceOut:
    """How each printed item read across the class's copies.

    One child misreading question 7 is a child; twenty of them is a bad
    photocopy. This names the item, never the student.
    """
    return sheet_confidence_out(sheet_id, scan_svc.confidence_by_item(db, scope, sheet_id))


@router.get(
    "/students/{student_id}/sheets/{sheet_id}", response_model=StudentSheetOut
)
def student_sheet(
    student_id: uuid.UUID,
    sheet_id: uuid.UUID,
    scope: ScopeDep,
    db: DbDep,
    storage: StorageDep,
) -> StudentSheetOut:
    """One pupil's copy, question by question.

    What they put, what was expected, what each answer was worth, and the total —
    the view a teacher has open while handing the paper back.
    """
    breakdown = results_svc.student_sheet_breakdown(db, scope, student_id, sheet_id)
    return student_sheet_out(breakdown, storage=storage)
