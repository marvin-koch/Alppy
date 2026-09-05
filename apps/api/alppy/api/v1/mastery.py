"""The mastery matrix and the student profile.

Both are computed from attempts through ``alppy.mastery.model`` rather than
read straight out of ``MasterySnapshot``: the score decays with time, so a
matrix opened on Friday must not show Monday's numbers. Snapshots are the
history behind the curve, not the source of truth for today.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from alppy.api.deps import DbDep, TenantDep
from alppy.schemas import MasteryMatrixOut, StudentProfileOut
from alppy.services import mastery_service as svc

router = APIRouter(tags=["mastery"])


@router.get("/classes/{class_id}/mastery", response_model=MasteryMatrixOut)
def class_mastery(
    class_id: uuid.UUID,
    school_id: TenantDep,
    db: DbDep,
    subject_id: Annotated[uuid.UUID | None, Query()] = None,
) -> MasteryMatrixOut:
    """Students x competencies, one cell per pair, five bands."""
    return svc.class_matrix(db, school_id, class_id, subject_id=subject_id)


@router.get("/students/{student_id}/mastery", response_model=StudentProfileOut)
def student_mastery(
    student_id: uuid.UUID, school_id: TenantDep, db: DbDep
) -> StudentProfileOut:
    """Strengths, gaps worst-first, and the history behind each competency."""
    return svc.student_profile(db, school_id, student_id)
