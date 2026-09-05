"""Per-student adaptive proposals (F4) — retrieve first, generate only the gap.

For each student the service reads the latest `MasterySnapshot` per competency,
picks the weakest ones, fills the sheet from indexed textbook exercises, and
calls a model only for whatever retrieval could not supply.

Why retrieval comes first
-------------------------
A textbook exercise is *already* pedagogically vetted, printed in the language
the class works in, tied to a page the teacher can open, and free. A generated
one is none of those until a teacher reads it. So generation is the fallback,
not the default: it fills the remainder of a sheet that the corpus could not
fill, and every generated item arrives with `approved_at = None`.

The approval gate
-----------------
`ExerciseOrigin.AI_GENERATED` + `approved_at IS NULL` is the state that must
never reach paper. Two places enforce it:

* `retrieval.gather_candidates` will not propose such an exercise for an
  ordinary sheet (``include_unapproved=False``), and
* `ensure_printable` raises `UnapprovedExerciseError` — call it in the render
  path, which is where "never printed" actually means something.

The adaptive response is the one place unapproved items are surfaced, in their
own `generated` list, so the UI can mark them with the accent colour and the
teacher can approve them one by one.

Privacy
-------
A student's name never reaches a provider. The prompt is given
``alppy.ai.scrub.to_ref(student.uid)`` — "7B_15" — and the class roster is
handed to `AiClient.complete(student_names=...)`, which runs `assert_no_pii`
over the rendered system and user text before anything is sent. The roster is
passed even though the prompt has no name field: the gate is what proves the
property, and it must be armed to prove anything.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from alppy.ai.client import AiClient, load_prompt, parse_json_response
from alppy.ai.scrub import to_ref
from alppy.core.logging import get_logger
from alppy.models import Competency, Exercise, MasterySnapshot, Student
from alppy.models.enums import ExerciseOrigin, ExerciseType, MasteryBand
from alppy.schemas import (
    AdaptiveProposeResponse,
    AdaptiveStudentPlan,
    ExerciseProposal,
    Provenance,
)
from alppy.services import retrieval

log = get_logger(__name__)

TARGET_BANDS: tuple[MasteryBand, ...] = (MasteryBand.FADING, MasteryBand.WEAK, MasteryBand.OK)
"""Weakest first. `SOLID` is skipped — re-drilling a mastered competency spends
a student's attention on the thing they already have. `NONE` is skipped too: it
is 'never assessed', which is an absence of evidence, not a gap; the fallback
below covers a student with no evidence at all."""

BAND_PRIORITY: dict[MasteryBand, int] = {band: i for i, band in enumerate(TARGET_BANDS)}

MAX_TARGET_COMPETENCIES = 4
"""A sheet that chases eight gaps at once teaches nothing about any of them."""

FALLBACK_DIFFICULTY = 2
"""For a student with no mastery data: a gentle diagnostic level."""

STYLE_EXAMPLE_COUNT = 3
GENERATION_TEMPERATURE = 0.6


class UnapprovedExerciseError(RuntimeError):
    """An AI-generated exercise reached the print path without approval."""


@dataclass(frozen=True, slots=True)
class Gap:
    """One competency worth targeting for one student."""

    competency_id: uuid.UUID
    band: MasteryBand
    score: float
    target_difficulty: int


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def propose_adaptive(
    db: Session,
    *,
    school_id: uuid.UUID,
    class_id: uuid.UUID,
    subject_id: uuid.UUID,
    student_ids: list[uuid.UUID],
    items_per_student: int,
    allow_generation: bool,
    language: str,
    ai: AiClient | None = None,
) -> AdaptiveProposeResponse:
    """Build one differentiated plan per requested student.

    ``ai`` has a default and exists so a worker can share one client (and one
    audit buffer) across a whole class batch.
    """
    students = _students(db, school_id=school_id, class_id=class_id, student_ids=student_ids)
    roster_names = _roster_names(db, school_id=school_id, class_id=class_id)
    client = ai or AiClient()

    plans: list[AdaptiveStudentPlan] = []
    generated_total = 0

    for student in students:
        plan = _plan_for_student(
            db,
            student=student,
            school_id=school_id,
            subject_id=subject_id,
            items_per_student=items_per_student,
            allow_generation=allow_generation,
            language=language,
            roster_names=roster_names,
            ai=client,
        )
        generated_total += len(plan.generated)
        plans.append(plan)

    if generated_total:
        # Generated exercises are rows now: the response hands back their ids,
        # so they must outlive this transaction.
        db.commit()
    else:
        db.flush()

    log.info(
        "adaptive.propose",
        school_id=str(school_id),
        class_id=str(class_id),
        students=len(plans),
        generated=generated_total,
    )
    return AdaptiveProposeResponse(
        plans=plans,
        language=language,
        generated_count=generated_total,
        needs_approval=generated_total > 0,
    )


def ensure_printable(exercises: Iterable[Exercise]) -> None:
    """The gate. Raises unless every AI-generated exercise has been approved.

    Call this from the render path. It raises rather than filtering, because a
    sheet quietly missing three of its twelve items is a worse outcome for a
    teacher standing at a photocopier than an error that says why.
    """
    offenders = [
        ex
        for ex in exercises
        if ex.origin is ExerciseOrigin.AI_GENERATED and ex.approved_at is None
    ]
    if offenders:
        ids = ", ".join(str(ex.id) for ex in offenders[:5])
        raise UnapprovedExerciseError(
            f"{len(offenders)} AI-generated exercise(s) are not approved and cannot be "
            f"printed: {ids}"
        )


def is_printable(exercise: Exercise) -> bool:
    return not (
        exercise.origin is ExerciseOrigin.AI_GENERATED and exercise.approved_at is None
    )


def approve_exercises(
    db: Session,
    *,
    school_id: uuid.UUID,
    exercise_ids: Sequence[uuid.UUID],
    at: datetime | None = None,
) -> int:
    """Teacher approval. The only way an AI-generated item becomes printable."""
    if not exercise_ids:
        return 0
    stamp = at or datetime.now(UTC)
    rows = list(
        db.scalars(
            select(Exercise).where(
                Exercise.school_id == school_id, Exercise.id.in_(list(exercise_ids))
            )
        )
    )
    for row in rows:
        row.approved_at = stamp
    db.flush()
    return len(rows)


# --------------------------------------------------------------------------
# Gap targeting
# --------------------------------------------------------------------------
def latest_snapshots(
    db: Session, *, school_id: uuid.UUID, student_id: uuid.UUID
) -> list[MasterySnapshot]:
    """The most recent snapshot per competency for one student.

    Done in Python over an ordered fetch rather than with a window function:
    the row count per student is the number of competencies in one subject
    (tens), and this works identically on SQLite and Postgres.
    """
    rows = db.scalars(
        select(MasterySnapshot)
        .where(
            MasterySnapshot.school_id == school_id,
            MasterySnapshot.student_id == student_id,
        )
        .order_by(MasterySnapshot.computed_at.desc())
    )
    latest: dict[uuid.UUID, MasterySnapshot] = {}
    for row in rows:
        latest.setdefault(row.competency_id, row)
    return list(latest.values())


def pick_gaps(
    snapshots: Sequence[MasterySnapshot], *, limit: int = MAX_TARGET_COMPETENCIES
) -> list[Gap]:
    """Weakest competencies first: fading, then weak, then ok. Solid is skipped."""
    scored = [s for s in snapshots if s.band in BAND_PRIORITY]
    scored.sort(key=lambda s: (BAND_PRIORITY[s.band], s.score))
    return [
        Gap(
            competency_id=s.competency_id,
            band=s.band,
            score=s.score,
            target_difficulty=target_difficulty(s.score, s.band),
        )
        for s in scored[:limit]
    ]


def target_difficulty(score: float, band: MasteryBand) -> int:
    """The level to practise at — the level the student can work at now.

    Mastery maps onto a working level (1-4, monotone in the score), and a
    *fading* competency drops one below it: the evidence there is stale, so the
    first item should rebuild confidence rather than test it. A *weak* (fragile)
    competency is practised at level, which is where the struggle actually is.
    """
    bounded = max(0.0, min(1.0, score))
    level = 1 + math.floor(3.0 * bounded + 0.5)  # 1..4, half-up
    if band is MasteryBand.FADING:
        level -= 1
    return max(1, min(5, level))


# --------------------------------------------------------------------------
# Per-student plan
# --------------------------------------------------------------------------
def _plan_for_student(
    db: Session,
    *,
    student: Student,
    school_id: uuid.UUID,
    subject_id: uuid.UUID,
    items_per_student: int,
    allow_generation: bool,
    language: str,
    roster_names: list[str],
    ai: AiClient,
) -> AdaptiveStudentPlan:
    gaps = pick_gaps(latest_snapshots(db, school_id=school_id, student_id=student.id))
    competency_ids = [g.competency_id for g in gaps]
    labels = _competency_labels(db, competency_ids, language=language)

    # A student with no confirmed attempts yet gets a diagnostic set from the
    # subject at large rather than an empty sheet.
    diagnostic = not gaps
    difficulty = (
        FALLBACK_DIFFICULTY
        if diagnostic
        else round(sum(g.target_difficulty for g in gaps) / len(gaps))
    )
    intent = ", ".join(labels.values()) if labels else None

    # --- 1. retrieve -----------------------------------------------------
    candidates = retrieval.gather_candidates(
        db,
        school_id=school_id,
        subject_id=subject_id,
        chapter_ids=None,
        competency_ids=competency_ids or None,
        intent=intent,
        language=language,
        difficulty=difficulty,
        ai=ai,
    )
    selected = retrieval.select_diverse(candidates, count=items_per_student)
    retrieved = [
        retrieval.build_proposal(
            cand,
            language=language,
            target_difficulty=difficulty,
            intent=intent,
            extra_reason=_gap_reason(cand, gaps, language=language, diagnostic=diagnostic),
        )
        for cand in selected
    ]

    # --- 2. generate only the gap ---------------------------------------
    generated: list[ExerciseProposal] = []
    shortfall = items_per_student - len(retrieved)
    if shortfall > 0 and allow_generation and competency_ids:
        generated = _generate(
            db,
            student=student,
            school_id=school_id,
            subject_id=subject_id,
            competency_ids=competency_ids,
            labels=list(labels.values()),
            difficulty=difficulty,
            count=shortfall,
            language=language,
            style_examples=[c.exercise.statement for c in selected[:STYLE_EXAMPLE_COUNT]],
            chapter_id=next((c.exercise.chapter_id for c in selected), None),
            roster_names=roster_names,
            ai=ai,
        )

    return AdaptiveStudentPlan(
        student_id=student.id,
        student_uid=student.uid,
        targeted_competency_ids=competency_ids,
        retrieved=retrieved,
        generated=generated,
    )


def _gap_reason(
    candidate: retrieval.Candidate,
    gaps: Sequence[Gap],
    *,
    language: str,
    diagnostic: bool,
) -> str | None:
    p = _GAP_PHRASES.get(language, _GAP_PHRASES["en"])
    if diagnostic:
        return p["diagnostic"]
    hit = next((g for g in gaps if g.competency_id in candidate.matched_competency_ids), None)
    if hit is None:
        return None
    return p["gap"].format(band=_BAND_WORDS.get(language, _BAND_WORDS["en"])[hit.band])


_GAP_PHRASES: dict[str, dict[str, str]] = {
    "fr": {
        "gap": "cible une compétence {band}",
        "diagnostic": "aucune donnée de maîtrise : série de diagnostic",
        "generated": "généré pour combler la fiche — validation requise",
    },
    "de": {
        "gap": "zielt auf eine {band} Kompetenz",
        "diagnostic": "keine Kompetenzdaten: diagnostische Serie",
        "generated": "erzeugt, um das Blatt zu füllen — Freigabe erforderlich",
    },
    "en": {
        "gap": "targets a {band} competency",
        "diagnostic": "no mastery data yet: diagnostic set",
        "generated": "generated to complete the sheet — approval required",
    },
}

_BAND_WORDS: dict[str, dict[MasteryBand, str]] = {
    "fr": {MasteryBand.FADING: "en perte", MasteryBand.WEAK: "fragile", MasteryBand.OK: "acquise"},
    "de": {MasteryBand.FADING: "verblassende", MasteryBand.WEAK: "brüchige", MasteryBand.OK: "solide"},
    "en": {MasteryBand.FADING: "fading", MasteryBand.WEAK: "fragile", MasteryBand.OK: "ok"},
}


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------
def _generate(
    db: Session,
    *,
    student: Student,
    school_id: uuid.UUID,
    subject_id: uuid.UUID,
    competency_ids: Sequence[uuid.UUID],
    labels: Sequence[str],
    difficulty: int,
    count: int,
    language: str,
    style_examples: Sequence[str],
    chapter_id: uuid.UUID | None,
    roster_names: list[str],
    ai: AiClient,
) -> list[ExerciseProposal]:
    prompt = load_prompt("generate_exercises")
    # to_ref validates the UID. Passing a name where a UID belongs raises here,
    # before a prompt is even rendered.
    ref = to_ref(student.uid)

    values = {
        "language": language,
        "competency_labels": "; ".join(labels) or "—",
        "difficulty": difficulty,
        "count": count,
        "style_examples": _format_style_examples(style_examples),
        "student_ref": str(ref),
    }

    try:
        response, record = ai.complete(
            prompt=prompt,
            purpose="adaptive_generate",
            values=values,
            # The gate. Armed with the real roster so that a future edit which
            # leaks a name into any of these values fails loudly here.
            student_names=roster_names,
            temperature=GENERATION_TEMPERATURE,
        )
        payload = parse_json_response(response.text)
    except Exception as exc:
        log.warning(
            "adaptive.generate.failed",
            student_uid=str(ref),
            error=type(exc).__name__,
        )
        return []

    competencies = list(
        db.scalars(select(Competency).where(Competency.id.in_(list(competency_ids))))
    )
    proposals: list[ExerciseProposal] = []
    for item in (payload.get("exercises") or [])[:count]:
        exercise = _build_generated_exercise(
            item,
            school_id=school_id,
            subject_id=subject_id,
            chapter_id=chapter_id,
            language=language,
            difficulty=difficulty,
            student_uid=str(ref),
            competency_ids=competency_ids,
            model=record.model,
            prompt_name=f"{prompt.name}.{prompt.version}",
        )
        if exercise is None:
            continue
        exercise.competencies = competencies
        db.add(exercise)
        proposals.append(
            _generated_proposal(exercise, language=language, difficulty=difficulty)
        )
    db.flush()
    log.info(
        "adaptive.generate",
        student_uid=str(ref),
        requested=count,
        produced=len(proposals),
        model=record.model,
    )
    return proposals


def _format_style_examples(statements: Sequence[str]) -> str:
    """Retrieved exercises become the register the generated ones must match.

    Without them the model writes generic textbook English-textbook prose; with
    them a generated item reads like the rest of the sheet, which is what makes
    the accent marking a *label* rather than a giveaway.
    """
    if not statements:
        return "(no example available — follow the rules above)"
    return "\n".join(f"- {' '.join(s.split())}" for s in statements)


def _build_generated_exercise(
    item: object,
    *,
    school_id: uuid.UUID,
    subject_id: uuid.UUID,
    chapter_id: uuid.UUID | None,
    language: str,
    difficulty: int,
    student_uid: str,
    competency_ids: Sequence[uuid.UUID],
    model: str,
    prompt_name: str,
) -> Exercise | None:
    if not isinstance(item, dict):
        return None
    statement = str(item.get("statement") or "").strip()
    if len(statement) < 8:
        return None
    try:
        kind = ExerciseType(str(item.get("type") or "mcq").strip().lower())
    except ValueError:
        return None

    options = item.get("options")
    options = [str(o).strip() for o in options] if isinstance(options, list) else None
    answer_index = item.get("answer_index")
    answer_index = answer_index if isinstance(answer_index, int) else None
    answer_bool = item.get("answer_bool")
    answer_bool = answer_bool if isinstance(answer_bool, bool) else None

    if kind is ExerciseType.MCQ:
        if not options or len(options) < 2 or answer_index is None:
            return None
        if not 0 <= answer_index < len(options):
            return None
        answer_bool = None
    elif kind is ExerciseType.TRUE_FALSE:
        if answer_bool is None:
            return None
        options, answer_index = None, None
    else:
        options, answer_index, answer_bool = None, None, None

    return Exercise(
        id=uuid.uuid4(),
        school_id=school_id,
        subject_id=subject_id,
        chapter_id=chapter_id,
        type=kind,
        origin=ExerciseOrigin.AI_GENERATED,
        language=language,
        statement=statement,
        options=options,
        answer_index=answer_index,
        answer_bool=answer_bool,
        explanation=(str(item.get("explanation")).strip() or None)
        if item.get("explanation")
        else None,
        difficulty=_clamp(item.get("difficulty"), default=difficulty),
        # The gate: never printable until a teacher says so.
        approved_at=None,
        generation_meta={
            "student_ref": student_uid,  # UID, never a name
            "competency_ids": [str(c) for c in competency_ids],
            "prompt": prompt_name,
            "model": model,
            "target_difficulty": difficulty,
            "language": language,
        },
    )


def _generated_proposal(
    exercise: Exercise, *, language: str, difficulty: int
) -> ExerciseProposal:
    p = retrieval.phrases(language)
    gap = _GAP_PHRASES.get(language, _GAP_PHRASES["en"])
    reason = " · ".join(
        [
            gap["generated"],
            p["difficulty_target"].format(difficulty=exercise.difficulty, target=difficulty),
            p["language"].format(language=exercise.language),
        ]
    )
    return ExerciseProposal(
        exercise=retrieval.exercise_out(
            exercise, [c.id for c in exercise.competencies]
        ),
        score=0.0,  # not ranked against the corpus: it exists to fill a gap
        provenance=Provenance(
            source_id=None,
            source_filename=None,
            page=None,
            excerpt=None,
            similarity=None,
            reason=reason,
        ),
    )


def _clamp(value: object, *, default: int) -> int:
    """Coerce a model-supplied difficulty into 1..5.

    The value arrives from parsed JSON, so it is genuinely `object`: a model can
    return "3", 3, 3.0 or nonsense, and none of those should crash a sheet.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return max(1, min(5, default))
    try:
        return max(1, min(5, int(float(value))))
    except (TypeError, ValueError):
        return max(1, min(5, default))


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
def _students(
    db: Session,
    *,
    school_id: uuid.UUID,
    class_id: uuid.UUID,
    student_ids: Sequence[uuid.UUID],
) -> list[Student]:
    stmt = select(Student).where(
        Student.school_id == school_id, Student.class_id == class_id
    )
    if student_ids:
        stmt = stmt.where(Student.id.in_(list(student_ids)))
    rows = list(db.scalars(stmt.order_by(Student.number)))
    if student_ids:
        order = {sid: i for i, sid in enumerate(student_ids)}
        rows.sort(key=lambda s: order.get(s.id, len(order)))
    return rows


def _roster_names(db: Session, *, school_id: uuid.UUID, class_id: uuid.UUID) -> list[str]:
    """Every name in the class, for the PII gate to check prompts against.

    Names are read here and used for nothing except *forbidding* them.
    """
    names: list[str] = []
    for student in db.scalars(
        select(Student).where(Student.school_id == school_id, Student.class_id == class_id)
    ):
        names.extend(n for n in (student.first_name, student.last_name) if n and len(n) > 1)
    return names


def _competency_labels(
    db: Session, competency_ids: Sequence[uuid.UUID], *, language: str
) -> dict[uuid.UUID, str]:
    if not competency_ids:
        return {}
    rows = db.scalars(
        select(Competency)
        .options(selectinload(Competency.children))
        .where(Competency.id.in_(list(competency_ids)))
    )
    by_id = {row.id: row for row in rows}
    out: dict[uuid.UUID, str] = {}
    for cid in competency_ids:
        row = by_id.get(cid)
        if row is None:
            continue
        labels = row.labels or {}
        out[cid] = labels.get(language) or labels.get("en") or labels.get("fr") or row.code
    return out
