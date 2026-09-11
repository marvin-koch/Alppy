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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from alppy.ai.audit import flush as flush_ai_log
from alppy.ai.base import ChatTruncatedError
from alppy.ai.client import AiClient, load_prompt, parse_json_response
from alppy.ai.scrub import PiiLeakError, scrub, to_ref
from alppy.core.config import get_settings
from alppy.core.logging import get_logger
from alppy.db.validity import today
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
    TargetingBasis,
)
from alppy.services import retrieval
from alppy.services.adaptive_clustering import cluster_students_with_model
from alppy.services.approval import (
    UnapprovedExerciseError,
    approve_exercises,
    discard_exercises,
    ensure_printable,
    is_printable,
)
from alppy.services.enrollment import enrolled_student_ids
from alppy.services.performance_summary import SheetPerformance, sheet_performance
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

TARGET_BANDS: tuple[MasteryBand, ...] = (
    MasteryBand.FADING,
    MasteryBand.WEAK,
    MasteryBand.OK,
    MasteryBand.SOLID,
)
"""Weakest first, and `SOLID` last as a **stretch** target.

`SOLID` used to be skipped, on the argument that re-drilling a mastered
competency spends a student's attention on what they already have. That
argument is right about *re-drilling* and wrong about the student it actually
described: with no gap in any band, `pick_gaps` returned empty, the plan fell
into its `diagnostic` branch, and a child who had mastered everything was
handed `FALLBACK_DIFFICULTY = 2` — easier work than they can already do. The
zone of proximal development points the other way, so `SOLID` is targeted at
lowest priority and `target_difficulty` pushes it *above* the working level
rather than at it. `MAX_STRETCH_COMPETENCIES` keeps it from crowding out real
gap work.

`NONE` is still skipped: it is 'never assessed', which is an absence of
evidence rather than a gap; the diagnostic fallback covers a student with no
evidence at all."""

BAND_PRIORITY: dict[MasteryBand, int] = {band: i for i, band in enumerate(TARGET_BANDS)}

MAX_TARGET_COMPETENCIES = 4
"""A sheet that chases eight gaps at once teaches nothing about any of them."""

MAX_STRETCH_COMPETENCIES = 1
"""How many of the targeted competencies may be a `SOLID` stretch target.

One. A sheet is for the gaps; stretch is the part that keeps a strong student
from being bored by their own revision. A student with *only* solid
competencies is the exception the cap deliberately does not apply to — see
`pick_gaps` — because for them there is no gap work to protect."""

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
    n_groups: int | None = None,
    source_sheet_id: uuid.UUID | None = None,
    llm_grouping: bool = False,
    commit: bool = True,
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

    ``n_groups`` supersedes ``group`` and is the whole point of the feature: it
    partitions the selection into that many personalised groups, each with its
    own shared item list. The two ends of the range are the two modes that
    already existed — 1 is the single shared sheet, and a value at or above the
    class size is one sheet per student — so nothing that worked before needs a
    different call.

    ``source_sheet_id`` is the sheet the teacher has just corrected. When it has
    confirmed results for a student, those results — not the term's rolling
    mastery average — choose that student's competencies. It is one query for
    the whole class, run here rather than per plan.

    ``commit`` is False when a worker task is the caller. ``worker/tasks.py``
    owns the transaction boundary — "a pipeline function must not commit or
    close ``db`` itself" — and committing underneath it would end the job's
    transaction halfway through, before the ``Job`` row is marked succeeded.

    ``ai`` has a default and exists so a worker can share one client (and one
    audit buffer) across a whole class batch.
    """
    students = _students(db, school_id=school_id, class_id=class_id, student_ids=student_ids)
    roster_names = _roster_names(db, school_id=school_id, class_id=class_id)
    client = ai or AiClient()
    performance: dict[uuid.UUID, SheetPerformance] = {}
    if source_sheet_id is not None:
        performance = sheet_performance(
            db,
            school_id=school_id,
            student_ids=[s.id for s in students],
            sheet_id=source_sheet_id,
        )
    resolved = language or source_language(
        db, school_id=school_id, subject_id=subject_id, fallback=fallback_language
    )

    failures: list[AdaptiveGenerationFailure] = []
    group_plan: AdaptiveGroupPlan | None = None
    group_plans: list[AdaptiveGroupPlan] = []
    collector = _Collector()

    # A request for as many groups as there are students is the per-student
    # path spelled differently, and the per-student planner targets each child's
    # own gaps rather than a one-member union. Route it there.
    wants_groups = n_groups is not None and n_groups > 1 and n_groups < len(students)
    single_group = group or (n_groups == 1)

    grouped_by_model = False
    if wants_groups:
        assert n_groups is not None
        plans, group_plans, grouped_by_model = _plan_for_groups(
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
            n_groups=n_groups,
            performance=performance,
            collector=collector,
            llm_grouping=llm_grouping,
        )
    elif single_group:
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
            performance=performance,
            collector=collector,
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
                    performance=performance.get(student.id),
                    collector=collector,
                )
            )

    # --- one pass over every plan's generation --------------------------
    # Retrieval is done; the shortfalls are known. This is the only place a
    # model is called for exercises, and it is where several plans become one
    # request. `seen` is shared across the whole run: rebuilt per call, it let
    # two groups in the same proposal generate the identical statement.
    if collector.asks:
        # Retrieval is finished and every row it wrote is durable before the
        # first model call goes out (audit 03, B11). Without this commit the
        # whole proposal — targeting, retrieval, every plan — sits in one open
        # transaction across up to three batched generation calls, each of
        # which can take a minute. A worker holding a write transaction open
        # for three minutes is a connection nobody else can have and a lock
        # nobody else can take, and if the provider hangs, the rollback throws
        # away work that had nothing to do with the provider.
        #
        # It is safe precisely because the batching design already separates
        # the phases: `collector.resolve` below writes the generated rows in
        # its own transaction, and a proposal whose generation fails is meant
        # to keep its retrieved items — that is what `failures` reports.
        db.commit()
        seen = _rejected_statements(db, school_id=school_id, subject_id=subject_id)
        collector.resolve(
            generate_for_asks(
                db,
                school_id=school_id,
                class_id=class_id,
                subject_id=subject_id,
                asks=collector.asks,
                language=resolved,
                roster_names=roster_names,
                ai=client,
                seen=seen,
            ),
            failures=failures,
        )

    generated_total = sum(len(p.generated) for p in plans)
    if group_plan is not None:
        # The group's items are shared, so summing the per-student plans would
        # count the same rows once per child.
        generated_total = len(group_plan.generated)
    elif group_plans:
        # Same again, per group: the clusters are disjoint, so summing the
        # groups counts each generated row exactly once.
        generated_total = sum(len(g.generated) for g in group_plans)

    if generated_total and commit:
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
        mode=("groups" if group_plans else "group" if single_group else "per_student"),
        groups=len(group_plans),
        grouped_by_model=grouped_by_model,
    )
    return AdaptiveProposeResponse(
        plans=plans,
        grouped_by_model=grouped_by_model,
        group=group_plan,
        groups=group_plans,
        language=resolved,
        generated_count=generated_total,
        needs_approval=generated_total > 0,
        failures=failures,
    )


# --------------------------------------------------------------------------
# Gap targeting
# --------------------------------------------------------------------------
def latest_snapshots(
    db: Session, *, school_id: uuid.UUID, person_id: uuid.UUID
) -> list[MasterySnapshot]:
    """The most recent snapshot per competency for one pupil.

    Done in Python over an ordered fetch rather than with a window function:
    the row count per pupil is the number of competencies in one subject
    (tens), and this works identically on SQLite and Postgres.

    Person-keyed since 0028, which is what lets a repeating pupil's gaps in
    September be the gaps they actually finished June with, rather than an
    empty set.
    """
    rows = db.scalars(
        select(MasterySnapshot)
        .where(
            MasterySnapshot.school_id == school_id,
            MasterySnapshot.person_id == person_id,
        )
        .order_by(MasterySnapshot.computed_at.desc())
    )
    latest: dict[uuid.UUID, MasterySnapshot] = {}
    for row in rows:
        latest.setdefault(row.competency_id, row)
    return list(latest.values())


class BandedSignal(Protocol):
    """What ranking a competency needs: which one, how well, how sure.

    A protocol so the same ranking serves both inputs — a stored
    ``MasterySnapshot`` (every attempt ever) and a ``CompetencySignal`` computed
    from one sheet. The alternative was a second `pick_gaps`, and two rankings
    that drift apart is exactly how the strongest child in a class ends up with
    the easiest sheet (D32).
    """

    @property
    def competency_id(self) -> uuid.UUID: ...

    @property
    def band(self) -> MasteryBand: ...

    @property
    def score(self) -> float: ...


def gaps_for_student(
    db: Session,
    *,
    school_id: uuid.UUID,
    person_id: uuid.UUID,
    performance: SheetPerformance | None,
) -> tuple[list[Gap], TargetingBasis]:
    """This student's gaps, and — just as important — where they came from.

    A teacher who corrects a sheet expects the follow-up to answer *that sheet*.
    So when the source sheet has results for this child, they win: the plan is
    about the lesson just taught, not about the term's rolling average.

    The fallback is not a second opinion. `MasterySnapshot` is derived from the
    same `Attempt` rows, unfiltered by sheet and weighted by recency and
    difficulty — so the two can disagree about the same child, and when they do
    the sheet is the more specific claim. Falling back only when the sheet says
    *nothing* keeps that from becoming an argument the model has to settle.

    A student with neither is the diagnostic case, and it is reported as such
    rather than silently looking like a student with no gaps.
    """
    if performance is not None and performance.has_evidence:
        return pick_gaps(performance.signals), "source_sheet"
    gaps = pick_gaps(latest_snapshots(db, school_id=school_id, person_id=person_id))
    return gaps, ("mastery" if gaps else "diagnostic")


def pick_gaps(
    snapshots: Sequence[BandedSignal],
    *,
    limit: int = MAX_TARGET_COMPETENCIES,
    max_stretch: int = MAX_STRETCH_COMPETENCIES,
) -> list[Gap]:
    """Weakest competencies first: fading, then weak, then ok, then solid.

    Real gaps fill the sheet first. `SOLID` entries are *stretch* and are
    admitted only with whatever room is left, at most ``max_stretch`` of them —
    so a student with four fading competencies gets four of those and no
    stretch at all.

    The exception is a student with nothing but solid competencies. There is no
    gap work to protect for them, so the cap is lifted and the whole sheet is
    stretch; the alternative is the diagnostic fallback, which hands the
    strongest child in the class the easiest sheet.
    """
    scored = [s for s in snapshots if s.band in BAND_PRIORITY]
    scored.sort(key=lambda s: (BAND_PRIORITY[s.band], s.score))

    gaps = [s for s in scored if s.band is not MasteryBand.SOLID]
    stretch = [s for s in scored if s.band is MasteryBand.SOLID]

    taken = gaps[:limit]
    room = limit - len(taken)
    if room > 0:
        # No gaps at all: the cap has nothing to protect, so let stretch fill.
        allowance = room if not taken else min(room, max_stretch)
        taken += stretch[:allowance]

    return [
        Gap(
            competency_id=s.competency_id,
            band=s.band,
            score=s.score,
            target_difficulty=target_difficulty(s.score, s.band),
        )
        for s in taken
    ]


def target_difficulty(score: float, band: MasteryBand) -> int:
    """The level to practise at — the level the student can work at now.

    Mastery maps onto a working level (1-4, monotone in the score), and a
    *fading* competency drops one below it: the evidence there is stale, so the
    first item should rebuild confidence rather than test it. A *weak* (fragile)
    competency is practised at level, which is where the struggle actually is.
    A *solid* one is practised one level **above**: it is targeted as stretch
    (see `TARGET_BANDS`), and stretch means the next thing up, not the thing
    already held. That is the only direction in which the clamp at 5 is
    reachable.
    """
    bounded = max(0.0, min(1.0, score))
    level = 1 + math.floor(3.0 * bounded + 0.5)  # 1..4, half-up
    if band is MasteryBand.FADING:
        level -= 1
    elif band is MasteryBand.SOLID:
        level += 1
    return max(1, min(5, level))


# --------------------------------------------------------------------------
# Deferred generation
# --------------------------------------------------------------------------
Finisher = Callable[[list[ExerciseProposal], AdaptiveGenerationFailure | None], None]


@dataclass(slots=True)
class _Collector:
    """Every plan's generation ask, gathered before any of them is sent.

    The planners still do their own retrieval and still decide their own
    shortfall — nothing about targeting moves. What moves is *when* the model is
    called: each planner registers what it needs and a closure that finishes its
    plan, and the whole run is filled in one pass afterwards.

    That is the same move D33 made for grouping — a phase placed above a planner
    that already worked — and it is why the batched path did not need a second
    planner to keep in step with the first.
    """

    asks: list[_GenerationAsk] = field(default_factory=list)
    finishers: dict[str, Finisher] = field(default_factory=dict)

    def register(
        self,
        *,
        competency_ids: Sequence[uuid.UUID],
        labels: Sequence[str],
        difficulty: int,
        count: int,
        style_examples: Sequence[str],
        chapter_id: uuid.UUID | None,
        student_refs: Sequence[str],
        owner_id: uuid.UUID,
        owner_uid: str,
        finish: Finisher,
    ) -> None:
        # Opaque and sequential. Never a UID: it is shorter, and it means the
        # batched prompt carries no student reference at all.
        plan_id = f"P{len(self.asks) + 1}"
        self.asks.append(
            _GenerationAsk(
                plan_id=plan_id,
                competency_ids=list(competency_ids),
                labels=list(labels),
                difficulty=difficulty,
                count=count,
                style_examples=list(style_examples),
                chapter_id=chapter_id,
                student_refs=list(student_refs),
                owner_id=owner_id,
                owner_uid=owner_uid,
            )
        )
        self.finishers[plan_id] = finish

    def resolve(
        self,
        results: dict[str, tuple[list[ExerciseProposal], AdaptiveGenerationFailure | None]],
        *,
        failures: list[AdaptiveGenerationFailure],
    ) -> None:
        for ask in self.asks:
            proposals, failure = results.get(ask.plan_id, ([], None))
            if failure is not None:
                failures.append(
                    failure.model_copy(
                        update={"student_id": ask.owner_id, "student_uid": ask.owner_uid}
                    )
                )
            self.finishers[ask.plan_id](proposals, failure)


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
    performance: SheetPerformance | None = None,
    collector: _Collector | None = None,
) -> AdaptiveStudentPlan:
    gaps, basis = gaps_for_student(
        db, school_id=school_id, person_id=student.person_id, performance=performance
    )
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

    plan = AdaptiveStudentPlan(
        student_id=student.id,
        student_uid=student.uid,
        targeted_competency_ids=competency_ids,
        retrieved=retrieved,
        generated=[],
        targeting_basis=basis,
        evidence_partial=bool(performance is not None and performance.is_partial),
    )

    # --- 2. generate only the gap ---------------------------------------
    shortfall = items_per_student - len(retrieved)
    if shortfall > 0 and allow_generation and competency_ids:
        assert collector is not None  # every caller supplies one

        def finish(
            proposals: list[ExerciseProposal],
            _failure: AdaptiveGenerationFailure | None,
        ) -> None:
            plan.generated = proposals

        collector.register(
            competency_ids=competency_ids,
            labels=list(labels.values()),
            difficulty=difficulty,
            count=shortfall,
            style_examples=[c.exercise.statement for c in selected[:STYLE_EXAMPLE_COUNT]],
            chapter_id=next((c.exercise.chapter_id for c in selected), None),
            student_refs=[str(to_ref(student.uid))],
            owner_id=student.id,
            owner_uid=student.uid,
            finish=finish,
        )

    return plan


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
    performance: dict[uuid.UUID, SheetPerformance] | None = None,
    collector: _Collector | None = None,
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
    bases: dict[uuid.UUID, TargetingBasis] = {}
    for student in students:
        per_student[student.id], bases[student.id] = gaps_for_student(
            db,
            school_id=school_id,
            person_id=student.person_id,
            performance=(performance or {}).get(student.id),
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

    # Attribution: which of the group is each item actually for?
    gap_ids_by_student = {
        s.id: {g.competency_id for g in per_student[s.id]} for s in students
    }

    def attribute(proposals: Sequence[ExerciseProposal]) -> list[AdaptiveGroupItem]:
        items: list[AdaptiveGroupItem] = []
        for proposal in proposals:
            covered = set(proposal.exercise.competency_ids)
            uids = [s.uid for s in students if gap_ids_by_student[s.id] & covered] or [
                s.uid for s in students
            ]  # a diagnostic item is for everyone
            items.append(
                AdaptiveGroupItem(exercise_id=proposal.exercise.id, for_student_uids=uids)
            )
        return items

    group_plan = AdaptiveGroupPlan(
        student_ids=[s.id for s in students],
        student_uids=[s.uid for s in students],
        targeted_competency_ids=list(ranked),
        retrieved=retrieved,
        generated=[],
        items=attribute(retrieved),
    )

    # Every child still gets their own page with their own UID grid: the
    # questions are shared, the paper never is.
    plans = [
        AdaptiveStudentPlan(
            student_id=s.id,
            student_uid=s.uid,
            targeted_competency_ids=list(ranked),
            retrieved=retrieved,
            generated=[],
            targeting_basis=bases[s.id],
            evidence_partial=bool(
                (perf := (performance or {}).get(s.id)) is not None and perf.is_partial
            ),
        )
        for s in students
    ]

    shortfall = items_per_student - len(retrieved)
    if shortfall > 0 and allow_generation and ranked and students:
        assert collector is not None  # every caller supplies one

        def finish(
            proposals: list[ExerciseProposal],
            _failure: AdaptiveGenerationFailure | None,
        ) -> None:
            # The group's items are shared, so every member's plan points at the
            # same list. Attribution is recomputed over the whole sheet: a
            # generated item is for whoever needed the competency it covers.
            group_plan.generated = proposals
            group_plan.items = attribute([*retrieved, *proposals])
            for member in plans:
                member.generated = proposals

        collector.register(
            competency_ids=ranked,
            labels=list(labels.values()),
            difficulty=difficulty,
            count=shortfall,
            style_examples=[c.exercise.statement for c in selected[:STYLE_EXAMPLE_COUNT]],
            chapter_id=next((c.exercise.chapter_id for c in selected), None),
            student_refs=[str(to_ref(s.uid)) for s in students],
            owner_id=students[0].id,
            # The group's own name once it has one; "group" for the single
            # shared sheet, which has no index to distinguish it from.
            owner_uid="group",
            finish=finish,
        )

    return plans, group_plan


# --------------------------------------------------------------------------
# N groups
# --------------------------------------------------------------------------
@dataclass(slots=True)
class _Bucket:
    """A candidate group, with a key that survives re-partitioning.

    The key is what a teacher's manual move is recorded against. Recording a
    move against a *position* is the bug that looks fine until the partition
    changes underneath it: groups reorder, one empties, and a student the
    teacher placed by hand silently lands somewhere else.
    """

    key: str
    gap_id: uuid.UUID | None
    members: list[Student]


def _severity(gap: Gap | None) -> tuple[int, float]:
    """Worst first. A student with no gap at all sorts last, not first —
    an absence of evidence is not a weakness (`mastery_service` says the same)."""
    if gap is None:
        return (len(TARGET_BANDS), 0.0)
    return (BAND_PRIORITY[gap.band], gap.score)


def cluster_students(
    students: Sequence[Student],
    gaps_by_student: dict[uuid.UUID, list[Gap]],
    *,
    n_groups: int,
) -> list[list[Student]]:
    """Partition a class into ``n_groups``, by the gap they most need.

    The rule has to be one a teacher can state and defend, because they are the
    one who will have to justify it to a parent:

        *Students with the same principal gap go together. If that gives more
        groups than you asked for, the smallest merge; if fewer, the largest
        splits by how badly.*

    Both extremes already exist and are preserved exactly: ``n_groups == 1`` is
    today's single shared group, and ``n_groups >= len(students)`` is one sheet
    per student. Nothing in between existed before.

    Deterministic: ties break on the roster number, so re-running produces the
    same partition and the teacher is not shown a reshuffled class for nothing.
    """
    if n_groups <= 1 or len(students) <= 1:
        return [list(students)]

    by_gap: dict[uuid.UUID | None, list[Student]] = {}
    for student in students:
        gaps = gaps_by_student.get(student.id) or []
        principal = gaps[0].competency_id if gaps else None
        by_gap.setdefault(principal, []).append(student)

    def rank(student: Student) -> tuple[int, float, int]:
        gaps = gaps_by_student.get(student.id) or []
        band, score = _severity(gaps[0] if gaps else None)
        return (band, score, student.number)

    buckets = [
        _Bucket(key=str(gap_id), gap_id=gap_id, members=sorted(members, key=rank))
        for gap_id, members in by_gap.items()
    ]

    # More gaps than groups: merge the smallest pair, repeatedly. Merging the
    # smallest keeps the largest coherent groups intact, which is where the
    # shared sheet earns its keep.
    while len(buckets) > n_groups:
        buckets.sort(key=lambda b: (len(b.members), _severity_of(b, gaps_by_student)))
        first, second = buckets.pop(0), buckets.pop(0)
        keep = first if len(first.members) >= len(second.members) else second
        buckets.append(
            _Bucket(
                key=f"{first.key}+{second.key}",
                gap_id=keep.gap_id,
                members=sorted(first.members + second.members, key=rank),
            )
        )

    # Fewer gaps than groups: split the largest by severity, so the half that
    # is struggling most is not held to the pace of the half that is not.
    serial = 0
    while len(buckets) < n_groups and any(len(b.members) > 1 for b in buckets):
        buckets.sort(key=lambda b: -len(b.members))
        big = buckets.pop(0)
        half = (len(big.members) + 1) // 2
        serial += 1
        buckets.append(
            _Bucket(key=f"{big.key}/a{serial}", gap_id=big.gap_id, members=big.members[:half])
        )
        buckets.append(
            _Bucket(key=f"{big.key}/b{serial}", gap_id=big.gap_id, members=big.members[half:])
        )

    buckets.sort(key=lambda b: _severity_of(b, gaps_by_student))
    return [b.members for b in buckets if b.members]


def _severity_of(
    bucket: _Bucket, gaps_by_student: dict[uuid.UUID, list[Gap]]
) -> tuple[float, float]:
    """A group's average severity, worst first, for a stable group order."""
    if not bucket.members:
        return (float(len(TARGET_BANDS)), 0.0)
    bands = 0.0
    scores = 0.0
    for student in bucket.members:
        gaps = gaps_by_student.get(student.id) or []
        band, score = _severity(gaps[0] if gaps else None)
        bands += band
        scores += score
    n = len(bucket.members)
    return (bands / n, scores / n)


def _plan_for_groups(
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
    n_groups: int,
    performance: dict[uuid.UUID, SheetPerformance] | None = None,
    collector: _Collector | None = None,
    llm_grouping: bool = False,
) -> tuple[list[AdaptiveStudentPlan], list[AdaptiveGroupPlan], bool]:
    """``n_groups`` shared sheets, one call to `_plan_for_group` per cluster.

    `_plan_for_group` is unchanged: it always took an arbitrary sequence of
    students, so N groups is a partition placed above it rather than a second
    planner to keep in step with the first.
    """
    gaps_by_student = {
        s.id: gaps_for_student(
            db,
            school_id=school_id,
            person_id=s.person_id,
            performance=(performance or {}).get(s.id),
        )[0]
        for s in students
    }
    clusters = cluster_students(students, gaps_by_student, n_groups=n_groups)
    grouped_by_model = False
    if llm_grouping:
        # The deterministic partition is the seed AND the fallback. There is no
        # path here where a model failure produces a worse partition rather than
        # this one (D33, I-adaptive-10).
        every_gap = [g.competency_id for gaps in gaps_by_student.values() for g in gaps]
        clusters, grouped_by_model = cluster_students_with_model(
            db,
            school_id=school_id,
            students=students,
            gaps_by_student=gaps_by_student,
            seed=clusters,
            n_groups=n_groups,
            competency_labels=_competency_labels(db, every_gap, language=language),
            roster_names=roster_names,
            ai=ai,
        )

    plans: list[AdaptiveStudentPlan] = []
    group_plans: list[AdaptiveGroupPlan] = []
    for index, cluster in enumerate(clusters, start=1):
        cluster_plans, group_plan = _plan_for_group(
            db,
            students=cluster,
            school_id=school_id,
            class_id=class_id,
            subject_id=subject_id,
            items_per_student=items_per_student,
            allow_generation=allow_generation,
            language=language,
            roster_names=roster_names,
            failures=failures,
            ai=ai,
            performance=performance,
            collector=collector,
        )
        label = _group_label(index, group_plan, language=language, db=db)
        group_plan.label = label
        group_plan.index = index
        # A four-group provider outage used to print four lines all reading
        # "group : ...", which named nothing. The ask is the last one this
        # cluster registered, so re-labelling it here reaches the right one.
        if collector is not None and collector.asks:
            collector.asks[-1].owner_uid = label
        for plan in cluster_plans:
            plan.group_label = label
            plan.group_index = index
        plans.extend(cluster_plans)
        group_plans.append(group_plan)
    return plans, group_plans, grouped_by_model


def _group_label(
    index: int, plan: AdaptiveGroupPlan, *, language: str, db: Session
) -> str:
    """"Série 2 · Fractions équivalentes" — the number and what it is for.

    The number alone is a bucket; the competency alone does not survive two
    groups chasing the same one after a split. Truncated to the column the
    printed page gives it.
    """
    words = _GROUP_WORDS.get(language, _GROUP_WORDS["en"])
    labels = _competency_labels(db, plan.targeted_competency_ids[:1], language=language)
    name = next(iter(labels.values()), "")
    base = f"{words['group']} {index}"
    full = f"{base} · {name}" if name else base
    return full[:60]


# "Groupe" is spent elsewhere. A Cycle 3 class IS a teaching group — that is
# what the word means to a teacher in Sion — and using it here as well for "the
# cohort of pupils receiving this variant" left the product with one word for
# two containers. This is the differentiation cohort, so it is named after the
# thing it actually is: the SERIES of exercises that copy carries.
#
# `lot` was taken (the exported batch, and a scan pile) and `niveau` collides
# with an exercise's difficulty ("Niveau 3 sur 5"), so `série` is the word left
# standing — and it already appeared in this namespace for a diagnostic series.
#
# This is printed. `sheet_instance.group_label` stores the label as it stood,
# so sheets already made keep the word they were made with; only new proposals
# are labelled this way.
_GROUP_WORDS: dict[str, dict[str, str]] = {
    "fr": {"group": "Série"},
    "de": {"group": "Serie"},
    "en": {"group": "Set"},
}


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
    if hit.band is MasteryBand.SOLID:
        return p["stretch"]
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
        "stretch": "approfondit une compétence déjà acquise",
        "diagnostic": "aucune donnée de maîtrise : série de diagnostic",
        "generated": "généré pour combler la fiche — validation requise",
        "group": "pour {count} élève(s) du groupe : {uids}",
    },
    "de": {
        "gap": "zielt auf eine {band} Kompetenz",
        "stretch": "vertieft eine bereits gefestigte Kompetenz",
        "diagnostic": "keine Kompetenzdaten: diagnostische Serie",
        "generated": "erzeugt, um das Blatt zu füllen — Freigabe erforderlich",
        "group": "für {count} Lernende der Gruppe: {uids}",
    },
    "en": {
        "gap": "targets a {band} competency",
        "stretch": "extends a competency already solid",
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
"""No `SOLID` entry, deliberately: a solid competency is reported by the
`stretch` phrase, which says what the item is *for*, not by the `gap` sentence
with a band word slotted in. "cible une compétence acquise" would read as a
mistake — and `OK` already holds "acquise" in French, so the two would collide."""


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
    if isinstance(exc, ChatTruncatedError):
        # Its own reason, and not `unparsable_response`, which is what a
        # truncated answer looks like from the outside. The teacher would read
        # "the model returned something unusable" for a cause that is a number
        # in the configuration — ALPPY_AI_MAX_OUTPUT_TOKENS_BATCH.
        return ("truncated", "the answer was cut off by the output-token limit")
    if isinstance(exc, (ValueError, TypeError)):
        return ("unparsable_response", "the model did not return usable JSON")
    return ("provider_error", type(exc).__name__)


ADAPTIVE_BATCH_MAX_PLANS = 8
"""How many plans one generation call may carry.

Not a tuning knob so much as a blast radius. Everything in one call shares one
output budget and one failure: a provider error or a truncation costs every plan
in the chunk, and the split retry that repairs it costs one call per plan. Eight
keeps both numbers small.
"""

TOKENS_PER_GENERATED_ITEM = 220
"""A rough ceiling for one MCQ: statement, four options, explanation, JSON
punctuation. Used only to size the batch's output budget, and deliberately
generous — the failure it exists to prevent is a truncated response, which
presents as an unparsable one and costs the whole chunk."""


@dataclass(slots=True)
class _GenerationAsk:
    """One plan's generation request, with retrieval already done.

    ``plan_id`` is opaque — "P1", never a UID. It is shorter, and it means the
    batched path sends no student reference to the provider at all.
    """

    plan_id: str
    competency_ids: list[uuid.UUID]
    labels: list[str]
    difficulty: int
    count: int
    style_examples: list[str]
    chapter_id: uuid.UUID | None
    student_refs: list[str]
    """UIDs, for ``generation_meta`` on the stored row. Never for the prompt."""

    owner_id: uuid.UUID
    owner_uid: str
    """Whose failure this is, for the message the teacher reads."""


def _plan_lines(asks: Sequence[_GenerationAsk]) -> tuple[str, str]:
    """The competency legend and the plan lines.

    The legend is the batching saving that is actually worth having: in
    per-student mode two dozen plans usually share the same handful of
    competencies, and spelling each label out per plan pays for them again and
    again.
    """
    legend: dict[str, str] = {}
    keys: dict[str, str] = {}
    for ask in asks:
        for label in ask.labels:
            if label not in keys:
                key = f"C{len(keys) + 1}"
                keys[label] = key
                legend[key] = label
    lines = []
    for ask in asks:
        refs = ",".join(keys[label] for label in ask.labels) or "-"
        lines.append(
            f"[{ask.plan_id}] competencies: {refs} | "
            f"difficulty: {ask.difficulty} | count: {ask.count}"
        )
    legend_text = "\n".join(f"{k} = {v}" for k, v in legend.items()) or "(none)"
    return legend_text, "\n".join(lines)


def _chunk(asks: Sequence[_GenerationAsk], size: int) -> list[list[_GenerationAsk]]:
    return [list(asks[i : i + size]) for i in range(0, len(asks), size)]


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
    seen: set[str] | None = None,
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
        flush_ai_log(db, school_id=school_id, ai=ai)
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

    return _materialise(
        db,
        school_id=school_id,
        class_id=class_id,
        subject_id=subject_id,
        ask=_GenerationAsk(
            plan_id=ref or "-",
            competency_ids=list(competency_ids),
            labels=list(labels),
            difficulty=difficulty,
            count=count,
            style_examples=list(style_examples),
            chapter_id=chapter_id,
            student_refs=list(student_refs),
            owner_id=uuid.UUID(int=0),
            owner_uid=ref,
        ),
        items=payload.get("exercises") or [],
        language=language,
        model=record.model,
        prompt_label=f"{prompt.name}.{prompt.version}",
        seen=seen,
    )


def _materialise(
    db: Session,
    *,
    school_id: uuid.UUID,
    class_id: uuid.UUID,
    subject_id: uuid.UUID,
    ask: _GenerationAsk,
    items: Sequence[Any],
    language: str,
    model: str,
    prompt_label: str,
    seen: set[str] | None = None,
) -> tuple[list[ExerciseProposal], AdaptiveGenerationFailure | None]:
    """Turn one plan's raw items into rows, dropping what cannot be printed.

    Shared by the single-plan and batched paths so the validation rules cannot
    diverge between them — a schema-invalid item is dropped and the good items
    beside it survive (I-adaptive-08), in both.

    ``seen`` is passed in by the batched caller and shared across the whole run;
    the default builds a per-call set, which is what the single-plan path did.
    """
    competencies = list(
        db.scalars(select(Competency).where(Competency.id.in_(list(ask.competency_ids))))
    )
    rejected: list[str] = []
    if seen is None:
        seen = _rejected_statements(db, school_id=school_id, subject_id=subject_id)
    proposals: list[ExerciseProposal] = []

    for item in list(items)[: ask.count]:
        try:
            parsed = GeneratedExerciseIn.model_validate(item)
        except ValidationError as exc:
            rejected.append(_first_error(exc))
            continue
        if _normalise(parsed.statement) in seen:
            # The teacher already threw this one away, or it is a duplicate of
            # something we just made — possibly for a different group in this
            # very run. Offering it again wastes their attention.
            rejected.append("duplicate of an item already discarded or proposed")
            continue
        seen.add(_normalise(parsed.statement))

        exercise = _build_generated_exercise(
            parsed,
            school_id=school_id,
            class_id=class_id,
            subject_id=subject_id,
            chapter_id=ask.chapter_id,
            language=language,
            difficulty=ask.difficulty,
            student_refs=ask.student_refs,
            competency_ids=ask.competency_ids,
            model=model,
            prompt_name=prompt_label,
        )
        exercise.competencies = competencies
        db.add(exercise)
        proposals.append(
            _generated_proposal(exercise, language=language, difficulty=ask.difficulty)
        )

    db.flush()
    log.info(
        "adaptive.generate",
        plan=ask.plan_id,
        requested=ask.count,
        produced=len(proposals),
        rejected=len(rejected),
        model=model,
    )
    failure: AdaptiveGenerationFailure | None = None
    if len(proposals) < ask.count:
        detail = (
            "; ".join(rejected[:3])
            if rejected
            else "the model returned fewer exercises than were asked for"
        )
        failure = _failure(
            "incomplete", requested=ask.count, produced=len(proposals), detail=detail
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
        flush_ai_log(db, school_id=school_id, ai=ai)


def generate_for_asks(
    db: Session,
    *,
    school_id: uuid.UUID,
    class_id: uuid.UUID,
    subject_id: uuid.UUID,
    asks: Sequence[_GenerationAsk],
    language: str,
    roster_names: list[str],
    ai: AiClient,
    seen: set[str],
) -> dict[str, tuple[list[ExerciseProposal], AdaptiveGenerationFailure | None]]:
    """Fill every ask, in as few calls as the plans allow.

    One chunk is one call. Two kinds of failure, handled differently on purpose:

    * **Per plan** — its entry is missing from the response, or every item in it
      was rejected by the schema. That plan alone comes up short and is reported;
      the plans beside it are untouched. This is I-adaptive-08's per-item drop
      rule lifted one level.
    * **Per call** — the provider threw, the response would not parse, or the
      answer was truncated. Batched, that would cost eight plans what used to
      cost one, and I-adaptive-09 says a plan's failure is its own. So the chunk
      is **retried once, split into single-plan calls**. Bounded at one extra
      round, and a failure that persists is then reported per plan exactly as it
      was before batching existed.

    ``seen`` is shared across every ask in the run. Rebuilt per call, it let two
    groups in the same proposal generate the identical statement — the teacher
    reads it twice and has no way to tell which sheet it belongs to.
    """
    results: dict[str, tuple[list[ExerciseProposal], AdaptiveGenerationFailure | None]] = {}
    for chunk in _chunk(asks, ADAPTIVE_BATCH_MAX_PLANS):
        if len(chunk) == 1:
            ask = chunk[0]
            results[ask.plan_id] = _generate_one(
                db,
                school_id=school_id,
                class_id=class_id,
                subject_id=subject_id,
                ask=ask,
                language=language,
                roster_names=roster_names,
                ai=ai,
                seen=seen,
            )
            continue
        try:
            payload = _ask_batch(
                db,
                school_id=school_id,
                asks=chunk,
                language=language,
                roster_names=roster_names,
                ai=ai,
            )
        except Exception as exc:
            reason, _detail = _classify(exc)
            log.warning(
                "adaptive.generate.batch_failed",
                plans=len(chunk),
                reason=reason,
                error=type(exc).__name__,
            )
            # The split retry. One call per plan, which is what the code did
            # before batching, so a persistent fault degrades to the old
            # behaviour rather than to a class-wide blank.
            for ask in chunk:
                results[ask.plan_id] = _generate_one(
                    db,
                    school_id=school_id,
                    class_id=class_id,
                    subject_id=subject_id,
                    ask=ask,
                    language=language,
                    roster_names=roster_names,
                    ai=ai,
                    seen=seen,
                )
            continue

        by_plan = {
            str(entry.get("plan_id")): entry.get("exercises") or []
            for entry in (payload.get("plans") or [])
            if isinstance(entry, dict)
        }
        for ask in chunk:
            results[ask.plan_id] = _materialise(
                db,
                school_id=school_id,
                class_id=class_id,
                subject_id=subject_id,
                ask=ask,
                items=by_plan.get(ask.plan_id) or [],
                language=language,
                model=ai.records[-1].model if ai.records else "",
                prompt_label="generate_exercises_batch.v1",
                seen=seen,
            )
    return results


def _ask_batch(
    db: Session,
    *,
    school_id: uuid.UUID,
    asks: Sequence[_GenerationAsk],
    language: str,
    roster_names: list[str],
    ai: AiClient,
) -> dict[str, Any]:
    """One call for several plans. Raises; the caller decides what that costs."""
    prompt = load_prompt("generate_exercises_batch")
    legend, plans = _plan_lines(asks)
    # Style examples are shared across the chunk and sent once. They come from
    # the same subject corpus, so per-plan copies were paying for the same prose
    # several times over.
    examples: list[str] = []
    for ask in asks:
        for example in ask.style_examples:
            if example not in examples:
                examples.append(example)

    total = sum(ask.count for ask in asks)
    settings = get_settings()
    budget = min(
        settings.ai_max_output_tokens_batch,
        max(settings.ai_max_output_tokens, total * TOKENS_PER_GENERATED_ITEM),
    )

    response, record = ai.complete(
        prompt=prompt,
        purpose="adaptive_generate_batch",
        values={
            "language": language,
            "max_options": MAX_OPTIONS,
            "competency_legend": legend,
            "plans": plans,
            "style_examples": _format_style_examples(
                examples[:STYLE_EXAMPLE_COUNT], roster_names=roster_names
            ),
        },
        student_names=roster_names,
        temperature=GENERATION_TEMPERATURE,
        max_tokens=budget,
        # A batch of up to eight plans is not a vision call over one crop, and
        # the two must not share a budget: the default ceiling would strangle
        # this, and this one applied everywhere would let a single crop hang for
        # three minutes (audit 03, B10).
        timeout_s=settings.provider_batch_timeout_s,
    )
    # Audited before parsing: a call that was made and then failed to parse
    # still cost tokens and still happened.
    flush_ai_log(db, school_id=school_id, ai=ai)
    _ = record
    return parse_json_response(response.text)


def _generate_one(
    db: Session,
    *,
    school_id: uuid.UUID,
    class_id: uuid.UUID,
    subject_id: uuid.UUID,
    ask: _GenerationAsk,
    language: str,
    roster_names: list[str],
    ai: AiClient,
    seen: set[str],
) -> tuple[list[ExerciseProposal], AdaptiveGenerationFailure | None]:
    """The single-plan path: the original prompt, unchanged.

    Used for a chunk of one and as the split retry, so the behaviour a batch
    degrades to is the behaviour that shipped before batching.
    """
    return _generate(
        db,
        school_id=school_id,
        class_id=class_id,
        subject_id=subject_id,
        student_refs=ask.student_refs,
        competency_ids=ask.competency_ids,
        labels=ask.labels,
        difficulty=ask.difficulty,
        count=ask.count,
        language=language,
        style_examples=ask.style_examples,
        chapter_id=ask.chapter_id,
        roster_names=roster_names,
        ai=ai,
        seen=seen,
    )


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

    # The outgoing statement, remembered BEFORE anything is written, because
    # the discard has moved (audit 03, B11).
    #
    # It used to be discarded here, first, so that `_rejected_statements` would
    # already contain it by the time generation ran and the model could not
    # hand back the item the teacher had just rejected. That worked, and it
    # held a write transaction open across a retrieval pass and a model call —
    # seconds of provider latency with a row locked behind it, on the one
    # database connection this request owns.
    #
    # So the discard moves below the generation, and what the discard used to
    # provide is passed in explicitly: `seen` is seeded with the outgoing
    # statement. Same guarantee, no transaction spanning the network.
    seen = _rejected_statements(db, school_id=school_id, subject_id=exercise.subject_id)
    seen.add(_normalise(exercise.statement))

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
        seen=seen,
    )
    if not proposals:
        db.rollback()
        detail = failure.detail if failure else "no replacement was produced"
        raise AdaptiveGenerationError(detail)

    # Only now, with a replacement in hand, is anything taken away. The old
    # behaviour discarded first and rolled back on failure, which is the same
    # outcome by a longer road — except that the road ran through a model call.
    discard_exercises(db, school_id=school_id, exercise_ids=[exercise.id])
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
            # The HOME class: this legacy fallback has to name one class, and
            # a student may now sit in several (D69).
            return student.home_class_id
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
        Student.school_id == school_id,
        Student.id.in_(enrolled_student_ids(class_id, on=today())),
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
        select(Student).where(
            Student.school_id == school_id,
            Student.id.in_(enrolled_student_ids(class_id, on=today())),
        )
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
