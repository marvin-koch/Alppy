"""Uploaded textbook PDFs and the exercises extracted from them.

The upload handler does exactly three things: validate, store, enqueue. Parsing
a 300-page PDF, chunking it, embedding it and asking a model to extract
exercises all happen in the worker (``alppy.ingest.pipeline``), which is why
this endpoint answers in milliseconds regardless of the file.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.api.deps import (
    AiRateLimit,
    DbDep,
    ScopeDep,
    SettingsDep,
    StorageDep,
    TeacherDep,
    TenantDep,
    load_optional,
    read_upload,
    scoped_get,
    start_job,
)
from alppy.models import (
    Chapter,
    Competency,
    Exercise,
    Job,
    Source,
    SourceSection,
    Subject,
    exercise_competency,
)
from alppy.models.enums import (
    EventKind,
    EventSubject,
    ExerciseOrigin,
    ExerciseType,
    JobKind,
    JobStatus,
)
from alppy.schemas import (
    ExerciseCreate,
    ExerciseFacets,
    ExerciseListOut,
    ExerciseOut,
    ExerciseUpdate,
    JobOut,
    SourceOut,
    SourceSectionOut,
    SourceUpdate,
)
from alppy.services import event_service, exercise_out, job_out, source_out, source_section_out
from alppy.services import nouns_service as nouns
from alppy.storage import storage_key

router = APIRouter(tags=["sources"])

UNTAGGED_CHAPTER = "none"
"""The `chapter_id` sentinel for exercises with no chapter at all."""

PDF_ONLY = ("application/pdf",)


def _exercise_counts(db: Session, school_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(Exercise.source_id, func.count(Exercise.id))
        .where(Exercise.school_id == school_id)
        .where(Exercise.source_id.is_not(None))
        .group_by(Exercise.source_id)
    ).all()
    return {source_id: int(count) for source_id, count in rows if source_id is not None}


def _section_counts(db: Session, school_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(SourceSection.source_id, func.count(SourceSection.id))
        .where(SourceSection.school_id == school_id)
        .group_by(SourceSection.source_id)
    ).all()
    return {source_id: int(count) for source_id, count in rows}


def _get_source(db: Session, school_id: uuid.UUID, source_id: uuid.UUID) -> Source:
    source = db.execute(
        select(Source).where(Source.id == source_id).where(Source.school_id == school_id)
    ).scalar_one_or_none()
    if source is None:
        raise errors.not_found("source", id=str(source_id))
    return source


@router.get("/sources", response_model=list[SourceOut])
def list_sources(school_id: TenantDep, db: DbDep) -> list[SourceOut]:
    counts = _exercise_counts(db, school_id)
    rows = db.execute(
        select(Source).where(Source.school_id == school_id).order_by(Source.created_at.desc())
    ).scalars()
    sections = _section_counts(db, school_id)
    return [
        source_out(s, exercise_count=counts.get(s.id, 0), section_count=sections.get(s.id, 0))
        for s in rows
    ]


# A full ingest is a whole textbook through the extraction prompts — the most
# expensive single thing a teacher can start, and it starts from this handler's
# job. Same bucket as `/extract` below.
@router.post(
    "/sources",
    response_model=SourceOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[AiRateLimit],
)
async def upload_source(
    teacher: TeacherDep,
    school_id: TenantDep,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    subject_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File()],
) -> SourceOut:
    subject = db.execute(
        select(Subject).where(Subject.id == subject_id).where(Subject.school_id == school_id)
    ).scalar_one_or_none()
    if subject is None:
        raise errors.not_found("subject", id=str(subject_id))

    payload = await read_upload(file, settings, allowed=PDF_ONLY)
    digest = hashlib.sha256(payload.data).hexdigest()

    duplicate = db.execute(
        select(Source).where(Source.school_id == school_id).where(Source.sha256 == digest)
    ).scalar_one_or_none()
    if duplicate is not None:
        # Re-uploading the same book should not re-ingest it, and must not
        # produce a second copy of every exercise.
        counts = _exercise_counts(db, school_id)
        return source_out(
            duplicate,
            exercise_count=counts.get(duplicate.id, 0),
            section_count=_section_counts(db, school_id).get(duplicate.id, 0),
        )

    source_id = uuid.uuid4()
    key = storage_key("sources", school_id, source_id, payload.filename)
    storage.put_bytes(key, payload.data, payload.content_type)

    source = Source(
        id=source_id,
        school_id=school_id,
        subject_id=subject.id,
        uploaded_by_id=teacher.id,
        filename=payload.filename,
        storage_key=key,
        content_type=payload.content_type,
        size_bytes=payload.size,
        sha256=digest,
        status=JobStatus.QUEUED,
    )
    db.add(source)
    job = Job(
        id=uuid.uuid4(),
        school_id=school_id,
        kind=JobKind.INGEST_SOURCE,
        status=JobStatus.QUEUED,
        progress=0.0,
        message="queued for ingestion",
        payload={"source_id": str(source_id)},
    )
    db.add(job)
    # Fail loudly here rather than accepting a file nothing will ever read.
    load_optional("alppy.ingest.pipeline", "ingest_source", feature="source ingestion")
    event_service.record(
        db,
        school_id=school_id,
        kind=EventKind.SOURCE_IMPORTED,
        subject_type=EventSubject.SOURCE,
        subject_id=source.id,
        summary=source.filename,
        actor_id=teacher.id,
        subject_area_id=source.subject_id,
        detail={"bytes": payload.size},
    )
    db.commit()
    # The row is committed, so the worker can see it; now tell the worker.
    start_job(db, job)
    db.refresh(source)
    return source_out(source, exercise_count=0)


@router.get("/sources/{source_id}", response_model=SourceOut)
def get_source(source_id: uuid.UUID, school_id: TenantDep, db: DbDep) -> SourceOut:
    source = _get_source(db, school_id, source_id)
    return source_out(
        source,
        exercise_count=_exercise_counts(db, school_id).get(source.id, 0),
        section_count=_section_counts(db, school_id).get(source.id, 0),
    )


@router.get("/sources/{source_id}/status", response_model=JobOut)
def get_source_status(source_id: uuid.UUID, school_id: TenantDep, db: DbDep) -> JobOut:
    """The ingestion job for this source, for the polling client."""
    source = _get_source(db, school_id, source_id)
    jobs = db.execute(
        select(Job)
        .where(Job.school_id == school_id)
        .where(Job.kind == JobKind.INGEST_SOURCE)
        .order_by(Job.created_at.desc())
    ).scalars()
    for job in jobs:
        if str((job.payload or {}).get("source_id")) == str(source.id):
            return job_out(job)
    raise errors.not_found("ingestion job", source_id=str(source_id))


@router.get("/sources/{source_id}/sections", response_model=list[SourceSectionOut])
def list_source_sections(
    source_id: uuid.UUID, school_id: TenantDep, db: DbDep
) -> list[SourceSectionOut]:
    """The document's own table of contents, with per-chapter exercise counts.

    This is the builder's primary navigation. A textbook holds far more
    exercises than any teacher will read past, so the first question is never
    "show me everything" — it is "which chapter am I teaching".
    """
    source = _get_source(db, school_id, source_id)
    counts: dict[uuid.UUID, int] = {
        section_id: int(count)
        for section_id, count in db.execute(
            select(Exercise.source_section_id, func.count(Exercise.id))
            .where(Exercise.source_id == source.id)
            .where(Exercise.source_section_id.is_not(None))
            .group_by(Exercise.source_section_id)
        ).all()
        if section_id is not None
    }
    rows = db.execute(
        select(SourceSection)
        .where(SourceSection.source_id == source.id)
        .order_by(SourceSection.position.asc())
    ).scalars()
    return [source_section_out(r, exercise_count=counts.get(r.id, 0)) for r in rows]


@router.post(
    "/sources/{source_id}/sections/{section_id}/extract",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[AiRateLimit],
)
def extract_source_section(
    source_id: uuid.UUID, section_id: uuid.UUID, school_id: TenantDep, db: DbDep
) -> JobOut:
    """Read one chapter for exercises, on demand.

    Import maps every chapter and indexes every page — both cheap — but only
    transcribes as many chapters as the import budget allows. This is the door
    for the rest, so a 400-page book costs nothing until somebody teaches from
    chapter nineteen. Rate limited with the other model-reaching paths.
    """
    source = _get_source(db, school_id, source_id)
    section = db.execute(
        select(SourceSection)
        .where(SourceSection.id == section_id)
        .where(SourceSection.source_id == source.id)
    ).scalar_one_or_none()
    if section is None:
        raise errors.not_found("source section", id=str(section_id))
    if source.status is not JobStatus.SUCCEEDED:
        raise errors.unprocessable(
            "this document is not indexed yet, so its chapters cannot be read"
        )
    load_optional("alppy.ingest.pipeline", "extract_section", feature="exercise extraction")

    job = Job(
        id=uuid.uuid4(),
        school_id=school_id,
        kind=JobKind.EXTRACT_SECTION,
        status=JobStatus.QUEUED,
        progress=0.0,
        message="queued for extraction",
        payload={"section_id": str(section.id), "source_id": str(source.id)},
    )
    db.add(job)
    # Recorded on the SECTION, not the document: a source has many chapters, and
    # keying these on the source id would collapse them into one line in the
    # agenda — and one row under the log's (kind, subject) identity.
    event_service.record(
        db,
        school_id=school_id,
        kind=EventKind.CHAPTER_READ,
        subject_type=EventSubject.SOURCE,
        subject_id=section.id,
        summary=section.title,
        subject_area_id=source.subject_id,
    )
    db.commit()
    start_job(db, job)
    db.refresh(job)
    return job_out(job)



def _chapter_filter(chapter_id: str) -> Any:
    """A Theme id, or the literal ``none`` for rows the ingest could not tag.

    The sentinel is what makes the builder's counted "Sans thème" bucket
    reachable: absent means "no theme filter", ``none`` means "the untagged
    ones", and without the distinction those exercises would have no selector
    at all now that Theme is the picker's root (D59).
    """
    if chapter_id == UNTAGGED_CHAPTER:
        return Exercise.chapter_id.is_(None)
    try:
        return Exercise.chapter_id == uuid.UUID(chapter_id)
    except ValueError as exc:
        raise errors.unprocessable(
            "chapter_id must be a uuid or 'none'", chapter_id=chapter_id
        ) from exc


def _search_filter(q: str) -> Any:
    """The book's own code and title as well as the statement.

    A teacher looks for "NO64" or "Rectangle coloré" far more often than for a
    phrase from the body. `ilike` rather than a tsvector: even unscoped this is
    one school's corpus, and an index would buy nothing a teacher could
    measure until that is much larger than it is.
    """
    needle = f"%{q.strip()}%"
    return or_(
        Exercise.statement.ilike(needle),
        Exercise.label.ilike(needle),
        Exercise.title.ilike(needle),
    )


def _exercise_page(
    db: Session,
    common: list[Any],
    *,
    type: ExerciseType | None,
    offset: int,
    limit: int,
    order_by: Any,
) -> ExerciseListOut:
    """One page of exercises plus the type facets, from one filter list.

    The page and the facet counts take the SAME conditions, so the two can
    never disagree about what "this filter" means. The facets deliberately
    exclude the type filter: a chip has to report what selecting it would
    give, not what it gives once already selected.
    """
    by_type = {
        kind: int(count)
        for kind, count in db.execute(
            select(Exercise.type, func.count(Exercise.id)).where(*common).group_by(Exercise.type)
        ).all()
    }
    facets = ExerciseFacets(
        total=sum(by_type.values()),
        mcq=by_type.get(ExerciseType.MCQ, 0),
        true_false=by_type.get(ExerciseType.TRUE_FALSE, 0),
        open=by_type.get(ExerciseType.OPEN, 0),
    )

    filtered = [*common, Exercise.type == type] if type is not None else common
    total = int(
        db.scalar(select(func.count()).select_from(Exercise).where(*filtered)) or 0
    )
    rows = db.execute(
        select(Exercise).where(*filtered).order_by(*order_by).offset(offset).limit(limit)
    ).scalars()
    return ExerciseListOut(
        items=[exercise_out(e) for e in rows],
        total=total,
        offset=offset,
        limit=limit,
        facets=facets,
    )


@router.get("/exercises", response_model=ExerciseListOut)
def list_exercises(
    school_id: TenantDep,
    db: DbDep,
    competency_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    source_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    subject_id: Annotated[uuid.UUID | None, Query()] = None,
    chapter_id: Annotated[str | None, Query()] = None,
    type: Annotated[ExerciseType | None, Query()] = None,
    difficulty: Annotated[int | None, Query(ge=1, le=5)] = None,
    origin: Annotated[ExerciseOrigin | None, Query()] = None,
    approved: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ExerciseListOut:
    """The school's whole corpus, filtered — the bank.

    Every exercise was reachable only THROUGH the document it came from, so a
    teacher who wanted "every fractions item at difficulty 2, wherever it came
    from" had to open each source and filter it by hand, and an exercise they
    wrote themselves (no source at all) was reachable from nothing but the
    sheet it was first used on.

    Staffroom-shared, like the documents it reads: scoped to the school and to
    nothing narrower (I-platform-04). `competency_id` and `source_id` repeat.

    `approved=false` is the review queue — the AI-generated items waiting for
    the second look that `Exercise.approved_at` exists to require. Discarded
    rows are never listed, here or anywhere.
    """
    common: list[Any] = [
        Exercise.school_id == school_id,
        Exercise.discarded_at.is_(None),
    ]
    if subject_id is not None:
        common.append(Exercise.subject_id == subject_id)
    if source_id:
        common.append(Exercise.source_id.in_(source_id))
    if chapter_id is not None:
        common.append(_chapter_filter(chapter_id))
    if difficulty is not None:
        common.append(Exercise.difficulty == difficulty)
    if origin is not None:
        common.append(Exercise.origin == origin)
    if approved is not None:
        common.append(
            Exercise.approved_at.is_not(None) if approved else Exercise.approved_at.is_(None)
        )
    if competency_id:
        # The m2m rather than `Exercise.chapter_id`: what an exercise CREDITS,
        # not where it sits. `ix_exercise_competency_competency` is the index
        # this needs — the table's PK leads with `exercise_id` and cannot
        # serve a lookup the other way round.
        common.append(
            Exercise.id.in_(
                select(exercise_competency.c.exercise_id).where(
                    exercise_competency.c.competency_id.in_(competency_id)
                )
            )
        )
    if q and q.strip():
        common.append(_search_filter(q))

    return _exercise_page(
        db,
        common,
        type=type,
        offset=offset,
        limit=limit,
        # Newest first across the whole corpus: `source_page` orders one
        # document and means nothing between two.
        order_by=(Exercise.created_at.desc(), Exercise.id.asc()),
    )


@router.get("/sources/{source_id}/exercises", response_model=ExerciseListOut)
def list_source_exercises(
    source_id: uuid.UUID,
    school_id: TenantDep,
    db: DbDep,
    section_id: Annotated[uuid.UUID | None, Query()] = None,
    chapter_id: Annotated[str | None, Query()] = None,
    type: Annotated[ExerciseType | None, Query()] = None,
    difficulty: Annotated[int | None, Query(ge=1, le=5)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ExerciseListOut:
    """One page of a document's exercises, filtered in the database.

    This used to return every row of the document in a single array. That is
    fine for a worksheet and roughly two megabytes of JSON for a textbook, sent
    through the Worker proxy into a thousand React rows, so both the filter and
    the paging live in Postgres now.

    The type facet counts are computed with every filter applied *except* the
    type itself, so a chip reads what selecting it would actually give.
    """
    source = _get_source(db, school_id, source_id)

    # One list of conditions, applied to both queries: the page and the facet
    # counts must never disagree about what "this filter" means.
    common: list[Any] = [
        Exercise.school_id == school_id,
        Exercise.source_id == source.id,
        Exercise.discarded_at.is_(None),
    ]
    if section_id is not None:
        common.append(Exercise.source_section_id == section_id)
    if chapter_id is not None:
        common.append(_chapter_filter(chapter_id))
    if difficulty is not None:
        common.append(Exercise.difficulty == difficulty)
    if q and q.strip():
        common.append(_search_filter(q))

    return _exercise_page(
        db,
        common,
        type=type,
        offset=offset,
        limit=limit,
        # A document is read in its own order, which is the page it is printed on.
        order_by=(Exercise.source_page.asc(), Exercise.created_at.asc()),
    )


@router.post("/exercises", response_model=ExerciseOut, status_code=status.HTTP_201_CREATED)
def create_exercise(payload: ExerciseCreate, school_id: TenantDep, db: DbDep) -> ExerciseOut:
    """An exercise the teacher wrote themselves, in the sheet builder.

    `ExerciseOrigin.TEACHER`, so it carries no source page to audit against a
    book, wears no mandarin accent, and passes the approval gate by construction.
    It is a real corpus row rather than something sheet-local: `SheetItem` points
    at an `Exercise` with a non-null FK, and the teacher who writes a good
    true/false item should get it back next term.

    The answer/type agreement is enforced in `ExerciseCreate`, not here.
    """
    # Both are school-scoped rows, so both are looked up *within* the tenant.
    # `db.get` by primary key alone would happily accept another school's
    # subject id and file the exercise against it — school_id would be right
    # and the foreign keys would point across the tenant boundary.
    subject = db.execute(
        select(Subject)
        .where(Subject.id == payload.subject_id)
        .where(Subject.school_id == school_id)
    ).scalar_one_or_none()
    if subject is None:
        raise errors.not_found("subject", id=str(payload.subject_id))

    chapter: Chapter | None = None
    if payload.chapter_id is not None:
        chapter = db.execute(
            select(Chapter)
            .where(Chapter.id == payload.chapter_id)
            .where(Chapter.school_id == school_id)
        ).scalar_one_or_none()
        if chapter is None:
            raise errors.not_found("chapter", id=str(payload.chapter_id))

    exercise = Exercise(
        id=uuid.uuid4(),
        school_id=school_id,
        subject_id=payload.subject_id,
        chapter_id=payload.chapter_id,
        type=payload.type,
        origin=ExerciseOrigin.TEACHER,
        language=str(payload.language),
        statement=payload.statement.strip(),
        options=list(payload.options) if payload.options else None,
        answer_index=payload.answer_index,
        answer_bool=payload.answer_bool,
        answer_text=payload.answer_text,
        explanation=payload.explanation,
        difficulty=payload.difficulty,
        # Written by a teacher, so already approved. Leaving this null would
        # make `approval.is_printable` a coin toss on the origin check alone.
        approved_at=datetime.now(UTC),
    )
    if payload.competency_ids:
        exercise.competencies = list(
            db.execute(
                select(Competency).where(Competency.id.in_(payload.competency_ids))
            ).scalars()
        )
    elif chapter is not None and chapter.primary_competency_id is not None:
        # An exercise that credits nothing is invisible to the mastery model:
        # `load_attempt_inputs` INNER JOINs `exercise_competency`, so attempts
        # on an untagged exercise produce no evidence at all — silently. Every
        # sheet a teacher built from their own items therefore scored points in
        # the results matrix and moved no band anywhere.
        #
        # The Theme the teacher filed this under is a stated fact, not the
        # inferred `Exercise.chapter_id` D60 refuses to promote: they picked it
        # in the builder before writing the item. So it credits that Theme's
        # PRIMARY competency — the one node the Competence level rolls up
        # through, resolved per school from `School.default_curriculum` (D56).
        #
        # Deliberately not `chapter.competencies`: that is the tagging set, and
        # a Theme legitimately spans four codes across two curricula, so one
        # hand-written MCQ would land as evidence four times. The textbook
        # ingest credits one competency per exercise and this matches it.
        #
        # The `unfiled` bucket carries no primary, so it still credits nothing.
        primary = db.get(Competency, chapter.primary_competency_id)
        if primary is not None:
            exercise.competencies = [primary]
    db.add(exercise)
    db.commit()
    db.refresh(exercise)
    return exercise_out(exercise)


@router.patch("/exercises/{exercise_id}", response_model=ExerciseOut)
def update_exercise(
    exercise_id: uuid.UUID,
    payload: ExerciseUpdate,
    school_id: TenantDep,
    teacher: TeacherDep,
    db: DbDep,
) -> ExerciseOut:
    """Edit an extracted or generated exercise, and approve it for printing.

    Approval is the gate an AI-generated exercise must pass before it can be
    printed — the teacher is the one who signs off, never the model.

    Two acts here are recorded rather than merely performed (audit 03, B21),
    and `TeacherDep` is present only to name who did them — the gate stays
    tenant-grained, so the flat staffroom (D85) is unchanged:

    * **Approving.** The gate CLAUDE.md calls load-bearing is satisfied by *a*
      teacher, not by the teacher whose class receives the sheet. Under D85
      that is intended; it was not written down, and nothing recorded who
      signed off on an item a model wrote.
    * **Editing an answer key.** `_answer_key` resolves live, so changing
      `answer_index` on Wednesday regrades Tuesday's scans on Thursday. That is
      deliberate for the typo case and undetectable for the mistake case,
      because nothing recorded that the key moved at all.
    """
    exercise = db.execute(
        select(Exercise).where(Exercise.id == exercise_id).where(Exercise.school_id == school_id)
    ).scalar_one_or_none()
    if exercise is None:
        raise errors.not_found("exercise", id=str(exercise_id))

    if payload.statement is not None:
        exercise.statement = payload.statement
    if payload.options is not None:
        exercise.options = payload.options
    if payload.answer_index is not None:
        exercise.answer_index = payload.answer_index
    if payload.answer_bool is not None:
        exercise.answer_bool = payload.answer_bool
    if payload.answer_text is not None:
        exercise.answer_text = payload.answer_text
    if payload.explanation is not None:
        exercise.explanation = payload.explanation
    if payload.difficulty is not None:
        exercise.difficulty = payload.difficulty
    # Read before the write, so "was it already approved" is answerable: a
    # second approval of an approved item is not the moment worth recording.
    was_approved = exercise.approved_at is not None
    key_changed = any(
        value is not None
        for value in (payload.answer_index, payload.answer_bool, payload.answer_text)
    )

    if payload.approved is not None:
        exercise.approved_at = datetime.now(UTC) if payload.approved else None

    if key_changed:
        event_service.record(
            db,
            school_id=school_id,
            kind=EventKind.EXERCISE_EDITED,
            subject_type=EventSubject.EXERCISE,
            subject_id=exercise.id,
            summary=exercise.statement[:200],
            actor_id=teacher.id,
            subject_area_id=exercise.subject_id,
        )
    if payload.approved and not was_approved:
        event_service.record(
            db,
            school_id=school_id,
            kind=EventKind.EXERCISE_APPROVED,
            subject_type=EventSubject.EXERCISE,
            subject_id=exercise.id,
            summary=exercise.statement[:200],
            actor_id=teacher.id,
            subject_area_id=exercise.subject_id,
        )

    db.commit()
    db.refresh(exercise)
    return exercise_out(exercise)


@router.patch("/sources/{source_id}", response_model=SourceOut)
def update_source(
    source_id: uuid.UUID, payload: SourceUpdate, scope: ScopeDep, db: DbDep
) -> SourceOut:
    """Edit a textbook's own metadata.

    Not its `subject_id`: exercises cut from the book carry their own, so
    re-filing the book would leave every exercise behind under the old Branch.
    """
    source = scoped_get(db, Source, source_id, scope.school_id, label="source")
    row = nouns.update_source(
        db,
        scope,
        source,
        title=payload.title,
        language=payload.language,
        publisher=payload.publisher,
        isbn=payload.isbn,
        url=payload.url,
    )
    db.commit()
    return source_out(row)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: uuid.UUID, scope: ScopeDep, db: DbDep) -> None:
    """Remove a textbook. Refused while exercises still cite it.

    `Exercise.source_id` is SET NULL, so this would otherwise succeed and
    quietly strip the provenance from every exercise cut from the book — the
    one thing `ExerciseOrigin.TEXTBOOK` exists to assert. The stored PDF is
    left in place: `Storage` has no `delete`, and this is not the route to
    introduce an untested destructive call on the object store.
    """
    source = scoped_get(db, Source, source_id, scope.school_id, label="source")
    nouns.delete_source(db, scope, source)
    db.commit()
