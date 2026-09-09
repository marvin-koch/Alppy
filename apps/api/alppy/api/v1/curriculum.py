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
from alppy.api.deps import DbDep, ScopeDep, TenantDep, scoped_get
from alppy.models import Chapter, Competency, Subject
from alppy.models.enums import CurriculumKind
from alppy.schemas import ChapterOut, ChapterUpdate, CompetencyOut, LocalisedText
from alppy.services import chapter_out, competency_out
from alppy.services import nouns_service as svc

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

    # `uq_chapter_key` would otherwise surface as an IntegrityError 500. A key
    # already used in this subject is a caller mistake worth naming.
    clash = db.execute(
        select(Chapter)
        .where(Chapter.school_id == school_id)
        .where(Chapter.subject_id == payload.subject_id)
        .where(Chapter.key == payload.key)
    ).scalar_one_or_none()
    if clash is not None:
        raise errors.conflict("a chapter with this key already exists", key=payload.key)

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


@router.patch("/chapters/{chapter_id}", response_model=ChapterOut)
def update_chapter(
    chapter_id: uuid.UUID, payload: ChapterUpdate, scope: ScopeDep, db: DbDep
) -> ChapterOut:
    """Rename a Theme, move it, or change what it credits.

    `competency_ids` is the m2m — what this Theme claims to cover, across both
    curricula. This is the honest shape of "add a competence I teach": a
    teacher cannot create a `Competency` (national reference data, shared by
    every school, D11), but they choose which ones their Theme credits.
    """
    chapter = scoped_get(db, Chapter, chapter_id, scope.school_id, label="chapter")
    row = svc.update_chapter(
        db,
        scope,
        chapter,
        labels=payload.labels,
        position=payload.position,
        competency_ids=payload.competency_ids,
    )
    db.commit()
    return chapter_out(row)


@router.delete("/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chapter(chapter_id: uuid.UUID, scope: ScopeDep, db: DbDep) -> None:
    """Remove a Theme. Refused while sheets still sit in it, and on `unfiled`."""
    chapter = scoped_get(db, Chapter, chapter_id, scope.school_id, label="chapter")
    svc.delete_chapter(db, scope, chapter)
    db.commit()
