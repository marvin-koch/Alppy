"""The mastery matrix, the student profile, and the drill-down behind a cell.

All three are computed from attempts through ``alppy.mastery.model`` rather than
read straight out of ``MasterySnapshot``: the score decays with time, so a
matrix opened on Friday must not show Monday's numbers. Snapshots are the
history behind the curve, not the source of truth for today.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from alppy.api.deps import DbDep, ScopeDep
from alppy.schemas import CompetencyAttemptsOut, MasteryMatrixOut, StudentProfileOut
from alppy.services import mastery_service as svc

router = APIRouter(tags=["mastery"])


@router.get("/classes/{class_id}/mastery", response_model=MasteryMatrixOut)
def class_mastery(
    class_id: uuid.UUID,
    scope: ScopeDep,
    db: DbDep,
    subject_id: Annotated[uuid.UUID | None, Query()] = None,
    chapter_id: Annotated[uuid.UUID | None, Query()] = None,
    sort: Annotated[Literal["roster", "weakest"], Query()] = "roster",
) -> MasteryMatrixOut:
    """Students x competencies, one cell per pair, five bands.

    ``chapter_id`` narrows the columns to one chapter — a teacher marking a
    fractions test does not want twenty-five columns of everything else.
    ``sort=weakest`` puts the students who need help at the top, which is the
    order the teacher actually reads the grid in.
    """
    return svc.class_matrix(
        db,
        scope,
        class_id,
        subject_id=subject_id,
        chapter_id=chapter_id,
        sort=sort,
    )


@router.get("/students/{student_id}/mastery", response_model=StudentProfileOut)
def student_mastery(
    student_id: uuid.UUID, scope: ScopeDep, db: DbDep
) -> StudentProfileOut:
    """Strengths, gaps worst-first, the curve history, and the sheets sat."""
    return svc.student_profile(db, scope, student_id)


@router.get(
    "/students/{student_id}/competencies/{competency_id}/attempts",
    response_model=CompetencyAttemptsOut,
)
def student_competency_attempts(
    student_id: uuid.UUID, competency_id: uuid.UUID, scope: ScopeDep, db: DbDep
) -> CompetencyAttemptsOut:
    """The individual answers behind one matrix cell.

    A band is an argument, and this is the evidence for it: every attempt with
    its date, its outcome, whether the teacher overrode the scanner, and links
    back to the sheet it was printed on and the scan it was read from.
    """
    return svc.competency_attempts(db, scope, student_id, competency_id)
