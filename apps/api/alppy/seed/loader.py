"""Load ``seed/data/*.json`` into the database. Idempotent, and loud on a bad reference.

Two entry points:

* ``load_reference_data`` — subjects, competencies (two curricula, hierarchical),
  chapters. Curriculum data is shared reference data and is not school-scoped;
  subjects and chapters are.
* ``load_demo_corpus`` — the 63 self-authored exercises. These are loaded as a
  real `Source` with real `SourceChunk` rows, embedded exactly like an uploaded
  PDF, rather than as bare `Exercise` rows. That is deliberate: it means the
  demo corpus exercises retrieval, provenance and the adaptive path through the
  *same* code as a teacher's own upload, so the demo cannot pass while the
  product is broken.

Idempotence is by natural key at every level — `Subject.key`, `Competency.code`
within a curriculum, `Chapter.key`, and `(source_id, position)` for a chunk and
its exercise. Running the loader twice updates in place; it never duplicates.

Validation happens as the data is read, and a failure names the offending key:
"chapter 'fractions' references unknown competency code 'MSN 99.9'" is
actionable, "IntegrityError: null value in column competency_id" is not.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.ai.client import AiClient
from alppy.core.logging import get_logger
from alppy.models import (
    UNFILED_CHAPTER_KEY,
    Chapter,
    Competency,
    CurriculumEdition,
    Exercise,
    School,
    Source,
    SourceChunk,
    SourceSection,
    Stream,
    Subject,
)
from alppy.models.enums import (
    CompetencyKind,
    CurriculumKind,
    CurriculumYear,
    ExerciseOrigin,
    ExerciseType,
    JobStatus,
)
from alppy.services import chapter_service

log = get_logger(__name__)

DATA_DIR = Path(__file__).parent / "data"

OFFICIAL_PER_FILE = "per_msn_cycle3.json"
STREAMS_FILE = "streams.json"
"""Written by `scripts/fetch-per-curriculum.py`, from CIIP's own API.

Committed rather than fetched at seed time: `docker compose up` has to work
with no network, and a curriculum that changes under a running seed is a
curriculum nobody can reproduce a band from."""

SUBJECT_LABELS: dict[str, dict[str, str]] = {
    "mathematics": {"fr": "Mathématiques", "de": "Mathematik", "en": "Mathematics"},
    "french": {"fr": "Français", "de": "Französisch", "en": "French"},
    "german": {"fr": "Allemand", "de": "Deutsch", "en": "German"},
}
"""Subjects are derived from the ``subject`` key the curriculum data already
carries, rather than from a fourth JSON file that could drift out of step with
it. A key with no entry here gets its own key as its label in all three
locales — visible, and better than refusing to load."""

DEMO_SOURCE_FILENAME = "Demo corpus — maths cycle 3"
DEMO_STORAGE_KEY = "seed/demo-corpus-maths-cycle3.json"

EMBED_BATCH = 32


class SeedError(ValueError):
    """A seed file is internally inconsistent. Always names the offending key."""


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------
@dataclass(slots=True)
class ReferenceLoadResult:
    subject_ids: dict[str, uuid.UUID] = field(default_factory=dict)
    competency_ids: dict[str, uuid.UUID] = field(default_factory=dict)
    #: The fetched, citable PER tree, keyed by code. Separate from
    #: `competency_ids` so nothing reaches an official row by accident.
    official_competency_ids: dict[str, uuid.UUID] = field(default_factory=dict)
    streams_created: int = 0
    chapter_ids: dict[str, uuid.UUID] = field(default_factory=dict)
    #: The per-subject `unfiled` bucket, keyed by subject key. Every sheet
    #: whose teacher has not filed it lands here; `sheet.chapter_id` is NOT
    #: NULL, so this row has to exist before a sheet can be created at all.
    unfiled_chapter_ids: dict[str, uuid.UUID] = field(default_factory=dict)
    subjects_created: int = 0
    competencies_created: int = 0
    chapters_created: int = 0

    @property
    def competency_count(self) -> int:
        return len(self.competency_ids)


@dataclass(slots=True)
class CorpusLoadResult:
    source_id: uuid.UUID
    chunks: int = 0
    sections: int = 0
    exercises_created: int = 0
    exercises_updated: int = 0
    exercise_ids: dict[str, uuid.UUID] = field(default_factory=dict)

    @property
    def exercise_count(self) -> int:
        return len(self.exercise_ids)


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------
def read_seed_file(name: str, *, data_dir: Path | None = None) -> tuple[dict[str, Any], bytes]:
    path = (data_dir or DATA_DIR) / name
    if not path.exists():
        raise SeedError(f"missing seed file {name} in {path.parent}")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise SeedError(f"seed file {name} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SeedError(f"seed file {name} must contain a JSON object")
    return payload, raw


def _entries(payload: dict[str, Any], key: str, name: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list):
        raise SeedError(f"seed file {name} must contain a '{key}' list")
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SeedError(f"{name}: entry {i} of '{key}' is not an object")
    return rows


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------
def load_reference_data(
    db: Session, *, school_id: uuid.UUID, data_dir: Path | None = None
) -> ReferenceLoadResult:
    """Subjects, competencies and chapters. Safe to run on every boot."""
    result = ReferenceLoadResult()

    competencies_payload, _ = read_seed_file("competencies.json", data_dir=data_dir)
    chapters_payload, _ = read_seed_file("chapters.json", data_dir=data_dir)
    competency_rows = _entries(competencies_payload, "competencies", "competencies.json")
    chapter_rows = _entries(chapters_payload, "chapters", "chapters.json")

    subject_keys = _ordered_unique(
        [_required(r, "subject", "competencies.json", r.get("code", f"#{i}")) for i, r in enumerate(competency_rows)]
        + [_required(r, "subject", "chapters.json", r.get("key", f"#{i}")) for i, r in enumerate(chapter_rows)]
    )
    result.subject_ids, result.subjects_created = _load_subjects(
        db, school_id=school_id, keys=subject_keys
    )
    result.competency_ids, result.competencies_created = _load_competencies(db, competency_rows)

    # The fetched PER, in its own edition beside the hand-authored rows. Keyed
    # separately from `competency_ids` so a chapter cannot reach an official
    # code by accident: moving one is a deliberate edit to chapters.json.
    result.official_competency_ids, official_created = load_official_per(db, data_dir=data_dir)
    result.competencies_created += official_created

    result.streams_created = load_streams(db, data_dir=data_dir)

    # Before the chapters: a sheet cannot be created without a chapter_id, and
    # the fallback has to exist for every subject the school now has.
    result.unfiled_chapter_ids = chapter_service.ensure_unfiled_chapters(
        db, school_id=school_id, subject_ids=result.subject_ids
    )

    school = db.get(School, school_id)
    if school is None:
        raise SeedError(f"school '{school_id}' does not exist")
    result.chapter_ids, result.chapters_created = _load_chapters(
        db,
        school_id=school_id,
        rows=chapter_rows,
        subject_ids=result.subject_ids,
        # Both editions, merged. A chapter names the code it means and the
        # loader finds it; the two sets are disjoint (`MSN 31.2` was invented,
        # `MSN 34.C8` is CIIP's), so nothing is ambiguous — and a Theme moving
        # onto an official row is then one edit to chapters.json rather than a
        # migration.
        competency_ids={**result.competency_ids, **result.official_competency_ids},
        curriculum=school.default_curriculum,
    )
    db.flush()
    log.info(
        "seed.reference",
        subjects=len(result.subject_ids),
        competencies=len(result.competency_ids),
        official_competencies=len(result.official_competency_ids),
        streams=result.streams_created,
        chapters=len(result.chapter_ids),
    )
    return result


def _load_subjects(
    db: Session, *, school_id: uuid.UUID, keys: Sequence[str]
) -> tuple[dict[str, uuid.UUID], int]:
    existing = {
        s.key: s for s in db.scalars(select(Subject).where(Subject.school_id == school_id))
    }
    out: dict[str, uuid.UUID] = {}
    created = 0
    for key in keys:
        labels = SUBJECT_LABELS.get(key) or dict.fromkeys(("fr", "de", "en"), key)
        row = existing.get(key)
        if row is None:
            row = Subject(id=uuid.uuid4(), school_id=school_id, key=key, labels=labels)
            db.add(row)
            created += 1
        else:
            row.labels = labels
        out[key] = row.id
    db.flush()
    return out, created


#: The edition each curriculum's hand-authored `competencies.json` rows belong
#: to. Those rows are NOT marked official: five of the PER codes are real and
#: eleven were invented in CIIP's notation, and the seed loader cannot tell
#: which is which by looking. `per_msn_cycle3.json` is the fetched, citable one
#: and lands in its own edition beside them (audit H3).
LEGACY_EDITIONS = {CurriculumKind.PER: "2010", CurriculumKind.LP21: "2014"}


def _ensure_edition(db: Session, curriculum: CurriculumKind, edition: str) -> uuid.UUID:
    """One `curriculum_edition` row per (curriculum, edition). Idempotent."""
    row = db.scalars(
        select(CurriculumEdition)
        .where(CurriculumEdition.curriculum == curriculum)
        .where(CurriculumEdition.edition == edition)
    ).first()
    if row is None:
        row = CurriculumEdition(id=uuid.uuid4(), curriculum=curriculum, edition=edition)
        db.add(row)
        db.flush()
    return row.id


def _load_competencies(
    db: Session, rows: Sequence[dict[str, Any]]
) -> tuple[dict[str, uuid.UUID], int]:
    """Two passes: create every node, then wire parents.

    One pass would require the file to be topologically sorted, which is a
    constraint on hand-authored data that nothing enforces and everyone
    forgets.
    """
    existing = {
        (row.curriculum, row.edition_id, row.code): row
        for row in db.scalars(select(Competency))
    }
    by_code: dict[str, Competency] = {}
    created = 0

    for i, entry in enumerate(rows):
        code = _required(entry, "code", "competencies.json", f"#{i}")
        curriculum_raw = _required(entry, "curriculum", "competencies.json", code)
        try:
            curriculum = CurriculumKind(curriculum_raw)
        except ValueError as exc:
            raise SeedError(
                f"competency '{code}' has unknown curriculum '{curriculum_raw}'"
            ) from exc
        if code in by_code:
            raise SeedError(f"competency code '{code}' appears twice in competencies.json")

        edition_id = _ensure_edition(db, curriculum, LEGACY_EDITIONS[curriculum])
        row = existing.get((curriculum, edition_id, code))
        if row is None:
            row = Competency(
                id=uuid.uuid4(), curriculum=curriculum, code=code, edition_id=edition_id
            )
            db.add(row)
            created += 1
        row.subject_key = _required(entry, "subject", "competencies.json", code)
        row.cycle = int(entry.get("cycle") or 3)
        row.labels = _localised(entry, "labels", "competency", code)
        row.description = entry.get("description") or {}
        row.kind = CompetencyKind(entry.get("kind") or "objectif")
        # Never True from this file. The rows here predate the fetch and the
        # loader cannot tell a real CIIP code from one written to look like one.
        row.is_official = False
        row.source_ref = None
        by_code[code] = row

    db.flush()

    for entry in rows:
        parent_code = entry.get("parent_code")
        if not parent_code:
            continue
        code = entry["code"]
        parent = by_code.get(parent_code)
        if parent is None:
            raise SeedError(
                f"competency '{code}' references unknown parent_code '{parent_code}'"
            )
        if parent.code == code:
            raise SeedError(f"competency '{code}' is its own parent")
        by_code[code].parent_id = parent.id

    db.flush()
    return {code: row.id for code, row in by_code.items()}, created


def load_official_per(
    db: Session, *, data_dir: Path | None = None
) -> tuple[dict[str, uuid.UUID], int]:
    """Seed the fetched PER tree — the five real levels, every row citable.

    Written by `scripts/fetch-per-curriculum.py` from CIIP's own API, and read
    from a committed file rather than fetched here: `docker compose up` has to
    work with no network.

    Lands in its own EDITION beside the hand-authored rows rather than
    replacing them (audit H3). Overwriting would have rewritten the very rows
    every existing band was computed from — and would have broken every chapter
    and test still pointing at them — for no gain that a second edition does
    not give. The old rows stay, marked `is_official = False`; a chapter moves
    when somebody moves it.
    """
    path = (data_dir or DATA_DIR) / OFFICIAL_PER_FILE
    if not path.exists():
        # Optional, and only for a caller that supplied its own data directory:
        # a test fixture or a deployment carrying a different curriculum should
        # not be forced to ship a fetched PER it does not use. The shipped
        # directory always has it.
        log.info("seed.official_per.absent", path=str(path))
        return {}, 0
    payload, _raw = read_seed_file(OFFICIAL_PER_FILE, data_dir=data_dir)
    rows = payload.get("competencies") or []
    curriculum = CurriculumKind(payload["curriculum"])
    edition_id = _ensure_edition(db, curriculum, str(payload["edition"]))
    subject_key = payload.get("subject_key") or "mathematics"
    cycle = int(payload.get("cycle") or 3)

    existing = {
        row.code: row
        for row in db.scalars(
            select(Competency).where(Competency.edition_id == edition_id)
        )
    }
    by_code: dict[str, Competency] = {}
    created = 0
    for entry in rows:
        code = entry["code"]
        row = existing.get(code)
        if row is None:
            row = Competency(
                id=uuid.uuid4(), curriculum=curriculum, code=code, edition_id=edition_id
            )
            db.add(row)
            created += 1
        row.subject_key = subject_key
        row.cycle = cycle
        row.labels = entry["labels"]
        row.description = entry.get("description") or {}
        row.kind = CompetencyKind(entry["kind"])
        row.year = CurriculumYear(entry["year"]) if entry.get("year") else None
        row.is_official = bool(entry.get("is_official"))
        row.source_ref = entry.get("source_ref")
        by_code[code] = row

    db.flush()
    for entry in rows:
        parent_code = entry.get("parent_code")
        if parent_code:
            by_code[entry["code"]].parent_id = by_code[parent_code].id
    db.flush()
    return {code: row.id for code, row in by_code.items()}, created


def load_streams(db: Session, *, data_dir: Path | None = None) -> int:
    """The cantonal level vocabularies (audit H2). Idempotent by (canton, code).

    Reference data, not a school's: a canton's streams are the canton's, shared
    by every school in it — the same argument `Competency` makes. Seeded for
    the six Romandie cantons.

    A FILE and a table, not an enum, because the finding's own test is "can a
    canton be added without a migration" — and reforms happen on a cantonal
    parliament's schedule, not ours.
    """
    path = (data_dir or DATA_DIR) / STREAMS_FILE
    if not path.exists():
        log.info("seed.streams.absent", path=str(path))
        return 0
    payload, _raw = read_seed_file(STREAMS_FILE, data_dir=data_dir)
    rows = _entries(payload, "streams", STREAMS_FILE)
    existing = {(row.canton, row.code): row for row in db.scalars(select(Stream))}
    created = 0
    for entry in rows:
        canton = _required(entry, "canton", STREAMS_FILE, entry.get("code", "?"))
        code = _required(entry, "code", STREAMS_FILE, canton)
        row = existing.get((canton, code))
        if row is None:
            row = Stream(id=uuid.uuid4(), canton=canton, code=code)
            db.add(row)
            created += 1
        row.labels = _localised(entry, "labels", "stream", f"{canton}/{code}")
        row.position = int(entry.get("position") or 0)
    db.flush()
    return created


UNFILED_POSITION = 999
"""Past every seeded chapter's 0..6, so `ORDER BY position` puts it last
without a second query to filter it out."""

UNFILED_LABELS: dict[str, str] = {
    "fr": "Non classé",
    "de": "Nicht zugeordnet",
    "en": "Unfiled",
}


def _ensure_unfiled_chapters(
    db: Session, *, school_id: uuid.UUID, subject_ids: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    """One `unfiled` Chapter per subject. Idempotent by (school, subject, key)."""
    existing = {
        row.subject_id: row
        for row in db.scalars(
            select(Chapter).where(
                Chapter.school_id == school_id, Chapter.key == UNFILED_CHAPTER_KEY
            )
        )
    }
    out: dict[str, uuid.UUID] = {}
    for subject_key, subject_id in subject_ids.items():
        row = existing.get(subject_id)
        if row is None:
            row = Chapter(
                id=uuid.uuid4(),
                school_id=school_id,
                subject_id=subject_id,
                key=UNFILED_CHAPTER_KEY,
            )
            db.add(row)
        row.labels = dict(UNFILED_LABELS)
        row.position = UNFILED_POSITION
        # Never a parent, never in the tree, never in a roll-up.
        row.primary_competency_id = None
        out[subject_key] = row.id
    db.flush()
    return out


def _load_chapters(
    db: Session,
    *,
    school_id: uuid.UUID,
    rows: Sequence[dict[str, Any]],
    subject_ids: dict[str, uuid.UUID],
    competency_ids: dict[str, uuid.UUID],
    curriculum: CurriculumKind,
) -> tuple[dict[str, uuid.UUID], int]:
    existing = {
        row.key: row
        for row in db.scalars(
            select(Chapter).where(
                Chapter.school_id == school_id, Chapter.key != UNFILED_CHAPTER_KEY
            )
        )
    }
    by_id = {row.id: row for row in db.scalars(select(Competency))}
    out: dict[str, uuid.UUID] = {}
    created = 0

    for position, entry in enumerate(rows):
        key = _required(entry, "key", "chapters.json", f"#{position}")
        subject_key = _required(entry, "subject", "chapters.json", key)
        subject_id = subject_ids.get(subject_key)
        if subject_id is None:
            raise SeedError(f"chapter '{key}' references unknown subject '{subject_key}'")

        codes = entry.get("competency_codes") or []
        if not isinstance(codes, list):
            raise SeedError(f"chapter '{key}': competency_codes must be a list")
        competencies: list[Competency] = []
        for code in codes:
            cid = competency_ids.get(code)
            if cid is None:
                raise SeedError(f"chapter '{key}' references unknown competency code '{code}'")
            competencies.append(by_id[cid])

        row = existing.get(key)
        if row is None:
            row = Chapter(id=uuid.uuid4(), school_id=school_id, key=key, subject_id=subject_id)
            db.add(row)
            created += 1
        # The canonical parent for this school's curriculum. A chapter tags
        # competencies from BOTH curricula on purpose (docs/curriculum.md §3);
        # exactly one of them is where this school files it.
        primary = entry.get("primary_competency_code")
        if not isinstance(primary, dict):
            raise SeedError(
                f"chapter '{key}': primary_competency_code must be an object "
                f"keyed by curriculum"
            )
        primary_code = primary.get(curriculum.value)
        if not primary_code:
            raise SeedError(
                f"chapter '{key}' has no primary_competency_code for curriculum "
                f"'{curriculum.value}'"
            )
        primary_id = competency_ids.get(primary_code)
        if primary_id is None:
            raise SeedError(
                f"chapter '{key}' primary_competency_code references unknown "
                f"competency code '{primary_code}'"
            )
        if primary_code not in codes:
            raise SeedError(
                f"chapter '{key}' primary_competency_code '{primary_code}' is not "
                f"among its own competency_codes"
            )

        row.subject_id = subject_id
        row.labels = _localised(entry, "labels", "chapter", key)
        row.position = position
        row.competencies = competencies
        row.primary_competency_id = primary_id
        out[key] = row.id

    db.flush()
    return out, created


# --------------------------------------------------------------------------
# Demo corpus
# --------------------------------------------------------------------------
def load_demo_corpus(
    db: Session,
    *,
    school_id: uuid.UUID,
    subject_id: uuid.UUID,
    data_dir: Path | None = None,
    ai: AiClient | None = None,
) -> CorpusLoadResult:
    """Load ``exercises.json`` as an indexed `Source` with embedded chunks.

    Requires `load_reference_data` to have run: every exercise resolves a
    `chapter_key` and a list of `competency_codes`, and an unresolvable one
    raises rather than loading a partly-tagged corpus that would then silently
    under-retrieve.
    """
    payload, raw = read_seed_file("exercises.json", data_dir=data_dir)
    rows = _entries(payload, "exercises", "exercises.json")
    client = ai or AiClient()

    chapters = {
        c.key: c for c in db.scalars(select(Chapter).where(Chapter.school_id == school_id))
    }
    competencies = {c.code: c for c in db.scalars(select(Competency))}

    source = _demo_source(db, school_id=school_id, subject_id=subject_id, raw=raw, rows=rows)
    existing_chunks = {
        c.position: c
        for c in db.scalars(select(SourceChunk).where(SourceChunk.source_id == source.id))
    }
    existing_exercises = {
        e.source_chunk_id: e
        for e in db.scalars(select(Exercise).where(Exercise.source_id == source.id))
        if e.source_chunk_id is not None
    }

    result = CorpusLoadResult(source_id=source.id)
    sections = _demo_sections(db, source=source, chapters=chapters, rows=rows)
    result.sections = len(sections)
    chunk_texts = [_chunk_text(entry) for entry in rows]
    vectors = _embed_all(client, chunk_texts)

    for position, entry in enumerate(rows):
        key = _required(entry, "key", "exercises.json", f"#{position}")
        chapter_key = _required(entry, "chapter_key", "exercises.json", key)
        chapter = chapters.get(chapter_key)
        if chapter is None:
            raise SeedError(f"exercise '{key}' references unknown chapter_key '{chapter_key}'")

        codes = entry.get("competency_codes") or []
        if not isinstance(codes, list) or not codes:
            raise SeedError(f"exercise '{key}' must list at least one competency code")
        tagged: list[Competency] = []
        for code in codes:
            competency = competencies.get(code)
            if competency is None:
                raise SeedError(
                    f"exercise '{key}' references unknown competency code '{code}'"
                )
            tagged.append(competency)

        try:
            kind = ExerciseType(_required(entry, "type", "exercises.json", key))
        except ValueError as exc:
            raise SeedError(f"exercise '{key}' has unknown type '{entry.get('type')}'") from exc

        hint = entry.get("source_hint") or {}
        page = int(hint.get("page") or 1)

        chunk = existing_chunks.get(position)
        if chunk is None:
            chunk = SourceChunk(
                id=uuid.uuid4(),
                school_id=school_id,
                source_id=source.id,
                page=page,
                position=position,
            )
            db.add(chunk)
        chunk.page = page
        chunk.text = chunk_texts[position]
        chunk.embedding = vectors[position]
        db.flush()
        result.chunks += 1

        exercise = existing_exercises.get(chunk.id)
        if exercise is None:
            exercise = Exercise(id=uuid.uuid4(), school_id=school_id, subject_id=subject_id)
            db.add(exercise)
            result.exercises_created += 1
        else:
            result.exercises_updated += 1

        exercise.subject_id = subject_id
        exercise.chapter_id = chapter.id
        exercise.source_id = source.id
        exercise.source_chunk_id = chunk.id
        exercise.source_section_id = sections.get(chapter_key)
        exercise.source_page = page
        exercise.type = kind
        exercise.origin = ExerciseOrigin.TEXTBOOK
        exercise.language = _required(entry, "language", "exercises.json", key)
        exercise.statement = _required(entry, "statement", "exercises.json", key)
        exercise.options = _validated_options(entry, key=key, kind=kind)
        exercise.answer_index = entry.get("answer_index") if kind is ExerciseType.MCQ else None
        exercise.answer_bool = (
            entry.get("answer_bool") if kind is ExerciseType.TRUE_FALSE else None
        )
        exercise.answer_text = entry.get("answer_text") if kind is ExerciseType.OPEN else None
        exercise.explanation = entry.get("explanation")
        exercise.difficulty = max(1, min(5, int(entry.get("difficulty") or 3)))
        exercise.competencies = tagged
        db.flush()
        result.exercise_ids[key] = exercise.id

    source.status = JobStatus.SUCCEEDED
    source.error = None
    source.page_count = max((c.page for c in db.scalars(
        select(SourceChunk).where(SourceChunk.source_id == source.id)
    )), default=1)
    db.flush()
    log.info(
        "seed.corpus",
        source_id=str(source.id),
        chunks=result.chunks,
        sections=result.sections,
        created=result.exercises_created,
        updated=result.exercises_updated,
    )
    return result


def _demo_sections(
    db: Session,
    *,
    source: Source,
    chapters: dict[str, Any],
    rows: Sequence[dict[str, Any]],
) -> dict[str, uuid.UUID]:
    """The demo corpus's outline, one section per chapter it covers.

    The seed writes `Exercise` rows straight into the database instead of
    running them through `ingest.pipeline`, so nothing would otherwise detect
    sections for it — and a demo whose only document has no chapters would show
    the sheet builder's main control empty on a clean `docker compose up`.

    A synthetic corpus has no printed headings to read, so the chapter each row
    already declares is the honest structure here, and the page range is
    whatever pages its exercises actually claim.

    Returns ``chapter_key -> section_id``.
    """
    spans: dict[str, list[int]] = {}
    order: list[str] = []
    for entry in rows:
        key = str(entry.get("chapter_key") or "")
        if not key:
            continue
        page = int((entry.get("source_hint") or {}).get("page") or 1)
        if key not in spans:
            spans[key] = []
            order.append(key)
        spans[key].append(page)

    existing = {
        row.title: row
        for row in db.scalars(
            select(SourceSection).where(SourceSection.source_id == source.id)
        )
    }
    mapping: dict[str, uuid.UUID] = {}
    for position, key in enumerate(order):
        chapter = chapters.get(key)
        labels = getattr(chapter, "labels", None) or {}
        title = str(
            (labels.get("fr") or labels.get("de") or labels.get("en") or key)
            if isinstance(labels, dict)
            else key
        )
        pages = spans[key]
        section = existing.get(title)
        if section is None:
            section = SourceSection(
                id=uuid.uuid4(),
                school_id=source.school_id,
                source_id=source.id,
                title=title[:300],
                label=str(position + 1),
            )
            db.add(section)
        section.page_from = min(pages)
        section.page_to = max(pages)
        section.position = position
        # The demo corpus is already transcribed, so its chapters are read.
        section.extracted_at = section.extracted_at or datetime.now(UTC)
        db.flush()
        mapping[key] = section.id
    return mapping


def _demo_source(
    db: Session,
    *,
    school_id: uuid.UUID,
    subject_id: uuid.UUID,
    raw: bytes,
    rows: Sequence[dict[str, Any]],
) -> Source:
    """The `Source` the demo corpus hangs off, keyed on the file's sha256.

    Same key the ingestion pipeline uses, so re-seeding after an edit to
    ``exercises.json`` is recognised as new content rather than as a duplicate.
    """
    digest = hashlib.sha256(raw).hexdigest()
    filename = str(
        (rows[0].get("source_hint") or {}).get("document") if rows else ""
    ) or DEMO_SOURCE_FILENAME

    source = db.scalars(
        select(Source)
        .where(Source.school_id == school_id, Source.storage_key == DEMO_STORAGE_KEY)
        .limit(1)
    ).first()
    if source is None:
        source = Source(
            id=uuid.uuid4(),
            school_id=school_id,
            subject_id=subject_id,
            filename=filename[:255],
            storage_key=DEMO_STORAGE_KEY,
            content_type="application/json",
            size_bytes=len(raw),
            sha256=digest,
        )
        db.add(source)
    source.subject_id = subject_id
    source.filename = filename[:255]
    source.size_bytes = len(raw)
    source.sha256 = digest
    # The corpus is deliberately bilingual (fr and de side by side), so the
    # document has no single language; each Exercise carries its own.
    source.language = None
    source.status = JobStatus.RUNNING
    db.flush()
    return source


def _chunk_text(entry: dict[str, Any]) -> str:
    """What gets embedded and what the provenance excerpt shows.

    Statement plus options: the options carry real signal ("3/4", "6/8" tells an
    embedding this is about equivalent fractions) and they are part of what the
    teacher reads in the excerpt. The explanation is left out — it contains the
    answer, and the excerpt is shown next to the proposal in the builder.
    """
    parts = [str(entry.get("statement") or "").strip()]
    options = entry.get("options")
    if isinstance(options, list) and options:
        parts.append(" · ".join(str(o) for o in options))
    return "\n".join(p for p in parts if p)


def _embed_all(client: AiClient, texts: Sequence[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        vectors.extend(client.embed(list(texts[start : start + EMBED_BATCH])))
    if len(vectors) != len(texts):
        raise SeedError(
            f"embedding provider returned {len(vectors)} vectors for {len(texts)} chunks"
        )
    return vectors


def _validated_options(
    entry: dict[str, Any], *, key: str, kind: ExerciseType
) -> list[str] | None:
    if kind is not ExerciseType.MCQ:
        return None
    options = entry.get("options")
    if not isinstance(options, list) or len(options) < 2:
        raise SeedError(f"exercise '{key}' is mcq but has fewer than two options")
    index = entry.get("answer_index")
    if not isinstance(index, int) or not 0 <= index < len(options):
        raise SeedError(
            f"exercise '{key}' is mcq but answer_index {index!r} is not a valid option index"
        )
    return [str(o) for o in options]


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _required(entry: dict[str, Any], field_name: str, file_name: str, key: object) -> str:
    value = entry.get(field_name)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise SeedError(f"{file_name}: entry '{key}' is missing required field '{field_name}'")
    return str(value).strip() if isinstance(value, str) else str(value)


def _localised(entry: dict[str, Any], field_name: str, kind: str, key: str) -> dict[str, str]:
    labels = entry.get(field_name)
    if not isinstance(labels, dict) or not labels:
        raise SeedError(f"{kind} '{key}' is missing '{field_name}'")
    missing = [loc for loc in ("fr", "de", "en") if not labels.get(loc)]
    if missing:
        raise SeedError(
            f"{kind} '{key}' has no {field_name} for locale(s) {', '.join(missing)}"
        )
    return {str(k): str(v) for k, v in labels.items()}


def _ordered_unique(values: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen
