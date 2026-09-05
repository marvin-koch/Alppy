"""Curriculum reference data and the teacher's own chapter grouping.

Competencies are shared reference data (LP21 and PER coexist in one table and
carry no ``school_id``); chapters are the teacher's textbook-oriented grouping
and are school-scoped like everything else.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from alppy.api import errors
from alppy.api.deps import DbDep, TenantDep
from alppy.models import Chapter, Competency, Subject
from alppy.models.enums import CurriculumKind
from alppy.schemas import ChapterOut, CompetencyOut, LocalisedText
from alppy.services import chapter_out, competency_out

router = APIRouter(tags=["curriculum"])


class ChapterCreate(BaseModel):
    """Not in ``alppy.schemas`` — see the report note on the contract gap."""

    subject_id: uuid.UUID
    key: Annotated[str, Field(min_length=1, max_length=80)]
    labels: LocalisedText
    position: Annotated[int, Field(ge=0)] = 0
    competency_ids: Annotated[list[uuid.UUID], Field(max_length=50)] = []


@router.get("/curricula/{kind}/competencies", response_model=list[CompetencyOut])
def list_competencies(
    kind: CurriculumKind,
    db: DbDep,
    _school_id: TenantDep,
    subject_key: Annotated[str | None, Query()] = None,
    cycle: Annotated[int | None, Query(ge=1, le=3)] = None,
) -> list[CompetencyOut]:
    stmt = select(Competency).where(Competency.curriculum == kind)
    if subject_key is not None:
        stmt = stmt.where(Competency.subject_key == subject_key)
    if cycle is not None:
        stmt = stmt.where(Competency.cycle == cycle)
    rows = db.execute(stmt.order_by(Competency.code.asc())).scalars()
    return [competency_out(c) for c in rows]


@router.get("/chapters", response_model=list[ChapterOut])
def list_chapters(
    school_id: TenantDep,
    db: DbDep,
    subject_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ChapterOut]:
    stmt = select(Chapter).where(Chapter.school_id == school_id)
    if subject_id is not None:
        stmt = stmt.where(Chapter.subject_id == subject_id)
    rows = db.execute(stmt.order_by(Chapter.position.asc(), Chapter.key.asc())).scalars()
    return [chapter_out(c) for c in rows]


@router.post("/chapters", response_model=ChapterOut, status_code=status.HTTP_201_CREATED)
def create_chapter(payload: ChapterCreate, school_id: TenantDep, db: DbDep) -> ChapterOut:
    subject = db.execute(
        select(Subject)
        .where(Subject.id == payload.subject_id)
        .where(Subject.school_id == school_id)
    ).scalar_one_or_none()
    if subject is None:
        raise errors.not_found("subject", id=str(payload.subject_id))

    competencies: list[Competency] = []
    if payload.competency_ids:
        competencies = list(
            db.execute(
                select(Competency).where(Competency.id.in_(payload.competency_ids))
            ).scalars()
        )
        missing = {str(i) for i in payload.competency_ids} - {str(c.id) for c in competencies}
        if missing:
            raise errors.not_found("competency", ids=sorted(missing))

    chapter = Chapter(
        id=uuid.uuid4(),
        school_id=school_id,
        subject_id=subject.id,
        key=payload.key,
        labels=dict(payload.labels),
        position=payload.position,
    )
    chapter.competencies = competencies
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter_out(chapter)
