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
never reach paper. It is enforced in `alppy.services.approval`, which the
sheet builder and both render entry points call — see that module for why the
gate does not live here. This module only ever *creates* items in that state and
surfaces them in their own `generated` list, so the UI can mark them with the
accent colour and the teacher can read each one before approving it.

Language
--------
The language of a generated exercise follows the **source material**, never the
teacher's interface. `source_language` reads it off the corpus the class
actually works from; the teacher's locale is only a last resort for a subject
with no indexed exercises at all. Getting this wrong is not merely a wrong label:
`Exercise.language` chooses the printed true/false glyphs (V/F · R/F · T/F),
and the detector reads bubbles by position, so a mislabelled item prints the
wrong letters next to the right holes.

Privacy
-------
A student's name never reaches a provider. The prompt is given
``alppy.ai.scrub.to_ref(student.uid)`` — "7B_15" — and the class roster is
handed to `AiClient.complete(student_names=...)`, which runs `assert_no_pii`
over the rendered system and user text before anything is sent.

Style examples are *scrubbed* on the way in rather than merely asserted over.
They are textbook prose, and Swiss textbook prose is full of Léa, Noah and Emma
— who are also in the class. Asserting alone meant a corpus that happened to
name a pupil silently killed generation for that student (decisions-log D10 was
too optimistic: the roster match is exact, but it is exact against *content*
too). `scrub` redacts them; `assert_no_pii` stays armed as the final assertion,
because the gate is what proves the property.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from alppy.ai.audit import record_calls
from alppy.ai.client import AiClient, load_prompt, parse_json_response
from alppy.ai.scrub import PiiLeakError, scrub, to_ref
from alppy.core.logging import get_logger
from alppy.models import Competency, Exercise, MasterySnapshot, Student
from alppy.models.enums import ExerciseOrigin, ExerciseType, MasteryBand
from alppy.schemas import (
    AdaptiveGenerationFailure,
    AdaptiveGroupItem,
    AdaptiveGroupPlan,
    AdaptiveProposeResponse,
    AdaptiveStudentPlan,
    ExerciseProposal,
    Provenance,
)
from alppy.services import retrieval
from alppy.services.approval import (
    UnapprovedExerciseError,
    approve_exercises,
    discard_exercises,
    ensure_printable,
    is_printable,
)
from alppy.sheets.layout import MAX_OPTIONS

log = get_logger(__name__)

# Re-exported so callers (and the existing tests) can reach the gate through the
# adaptive service, while the gate itself stays importable with no dependency on
# this module. See `alppy.services.approval`.
__all__ = [
    "AdaptiveGenerationError",
    "Gap",
    "UnapprovedExerciseError",
    "approve_exercises",
    "discard_exercises",
    "ensure_printable",
    "is_printable",
    "pick_gaps",
    "propose_adaptive",
    "regenerate_exercise",
    "source_language",
    "target_difficulty",
]

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


class AdaptiveGenerationError(RuntimeError):
    """Regeneration could not produce a replacement item."""


@dataclass(frozen=True, slots=True)
class Gap:
    """One competency worth targeting for one student."""

    competency_id: uuid.UUID
    band: MasteryBand
    score: float
    target_difficulty: int


# --------------------------------------------------------------------------
# The strict response schema
# --------------------------------------------------------------------------
def _normalise(text: str) -> str:
    """Casefolded, whitespace-collapsed form used to compare two statements."""
    return " ".join(text.split()).casefold()


class GeneratedExerciseIn(BaseModel):
    """What a generated item must look like before it is allowed to become a row.

    `extra="forbid"` on purpose. A model that invents a field has not understood
    the schema it was given, and quietly dropping the field is how a plausible
    item with a wrong answer key ends up on a printed sheet. The whole item is
    rejected; the others in the same response are unaffected.

    Every rule below is a thing that would otherwise reach paper:

    * **type** is restricted to the two auto-gradable kinds. A generated `open`
      item claims no bubbles, can never be graded, and so occupies a slot on a
      sheet whose only purpose is to produce evidence.
    * **options** are capped at ``MAX_OPTIONS`` because the answer grid draws
      exactly that many bubbles. Six printed options and four bubbles means the
      correct answer has no hole to fill and every child is marked wrong.
    * **options are distinct and non-empty.** Two identical options with the key
      on one of them scores a child wrong for choosing the same answer.
    * **answer_index** must address an option that exists.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["mcq", "true_false"]
    statement: str
    options: list[str] | None = None
    answer_index: int | None = None
    answer_bool: bool | None = None
    explanation: str | None = None
    # Deliberately untyped: models return 3, "3" and 3.0 for this, and none of
    # those should cost us an otherwise good exercise. Clamped by `_clamp`.
    difficulty: Any = None

    @model_validator(mode="after")
    def _check(self) -> GeneratedExerciseIn:
        if len(self.statement) < 8:
            raise ValueError("statement is too short to be an exercise")
        if len(self.statement) > 600:
            raise ValueError("statement will not fit a printed item slot")

        if self.type == "mcq":
            options = [o.strip() for o in (self.options or [])]
            if not 2 <= len(options) <= MAX_OPTIONS:
                raise ValueError(f"an mcq needs 2..{MAX_OPTIONS} options, got {len(options)}")
            if any(not o for o in options):
                raise ValueError("an mcq option cannot be blank")
            if len({o.casefold() for o in options}) != len(options):
                raise ValueError("two mcq options are the same; one key would mark both")
            if self.answer_index is None or not 0 <= self.answer_index < len(options):
                raise ValueError("answer_index does not address an option that exists")
            self.options = options
            self.answer_bool = None
        else:  # true_false
            if self.answer_bool is None:
                raise ValueError("a true/false item needs exactly one truth value")
            if self.options:
                raise ValueError("a true/false item carries no options")
            self.options = None
            self.answer_index = None
        return self


# --------------------------------------------------------------------------
# Language
# --------------------------------------------------------------------------
def source_language(
    db: Session, *, school_id: uuid.UUID, subject_id: uuid.UUID, fallback: str
) -> str:
    """The language the class actually works in, read off the corpus.

    The modal language of the *textbook* exercises indexed for this subject.
    Generated exercises are stored, printed and graded in it, and it is not the
    teacher's UI locale: a teacher may read Alppy in English while their class
    works in French, and the child holding the paper is what matters.

    Ties break on the language code so the answer is stable across runs.
    """
    rows = db.execute(
        select(Exercise.language, func.count(Exercise.id))
        .where(
            Exercise.school_id == school_id,
            Exercise.subject_id == subject_id,
            Exercise.origin == ExerciseOrigin.TEXTBOOK,
        )
        .group_by(Exercise.language)
    ).all()
    if not rows:
        # No corpus at all: nothing to follow, so the teacher's locale is the
        # only signal we have.
        return fallback
    counted = [(str(language), int(count)) for language, count in rows]
    return sorted(counted, key=lambda r: (-r[1], r[0]))[0][0]


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
    language: str | None = None,
    fallback_language: str = "fr",
    group: bool = False,
    ai: AiClient | None = None,
) -> AdaptiveProposeResponse:
    """Build one differentiated plan per requested student.

    ``language`` is an explicit teacher override and is normally ``None``; the
    language otherwise comes from the corpus (`source_language`), never from the
    UI locale. ``fallback_language`` is used only when the subject has no
    indexed exercises to read a language off.

    ``group`` builds ONE shared item list for the whole selection, targeting the
    union of their gaps, and still returns a per-student plan for each of them
    so the batch export is unchanged — every child needs their own page with
    their own UID grid whether or not the questions are shared.

    ``ai`` has a default and exists so a worker can share one client (and one
    audit buffer) across a whole class batch.
    """
    students = _students(db, school_id=school_id, class_id=class_id, student_ids=student_ids)
    roster_names = _roster_names(db, school_id=school_id, class_id=class_id)
    client = ai or AiClient()
    resolved = language or source_language(
        db, school_id=school_id, subject_id=subject_id, fallback=fallback_language
    )

    failures: list[AdaptiveGenerationFailure] = []
    group_plan: AdaptiveGroupPlan | None = None

    if group:
        plans, group_plan = _plan_for_group(
            db,
            students=students,
            school_id=school_id,
            class_id=class_id,
            subject_id=subject_id,
            items_per_student=items_per_student,
            allow_generation=allow_generation,
            language=resolved,
            roster_names=roster_names,
            failures=failures,
            ai=client,
        )
    else:
        plans = []
        for student in students:
            plans.append(
                _plan_for_student(
                    db,
                    student=student,
                    school_id=school_id,
                    class_id=class_id,
                    subject_id=subject_id,
                    items_per_student=items_per_student,
                    allow_generation=allow_generation,
                    language=resolved,
                    roster_names=roster_names,
                    failures=failures,
                    ai=client,
                )
            )

    generated_total = sum(len(p.generated) for p in plans)
    if group_plan is not None:
        # The group's items are shared, so summing the per-student plans would
        # count the same rows once per child.
        generated_total = len(group_plan.generated)

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
        retrieved=sum(len(p.retrieved) for p in plans),
        generated=generated_total,
        failures=len(failures),
        language=resolved,
        mode="group" if group else "per_student",
    )
    return AdaptiveProposeResponse(
        plans=plans,
        group=group_plan,
        language=resolved,
        generated_count=generated_total,
        needs_approval=generated_total > 0,
        failures=failures,
    )


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
    class_id: uuid.UUID,
    subject_id: uuid.UUID,
    items_per_student: int,
    allow_generation: bool,
    language: str,
    roster_names: list[str],
    failures: list[AdaptiveGenerationFailure],
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
        generated, failure = _generate(
            db,
            school_id=school_id,
            class_id=class_id,
            subject_id=subject_id,
            student_refs=[str(to_ref(student.uid))],
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
        if failure is not None:
            failures.append(
                failure.model_copy(
                    update={"student_id": student.id, "student_uid": student.uid}
                )
            )

    return AdaptiveStudentPlan(
        student_id=student.id,
        student_uid=student.uid,
        targeted_competency_ids=competency_ids,
        retrieved=retrieved,
        generated=generated,
    )


# --------------------------------------------------------------------------
# Group plan
# --------------------------------------------------------------------------
def _plan_for_group(
    db: Session,
    *,
    students: Sequence[Student],
    school_id: uuid.UUID,
    class_id: uuid.UUID,
    subject_id: uuid.UUID,
    items_per_student: int,
    allow_generation: bool,
    language: str,
    roster_names: list[str],
    failures: list[AdaptiveGenerationFailure],
    ai: AiClient,
) -> tuple[list[AdaptiveStudentPlan], AdaptiveGroupPlan]:
    """One shared item list for several students with overlapping gaps.

    The union is ranked by **how many of the group need each competency**, then
    by how badly. Targeting the widest overlap first is what makes a group sheet
    worth printing at all: an item only two of five children need is nearly a
    per-student sheet with extra steps.

    Each item then reports which of the group it is actually for, so the teacher
    can see the sheet is not uniform even though the paper is.
    """
    per_student: dict[uuid.UUID, list[Gap]] = {}
    for student in students:
        per_student[student.id] = pick_gaps(
            latest_snapshots(db, school_id=school_id, student_id=student.id)
        )

    # competency -> the students who need it
    need: dict[uuid.UUID, list[Student]] = {}
    severity: dict[uuid.UUID, tuple[int, float]] = {}
    for student in students:
        for gap in per_student[student.id]:
            need.setdefault(gap.competency_id, []).append(student)
            best = severity.get(gap.competency_id)
            here = (BAND_PRIORITY[gap.band], gap.score)
            if best is None or here < best:
                severity[gap.competency_id] = here

    ranked = sorted(
        need,
        key=lambda cid: (-len(need[cid]), severity[cid], str(cid)),
    )[:MAX_TARGET_COMPETENCIES]

    diagnostic = not ranked
    all_gaps = [g for gaps in per_student.values() for g in gaps if g.competency_id in ranked]
    difficulty = (
        FALLBACK_DIFFICULTY
        if not all_gaps
        else round(sum(g.target_difficulty for g in all_gaps) / len(all_gaps))
    )
    labels = _competency_labels(db, ranked, language=language)
    intent = ", ".join(labels.values()) if labels else None

    candidates = retrieval.gather_candidates(
        db,
        school_id=school_id,
        subject_id=subject_id,
        chapter_ids=None,
        competency_ids=ranked or None,
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
            extra_reason=_group_reason(cand, need, language=language, diagnostic=diagnostic),
        )
        for cand in selected
    ]

    generated: list[ExerciseProposal] = []
    shortfall = items_per_student - len(retrieved)
    if shortfall > 0 and allow_generation and ranked:
        generated, failure = _generate(
            db,
            school_id=school_id,
            class_id=class_id,
            subject_id=subject_id,
            student_refs=[str(to_ref(s.uid)) for s in students],
            competency_ids=ranked,
            labels=list(labels.values()),
            difficulty=difficulty,
            count=shortfall,
            language=language,
            style_examples=[c.exercise.statement for c in selected[:STYLE_EXAMPLE_COUNT]],
            chapter_id=next((c.exercise.chapter_id for c in selected), None),
            roster_names=roster_names,
            ai=ai,
        )
        if failure is not None and students:
            failures.append(
                failure.model_copy(
                    update={"student_id": students[0].id, "student_uid": "group"}
                )
            )

    # Attribution: which of the group is each item actually for?
    gap_ids_by_student = {
        s.id: {g.competency_id for g in per_student[s.id]} for s in students
    }
    items: list[AdaptiveGroupItem] = []
    for proposal in [*retrieved, *generated]:
        covered = set(proposal.exercise.competency_ids)
        uids = [
            s.uid for s in students if gap_ids_by_student[s.id] & covered
        ] or [s.uid for s in students]  # a diagnostic item is for everyone
        items.append(AdaptiveGroupItem(exercise_id=proposal.exercise.id, for_student_uids=uids))

    group_plan = AdaptiveGroupPlan(
        student_ids=[s.id for s in students],
        student_uids=[s.uid for s in students],
        targeted_competency_ids=list(ranked),
        retrieved=retrieved,
        generated=generated,
        items=items,
    )

    # Every child still gets their own page with their own UID grid: the
    # questions are shared, the paper never is.
    plans = [
        AdaptiveStudentPlan(
            student_id=s.id,
            student_uid=s.uid,
            targeted_competency_ids=list(ranked),
            retrieved=retrieved,
            generated=generated,
        )
        for s in students
    ]
    return plans, group_plan


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


def _group_reason(
    candidate: retrieval.Candidate,
    need: dict[uuid.UUID, list[Student]],
    *,
    language: str,
    diagnostic: bool,
) -> str | None:
    p = _GAP_PHRASES.get(language, _GAP_PHRASES["en"])
    if diagnostic:
        return p["diagnostic"]
    uids = sorted(
        {s.uid for cid in candidate.matched_competency_ids for s in need.get(cid, [])}
    )
    if not uids:
        return None
    return p["group"].format(count=len(uids), uids=", ".join(uids))


_GAP_PHRASES: dict[str, dict[str, str]] = {
    "fr": {
        "gap": "cible une compétence {band}",
        "diagnostic": "aucune donnée de maîtrise : série de diagnostic",
        "generated": "généré pour combler la fiche — validation requise",
        "group": "pour {count} élève(s) du groupe : {uids}",
    },
    "de": {
        "gap": "zielt auf eine {band} Kompetenz",
        "diagnostic": "keine Kompetenzdaten: diagnostische Serie",
        "generated": "erzeugt, um das Blatt zu füllen — Freigabe erforderlich",
        "group": "für {count} Lernende der Gruppe: {uids}",
    },
    "en": {
        "gap": "targets a {band} competency",
        "diagnostic": "no mastery data yet: diagnostic set",
        "generated": "generated to complete the sheet — approval required",
        "group": "for {count} student(s) in the group: {uids}",
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
def _failure(reason: str, *, requested: int, produced: int, detail: str) -> AdaptiveGenerationFailure:
    """A failure carries the ids only once the caller knows whose it was."""
    return AdaptiveGenerationFailure(
        student_id=uuid.UUID(int=0),
        student_uid="",
        reason=reason,
        requested=requested,
        produced=produced,
        detail=detail,
    )


def _classify(exc: Exception) -> tuple[str, str]:
    """Map an exception to a reason the UI can render and a short detail."""
    if isinstance(exc, PiiLeakError):
        # Never echo the message: it names the leak.
        return ("pii_gate", "the prompt was blocked before it left Alppy")
    if isinstance(exc, (ValueError, TypeError)):
        return ("unparsable_response", "the model did not return usable JSON")
    return ("provider_error", type(exc).__name__)


def _generate(
    db: Session,
    *,
    school_id: uuid.UUID,
    class_id: uuid.UUID,
    subject_id: uuid.UUID,
    student_refs: Sequence[str],
    competency_ids: Sequence[uuid.UUID],
    labels: Sequence[str],
    difficulty: int,
    count: int,
    language: str,
    style_examples: Sequence[str],
    chapter_id: uuid.UUID | None,
    roster_names: list[str],
    ai: AiClient,
) -> tuple[list[ExerciseProposal], AdaptiveGenerationFailure | None]:
    """Ask for ``count`` items and keep the ones that survive the schema.

    Returns what it produced *and* what went wrong, because a shorter sheet with
    no explanation is the failure mode a teacher cannot act on: they see fifteen
    items where they asked for sixteen and have no way to know whether the
    corpus ran out or the provider fell over.
    """
    prompt = load_prompt("generate_exercises")
    ref = ", ".join(student_refs)

    values = {
        "language": language,
        "competency_labels": "; ".join(labels) or "—",
        "difficulty": difficulty,
        "count": count,
        "max_options": MAX_OPTIONS,
        # Redacted, not merely asserted over: see the module docstring.
        "style_examples": _format_style_examples(style_examples, roster_names=roster_names),
        "student_ref": ref,
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
        # On the record before the response is even parsed: a call that was
        # made and then failed to parse still cost tokens and still happened.
        record_calls(db, school_id=school_id, records=[record])
        payload = parse_json_response(response.text)
    except Exception as exc:
        reason, detail = _classify(exc)
        # A blocked or failed call still produced a CallRecord; persist it so
        # the audit trail shows the attempt rather than a gap.
        _record_last(db, school_id=school_id, ai=ai)
        log.warning(
            "adaptive.generate.failed",
            student_uid=ref,
            reason=reason,
            error=type(exc).__name__,
        )
        return [], _failure(reason, requested=count, produced=0, detail=detail)

    competencies = list(
        db.scalars(select(Competency).where(Competency.id.in_(list(competency_ids))))
    )
    rejected: list[str] = []
    seen = _rejected_statements(db, school_id=school_id, subject_id=subject_id)
    proposals: list[ExerciseProposal] = []

    for item in (payload.get("exercises") or [])[:count]:
        try:
            parsed = GeneratedExerciseIn.model_validate(item)
        except ValidationError as exc:
            rejected.append(_first_error(exc))
            continue
        if _normalise(parsed.statement) in seen:
            # The teacher already threw this one away, or it is a duplicate of
            # something we just made. Offering it again wastes their attention.
            rejected.append("duplicate of an item already discarded or proposed")
            continue
        seen.add(_normalise(parsed.statement))

        exercise = _build_generated_exercise(
            parsed,
            school_id=school_id,
            class_id=class_id,
            subject_id=subject_id,
            chapter_id=chapter_id,
            language=language,
            difficulty=difficulty,
            student_refs=student_refs,
            competency_ids=competency_ids,
            model=record.model,
            prompt_name=f"{prompt.name}.{prompt.version}",
        )
        exercise.competencies = competencies
        db.add(exercise)
        proposals.append(_generated_proposal(exercise, language=language, difficulty=difficulty))

    db.flush()
    log.info(
        "adaptive.generate",
        student_uid=ref,
        requested=count,
        produced=len(proposals),
        rejected=len(rejected),
        model=record.model,
    )
    failure: AdaptiveGenerationFailure | None = None
    if len(proposals) < count:
        detail = (
            "; ".join(rejected[:3])
            if rejected
            else "the model returned fewer exercises than were asked for"
        )
        failure = _failure(
            "incomplete", requested=count, produced=len(proposals), detail=detail
        )
    return proposals, failure


def _first_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "did not match the schema"
    first = errors[0]
    location = ".".join(str(p) for p in first.get("loc", ())) or "item"
    return f"{location}: {first.get('msg', 'invalid')}"


def _record_last(db: Session, *, school_id: uuid.UUID, ai: AiClient) -> None:
    """Persist the most recent in-memory CallRecord, if it is not already stored.

    `AiClient.complete` appends a failed record and re-raises, so the failure
    path has one waiting that nobody would otherwise write.
    """
    if ai.records:
        record_calls(db, school_id=school_id, records=[ai.records[-1]])


def _rejected_statements(
    db: Session, *, school_id: uuid.UUID, subject_id: uuid.UUID
) -> set[str]:
    """Normalised statements the teacher has already discarded.

    Discarding is a decision, and re-proposing what was rejected is the fastest
    way to teach a teacher that the discard button does nothing.
    """
    rows = db.scalars(
        select(Exercise.statement).where(
            Exercise.school_id == school_id,
            Exercise.subject_id == subject_id,
            Exercise.discarded_at.is_not(None),
        )
    )
    return {_normalise(s) for s in rows}


def _format_style_examples(
    statements: Sequence[str], *, roster_names: Sequence[str]
) -> str:
    """Retrieved exercises become the register the generated ones must match.

    Without them the model writes generic textbook prose; with them a generated
    item reads like the rest of the sheet, which is what makes the accent
    marking a *label* rather than a giveaway.

    Scrubbed against the roster on the way in. A Swiss maths textbook is full of
    Léa, Noah and Emma, and so is the class — the name in the statement is the
    textbook's, not the child's, but the gate cannot tell the difference and
    should not have to.
    """
    if not statements:
        return "(no example available — follow the rules above)"
    cleaned = (scrub(" ".join(s.split()), names=list(roster_names)) for s in statements)
    return "\n".join(f"- {s}" for s in cleaned)


def _build_generated_exercise(
    item: GeneratedExerciseIn,
    *,
    school_id: uuid.UUID,
    class_id: uuid.UUID,
    subject_id: uuid.UUID,
    chapter_id: uuid.UUID | None,
    language: str,
    difficulty: int,
    student_refs: Sequence[str],
    competency_ids: Sequence[uuid.UUID],
    model: str,
    prompt_name: str,
) -> Exercise:
    kind = ExerciseType(item.type)
    return Exercise(
        id=uuid.uuid4(),
        school_id=school_id,
        subject_id=subject_id,
        chapter_id=chapter_id,
        type=kind,
        origin=ExerciseOrigin.AI_GENERATED,
        language=language,
        statement=item.statement,
        options=item.options,
        answer_index=item.answer_index,
        answer_bool=item.answer_bool,
        explanation=(item.explanation or None),
        difficulty=_clamp(item.difficulty, default=difficulty),
        # The gate: never printable until a teacher says so.
        approved_at=None,
        generation_meta={
            "student_refs": list(student_refs),  # UIDs, never names
            "class_id": str(class_id),
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
    return "3", 3, 3.0 or nonsense, and none of those should cost a good
    exercise.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return max(1, min(5, default))
    try:
        return max(1, min(5, int(float(value))))
    except (TypeError, ValueError):
        return max(1, min(5, default))


# --------------------------------------------------------------------------
# Regeneration
# --------------------------------------------------------------------------
def regenerate_exercise(
    db: Session,
    *,
    school_id: uuid.UUID,
    exercise_id: uuid.UUID,
    ai: AiClient | None = None,
) -> ExerciseProposal:
    """Replace one generated item with a fresh one, targeting the same gap.

    *Replaces*, never appends: the old row is discarded in the same
    transaction, so it can neither be printed nor proposed again, and the caller
    swaps the returned proposal into the slot the old one occupied.

    Raises `AdaptiveGenerationError` if no replacement could be produced — the
    old item is then left alone, because throwing away the teacher's only
    version of an item and handing back nothing is worse than a bad item.
    """
    exercise = db.scalars(
        select(Exercise)
        .options(selectinload(Exercise.competencies))
        .where(Exercise.id == exercise_id, Exercise.school_id == school_id)
    ).one_or_none()
    if exercise is None:
        raise AdaptiveGenerationError(f"no exercise {exercise_id}")
    if exercise.origin is not ExerciseOrigin.AI_GENERATED:
        raise AdaptiveGenerationError("only a generated exercise can be regenerated")

    meta = exercise.generation_meta or {}
    competency_ids = [c.id for c in exercise.competencies] or [
        uuid.UUID(c) for c in meta.get("competency_ids", [])
    ]
    language = str(meta.get("language") or exercise.language)
    difficulty = _clamp(meta.get("target_difficulty"), default=exercise.difficulty)
    class_id = _class_of(db, school_id=school_id, meta=meta)
    if class_id is None:
        raise AdaptiveGenerationError("cannot tell which class this item was generated for")

    client = ai or AiClient()
    labels = _competency_labels(db, competency_ids, language=language)
    roster_names = _roster_names(db, school_id=school_id, class_id=class_id)

    candidates = retrieval.gather_candidates(
        db,
        school_id=school_id,
        subject_id=exercise.subject_id,
        chapter_ids=None,
        competency_ids=competency_ids or None,
        intent=", ".join(labels.values()) or None,
        language=language,
        difficulty=difficulty,
        ai=client,
    )
    style = [c.exercise.statement for c in candidates[:STYLE_EXAMPLE_COUNT]]

    # Discard first, inside the same transaction. The replacement must not be
    # allowed to come back as a copy of what we are replacing, and
    # `_rejected_statements` is what stops it.
    discard_exercises(db, school_id=school_id, exercise_ids=[exercise.id])

    refs = [str(r) for r in meta.get("student_refs", [])] or _refs_from_legacy_meta(meta)
    proposals, failure = _generate(
        db,
        school_id=school_id,
        class_id=class_id,
        subject_id=exercise.subject_id,
        student_refs=refs or ["—"],
        competency_ids=competency_ids,
        labels=list(labels.values()),
        difficulty=difficulty,
        count=1,
        language=language,
        style_examples=style,
        chapter_id=exercise.chapter_id,
        roster_names=roster_names,
        ai=client,
    )
    if not proposals:
        db.rollback()
        detail = failure.detail if failure else "no replacement was produced"
        raise AdaptiveGenerationError(detail)

    db.commit()
    log.info(
        "adaptive.regenerate",
        replaced=str(exercise_id),
        replacement=str(proposals[0].exercise.id),
    )
    return proposals[0]


def _refs_from_legacy_meta(meta: dict[str, Any]) -> list[str]:
    """Rows written before `student_refs` was a list carried `student_ref`."""
    single = meta.get("student_ref")
    return [str(single)] if single else []


def _class_of(db: Session, *, school_id: uuid.UUID, meta: dict[str, Any]) -> uuid.UUID | None:
    """Which class an item was generated for.

    Newer rows record it; older ones only carry the UID, which still identifies
    the student uniquely inside a school.
    """
    raw = meta.get("class_id")
    if raw:
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            pass
    refs = [*(meta.get("student_refs") or []), *_refs_from_legacy_meta(meta)]
    for ref in refs:
        student = db.scalars(
            select(Student).where(Student.school_id == school_id, Student.uid == str(ref))
        ).first()
        if student is not None:
            return student.class_id
    return None


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
