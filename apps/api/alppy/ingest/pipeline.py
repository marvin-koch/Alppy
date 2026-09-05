"""``ingest_source`` — the whole F1 corpus path in one call.

    extract -> chunk -> embed -> persist chunks -> extract exercises -> persist

It runs inside a worker job (`JobKind.INGEST_SOURCE`), so it owns its
transaction and records its own outcome on the `Source` row: the teacher's
`/sources` screen reads `status`, `page_count`, `language` and `error` and
nothing else.

Two properties this module is responsible for:

**Idempotence, keyed on ``Source.sha256``.** `sha256` identifies the file's
content, so a `Source` that already has chunks and a `SUCCEEDED` status has
already been ingested from exactly these bytes and re-running is a no-op. A
run that failed part-way leaves rows behind; those are deleted and rebuilt
rather than added to. And a *second* upload of a file already ingested in the
same school (same `sha256`, different `Source` row — two teachers, one
textbook) is served by copying the existing chunks and exercises, which costs
no model calls at all.

**A scanned PDF is a reported failure, not an empty success.** See
`extract.ExtractedDocument.has_text`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from alppy.ai.client import AiClient, load_prompt, parse_json_response
from alppy.core.logging import get_logger
from alppy.ingest.chunk import Chunk, chunk_pages
from alppy.ingest.extract import ExtractedDocument, extract_pdf
from alppy.models import Exercise, Source, SourceChunk
from alppy.models.enums import ExerciseOrigin, ExerciseType, JobStatus

log = get_logger(__name__)

NO_TEXT_LAYER_ERROR = (
    "This PDF has no text layer — it looks like a scan of printed pages. "
    "Alppy cannot index it without OCR. Upload a digital (born-text) PDF, or "
    "run the file through an OCR tool first."
)
"""Written for the teacher, not for the log. It appears verbatim in the
`Source.error` field that the /sources screen renders."""

EMBED_BATCH = 32
MAX_EXTRACTION_CHUNKS = 200
"""Ceiling on model calls for one upload. A 400-page book is a background job,
not a licence to spend an afternoon of tokens; the remaining chunks are still
indexed and retrievable, they just contribute no structured exercises."""

DEFAULT_LANGUAGE = "fr"

BytesLoader = Callable[[Source], bytes]


@dataclass(slots=True)
class IngestResult:
    """What happened, for the job record and for tests."""

    source_id: uuid.UUID
    status: JobStatus
    page_count: int
    language: str | None
    chunks_created: int
    exercises_created: int
    reused_from_source_id: uuid.UUID | None = None
    skipped: bool = False
    error: str | None = None


def default_loader(source: Source) -> bytes:
    """Read the uploaded bytes.

    Object storage is another workstream's module; until it lands (and for the
    seed/demo path, which writes files to disk), ``storage_key`` is read as a
    filesystem path. Injecting ``loader`` is the supported way to plug the real
    store in without touching this module.
    """
    path = Path(source.storage_key)
    if not path.exists():
        raise FileNotFoundError(f"no bytes for source {source.id} at {source.storage_key}")
    return path.read_bytes()


def ingest_source(
    db: Session,
    *,
    source_id: uuid.UUID,
    loader: BytesLoader | None = None,
    ai: AiClient | None = None,
    extract_exercises: bool = True,
) -> None:
    """Ingest one uploaded PDF. Safe to re-run.

    The public contract is ``(db, *, source_id) -> None``; the remaining
    keyword arguments have defaults and exist so the worker can inject object
    storage and so tests can run without one.
    """
    run_ingest(
        db,
        source_id=source_id,
        loader=loader,
        ai=ai,
        extract_exercises=extract_exercises,
    )


def run_ingest(
    db: Session,
    *,
    source_id: uuid.UUID,
    loader: BytesLoader | None = None,
    ai: AiClient | None = None,
    extract_exercises: bool = True,
) -> IngestResult:
    """``ingest_source`` with a return value. Same work, reportable."""
    source = db.get(Source, source_id)
    if source is None:
        raise ValueError(f"no source {source_id}")

    already = _existing_chunk_count(db, source.id)
    if source.status is JobStatus.SUCCEEDED and already:
        log.info("ingest.skip.already_done", source_id=str(source.id), chunks=already)
        return IngestResult(
            source_id=source.id,
            status=JobStatus.SUCCEEDED,
            page_count=source.page_count or 0,
            language=source.language,
            chunks_created=0,
            exercises_created=0,
            skipped=True,
        )

    source.status = JobStatus.RUNNING
    source.error = None
    db.flush()

    try:
        twin = _ingested_twin(db, source)
        if twin is not None:
            result = _copy_from_twin(db, source=source, twin=twin)
        else:
            result = _ingest_fresh(
                db,
                source=source,
                loader=loader or default_loader,
                ai=ai,
                extract_exercises=extract_exercises,
            )
    except Exception as exc:
        db.rollback()
        failed = db.get(Source, source_id)
        if failed is not None:
            failed.status = JobStatus.FAILED
            failed.error = f"{type(exc).__name__}: {exc}"[:500]
            db.commit()
        log.warning("ingest.failed", source_id=str(source_id), error=type(exc).__name__)
        raise

    db.commit()
    log.info(
        "ingest.done",
        source_id=str(source_id),
        status=result.status.value,
        chunks=result.chunks_created,
        exercises=result.exercises_created,
    )
    return result


# --------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------
def _ingest_fresh(
    db: Session,
    *,
    source: Source,
    loader: BytesLoader,
    ai: AiClient | None,
    extract_exercises: bool,
) -> IngestResult:
    document = extract_pdf(loader(source))
    source.page_count = document.page_count

    if not document.has_text:
        # Recorded, not swallowed. A Source with zero chunks and a green tick
        # is the failure mode this branch exists to prevent.
        source.language = None
        source.status = JobStatus.FAILED
        source.error = NO_TEXT_LAYER_ERROR
        log.info("ingest.no_text_layer", source_id=str(source.id), pages=document.page_count)
        return IngestResult(
            source_id=source.id,
            status=JobStatus.FAILED,
            page_count=document.page_count,
            language=None,
            chunks_created=0,
            exercises_created=0,
            error=NO_TEXT_LAYER_ERROR,
        )

    source.language = document.language

    _wipe(db, source.id)
    client = ai or AiClient()
    chunks = chunk_pages(document.pages)
    rows = _persist_chunks(db, source=source, chunks=chunks, ai=client)

    created = 0
    if extract_exercises:
        created = _extract_and_persist_exercises(
            db, source=source, chunk_rows=rows, document=document, ai=client
        )

    source.status = JobStatus.SUCCEEDED
    source.error = None
    return IngestResult(
        source_id=source.id,
        status=JobStatus.SUCCEEDED,
        page_count=document.page_count,
        language=document.language,
        chunks_created=len(rows),
        exercises_created=created,
    )


def _persist_chunks(
    db: Session, *, source: Source, chunks: Sequence[Chunk], ai: AiClient
) -> list[SourceChunk]:
    rows: list[SourceChunk] = []
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start : start + EMBED_BATCH]
        vectors = ai.embed([c.text for c in batch])
        for chunk, vector in zip(batch, vectors, strict=True):
            row = SourceChunk(
                id=uuid.uuid4(),
                school_id=source.school_id,
                source_id=source.id,
                page=chunk.page,
                position=chunk.position,
                text=chunk.text,
                embedding=vector,
            )
            db.add(row)
            rows.append(row)
    db.flush()
    return rows


def _extract_and_persist_exercises(
    db: Session,
    *,
    source: Source,
    chunk_rows: Sequence[SourceChunk],
    document: ExtractedDocument,
    ai: AiClient,
) -> int:
    prompt = load_prompt("extract_exercises")
    language = document.language or DEFAULT_LANGUAGE
    seen: set[str] = set()
    created = 0

    for row in chunk_rows[:MAX_EXTRACTION_CHUNKS]:
        try:
            response, _ = ai.complete(
                prompt=prompt,
                purpose="extract_exercises",
                values={"language": language, "page": row.page, "chunk_text": row.text},
                temperature=0.0,
            )
            payload = parse_json_response(response.text)
        except Exception as exc:
            log.info(
                "ingest.extract.chunk_failed",
                source_id=str(source.id),
                page=row.page,
                error=type(exc).__name__,
            )
            continue

        for item in payload.get("exercises") or []:
            exercise = _build_exercise(
                item, source=source, chunk=row, language=language, seen=seen
            )
            if exercise is not None:
                db.add(exercise)
                created += 1

    db.flush()
    return created


def _build_exercise(
    item: object,
    *,
    source: Source,
    chunk: SourceChunk,
    language: str,
    seen: set[str],
) -> Exercise | None:
    """Turn one model-emitted object into an `Exercise`, or reject it.

    Rejection is silent and normal: the prompt is told to return nothing rather
    than invent, and a page of prose legitimately yields zero exercises.
    """
    if not isinstance(item, dict):
        return None
    statement = str(item.get("statement") or "").strip()
    if len(statement) < 8:
        return None
    key = " ".join(statement.lower().split())
    if key in seen:
        return None

    try:
        kind = ExerciseType(str(item.get("type") or "open").strip().lower())
    except ValueError:
        kind = ExerciseType.OPEN

    options = item.get("options")
    options = [str(o) for o in options] if isinstance(options, list) and options else None
    answer_index = item.get("answer_index")
    answer_index = int(answer_index) if isinstance(answer_index, int) else None
    if kind is ExerciseType.MCQ:
        if not options or len(options) < 2:
            return None
        if answer_index is not None and not 0 <= answer_index < len(options):
            answer_index = None
    else:
        options, answer_index = None, None

    answer_bool = item.get("answer_bool")
    answer_bool = answer_bool if isinstance(answer_bool, bool) else None
    if kind is not ExerciseType.TRUE_FALSE:
        answer_bool = None

    seen.add(key)
    return Exercise(
        id=uuid.uuid4(),
        school_id=source.school_id,
        subject_id=source.subject_id,
        source_id=source.id,
        source_chunk_id=chunk.id,
        source_page=chunk.page,
        type=kind,
        origin=ExerciseOrigin.TEXTBOOK,
        language=language,
        statement=statement,
        options=options,
        answer_index=answer_index,
        answer_bool=answer_bool,
        answer_text=_as_text(item.get("answer_text")),
        explanation=_as_text(item.get("explanation")),
        difficulty=_clamp_difficulty(item.get("difficulty")),
        # Textbook exercises are transcriptions, not proposals: no approval gate.
        approved_at=None,
    )


def _as_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _clamp_difficulty(value: object) -> int:
    """Coerce an extracted difficulty into 1..5.

    The value comes from parsed model JSON, so it is genuinely `object`: "3", 3,
    3.0 and nonsense are all possible, and none of them should fail an ingest.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 3
    try:
        return max(1, min(5, int(float(value))))
    except (TypeError, ValueError):
        return 3


# --------------------------------------------------------------------------
# Idempotence helpers
# --------------------------------------------------------------------------
def _existing_chunk_count(db: Session, source_id: uuid.UUID) -> int:
    return len(list(db.scalars(select(SourceChunk.id).where(SourceChunk.source_id == source_id))))


def _wipe(db: Session, source_id: uuid.UUID) -> None:
    """Remove what a previous partial run left, so a re-run rebuilds cleanly.

    Only rows this pipeline created: textbook exercises from this source. An
    AI-generated exercise never has a `source_id`, and a teacher's own edits
    live on the `SheetItem`, so nothing hand-made is at risk here.
    """
    db.execute(
        delete(Exercise).where(
            Exercise.source_id == source_id,
            Exercise.origin == ExerciseOrigin.TEXTBOOK,
        )
    )
    db.execute(delete(SourceChunk).where(SourceChunk.source_id == source_id))
    db.flush()


def _ingested_twin(db: Session, source: Source) -> Source | None:
    """An already-ingested source with the same bytes, in the same school."""
    return db.scalars(
        select(Source)
        .where(
            Source.school_id == source.school_id,
            Source.sha256 == source.sha256,
            Source.id != source.id,
            Source.status == JobStatus.SUCCEEDED,
        )
        .limit(1)
    ).first()


def _copy_from_twin(db: Session, *, source: Source, twin: Source) -> IngestResult:
    """Reuse an identical upload: same bytes, same chunks, zero model calls."""
    _wipe(db, source.id)
    chunk_map: dict[uuid.UUID, uuid.UUID] = {}

    twin_chunks = list(
        db.scalars(
            select(SourceChunk)
            .where(SourceChunk.source_id == twin.id)
            .order_by(SourceChunk.position)
        )
    )
    for old_chunk in twin_chunks:
        new_id = uuid.uuid4()
        chunk_map[old_chunk.id] = new_id
        db.add(
            SourceChunk(
                id=new_id,
                school_id=source.school_id,
                source_id=source.id,
                page=old_chunk.page,
                position=old_chunk.position,
                text=old_chunk.text,
                embedding=old_chunk.embedding,
            )
        )

    twin_exercises = list(
        db.scalars(
            select(Exercise).where(
                Exercise.source_id == twin.id,
                Exercise.origin == ExerciseOrigin.TEXTBOOK,
            )
        )
    )
    for old_exercise in twin_exercises:
        db.add(
            Exercise(
                id=uuid.uuid4(),
                school_id=source.school_id,
                subject_id=source.subject_id,
                chapter_id=old_exercise.chapter_id,
                source_id=source.id,
                source_chunk_id=chunk_map.get(old_exercise.source_chunk_id) if old_exercise.source_chunk_id else None,
                source_page=old_exercise.source_page,
                type=old_exercise.type,
                origin=ExerciseOrigin.TEXTBOOK,
                language=old_exercise.language,
                statement=old_exercise.statement,
                options=old_exercise.options,
                answer_index=old_exercise.answer_index,
                answer_bool=old_exercise.answer_bool,
                answer_text=old_exercise.answer_text,
                explanation=old_exercise.explanation,
                difficulty=old_exercise.difficulty,
            )
        )

    source.page_count = twin.page_count
    source.language = twin.language
    source.status = JobStatus.SUCCEEDED
    source.error = None
    db.flush()
    log.info("ingest.reused", source_id=str(source.id), twin_id=str(twin.id))
    return IngestResult(
        source_id=source.id,
        status=JobStatus.SUCCEEDED,
        page_count=twin.page_count or 0,
        language=twin.language,
        chunks_created=len(twin_chunks),
        exercises_created=len(twin_exercises),
        reused_from_source_id=twin.id,
    )
