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
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.api.deps import Scope
from alppy.mastery.model import AttemptInput, MasteryResult, compute_mastery
from alppy.models import (
    Attempt,
    Chapter,
    Class,
    Competency,
    Detection,
    Exercise,
    MasterySnapshot,
    Scan,
    ScanPage,
    Sheet,
    Student,
    chapter_competency,
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
)
from alppy.services import competency_out, student_out

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


def load_attempt_inputs(
    db: Session,
    school_id: uuid.UUID,
    student_ids: list[uuid.UUID],
    *,
    subject_id: uuid.UUID | None = None,
    competency_ids: list[uuid.UUID] | None = None,
    as_of: datetime | None = None,
) -> dict[Key, list[AttemptInput]]:
    """Every attempt, keyed by (student, competency).

    An exercise mapped to two competencies contributes to both — that is the
    point of the mapping, and it is why this cannot be a simple group-by.

    ``as_of`` drops attempts answered after that moment. Live callers never
    need it — nothing is answered in the future — but a snapshot dated last
    Tuesday must be computed from the evidence that existed last Tuesday, or
    backfilling a history produces the same number at every point on the curve.
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

    grouped: dict[Key, list[AttemptInput]] = defaultdict(list)
    for student_id, competency_id, correct, answered_at, difficulty in db.execute(stmt):
        at = _aware(answered_at)
        if at is None:  # pragma: no cover - answered_at is NOT NULL
            continue
        grouped[(student_id, competency_id)].append(
            AttemptInput(correct=bool(correct), answered_at=at, difficulty=int(difficulty))
        )
    return dict(grouped)


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
        .where(Student.class_id == class_id)
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

    db.flush()
    return written


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
        select(Class)
        .where(Class.id == class_id)
        .where(Class.school_id == school_id)
        .where(Class.teacher_id == scope.teacher_id)
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
    student = db.execute(
        select(Student)
        .join(Class, Class.id == Student.class_id)
        .where(Student.id == student_id)
        .where(Student.school_id == scope.school_id)
        .where(Class.teacher_id == scope.teacher_id)
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
        select(Attempt, Sheet.title, Scan.id)
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
    for attempt, title, scan_id in rows:
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
            )
            continue
        taken.attempts_count += 1
        if attempt.correct:
            taken.correct_count += 1
        if answered > taken.answered_at:
            taken.answered_at = answered
        if taken.scan_id is None:
            taken.scan_id = scan_id

    return sorted(by_sheet.values(), key=lambda s: s.answered_at, reverse=True)


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
