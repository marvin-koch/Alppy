"""Mastery: attempts in, bands out.

The model itself (``alppy.mastery.model``) is pure and has no idea a database
exists. This module is the only place that bridges the two: it loads attempts,
groups them by (student, competency), calls ``compute_mastery``, and persists
the result as a ``MasterySnapshot`` so the matrix is cheap to read and the
student profile has a history to draw.

Snapshot granularity is one row per (student, competency, day). Recomputing
twice on the same day updates the day's row rather than appending, which keeps
the profile curve readable — a teacher confirming four scans in one afternoon
should see one point, not four.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.api.deps import Scope
from alppy.mastery.model import (
    AttemptInput,
    MasteryResult,
    compute_mastery,
    roll_up_mastery,
)
from alppy.models import (
    Attempt,
    Chapter,
    Class,
    Competency,
    Detection,
    Exercise,
    MasteryBranchSnapshot,
    MasterySnapshot,
    Scan,
    ScanPage,
    Sheet,
    SheetItem,
    Student,
    chapter_competency,
    class_student,
    exercise_competency,
)
from alppy.models.enums import BAND_ORDER, DetectionOutcome, MasteryBand
from alppy.schemas import (
    AttemptOut,
    CompetencyAttemptsOut,
    CompetencyMastery,
    MasteryCell,
    MasteryMatrixOut,
    MasteryPoint,
    SheetTaken,
    StudentProfileOut,
    TreeMasteryOut,
)
from alppy.services import competency_out, student_out
from alppy.services.enrollment import enrolled_student_ids, owned_class_ids

ATTENTION_BANDS: Final[frozenset[MasteryBand]] = frozenset(
    {MasteryBand.WEAK, MasteryBand.FADING}
)
STRENGTH_BANDS: Final[frozenset[MasteryBand]] = frozenset({MasteryBand.SOLID, MasteryBand.OK})
MAX_STRENGTHS: Final = 5
MAX_GAPS: Final = 8
MAX_HISTORY_POINTS: Final = 30

Key = tuple[uuid.UUID, uuid.UUID]  # (student_id, competency_id)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; the model does arithmetic on them."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def _chapter_competency_ids(
    db: Session, school_id: uuid.UUID, chapter_id: uuid.UUID
) -> list[uuid.UUID]:
    """The competencies a chapter covers, scoped to the teacher's school.

    An unknown or foreign chapter yields an empty list rather than an error, so
    the filter narrows to nothing instead of leaking whether the id exists.
    """
    return list(
        db.execute(
            select(chapter_competency.c.competency_id)
            .join(Chapter, Chapter.id == chapter_competency.c.chapter_id)
            .where(Chapter.id == chapter_id)
            .where(Chapter.school_id == school_id)
        ).scalars()
    )


_BAND_SEVERITY: dict[MasteryBand, int] = {
    MasteryBand.FADING: 0,
    MasteryBand.WEAK: 1,
    MasteryBand.OK: 2,
    MasteryBand.SOLID: 3,
    MasteryBand.NONE: 4,
}


def weakest_assessed_band(children: list[MasteryResult]) -> MasteryBand | None:
    """The worst band among children that were actually assessed.

    NONE is not a weakness — it is the absence of evidence — so it is filtered
    out here rather than sorted last, matching ``_weakest_first``'s reading of
    the same distinction one level down.
    """
    assessed = [c.band for c in children if c.effective_n > 0.0]
    if not assessed:
        return None
    return min(assessed, key=lambda b: _BAND_SEVERITY[b])


def mastery_out(rolled: MasteryResult, children: list[MasteryResult]) -> TreeMasteryOut:
    """Serialise a roll-up together with the coverage behind it.

    The band alone would let a Theme read "acquis" while two of its three
    competencies were never examined. `assessed_count` / `child_count` and
    `weakest_band` are the companions that stop a colour travelling alone
    (DC-colour-08) at a level where the number is an aggregate.
    """
    return TreeMasteryOut(
        score=rolled.score,
        band=rolled.band,
        attempts_count=rolled.attempts_count,
        provisional=rolled.provisional,
        assessed_count=sum(1 for c in children if c.effective_n > 0.0),
        child_count=len(children),
        weakest_band=weakest_assessed_band(children),
        days_until_review=rolled.days_until_review,
        last_attempt_at=rolled.last_attempt_at,
    )


def load_attempt_inputs(
    db: Session,
    school_id: uuid.UUID,
    student_ids: list[uuid.UUID],
    *,
    subject_id: uuid.UUID | None = None,
    competency_ids: list[uuid.UUID] | None = None,
    sheet_id: uuid.UUID | None = None,
    as_of: datetime | None = None,
) -> dict[Key, list[AttemptInput]]:
    """Every attempt, keyed by (student, competency).

    An exercise mapped to two competencies contributes to both — that is the
    point of the mapping, and it is why this cannot be a simple group-by.

    ``as_of`` drops attempts answered after that moment. Live callers never
    need it — nothing is answered in the future — but a snapshot dated last
    Tuesday must be computed from the evidence that existed last Tuesday, or
    backfilling a history produces the same number at every point on the curve.

    ``sheet_id`` narrows to one sheet's results, for the adaptive planner
    answering "how did they do on *this*". Mastery itself never passes it: the
    model is a weighted mean over all the evidence, and scoping it to one lesson
    would make a bad afternoon erase a term.
    """
    if not student_ids:
        return {}
    if competency_ids is not None and not competency_ids:
        return {}
    stmt = (
        select(
            Attempt.student_id,
            exercise_competency.c.competency_id,
            Attempt.correct,
            Attempt.answered_at,
            Attempt.difficulty,
        )
        .join(exercise_competency, exercise_competency.c.exercise_id == Attempt.exercise_id)
        .where(Attempt.school_id == school_id)
        .where(Attempt.student_id.in_(student_ids))
    )
    if as_of is not None:
        stmt = stmt.where(Attempt.answered_at <= as_of)
    if subject_id is not None:
        stmt = stmt.join(Exercise, Exercise.id == Attempt.exercise_id).where(
            Exercise.subject_id == subject_id
        )
    if competency_ids is not None:
        stmt = stmt.where(exercise_competency.c.competency_id.in_(competency_ids))
    if sheet_id is not None:
        stmt = stmt.where(Attempt.sheet_id == sheet_id)

    grouped: dict[Key, list[AttemptInput]] = defaultdict(list)
    for student_id, competency_id, correct, answered_at, difficulty in db.execute(stmt):
        at = _aware(answered_at)
        if at is None:  # pragma: no cover - answered_at is NOT NULL
            continue
        grouped[(student_id, competency_id)].append(
            AttemptInput(correct=bool(correct), answered_at=at, difficulty=int(difficulty))
        )
    return dict(grouped)


def pool_by_competency(
    grouped: dict[Key, list[AttemptInput]],
) -> dict[uuid.UUID, list[AttemptInput]]:
    """Drop the student half of the key and concatenate.

    Turns per-student attempts into class-wide ones WITHOUT inventing a second
    aggregation rule: the pooled list still goes through the unchanged
    ``compute_mastery``, so "how is 7B doing on MSN 33.2" is computed by the
    same recency- and difficulty-weighted formula as "how is Lina doing on MSN
    33.2", just fed a longer list. A single-student call is the degenerate
    one-element case of the same fold.

    Note this pools across STUDENTS, never across competencies — pooling raw
    attempts from two competencies would derive one recency from the mixture,
    and a competency practised last week would launder the staleness of one
    last touched in June. Combining competencies is ``roll_up_mastery``'s job,
    and it works on results, each of which carries its own honest recency.
    """
    pooled: dict[uuid.UUID, list[AttemptInput]] = defaultdict(list)
    for (_student_id, competency_id), attempts in grouped.items():
        pooled[competency_id].extend(attempts)
    return dict(pooled)


def latest_snapshots(
    db: Session, school_id: uuid.UUID, student_ids: list[uuid.UUID]
) -> dict[Key, MasterySnapshot]:
    """The most recent snapshot per (student, competency)."""
    if not student_ids:
        return {}
    stmt = (
        select(MasterySnapshot)
        .where(MasterySnapshot.school_id == school_id)
        .where(MasterySnapshot.student_id.in_(student_ids))
        .order_by(MasterySnapshot.computed_at.asc())
    )
    latest: dict[Key, MasterySnapshot] = {}
    for snap in db.execute(stmt).scalars():
        latest[(snap.student_id, snap.competency_id)] = snap
    return latest


def _student_ids_for_class(
    db: Session, school_id: uuid.UUID, class_id: uuid.UUID
) -> list[Student]:
    stmt = (
        select(Student)
        .where(Student.school_id == school_id)
        .where(Student.id.in_(enrolled_student_ids(class_id)))
        .order_by(Student.number.asc())
    )
    return list(db.execute(stmt).scalars())


def assessed_competencies(
    db: Session,
    school_id: uuid.UUID,
    student_ids: list[uuid.UUID],
    *,
    subject_id: uuid.UUID | None = None,
    competency_ids: list[uuid.UUID] | None = None,
) -> list[Competency]:
    """Competencies the class has actually met, which is what the matrix shows.

    Showing the whole curriculum would be a wall of grey ``none`` cells; the
    teacher wants the competencies their sheets have touched.
    """
    if not student_ids:
        return []
    if competency_ids is not None and not competency_ids:
        return []
    stmt = (
        select(Competency)
        .join(exercise_competency, exercise_competency.c.competency_id == Competency.id)
        .join(Attempt, Attempt.exercise_id == exercise_competency.c.exercise_id)
        .where(Attempt.school_id == school_id)
        .where(Attempt.student_id.in_(student_ids))
        .distinct()
        .order_by(Competency.code.asc())
    )
    if subject_id is not None:
        stmt = stmt.join(Exercise, Exercise.id == Attempt.exercise_id).where(
            Exercise.subject_id == subject_id
        )
    if competency_ids is not None:
        stmt = stmt.where(Competency.id.in_(competency_ids))
    return list(db.execute(stmt).scalars())


# --------------------------------------------------------------------------
# Recompute
# --------------------------------------------------------------------------
def recompute_for_students(
    db: Session,
    school_id: uuid.UUID,
    student_ids: list[uuid.UUID],
    *,
    now: datetime | None = None,
) -> int:
    """Recompute and persist mastery. Returns the number of cells written.

    ``now`` is both the moment the score is computed *for* and the cut-off for
    the evidence that feeds it, so calling this at a series of past dates
    backfills a genuine time series rather than stamping today's number on
    yesterday's row.
    """
    at = _now(now)
    if not student_ids:
        return 0

    grouped = load_attempt_inputs(db, school_id, student_ids, as_of=at)
    existing = latest_snapshots(db, school_id, student_ids)
    day = at.date()
    written = 0

    for (student_id, competency_id), attempts in grouped.items():
        result = compute_mastery(attempts, at)
        snap = existing.get((student_id, competency_id))
        snap_day = _aware(snap.computed_at).date() if snap is not None else None  # type: ignore[union-attr]
        if snap is not None and snap_day == day:
            snap.computed_at = at
            snap.score = result.score
            snap.band = result.band
            snap.attempts_count = result.attempts_count
            snap.last_attempt_at = result.last_attempt_at
        else:
            db.add(
                MasterySnapshot(
                    id=uuid.uuid4(),
                    school_id=school_id,
                    student_id=student_id,
                    competency_id=competency_id,
                    computed_at=at,
                    score=result.score,
                    band=result.band,
                    attempts_count=result.attempts_count,
                    last_attempt_at=result.last_attempt_at,
                )
            )
        written += 1

    _write_branch_snapshots(db, school_id, grouped, at)
    db.flush()
    return written


def _write_branch_snapshots(
    db: Session,
    school_id: uuid.UUID,
    grouped: dict[tuple[uuid.UUID, uuid.UUID], list[AttemptInput]],
    at: datetime,
) -> None:
    """Stamp one branch-level row per (student, subject) for the curve.

    A CACHE, and the docstring on `MasteryBranchSnapshot` is the contract: no
    read path may answer "what is this child's band" from here. Every one
    recomputes, because the score decays and yesterday's number is wrong.

    What it buys is the one question recomputation cannot answer — *history*.
    A curve needs points, and there is nowhere else they could come from.

    Rolled up with `roll_up_mastery` over the SAME `MasteryResult`s the tree
    uses, never by pooling the raw attempts across competencies: that would
    derive one recency from a mixture, so a competency practised last week
    would launder the staleness of one last touched in June (I-mastery-10).

    Coverage is stored beside the score. A branch band over one assessed
    competency and one over three are different claims, and a cached number
    that dropped the denominator is the dishonesty DC-content-07 forbids.
    """
    if not grouped:
        return

    competency_ids = {competency_id for (_student, competency_id) in grouped}
    subject_of = _subject_by_competency(db, school_id, competency_ids)
    if not subject_of:
        return

    day = at.date()
    per_branch: dict[tuple[uuid.UUID, uuid.UUID], list[MasteryResult]] = defaultdict(list)
    for (student_id, competency_id), attempts in grouped.items():
        subject_id = subject_of.get(competency_id)
        if subject_id is None:
            # A competency no Theme in this school credits. It still counts
            # toward the child's own mastery; it simply belongs to no Branch,
            # so there is no curve for it to join.
            continue
        per_branch[(student_id, subject_id)].append(compute_mastery(attempts, at))

    existing = {
        (row.student_id, row.subject_id): row
        for row in db.execute(
            select(MasteryBranchSnapshot)
            .where(MasteryBranchSnapshot.school_id == school_id)
            .where(
                MasteryBranchSnapshot.student_id.in_(
                    {student_id for (student_id, _subject) in per_branch}
                )
            )
        ).scalars()
        if (stamped := _aware(row.computed_at)) is not None and stamped.date() == day
    }

    for (student_id, subject_id), results in per_branch.items():
        rolled = roll_up_mastery(results)
        assessed = sum(1 for r in results if r.attempts_count > 0)
        row = existing.get((student_id, subject_id))
        if row is not None:
            # One row per day, like `MasterySnapshot`: a second confirmation
            # this afternoon corrects this morning's point rather than drawing
            # the curve twice.
            row.computed_at = at
            row.score = rolled.score
            row.band = rolled.band
            row.child_count = len(results)
            row.assessed_child_count = assessed
        else:
            db.add(
                MasteryBranchSnapshot(
                    id=uuid.uuid4(),
                    school_id=school_id,
                    student_id=student_id,
                    subject_id=subject_id,
                    computed_at=at,
                    score=rolled.score,
                    band=rolled.band,
                    child_count=len(results),
                    assessed_child_count=assessed,
                )
            )


def _subject_by_competency(
    db: Session, school_id: uuid.UUID, competency_ids: set[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """Which Branch each competency is assessed in, for this school.

    Through `exercise_competency` and `Exercise.subject_id` — NOT through
    `chapter_competency`. The distinction matters and cost a failing test to
    find: a competency is assessed by EXERCISES, and an exercise always has a
    subject, while a Theme crediting that competency may simply not exist yet.
    Resolving through chapters left every curve empty until somebody had
    filed a Theme, which is the same circularity D57 removed from the Branch
    nav.

    It is also the more faithful edge: `exercise_competency` is what mastery
    itself reads through, so the curve is grouped by the same relation that
    produced the numbers.

    A competency assessed by exercises in two Branches resolves to whichever
    the join returns. The curve is a cache, and a tie is not worth a second
    table to break.
    """
    if not competency_ids:
        return {}
    rows = db.execute(
        select(exercise_competency.c.competency_id, Exercise.subject_id)
        .join(Exercise, Exercise.id == exercise_competency.c.exercise_id)
        .where(Exercise.school_id == school_id)
        .where(exercise_competency.c.competency_id.in_(competency_ids))
        .distinct()
    ).all()
    return dict(rows)  # type: ignore[arg-type]  # SQLAlchemy Row pairs


# --------------------------------------------------------------------------
# Read models
# --------------------------------------------------------------------------
def _cell(
    student_id: uuid.UUID, competency_id: uuid.UUID, result: MasteryResult
) -> MasteryCell:
    return MasteryCell(
        student_id=student_id,
        competency_id=competency_id,
        score=result.score,
        band=result.band,
        attempts_count=result.attempts_count,
        provisional=result.provisional,
        days_until_review=result.days_until_review,
        last_attempt_at=result.last_attempt_at,
    )


def _weakest_first(
    students: list[Student], results: dict[Key, MasteryResult]
) -> list[Student]:
    """Order the roster by each student's worst assessed cell, worst first.

    A never-assessed cell is deliberately NOT a weakness: it would sort every
    student who simply missed a lesson to the top of a list whose whole purpose
    is "who needs help". A student with nothing assessed at all sorts last.
    """
    def key(student: Student) -> tuple[int, float, int]:
        scores = [
            r.score
            for (sid, _cid), r in results.items()
            if sid == student.id and r.band is not MasteryBand.NONE
        ]
        if not scores:
            return (1, 0.0, student.number)  # nothing to judge — after everyone
        return (0, min(scores), student.number)

    return sorted(students, key=key)


def class_matrix(
    db: Session,
    scope: Scope,
    class_id: uuid.UUID,
    *,
    subject_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
    sort: str = "roster",
    now: datetime | None = None,
) -> MasteryMatrixOut:
    at = _now(now)
    school_id = scope.school_id
    # The matrix is a roster of named children: it follows class ownership, not
    # just the school boundary (decisions-log D23).
    school_class = db.execute(
        select(Class).where(Class.id == class_id).where(Class.id.in_(owned_class_ids(scope)))
    ).scalar_one_or_none()
    if school_class is None:
        raise errors.not_found("class", id=str(class_id))

    limit_to: list[uuid.UUID] | None = None
    if chapter_id is not None:
        limit_to = _chapter_competency_ids(db, school_id, chapter_id)

    students = _student_ids_for_class(db, school_id, class_id)
    student_ids = [s.id for s in students]
    competencies = assessed_competencies(
        db, school_id, student_ids, subject_id=subject_id, competency_ids=limit_to
    )
    grouped = load_attempt_inputs(
        db, school_id, student_ids, subject_id=subject_id, competency_ids=limit_to
    )

    results: dict[Key, MasteryResult] = {}
    for student in students:
        for competency in competencies:
            attempts = grouped.get((student.id, competency.id), [])
            results[(student.id, competency.id)] = compute_mastery(attempts, at)

    if sort == "weakest":
        students = _weakest_first(students, results)

    cells = [
        _cell(student.id, competency.id, results[(student.id, competency.id)])
        for student in students
        for competency in competencies
    ]

    return MasteryMatrixOut(
        class_id=class_id,
        students=[student_out(s) for s in students],
        competencies=[competency_out(c) for c in competencies],
        cells=cells,
        computed_at=at,
    )


def _owned_student(db: Session, scope: Scope, student_id: uuid.UUID) -> Student:
    """One student from a class the caller owns, or 404.

    A student profile names a child and lists their every answer, so it follows
    the same ownership rule as the class they sit in (decisions-log D23).
    """
    # Through ENROLLMENT, not the home class: a child co-enrolled in this
    # teacher's class is theirs to read even when another teacher's class
    # minted the uid. Widened deliberately, and only here — the school filter
    # above it is what keeps the widening inside one tenant (I-platform-10).
    student = db.execute(
        select(Student)
        .join(class_student, class_student.c.student_id == Student.id)
        .join(Class, Class.id == class_student.c.class_id)
        .where(Student.id == student_id)
        .where(Student.school_id == scope.school_id)
        .where(Class.id.in_(owned_class_ids(scope)))
        .limit(1)
    ).scalar_one_or_none()
    if student is None:
        raise errors.not_found("student", id=str(student_id))
    return student


def competency_attempts(
    db: Session,
    scope: Scope,
    student_id: uuid.UUID,
    competency_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> CompetencyAttemptsOut:
    """The individual answers behind one matrix cell, newest first.

    This is what a teacher reaches when they disagree with a band. Every row
    carries its provenance — the sheet it was printed on and the scan it was
    read from — because "where did this mark come from" is the first question
    asked of a number a teacher did not expect.
    """
    at = _now(now)
    school_id = scope.school_id
    student = _owned_student(db, scope, student_id)
    competency = db.execute(
        select(Competency).where(Competency.id == competency_id)
    ).scalar_one_or_none()
    if competency is None:
        raise errors.not_found("competency", id=str(competency_id))

    # One row per attempt, left-joined out to the sheet it was printed on and
    # the scan its detection came from. Both are nullable: a seeded attempt has
    # no paper behind it, and an attempt whose scan was deleted keeps the mark.
    stmt = (
        select(Attempt, Exercise, Sheet.title, Scan.id, Detection.outcome)
        .join(exercise_competency, exercise_competency.c.exercise_id == Attempt.exercise_id)
        .join(Exercise, Exercise.id == Attempt.exercise_id)
        .outerjoin(Sheet, Sheet.id == Attempt.sheet_id)
        .outerjoin(Detection, Detection.id == Attempt.detection_id)
        .outerjoin(ScanPage, ScanPage.id == Detection.scan_page_id)
        .outerjoin(Scan, Scan.id == ScanPage.scan_id)
        .where(Attempt.school_id == school_id)
        .where(Attempt.student_id == student_id)
        .where(exercise_competency.c.competency_id == competency_id)
        .order_by(Attempt.answered_at.desc())
    )

    rows = db.execute(stmt).all()
    attempts: list[AttemptOut] = []
    inputs: list[AttemptInput] = []
    for attempt, exercise, sheet_title, scan_id, outcome in rows:
        answered = _aware(attempt.answered_at)
        if answered is None:  # pragma: no cover - answered_at is NOT NULL
            continue
        inputs.append(
            AttemptInput(
                correct=bool(attempt.correct),
                answered_at=answered,
                difficulty=int(attempt.difficulty),
            )
        )
        attempts.append(
            AttemptOut(
                id=attempt.id,
                exercise_id=attempt.exercise_id,
                statement=exercise.statement,
                origin=exercise.origin,
                correct=bool(attempt.correct),
                difficulty=int(attempt.difficulty),
                answered_at=answered,
                sheet_id=attempt.sheet_id,
                sheet_title=sheet_title,
                scan_id=scan_id,
                corrected=outcome is DetectionOutcome.CORRECTED,
            )
        )

    result = compute_mastery(inputs, at)
    return CompetencyAttemptsOut(
        student=student_out(student),
        competency=competency_out(competency),
        score=result.score,
        band=result.band,
        provisional=result.provisional,
        days_until_review=result.days_until_review,
        attempts=attempts,
    )


def _sheets_taken(
    db: Session, school_id: uuid.UUID, student_id: uuid.UUID
) -> list[SheetTaken]:
    """The sheets this student actually sat, newest first.

    Grouped in Python rather than SQL because the scan id needs a two-hop
    outer join per attempt and the row count here is a handful of sheets.
    """
    rows = db.execute(
        select(Attempt, Sheet.title, Scan.id, Sheet.chapter_id)
        .join(Sheet, Sheet.id == Attempt.sheet_id)
        .outerjoin(Detection, Detection.id == Attempt.detection_id)
        .outerjoin(ScanPage, ScanPage.id == Detection.scan_page_id)
        .outerjoin(Scan, Scan.id == ScanPage.scan_id)
        .where(Attempt.school_id == school_id)
        .where(Attempt.student_id == student_id)
        .where(Attempt.sheet_id.is_not(None))
        .order_by(Attempt.answered_at.desc())
    ).all()

    by_sheet: dict[uuid.UUID, SheetTaken] = {}
    for attempt, title, scan_id, chapter_id in rows:
        answered = _aware(attempt.answered_at)
        if answered is None or attempt.sheet_id is None:  # pragma: no cover - NOT NULL
            continue
        taken = by_sheet.get(attempt.sheet_id)
        if taken is None:
            by_sheet[attempt.sheet_id] = SheetTaken(
                sheet_id=attempt.sheet_id,
                title=title,
                answered_at=answered,
                attempts_count=1,
                correct_count=1 if attempt.correct else 0,
                scan_id=scan_id,
                chapter_id=chapter_id,
            )
            continue
        taken.attempts_count += 1
        if attempt.correct:
            taken.correct_count += 1
        if answered > taken.answered_at:
            taken.answered_at = answered
        if taken.scan_id is None:
            taken.scan_id = scan_id

    # One band per sheet, through the same roll-up the sheet endpoint uses, so
    # the profile and `GET /sheets/{id}/mastery` cannot disagree about a pupil.
    for sheet_id, taken in by_sheet.items():
        competency_ids = _sheet_competency_ids(db, school_id, sheet_id)
        if not competency_ids:
            continue
        taken.mastery = sheet_mastery(
            db, school_id, sheet_id, [student_id], competency_ids
        ).get(student_id)

    return sorted(by_sheet.values(), key=lambda s: s.answered_at, reverse=True)


def _sheet_competency_ids(
    db: Session, school_id: uuid.UUID, sheet_id: uuid.UUID
) -> list[uuid.UUID]:
    """The competencies one sheet's items touch.

    The same derivation as `sheet_service.sheet_coverage`, kept here rather
    than imported: `sheet_service` imports this module, so the arrow only goes
    one way. Duplicating four lines of query beats an import cycle.
    """
    return list(
        db.execute(
            select(exercise_competency.c.competency_id)
            .join(Exercise, Exercise.id == exercise_competency.c.exercise_id)
            .join(SheetItem, SheetItem.exercise_id == Exercise.id)
            .where(SheetItem.sheet_id == sheet_id)
            .where(SheetItem.school_id == school_id)
            .distinct()
        ).scalars()
    )


def _history(
    db: Session, school_id: uuid.UUID, student_id: uuid.UUID
) -> dict[uuid.UUID, list[MasteryPoint]]:
    stmt = (
        select(MasterySnapshot)
        .where(MasterySnapshot.school_id == school_id)
        .where(MasterySnapshot.student_id == student_id)
        .order_by(MasterySnapshot.computed_at.asc())
    )
    points: dict[uuid.UUID, list[MasteryPoint]] = defaultdict(list)
    for snap in db.execute(stmt).scalars():
        computed = _aware(snap.computed_at)
        if computed is None:  # pragma: no cover - NOT NULL
            continue
        points[snap.competency_id].append(
            MasteryPoint(at=computed, score=snap.score, band=snap.band)
        )
    return {k: v[-MAX_HISTORY_POINTS:] for k, v in points.items()}


def student_profile(
    db: Session,
    scope: Scope,
    student_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> StudentProfileOut:
    at = _now(now)
    school_id = scope.school_id
    student = _owned_student(db, scope, student_id)

    grouped = load_attempt_inputs(db, school_id, [student_id])
    competency_ids = [cid for (_sid, cid) in grouped]
    by_id: dict[uuid.UUID, Competency] = {}
    if competency_ids:
        rows = db.execute(
            select(Competency).where(Competency.id.in_(competency_ids))
        ).scalars()
        by_id = {c.id: c for c in rows}

    history = _history(db, school_id, student_id)

    entries: list[CompetencyMastery] = []
    for (_student_id, competency_id), attempts in grouped.items():
        competency = by_id.get(competency_id)
        if competency is None:  # pragma: no cover - FK guarantees presence
            continue
        result = compute_mastery(attempts, at)
        entries.append(
            CompetencyMastery(
                competency=competency_out(competency),
                score=result.score,
                band=result.band,
                attempts_count=result.attempts_count,
                provisional=result.provisional,
                days_until_review=result.days_until_review,
                history=history.get(competency_id, []),
            )
        )

    entries.sort(key=lambda e: (BAND_ORDER.index(e.band), -e.score))
    strengths = [e for e in entries if e.band in STRENGTH_BANDS][:MAX_STRENGTHS]
    gaps = sorted(
        (e for e in entries if e.band in ATTENTION_BANDS), key=lambda e: e.score
    )[:MAX_GAPS]
    overall = sum(e.score for e in entries) / len(entries) if entries else 0.0

    sheets = _sheets_taken(db, school_id, student_id)

    return StudentProfileOut(
        student=student_out(student),
        overall_score=overall,
        strengths=strengths,
        gaps=gaps,
        all_competencies=entries,
        sheets_taken=len(sheets),
        sheets=sheets,
    )


def band_summary(
    db: Session, school_id: uuid.UUID, student_ids: list[uuid.UUID]
) -> tuple[dict[str, int], int]:
    """``(band_counts, students_needing_attention)`` from the latest snapshots."""
    counts: dict[str, int] = {band.value: 0 for band in BAND_ORDER}
    needing: set[uuid.UUID] = set()
    for (student_id, _competency_id), snap in latest_snapshots(
        db, school_id, student_ids
    ).items():
        counts[snap.band.value] = counts.get(snap.band.value, 0) + 1
        if snap.band in ATTENTION_BANDS:
            needing.add(student_id)
    return counts, len(needing)


def sheet_mastery(
    db: Session,
    school_id: uuid.UUID,
    sheet_id: uuid.UUID,
    student_ids: Sequence[uuid.UUID],
    competency_ids: Sequence[uuid.UUID],
    *,
    now: datetime | None = None,
) -> dict[uuid.UUID, TreeMasteryOut]:
    """One band per student for one sheet, rolled up from its competencies.

    The altitude the model was missing: `MasterySnapshot` answers "how is this
    child doing on X", the tree answers it for a Theme or a Branch, and nothing
    answered "how did this child do on *this sheet*" in the product's own
    vocabulary.

    The arithmetic is the existing one, and the grouping is the whole point.
    Attempts are bucketed **per competency** first, each bucket scored by
    `compute_mastery`, and only the results combined by `roll_up_mastery` — a
    mean over raw item correctness would derive one recency from a mixture and
    break I-mastery-10 at a new altitude, in the model whose purpose is fading.

    Every competency the sheet covers appears as a child, including those it
    got no evidence for: `compute_mastery([])` is the NONE band, which weighs
    nothing in the roll-up (I-mastery-09) but does count toward the coverage
    the caller has to show (DC-content-07).

    `Attempt.score` is never read here, only `correct` — a barème must not be
    able to move a band (I-mastery-08).
    """
    at = now or datetime.now(UTC)
    ids = list(student_ids)
    covered = list(competency_ids)
    if not ids:
        return {}

    grouped = load_attempt_inputs(db, school_id, ids, sheet_id=sheet_id, as_of=at)

    out: dict[uuid.UUID, TreeMasteryOut] = {}
    for student_id in ids:
        children = [
            compute_mastery(grouped.get((student_id, cid), []), at) for cid in covered
        ]
        out[student_id] = mastery_out(roll_up_mastery(children), children)
    return out


def sheet_mastery_overall(
    db: Session,
    school_id: uuid.UUID,
    sheet_id: uuid.UUID,
    student_ids: Sequence[uuid.UUID],
    competency_ids: Sequence[uuid.UUID],
    *,
    now: datetime | None = None,
) -> TreeMasteryOut:
    """The whole class on one sheet, as one band.

    Pooled across STUDENTS through the existing `pool_by_competency` — sound,
    and the same fold a single student goes through — then rolled up across
    competencies through `roll_up_mastery`. Never the other way round: pooling
    raw attempts across competencies is the one combination the model forbids
    (I-mastery-10).
    """
    at = now or datetime.now(UTC)
    ids = list(student_ids)
    covered = list(competency_ids)
    grouped = load_attempt_inputs(db, school_id, ids, sheet_id=sheet_id, as_of=at) if ids else {}
    pooled = pool_by_competency(grouped)
    children = [compute_mastery(pooled.get(cid, []), at) for cid in covered]
    return mastery_out(roll_up_mastery(children), children)
