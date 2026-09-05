"""Ranking exercises for a sheet (F1), and the candidate engine behind F4.

The teacher types an intent — *"révision fractions avant le test"* — picks
chapters and a difficulty, and gets an ordered list of exercises with a
provenance panel next to each one. This module produces that list.

The ranking formula
-------------------
Four scored terms, then a diversity penalty applied at selection time:

    base  = 0.45 · similarity        cosine, intent vector vs the exercise's
                                     source chunk. 0.5 for everything when the
                                     teacher typed no intent, so the term drops
                                     out rather than distorting.
          + 0.20 · difficulty_fit    1 − |difficulty − target| / 4
          + 0.20 · competency_fit    share of the exercise's competencies that
                                     the requested chapters actually ask for
          + 0.15 · language_fit      1.0 in the sheet's language, else 0.0

    score = base − 0.15 · same_chunk_already_taken
                 − 0.07 · same_chapter_already_taken
                 − 0.30 · near_duplicate_of_something_taken

Similarity is the largest single term but deliberately not a majority: an
embedding of a six-word intent is a weak signal, and a teacher who asked for
chapter *Fractions* at difficulty 2 has given two much stronger ones. When the
intent is empty the other three terms decide the order entirely, which is the
correct behaviour — not an accident.

Selection is greedy rather than a top-N sort, because the diversity penalty
depends on what has already been picked. Eight variations of the same fraction
addition off one textbook chunk is a worse sheet than eight merely-good items
that cover the chapter, and a plain sort cannot express that.

Language is a *preferential hard filter*, not just a term: candidates in the
sheet's language are exhausted before any other language is considered.
Printing a German exercise on a French sheet is a defect, not a trade-off — the
exercise's language follows the source material, never the teacher's UI locale.
``language_fit`` stays in the formula so the reported score still reflects it.

Postgres vs SQLite
------------------
On Postgres, cosine distance is computed by pgvector's ``<=>`` inside the
query. On SQLite the same cosine is computed in Python over the fetched rows.
Identical maths, and it means the whole RAG path — including this ranking — is
exercisable in CI with no Postgres and no API key.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from alppy.ai.client import AiClient
from alppy.core.logging import get_logger
from alppy.models import Chapter, Competency, Exercise, Source, SourceChunk, chapter_competency
from alppy.models.enums import ExerciseOrigin
from alppy.schemas import ExerciseOut, ExerciseProposal, Provenance

log = get_logger(__name__)

# --- weights. Change these and the docstring above together. ---------------
W_SIMILARITY = 0.45
W_DIFFICULTY = 0.20
W_COMPETENCY = 0.20
W_LANGUAGE = 0.15

P_SAME_CHUNK = 0.15
P_SAME_CHAPTER = 0.07
P_NEAR_DUPLICATE = 0.30

NEUTRAL_SIMILARITY = 0.5
"""Used for every candidate when there is no intent to embed, so the term is
constant and therefore cannot reorder anything."""

DUPLICATE_JACCARD = 0.6
"""Token overlap above which two statements are 'the same exercise again'."""

EXCERPT_CHARS = 180
CANDIDATE_LIMIT = 400
"""Ceiling on rows scored per request. A school's corpus is thousands of
exercises; the hard filters cut that to dozens, and this stops a filter-free
request from scoring the world."""

_TOKEN_RE = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)


class RetrievalError(RuntimeError):
    pass


@dataclass(slots=True)
class Candidate:
    """One scored exercise, with everything the provenance panel needs."""

    exercise: Exercise
    chunk: SourceChunk | None
    source: Source | None
    chapter: Chapter | None
    competency_ids: list[uuid.UUID]
    matched_competency_ids: list[uuid.UUID]
    similarity: float | None
    difficulty_fit: float
    competency_fit: float
    language_fit: float
    base_score: float
    tokens: frozenset[str] = field(default_factory=frozenset)
    competency_codes: list[str] = field(default_factory=list)

    @property
    def chunk_id(self) -> uuid.UUID | None:
        return self.chunk.id if self.chunk is not None else None


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def propose_exercises(
    db: Session,
    *,
    school_id: uuid.UUID,
    class_id: uuid.UUID,
    subject_id: uuid.UUID,
    chapter_ids: list[uuid.UUID],
    intent: str | None,
    count: int,
    language: str,
    difficulty: int | None,
) -> list[ExerciseProposal]:
    """Rank exercises for a sheet.

    ``class_id`` is accepted for symmetry with the request schema and for the
    audit trail; exercises belong to a school and a subject, not to a class, so
    it does not filter. AI-generated exercises awaiting approval are excluded:
    an unapproved item is not a thing the teacher may put on a sheet yet, so
    offering it here would be offering something the print path will refuse.
    """
    candidates = gather_candidates(
        db,
        school_id=school_id,
        subject_id=subject_id,
        chapter_ids=chapter_ids,
        competency_ids=None,
        intent=intent,
        language=language,
        difficulty=difficulty,
    )
    selected = select_diverse(candidates, count=count)
    log.info(
        "retrieval.propose",
        school_id=str(school_id),
        class_id=str(class_id),
        candidates=len(candidates),
        selected=len(selected),
        has_intent=bool(intent and intent.strip()),
    )
    return [
        build_proposal(c, language=language, target_difficulty=difficulty, intent=intent)
        for c in selected
    ]


def gather_candidates(
    db: Session,
    *,
    school_id: uuid.UUID,
    subject_id: uuid.UUID,
    chapter_ids: Sequence[uuid.UUID] | None = None,
    competency_ids: Sequence[uuid.UUID] | None = None,
    intent: str | None = None,
    language: str,
    difficulty: int | None = None,
    exclude_exercise_ids: Iterable[uuid.UUID] = (),
    include_unapproved: bool = False,
    ai: AiClient | None = None,
    limit: int = CANDIDATE_LIMIT,
) -> list[Candidate]:
    """Hard-filter, then score. The engine both F1 and F4 call.

    ``chapter_ids`` and ``competency_ids`` are both hard filters and they are
    OR-ed with each other: the adaptive path targets competencies directly
    (a student's gaps do not respect chapter edges), the sheet builder targets
    chapters, and passing both means "in these chapters or against these
    competencies".
    """
    wanted_competencies = set(competency_ids or ())
    chapter_competencies = _competencies_of_chapters(db, chapter_ids or ())
    excluded = set(exclude_exercise_ids)

    stmt = (
        select(Exercise)
        .options(selectinload(Exercise.competencies))
        .where(Exercise.school_id == school_id, Exercise.subject_id == subject_id)
    )
    if not include_unapproved:
        # origin=ai_generated + approved_at IS NULL is the one combination the
        # print path refuses, so it never becomes a proposal either.
        stmt = stmt.where(
            (Exercise.origin != ExerciseOrigin.AI_GENERATED)
            | (Exercise.approved_at.is_not(None))
        )
    rows = list(db.scalars(stmt.limit(limit)))

    chapters = _chapters_by_id(db, school_id=school_id)
    intent_vector = _embed_intent(intent, ai=ai)
    distances = (
        _chunk_similarities(db, school_id=school_id, vector=intent_vector)
        if intent_vector is not None
        else {}
    )
    chunks = _chunks_by_id(db, school_id=school_id)
    sources = _sources_by_id(db, school_id=school_id)

    candidates: list[Candidate] = []
    for exercise in rows:
        if exercise.id in excluded:
            continue
        own = [c.id for c in exercise.competencies]
        matched = _matched_competencies(
            own,
            chapter_ids=chapter_ids or (),
            exercise_chapter_id=exercise.chapter_id,
            chapter_competencies=chapter_competencies,
            wanted_competencies=wanted_competencies,
        )
        if matched is None:
            continue  # hard filter rejected it

        chunk = chunks.get(exercise.source_chunk_id) if exercise.source_chunk_id else None
        similarity = (
            distances.get(chunk.id) if (intent_vector is not None and chunk is not None) else None
        )
        sim_term = NEUTRAL_SIMILARITY if similarity is None else similarity
        difficulty_fit = _difficulty_fit(exercise.difficulty, difficulty)
        competency_fit = _competency_fit(own, matched)
        language_fit = 1.0 if exercise.language == language else 0.0

        candidates.append(
            Candidate(
                exercise=exercise,
                chunk=chunk,
                source=sources.get(exercise.source_id) if exercise.source_id else None,
                chapter=chapters.get(exercise.chapter_id) if exercise.chapter_id else None,
                competency_ids=own,
                matched_competency_ids=matched,
                similarity=similarity,
                difficulty_fit=difficulty_fit,
                competency_fit=competency_fit,
                language_fit=language_fit,
                base_score=(
                    W_SIMILARITY * sim_term
                    + W_DIFFICULTY * difficulty_fit
                    + W_COMPETENCY * competency_fit
                    + W_LANGUAGE * language_fit
                ),
                tokens=frozenset(_TOKEN_RE.findall(exercise.statement.lower())),
            )
        )

    _attach_competency_codes(db, candidates)
    candidates.sort(key=lambda c: (-c.base_score, str(c.exercise.id)))
    return candidates


def _attach_competency_codes(db: Session, candidates: Sequence[Candidate]) -> None:
    """Resolve the human-readable competency codes the reason string prints."""
    ids = {cid for c in candidates for cid in c.matched_competency_ids}
    if not ids:
        return
    codes = {row.id: row.code for row in db.scalars(select(Competency).where(Competency.id.in_(ids)))}
    for cand in candidates:
        cand.competency_codes = [
            codes[cid] for cid in cand.matched_competency_ids if cid in codes
        ]


def select_diverse(candidates: Sequence[Candidate], *, count: int) -> list[Candidate]:
    """Greedy selection with the diversity penalty recomputed at each pick.

    Language first: the pool is split so that everything in the sheet's
    language is offered before anything else. Within a pool the penalty is what
    stops eight near-identical items off one chunk.
    """
    if count <= 0:
        return []
    in_language = [c for c in candidates if c.language_fit >= 1.0]
    other = [c for c in candidates if c.language_fit < 1.0]

    picked: list[Candidate] = []
    for pool in (in_language, other):
        picked.extend(_greedy(pool, count=count - len(picked), already=picked))
        if len(picked) >= count:
            break
    return picked[:count]


def _greedy(
    pool: Sequence[Candidate], *, count: int, already: Sequence[Candidate]
) -> list[Candidate]:
    remaining = list(pool)
    picked: list[Candidate] = []
    context = list(already)
    while remaining and len(picked) < count:
        best_i, best_score = 0, -math.inf
        for i, cand in enumerate(remaining):
            score = cand.base_score - diversity_penalty(cand, context)
            if score > best_score:
                best_i, best_score = i, score
        chosen = remaining.pop(best_i)
        picked.append(chosen)
        context.append(chosen)
    return picked


def diversity_penalty(candidate: Candidate, taken: Sequence[Candidate]) -> float:
    """How much this candidate is punished for repeating what is already in."""
    penalty = 0.0
    for other in taken:
        if candidate.chunk_id is not None and candidate.chunk_id == other.chunk_id:
            penalty += P_SAME_CHUNK
        if (
            candidate.exercise.chapter_id is not None
            and candidate.exercise.chapter_id == other.exercise.chapter_id
        ):
            penalty += P_SAME_CHAPTER
        if _jaccard(candidate.tokens, other.tokens) >= DUPLICATE_JACCARD:
            penalty += P_NEAR_DUPLICATE
    return penalty


def score_of(candidate: Candidate, taken: Sequence[Candidate] = ()) -> float:
    return candidate.base_score - diversity_penalty(candidate, taken)


# --------------------------------------------------------------------------
# Proposal assembly
# --------------------------------------------------------------------------
def exercise_out(exercise: Exercise, competency_ids: Sequence[uuid.UUID] | None = None) -> ExerciseOut:
    """`ExerciseOut` with the many-to-many competency ids filled in.

    `ExerciseOut.competency_ids` has no matching attribute on the model, so
    ``model_validate`` alone would silently return an empty list — and the
    frontend would show an exercise tagged with nothing.
    """
    ids = list(competency_ids) if competency_ids is not None else [c.id for c in exercise.competencies]
    out = ExerciseOut.model_validate(exercise)
    return out.model_copy(update={"competency_ids": ids})


def build_proposal(
    candidate: Candidate,
    *,
    language: str,
    target_difficulty: int | None,
    intent: str | None,
    taken: Sequence[Candidate] = (),
    extra_reason: str | None = None,
) -> ExerciseProposal:
    return ExerciseProposal(
        exercise=exercise_out(candidate.exercise, candidate.competency_ids),
        score=round(score_of(candidate, taken), 4),
        provenance=build_provenance(
            candidate,
            language=language,
            target_difficulty=target_difficulty,
            intent=intent,
            extra_reason=extra_reason,
        ),
    )


def build_provenance(
    candidate: Candidate,
    *,
    language: str,
    target_difficulty: int | None,
    intent: str | None,
    extra_reason: str | None = None,
) -> Provenance:
    source = candidate.source
    chunk = candidate.chunk
    return Provenance(
        source_id=source.id if source is not None else None,
        source_filename=source.filename if source is not None else None,
        page=candidate.exercise.source_page or (chunk.page if chunk is not None else None),
        excerpt=_excerpt(chunk.text) if chunk is not None else None,
        similarity=round(candidate.similarity, 4) if candidate.similarity is not None else None,
        reason=_reason(
            candidate,
            language=language,
            target_difficulty=target_difficulty,
            intent=intent,
            extra=extra_reason,
        ),
    )


# The provenance panel is read by the teacher, in the language of the sheet.
# A bare number is not an audit trail; these phrases are.
_PHRASES: dict[str, dict[str, str]] = {
    "fr": {
        "chapter": "correspond au chapitre {chapter}",
        "competency": "compétence {competency}",
        "difficulty": "difficulté {difficulty}",
        "difficulty_target": "difficulté {difficulty} (visée {target})",
        "intent": "proche de votre intention « {intent} » (similarité {similarity})",
        "no_intent": "aucune intention saisie : classé par chapitre et difficulté",
        "page": "p. {page} de {filename}",
        "language": "rédigé en {language}, la langue de la source",
        "language_mismatch": "en {language}, différente de la langue de la fiche",
        "generated": "généré pour cette compétence — en attente de votre validation",
    },
    "de": {
        "chapter": "passt zum Kapitel {chapter}",
        "competency": "Kompetenz {competency}",
        "difficulty": "Schwierigkeit {difficulty}",
        "difficulty_target": "Schwierigkeit {difficulty} (Ziel {target})",
        "intent": "nahe an Ihrer Absicht „{intent}“ (Ähnlichkeit {similarity})",
        "no_intent": "keine Absicht eingegeben: nach Kapitel und Schwierigkeit geordnet",
        "page": "S. {page} aus {filename}",
        "language": "auf {language} verfasst, der Sprache der Quelle",
        "language_mismatch": "auf {language}, nicht die Sprache des Blattes",
        "generated": "für diese Kompetenz erzeugt — wartet auf Ihre Freigabe",
    },
    "en": {
        "chapter": "matches chapter {chapter}",
        "competency": "competency {competency}",
        "difficulty": "difficulty {difficulty}",
        "difficulty_target": "difficulty {difficulty} (target {target})",
        "intent": "similar to your intent “{intent}” (similarity {similarity})",
        "no_intent": "no intent given: ordered by chapter and difficulty",
        "page": "p. {page} of {filename}",
        "language": "written in {language}, the language of the source",
        "language_mismatch": "in {language}, not the language of this sheet",
        "generated": "generated for this competency — awaiting your approval",
    },
}


def phrases(language: str) -> dict[str, str]:
    return _PHRASES.get(language, _PHRASES["en"])


def _reason(
    candidate: Candidate,
    *,
    language: str,
    target_difficulty: int | None,
    intent: str | None,
    extra: str | None = None,
) -> str:
    p = phrases(language)
    parts: list[str] = []
    if extra:
        parts.append(extra)
    if candidate.chapter is not None:
        parts.append(p["chapter"].format(chapter=_label(candidate.chapter.labels, language)))
    if candidate.matched_competency_ids and candidate.competency_codes:
        parts.append(p["competency"].format(competency=", ".join(candidate.competency_codes)))
    if target_difficulty is None:
        parts.append(p["difficulty"].format(difficulty=candidate.exercise.difficulty))
    else:
        parts.append(
            p["difficulty_target"].format(
                difficulty=candidate.exercise.difficulty, target=target_difficulty
            )
        )
    if intent and intent.strip():
        if candidate.similarity is not None:
            parts.append(
                p["intent"].format(
                    intent=_shorten(intent), similarity=f"{candidate.similarity:.2f}"
                )
            )
    else:
        parts.append(p["no_intent"])
    if candidate.language_fit >= 1.0:
        parts.append(p["language"].format(language=candidate.exercise.language))
    else:
        parts.append(p["language_mismatch"].format(language=candidate.exercise.language))
    if candidate.source is not None and candidate.exercise.source_page:
        parts.append(
            p["page"].format(
                page=candidate.exercise.source_page, filename=candidate.source.filename
            )
        )
    return " · ".join(parts)


# --------------------------------------------------------------------------
# Scoring terms
# --------------------------------------------------------------------------
def _difficulty_fit(actual: int, target: int | None) -> float:
    """1.0 on target, falling linearly to 0.0 four levels away."""
    if target is None:
        return 1.0
    return max(0.0, 1.0 - abs(actual - target) / 4.0)


def _competency_fit(own: Sequence[uuid.UUID], matched: Sequence[uuid.UUID]) -> float:
    """Share of the exercise's competencies the request actually asked for.

    An exercise tagged with one competency, which is the one requested, is a
    better fit than one tagged with four of which one was requested — the
    second spends three quarters of the student's effort elsewhere.
    """
    if not own:
        return 0.5  # untagged: neither a match nor a mismatch
    if not matched:
        return 0.0
    return len(set(matched)) / len(set(own))


def _matched_competencies(
    own: Sequence[uuid.UUID],
    *,
    chapter_ids: Sequence[uuid.UUID],
    exercise_chapter_id: uuid.UUID | None,
    chapter_competencies: set[uuid.UUID],
    wanted_competencies: set[uuid.UUID],
) -> list[uuid.UUID] | None:
    """Apply the hard filter. ``None`` means rejected."""
    if not chapter_ids and not wanted_competencies:
        return list(own)

    by_chapter = bool(chapter_ids) and exercise_chapter_id in set(chapter_ids)
    from_chapter = [cid for cid in own if cid in chapter_competencies]
    from_wanted = [cid for cid in own if cid in wanted_competencies]

    if wanted_competencies and from_wanted:
        return from_wanted
    if by_chapter:
        return from_chapter or list(own)
    if chapter_ids and from_chapter:
        return from_chapter
    return None


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------
# Vector similarity — Postgres via pgvector, SQLite in Python
# --------------------------------------------------------------------------
def _embed_intent(intent: str | None, *, ai: AiClient | None) -> list[float] | None:
    text = (intent or "").strip()
    if not text:
        return None
    client = ai or AiClient()
    vectors = client.embed([text])
    return list(vectors[0]) if vectors else None


def _chunk_similarities(
    db: Session, *, school_id: uuid.UUID, vector: Sequence[float]
) -> dict[uuid.UUID, float]:
    """Cosine similarity of every chunk in the school against ``vector``.

    Postgres does it in the database with pgvector's ``<=>``; SQLite does the
    same arithmetic in Python. The two must agree, so both clamp negatives to
    zero: a negative cosine is 'unrelated', and letting it go negative would
    make an unrelated chunk *worse* than one with no embedding at all, which is
    not a distinction the ranking should be making.
    """
    dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
    if dialect == "postgresql":
        distance = SourceChunk.embedding.cosine_distance(list(vector))
        rows = db.execute(
            select(SourceChunk.id, distance).where(
                SourceChunk.school_id == school_id, SourceChunk.embedding.is_not(None)
            )
        ).all()
        return {row[0]: max(0.0, 1.0 - float(row[1])) for row in rows if row[1] is not None}

    out: dict[uuid.UUID, float] = {}
    for chunk in db.scalars(select(SourceChunk).where(SourceChunk.school_id == school_id)):
        if chunk.embedding is None:
            continue
        out[chunk.id] = max(0.0, cosine_similarity(vector, list(chunk.embedding)))
    return out


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise RetrievalError(f"embedding dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
def _competencies_of_chapters(db: Session, chapter_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
    if not chapter_ids:
        return set()
    rows = db.execute(
        select(chapter_competency.c.competency_id).where(
            chapter_competency.c.chapter_id.in_(list(chapter_ids))
        )
    ).all()
    return {row[0] for row in rows}


def chapters_for_competencies(
    db: Session, *, school_id: uuid.UUID, competency_ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    """Which chapters develop these competencies. Used by the adaptive path."""
    if not competency_ids:
        return []
    rows = db.execute(
        select(chapter_competency.c.chapter_id)
        .join(Chapter, Chapter.id == chapter_competency.c.chapter_id)
        .where(
            chapter_competency.c.competency_id.in_(list(competency_ids)),
            Chapter.school_id == school_id,
        )
    ).all()
    seen: list[uuid.UUID] = []
    for row in rows:
        if row[0] not in seen:
            seen.append(row[0])
    return seen


def _chapters_by_id(db: Session, *, school_id: uuid.UUID) -> dict[uuid.UUID, Chapter]:
    return {c.id: c for c in db.scalars(select(Chapter).where(Chapter.school_id == school_id))}


def _chunks_by_id(db: Session, *, school_id: uuid.UUID) -> dict[uuid.UUID, SourceChunk]:
    return {
        c.id: c for c in db.scalars(select(SourceChunk).where(SourceChunk.school_id == school_id))
    }


def _sources_by_id(db: Session, *, school_id: uuid.UUID) -> dict[uuid.UUID, Source]:
    return {s.id: s for s in db.scalars(select(Source).where(Source.school_id == school_id))}


def _label(labels: dict[str, str] | None, language: str) -> str:
    labels = labels or {}
    return labels.get(language) or labels.get("en") or labels.get("fr") or next(iter(labels.values()), "—")


def _excerpt(text: str, *, limit: int = EXCERPT_CHARS) -> str:
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[:limit].rsplit(" ", 1)[0] + "…"


def _shorten(text: str, *, limit: int = 60) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit].rsplit(" ", 1)[0] + "…"
