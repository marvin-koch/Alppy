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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from alppy.ai.audit import flush as flush_ai_log
from alppy.ai.client import AiClient, load_prompt, parse_json_response
from alppy.core.logging import get_logger
from alppy.ingest.chunk import Chunk, chunk_pages
from alppy.ingest.extract import ExtractedDocument, PdfExtractionError, extract_pdf
from alppy.ingest.regions import (
    ExerciseRegion,
    detect_exercise_regions,
    iter_region_images,
    read_outline,
)
from alppy.ingest.sections import detect_sections, sections_from_outline
from alppy.models import (
    Chapter,
    Competency,
    Exercise,
    Source,
    SourceChunk,
    SourceSection,
    chapter_competency,
)
from alppy.models.enums import ExerciseOrigin, ExerciseType, JobStatus
from alppy.storage import Storage, get_storage, storage_key

log = get_logger(__name__)

NO_TEXT_LAYER_ERROR = (
    "This PDF has no text layer — it looks like a scan of printed pages. "
    "Alppy cannot index it without OCR. Upload a digital (born-text) PDF, or "
    "run the file through an OCR tool first."
)
"""Written for the teacher, not for the log. It appears verbatim in the
`Source.error` field that the /sources screen renders."""

UNREADABLE_PDF_ERROR = (
    "Alppy could not read this PDF. It may be damaged, password-protected, or "
    "not really a PDF. Try exporting it again and re-uploading."
)
"""Teacher-facing, like `NO_TEXT_LAYER_ERROR`."""

UNEXPECTED_INGEST_ERROR = (
    "Indexing this book failed unexpectedly. Nothing was saved, so you can "
    "upload it again. If it keeps failing, the file itself is probably the "
    "problem rather than anything you did."
)
"""What the teacher is told when we do not recognise the failure.

`Source.error` is rendered verbatim on the /sources screen, so it may only
ever hold a sentence written for a teacher. It used to hold
``f"{type(exc).__name__}: {exc}"``, which for a database failure is the
failing SQL and its column names, for an ``OSError`` the server's absolute
paths, and for a botocore failure the bucket and its endpoint — printed on a
screen that spends a good deal of its life projected onto a classroom wall.
The diagnostic is not lost; it goes to the log, with a traceback."""

EMBED_BATCH = 32
MAX_EXTRACTION_CHUNKS = 200
"""Ceiling on model calls made *eagerly*, at import. A 400-page book is a
background job, not a licence to spend an afternoon of tokens.

This used to be the end of the story: chunks past the ceiling were indexed,
never transcribed, and the teacher was told to split the file by hand. Sections
changed that. Import now walks the document's own chapters in order and extracts
while this budget lasts, so anything that fitted before still arrives complete at
import — a worksheet, a single chapter, every test fixture. What used to fall off
the end now simply waits: the remaining sections carry ``extracted_at IS NULL``
and are read the first time a teacher opens one (``extract_section``)."""

MAX_SECTION_CHUNKS = 200
"""Ceiling for one on-demand section. A section this long is a book with no
usable headings, in which case the fallback section is the whole document and
this is the old per-upload cap under a new name."""

NO_GROUNDED_MODEL_NOTICE = (
    "Indexed for search, but no exercises were extracted: this deployment has no "
    "model configured that can read the document. Set ALPPY_AI_CHAT_PROVIDER and "
    "an API key, then re-upload to extract exercises."
)
"""Shown to the teacher on a *successful* ingest. The offline stand-in does not
read the prompt, so letting it "extract" would file invented exercises under
this teacher's filename and page numbers, with nothing marking them as written
by a model. Indexing still happens; only transcription is refused."""


def _chunk_cap_notice(extracted: int, total: int) -> str:
    """No longer an apology for a truncated book.

    The rest of the document is one click away rather than needing the teacher
    to split the PDF, so this says what *will* happen, not what failed to.
    """
    remaining = total - extracted
    return (
        f"Indexed the whole document. {extracted} of {total} chapters were read for "
        f"exercises straight away; the remaining {remaining} are read the first time "
        f"you open them in the sheet builder."
    )


def _section_cap_notice(scanned: int, total: int) -> str:
    return (
        f"Only the first {scanned} of {total} sections of this chapter were read for "
        f"exercises (per-chapter limit). The rest stays searchable."
    )


REGIONS_UNTAGGED_NOTICE = (
    "Exercises were read from the page layout, with a picture of each one. They "
    "are not yet classified or tagged with competencies: this deployment has no "
    "model configured that can read the document. Set ALPPY_AI_CHAT_PROVIDER and "
    "an API key, then open a chapter in the sheet builder to tag it."
)
"""A region-based ingest without a grounded model. Unlike the chunk path this
is *not* an empty result: every exercise exists, is searchable and prints with
its figure. What is missing is the classification, so the section keeps
offering its button and says why."""


def _regions_cap_notice(tagged: int, total: int) -> str:
    remaining = total - tagged
    return (
        f"Read every exercise from the page layout, with a picture of each one. "
        f"{tagged} of {total} chapters were classified and tagged straight away; "
        f"the remaining {remaining} are tagged the first time you open them in the "
        f"sheet builder."
    )


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


@dataclass(slots=True)
class SectionExtractionResult:
    """What one on-demand section extraction did, for the job record.

    ``skipped`` covers both harmless cases — already read, or no grounded model
    configured — and they are told apart by ``notice``."""

    section_id: uuid.UUID
    exercises_created: int
    exercises_total: int
    skipped: bool = False
    notice: str | None = None


def default_loader(source: Source) -> bytes:
    """Read the uploaded bytes for a source.

    ``storage_key`` is an object-storage key, because that is what
    ``POST /sources`` writes (``alppy.storage.storage_key``). Object storage is
    tried first and the filesystem second, so a key that happens to name a real
    file — the seed corpus, a fixture, a developer poking at a local path — still
    resolves.

    Reading the filesystem *first* is what made every ingestion job fail with
    ``FileNotFoundError`` while the bytes sat in MinIO, so the order here
    matters. Injecting ``loader`` remains the supported way to substitute a
    store in tests.
    """
    try:
        from alppy import storage as object_storage
    except ImportError:  # pragma: no cover - storage is a hard dependency
        object_storage = None  # type: ignore[assignment]

    if object_storage is not None:
        try:
            return bytes(object_storage.get_storage().get_bytes(source.storage_key))
        except Exception as exc:
            log.info(
                "ingest.storage_miss",
                source_id=str(source.id),
                key=source.storage_key,
                error=type(exc).__name__,
            )

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
    storage: Storage | None = None,
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
        storage=storage,
    )


def _teacher_facing_error(exc: BaseException) -> str:
    """The only thing allowed to reach ``Source.error``.

    One known failure has a sentence worth showing — the file would not open —
    and everything else gets the generic one. Widening this map is fine;
    passing an exception's own text through it is not."""
    if isinstance(exc, PdfExtractionError):
        return UNREADABLE_PDF_ERROR
    return UNEXPECTED_INGEST_ERROR


def run_ingest(
    db: Session,
    *,
    source_id: uuid.UUID,
    loader: BytesLoader | None = None,
    ai: AiClient | None = None,
    extract_exercises: bool = True,
    storage: Storage | None = None,
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
                storage=storage,
            )
    except Exception as exc:
        db.rollback()
        failed = db.get(Source, source_id)
        if failed is not None:
            failed.status = JobStatus.FAILED
            failed.error = _teacher_facing_error(exc)
            db.commit()
        log.warning(
            "ingest.failed",
            source_id=str(source_id),
            error=type(exc).__name__,
            exc_info=exc,
        )
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
    storage: Storage | None,
) -> IngestResult:
    data = loader(source)
    document = extract_pdf(data)
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
    sections = _persist_sections(
        db, source=source, document=document, outline=_outline_entries(data)
    )

    created = 0
    notice: str | None = None
    if extract_exercises:
        # The page layout first: a book that codes its exercises yields every
        # one of them, with a picture, and no model in the loop. Only a book
        # that does not is transcribed from its text layer.
        regions = _safe_regions(data, source)
        if regions:
            created, notice = _extract_regions_eagerly(
                db,
                source=source,
                sections=sections,
                regions=regions,
                data=data,
                language=document.language or DEFAULT_LANGUAGE,
                ai=client,
                storage=storage or get_storage(),
            )
        else:
            created, notice = _extract_eagerly(
                db,
                source=source,
                sections=sections,
                chunk_rows=rows,
                document=document,
                ai=client,
            )

    source.status = JobStatus.SUCCEEDED
    source.error = None
    source.notice = notice

    # Every model call this ingest made, on the record. No prompt content and
    # no student name reaches the row; see alppy.ai.audit.
    flush_ai_log(db, school_id=source.school_id, ai=client)

    return IngestResult(
        source_id=source.id,
        status=JobStatus.SUCCEEDED,
        page_count=document.page_count,
        language=document.language,
        chunks_created=len(rows),
        exercises_created=created,
    )


def _outline_entries(data: bytes) -> list[tuple[int, str, int]]:
    return [(e.level, e.title, e.page) for e in read_outline(data)]


def _safe_regions(data: bytes, source: Source) -> list[ExerciseRegion]:
    """The coded exercises of the document, or none.

    A failure here must not fail the ingest: the text path is a complete
    fallback, and a book whose geometry the detector cannot read is still a
    book worth indexing."""
    try:
        return detect_exercise_regions(data)
    except Exception as exc:
        log.warning("ingest.regions.failed", source_id=str(source.id), error=type(exc).__name__)
        return []


def _persist_sections(
    db: Session,
    *,
    source: Source,
    document: ExtractedDocument,
    outline: Sequence[tuple[int, str, int]] = (),
) -> list[SourceSection]:
    """Write the document's own outline. Always at least one row.

    The file's bookmarks win when it has them; ``detect_sections`` is the
    heuristic for a file that has none. Both guarantee the sections are
    contiguous and cover every page, so an exercise extracted from any page has
    a section to belong to. That is the whole point: the competency-derived
    ``chapter_id`` is allowed to be NULL, and the builder's primary filter must
    never be.
    """
    pages = list(document.pages)
    detected = (
        sections_from_outline(outline, first_page=pages[0].page, last_page=pages[-1].page)
        if pages and outline
        else []
    )
    if not detected:
        detected = detect_sections(pages)
    rows: list[SourceSection] = []
    for section in detected:
        row = SourceSection(
            id=uuid.uuid4(),
            school_id=source.school_id,
            source_id=source.id,
            title=section.title[:300],
            label=section.label,
            page_from=section.page_from,
            page_to=section.page_to,
            position=section.position,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    log.info("ingest.sections", source_id=str(source.id), sections=len(rows))
    return rows


def _chunks_in(chunk_rows: Sequence[SourceChunk], section: SourceSection) -> list[SourceChunk]:
    """The indexed chunks that fall inside a section's page range."""
    return [c for c in chunk_rows if section.page_from <= c.page <= section.page_to]


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


EXTRACT_PROMPT_VERSION = "v2"
"""v2 asks the model to tag each exercise with competency codes from a closed
catalogue. v1 is kept on disk: a `Source` ingested under it has untagged rows,
and knowing which prompt produced them is how you tell that apart from a model
that simply found no match."""


def _resolve_competencies(item: object, by_code: dict[str, Competency]) -> list[Competency]:
    """Map the model's returned codes onto real rows, dropping anything unknown.

    Silently dropping is right: the prompt supplies a closed list, so a code
    outside it is a model error, and an exercise tagged with a competency the
    curriculum does not have would corrupt the mastery matrix.
    """
    if not isinstance(item, dict):
        return []
    codes = item.get("competency_codes")
    if not isinstance(codes, list):
        return []
    out: list[Competency] = []
    for code in codes:
        row = by_code.get(str(code).strip())
        if row is not None and row not in out:
            out.append(row)
    return out


def _competency_catalogue(db: Session, source: Source) -> tuple[str, dict[str, Competency]]:
    """The competencies this subject's chapters actually ask for.

    Offered to the model as a closed list so tagging is a *choice from the
    curriculum*, not free text we would then have to guess at. Returns the
    prompt block and a code -> row map for resolving what comes back.
    """
    rows = list(
        db.scalars(
            select(Competency)
            .join(chapter_competency, chapter_competency.c.competency_id == Competency.id)
            .join(Chapter, Chapter.id == chapter_competency.c.chapter_id)
            .where(Chapter.school_id == source.school_id)
            .where(Chapter.subject_id == source.subject_id)
            .distinct()
        )
    )
    by_code = {r.code: r for r in rows}
    lines = [f"- {r.code} — {_competency_label(r)}" for r in sorted(rows, key=lambda r: r.code)]
    return ("\n".join(lines) or "- (none configured)"), by_code


def _competency_label(row: Competency) -> str:
    labels = getattr(row, "labels", None) or {}
    if isinstance(labels, dict) and labels:
        return str(labels.get("fr") or labels.get("de") or labels.get("en") or row.code)
    return str(getattr(row, "title", None) or row.code)


def _chapter_for(db: Session, source: Source, competencies: list[Competency]) -> uuid.UUID | None:
    """The chapter that best covers these competencies.

    An exercise belongs to the chapter that asks for most of what it practises.
    Without this the row is untagged, and an untagged exercise is invisible to
    the builder's chapter filter — which is the only way a teacher finds it.
    """
    if not competencies:
        return None
    ids = {c.id for c in competencies}
    best: tuple[int, int, uuid.UUID] | None = None
    chapters = db.scalars(
        select(Chapter)
        .where(Chapter.school_id == source.school_id)
        .where(Chapter.subject_id == source.subject_id)
    )
    for chapter in chapters:
        overlap = len({c.id for c in chapter.competencies} & ids)
        if overlap:
            # Most overlap wins; ties break on chapter order, so the result is
            # stable rather than dependent on row order.
            candidate = (overlap, -chapter.position, chapter.id)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
    return best[2] if best else None


def _extract_eagerly(
    db: Session,
    *,
    source: Source,
    sections: Sequence[SourceSection],
    chunk_rows: Sequence[SourceChunk],
    document: ExtractedDocument,
    ai: AiClient,
) -> tuple[int, str | None]:
    """Read as many sections as the import budget allows, in book order.

    A document small enough to have fitted under the old per-upload ceiling is
    still fully extracted here, so nothing that worked before now needs a click.
    A big one gets its opening chapters and leaves the rest marked unread, which
    is the state the builder offers an "Extract" button for.
    """
    if not ai.chat_is_grounded:
        log.info("ingest.extract.skipped_ungrounded", source_id=str(source.id))
        return 0, NO_GROUNDED_MODEL_NOTICE

    language = document.language or DEFAULT_LANGUAGE
    budget = MAX_EXTRACTION_CHUNKS
    created = 0
    done = 0

    for section in sections:
        in_section = _chunks_in(chunk_rows, section)
        # Stop *before* a section that will not fit whole. Half a chapter is the
        # worst outcome available: the teacher sees exercises and has no way to
        # tell that the back half of the chapter is missing. The first section
        # is exempt — a document with no usable headings is one section, and
        # refusing to read any of it would be a regression on today's behaviour.
        if done and len(in_section) > budget:
            break
        made, _ = _extract_into_section(
            db,
            source=source,
            section=section,
            chunk_rows=in_section,
            language=language,
            ai=ai,
        )
        created += made
        budget -= len(in_section)
        done += 1
        if budget <= 0:
            break

    notice = _chunk_cap_notice(done, len(sections)) if done < len(sections) else None
    return created, notice


def _extract_into_section(
    db: Session,
    *,
    source: Source,
    section: SourceSection,
    chunk_rows: Sequence[SourceChunk],
    language: str,
    ai: AiClient,
) -> tuple[int, str | None]:
    """Transcribe one section's chunks into `Exercise` rows.

    Stamps ``extracted_at`` even when the section yielded nothing: "read, and
    there was nothing here" and "never read" are different states, and only the
    second one should offer the teacher a button.
    """
    prompt = load_prompt("extract_exercises", version=EXTRACT_PROMPT_VERSION)
    catalogue, by_code = _competency_catalogue(db, source)
    seen = _existing_statements(db, source)
    created = 0

    for row in chunk_rows[:MAX_SECTION_CHUNKS]:
        try:
            response, _ = ai.complete(
                prompt=prompt,
                purpose="extract_exercises",
                values={
                    "language": language,
                    "page": row.page,
                    "chunk_text": row.text,
                    "competency_catalogue": catalogue,
                },
                # Transcription must be reproducible: same page, same rows.
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
            if exercise is None:
                continue
            exercise.source_section_id = section.id
            tagged = _resolve_competencies(item, by_code)
            exercise.competencies = tagged
            exercise.chapter_id = _chapter_for(db, source, tagged)
            db.add(exercise)
            created += 1

    section.extracted_at = datetime.now(UTC)
    section.extraction_notice = (
        _section_cap_notice(MAX_SECTION_CHUNKS, len(chunk_rows))
        if len(chunk_rows) > MAX_SECTION_CHUNKS
        else None
    )
    db.flush()
    return created, section.extraction_notice


# --------------------------------------------------------------------------
# The layout path: coded exercises, cut from the page
# --------------------------------------------------------------------------
def _regions_in(regions: Sequence[ExerciseRegion], section: SourceSection) -> list[ExerciseRegion]:
    return [r for r in regions if section.page_from <= r.page <= section.page_to]


def _figure_key(source: Source, region: ExerciseRegion) -> str:
    return storage_key("figures", source.school_id, source.id, f"p{region.page:03d}-{region.label}.png")


def _extract_regions_eagerly(
    db: Session,
    *,
    source: Source,
    sections: Sequence[SourceSection],
    regions: Sequence[ExerciseRegion],
    data: bytes,
    language: str,
    ai: AiClient,
    storage: Storage,
) -> tuple[int, str | None]:
    """Every coded exercise becomes a row now; the model runs while the budget lasts.

    Cutting a region out of the page costs nothing a teacher would notice, so
    all of them land at import — searchable, printable with their figure —
    whatever the model situation. Classification and competency tagging are the
    model's part, and they follow the same per-import budget and the same
    "whole chapters only" rule as the text path. A chapter past the budget keeps
    its rows and its button.
    """
    created = 0
    for section in sections:
        created += _persist_regions_into_section(
            db,
            source=source,
            section=section,
            regions=_regions_in(regions, section),
            data=data,
            language=language,
            storage=storage,
        )
    db.flush()

    if not ai.chat_is_grounded:
        log.info("ingest.regions.untagged", source_id=str(source.id), exercises=created)
        for section in sections:
            section.extraction_notice = REGIONS_UNTAGGED_NOTICE
        return created, REGIONS_UNTAGGED_NOTICE

    budget = MAX_EXTRACTION_CHUNKS
    done = 0
    for section in sections:
        in_section = _regions_in(regions, section)
        if done and len(in_section) > budget:
            break
        _enrich_section(db, source=source, section=section, language=language, ai=ai)
        budget -= len(in_section)
        done += 1
        if budget <= 0:
            break

    notice = _regions_cap_notice(done, len(sections)) if done < len(sections) else None
    return created, notice


def _persist_regions_into_section(
    db: Session,
    *,
    source: Source,
    section: SourceSection,
    regions: Sequence[ExerciseRegion],
    data: bytes,
    language: str,
    storage: Storage,
) -> int:
    """One `Exercise` per region, with its crop in object storage.

    The statement is the region's own text, so the builder's search and the
    sheet's alt text say what the picture says. An exercise that is *only* a
    figure keeps its title as the statement rather than an empty string.
    """
    if not regions:
        return 0
    created = 0
    for region, image in iter_region_images(data, regions):
        key = _figure_key(source, region)
        storage.put_bytes(key, image.png, "image/png")
        statement = region.text or region.title
        db.add(
            Exercise(
                id=uuid.uuid4(),
                school_id=source.school_id,
                subject_id=source.subject_id,
                source_id=source.id,
                source_section_id=section.id,
                source_page=region.page,
                label=region.label[:16],
                title=region.title[:200],
                figure_key=key,
                figure_width_mm=round(image.width_mm, 2),
                figure_height_mm=round(image.height_mm, 2),
                type=ExerciseType.OPEN,
                origin=ExerciseOrigin.TEXTBOOK,
                language=language,
                statement=statement,
                difficulty=3,
                approved_at=None,
            )
        )
        created += 1
    log.info(
        "ingest.regions.section",
        source_id=str(source.id),
        section=section.title,
        exercises=created,
    )
    return created


def _region_exercises(db: Session, section: SourceSection) -> list[Exercise]:
    """The rows the layout path wrote for this section, in book order."""
    return list(
        db.scalars(
            select(Exercise)
            .where(
                Exercise.source_section_id == section.id,
                Exercise.origin == ExerciseOrigin.TEXTBOOK,
                Exercise.label.is_not(None),
            )
            .order_by(Exercise.source_page, Exercise.label)
        )
    )


def _enrich_section(
    db: Session,
    *,
    source: Source,
    section: SourceSection,
    language: str,
    ai: AiClient,
) -> int:
    """Ask the model what each exercise *is*, never what it says.

    The statement, label, title and figure are facts read off the page and are
    not the model's to change. What the model adds is the classification — is
    this a choice, a true/false, an open question — the answer key if the page
    states one, a difficulty, and the competency codes from the closed
    catalogue. The prompt is the same transcription prompt as the text path,
    fed one exercise at a time; a model that returns nothing for an exercise
    leaves it as it was: open, untagged, still printable.
    """
    exercises = _region_exercises(db, section)
    prompt = load_prompt("extract_exercises", version=EXTRACT_PROMPT_VERSION)
    catalogue, by_code = _competency_catalogue(db, source)
    tagged = 0

    for exercise in exercises[:MAX_SECTION_CHUNKS]:
        text = f"{exercise.label} {exercise.title}\n{exercise.statement}"
        try:
            response, _ = ai.complete(
                prompt=prompt,
                purpose="extract_exercises",
                values={
                    "language": language,
                    "page": exercise.source_page,
                    "chunk_text": text,
                    "competency_catalogue": catalogue,
                },
                temperature=0.0,
            )
            payload = parse_json_response(response.text)
        except Exception as exc:
            log.info(
                "ingest.enrich.failed",
                source_id=str(source.id),
                label=exercise.label,
                error=type(exc).__name__,
            )
            continue
        items = payload.get("exercises") or []
        if not items:
            continue
        _apply_classification(exercise, items[0])
        competencies = _resolve_competencies(items[0], by_code)
        exercise.competencies = competencies
        exercise.chapter_id = _chapter_for(db, source, competencies)
        tagged += 1

    section.extracted_at = datetime.now(UTC)
    section.extraction_notice = (
        _section_cap_notice(MAX_SECTION_CHUNKS, len(exercises))
        if len(exercises) > MAX_SECTION_CHUNKS
        else None
    )
    db.flush()
    return tagged


def _apply_classification(exercise: Exercise, item: object) -> None:
    """Copy the model's type, options, key and difficulty onto a layout row.

    Same validation as ``_build_exercise``, with one difference in outcome: a
    text-path item that fails it is dropped, whereas a layout row already
    exists and is worth keeping — it stays open and untagged.
    """
    if not isinstance(item, dict):
        return
    classified = _coerce_classification(item) or (ExerciseType.OPEN, None, None, None)
    kind, options, answer_index, answer_bool = classified

    exercise.type = kind
    exercise.options = options
    exercise.answer_index = answer_index
    exercise.answer_bool = answer_bool
    exercise.answer_text = _as_text(item.get("answer_text"))
    exercise.explanation = _as_text(item.get("explanation"))
    exercise.difficulty = _clamp_difficulty(item.get("difficulty"))


def _existing_statements(db: Session, source: Source) -> set[str]:
    """Statements already transcribed from this document.

    De-duplication used to be per-run, which was enough while a document was
    extracted exactly once. Sections are extracted separately and their page
    ranges abut, so a chunk carrying the tail of one chapter and the head of the
    next can offer the same exercise twice. Seeding from the database keeps the
    guarantee across runs.
    """
    rows = db.scalars(
        select(Exercise.statement).where(
            Exercise.source_id == source.id,
            Exercise.origin == ExerciseOrigin.TEXTBOOK,
        )
    )
    return {" ".join(str(s).lower().split()) for s in rows}


def extract_section(
    db: Session, *, section_id: uuid.UUID, ai: AiClient | None = None
) -> SectionExtractionResult:
    """Read one section on demand. The worker's entry point.

    Idempotent by short-circuit: a section already carrying ``extracted_at`` is
    returned untouched rather than transcribed twice, so a double-click costs
    nothing and cannot duplicate rows.
    """
    section = db.get(SourceSection, section_id)
    if section is None:
        raise ValueError(f"no source section {section_id}")
    source = db.get(Source, section.source_id)
    if source is None:
        raise ValueError(f"section {section_id} points at a source that no longer exists")

    if section.extracted_at is not None:
        existing = db.scalar(
            select(func.count())
            .select_from(Exercise)
            .where(Exercise.source_section_id == section.id)
        )
        return SectionExtractionResult(
            section_id=section.id,
            exercises_created=0,
            exercises_total=int(existing or 0),
            skipped=True,
            notice=section.extraction_notice,
        )

    client = ai or AiClient()
    layout_rows = _region_exercises(db, section)
    if not client.chat_is_grounded:
        # Do NOT stamp extracted_at: nothing was read, and the section must keep
        # offering its button once a model is configured.
        return SectionExtractionResult(
            section_id=section.id,
            exercises_created=0,
            exercises_total=len(layout_rows),
            skipped=True,
            notice=REGIONS_UNTAGGED_NOTICE if layout_rows else NO_GROUNDED_MODEL_NOTICE,
        )

    if layout_rows:
        # The exercises already exist — the layout path wrote them at import.
        # What this section is waiting for is the model's classification.
        tagged = _enrich_section(
            db,
            source=source,
            section=section,
            language=source.language or DEFAULT_LANGUAGE,
            ai=client,
        )
        flush_ai_log(db, school_id=source.school_id, ai=client)
        db.commit()
        log.info(
            "ingest.section.tagged",
            section_id=str(section.id),
            source_id=str(source.id),
            tagged=tagged,
            exercises=len(layout_rows),
        )
        return SectionExtractionResult(
            section_id=section.id,
            exercises_created=0,
            exercises_total=len(layout_rows),
            skipped=False,
            notice=section.extraction_notice,
        )

    chunk_rows = list(
        db.scalars(
            select(SourceChunk)
            .where(
                SourceChunk.source_id == source.id,
                SourceChunk.page >= section.page_from,
                SourceChunk.page <= section.page_to,
            )
            .order_by(SourceChunk.position)
        )
    )
    created, notice = _extract_into_section(
        db,
        source=source,
        section=section,
        chunk_rows=chunk_rows,
        language=source.language or DEFAULT_LANGUAGE,
        ai=client,
    )
    flush_ai_log(db, school_id=source.school_id, ai=client)
    db.commit()
    log.info(
        "ingest.section.extracted",
        section_id=str(section.id),
        source_id=str(source.id),
        exercises=created,
    )
    return SectionExtractionResult(
        section_id=section.id,
        exercises_created=created,
        exercises_total=created,
        skipped=False,
        notice=notice,
    )


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

    classified = _coerce_classification(item)
    if classified is None:
        return None
    kind, options, answer_index, answer_bool = classified

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


def _coerce_classification(
    item: dict[str, Any],
) -> tuple[ExerciseType, list[str] | None, int | None, bool | None] | None:
    """``(type, options, answer_index, answer_bool)`` from model JSON, or ``None``.

    An MCQ needs at least two options and an index inside them — without the
    options it is not an MCQ at all, and ``None`` says so. A true/false keeps
    its boolean and nothing else; an open item keeps neither.
    """
    try:
        kind = ExerciseType(str(item.get("type") or "open").strip().lower())
    except ValueError:
        kind = ExerciseType.OPEN

    raw_options = item.get("options")
    options = (
        [str(o) for o in raw_options] if isinstance(raw_options, list) and raw_options else None
    )
    raw_index = item.get("answer_index")
    answer_index = int(raw_index) if isinstance(raw_index, int) else None
    if kind is ExerciseType.MCQ:
        if not options or len(options) < 2:
            return None
        if answer_index is not None and not 0 <= answer_index < len(options):
            answer_index = None
    else:
        options, answer_index = None, None

    raw_bool = item.get("answer_bool")
    answer_bool = raw_bool if isinstance(raw_bool, bool) and kind is ExerciseType.TRUE_FALSE else None
    return kind, options, answer_index, answer_bool


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
    # Sections last: Exercise.source_section_id is ON DELETE SET NULL, so
    # dropping them before the exercises would quietly detach rows we are about
    # to delete anyway, and dropping them after keeps the order readable.
    db.execute(delete(SourceSection).where(SourceSection.source_id == source_id))
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
    section_map: dict[uuid.UUID, uuid.UUID] = {}

    # The outline is part of what makes the copy usable: without it the twin's
    # exercises would land with a null section and vanish from the builder's
    # primary filter, which is exactly the failure this axis exists to avoid.
    twin_sections = list(
        db.scalars(
            select(SourceSection)
            .where(SourceSection.source_id == twin.id)
            .order_by(SourceSection.position)
        )
    )
    for old_section in twin_sections:
        new_id = uuid.uuid4()
        section_map[old_section.id] = new_id
        db.add(
            SourceSection(
                id=new_id,
                school_id=source.school_id,
                source_id=source.id,
                title=old_section.title,
                label=old_section.label,
                page_from=old_section.page_from,
                page_to=old_section.page_to,
                position=old_section.position,
                extracted_at=old_section.extracted_at,
                extraction_notice=old_section.extraction_notice,
            )
        )

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
                # The tags travel with the chapter they derived: a copy with
                # the chapter but no competencies reads as untagged to the
                # mastery matrix and the competency filter.
                competencies=list(old_exercise.competencies),
                source_id=source.id,
                source_chunk_id=chunk_map.get(old_exercise.source_chunk_id) if old_exercise.source_chunk_id else None,
                source_section_id=(
                    section_map.get(old_exercise.source_section_id)
                    if old_exercise.source_section_id
                    else None
                ),
                source_page=old_exercise.source_page,
                label=old_exercise.label,
                title=old_exercise.title,
                # Same bytes, same crop. Keys are per school and nothing deletes
                # an object, so sharing the figure between the twins is safe.
                figure_key=old_exercise.figure_key,
                figure_width_mm=old_exercise.figure_width_mm,
                figure_height_mm=old_exercise.figure_height_mm,
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
    source.notice = twin.notice
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
