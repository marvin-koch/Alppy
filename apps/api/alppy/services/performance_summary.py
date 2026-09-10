"""How a class did on one sheet, condensed per competency.

The adaptive planner has always targeted `MasterySnapshot` — every attempt a
student has ever had, decayed by recency and weighted by difficulty. That is the
right input for "what does this child need next term". It is the wrong input for
the thing a teacher actually does on a Tuesday: they correct today's sheet and
want the follow-up to answer *it*.

So this module reads one sheet's attempts and rolls them up per competency,
through the same `mastery.model` the snapshots use. Not a second scoring rule:
`compute_mastery` and `band_for` are imported, so a band means the same thing
here as it does everywhere else in the product.

Three things it refuses to paper over
-------------------------------------

**Attribution is many-to-many, so a roll-up does not partition.** An exercise
tagged with two competencies counts toward both; eight items can produce fourteen
(competency, outcome) pairs. The summary therefore says "3 of the 4 items
touching X were wrong", never "X: 75% of the sheet".

**An untagged item is invisible, and that is a lie by omission.** The attempt
join is an inner join on `exercise_competency`, so an exercise nobody tagged
contributes nothing — and a student who got five of eight wrong, all on untagged
items, would read as fine. `unattributed` counts them so the caller can say so.

**Evidence is often partial.** Attempts exist only after a scan is confirmed, and
low-confidence, blank and ungraded items never become attempts at all. A summary
built from three of twelve items, presented as "how they did on this sheet", is
the same class of error as a short sheet with no explanation. `answered` and
`printed` are both reported, so the caller can tell full evidence from a sliver.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alppy.mastery.model import compute_mastery
from alppy.models import Attempt, SheetInstance, Student, exercise_competency
from alppy.models.enums import MasteryBand
from alppy.services.mastery_service import load_attempt_inputs


@dataclass(frozen=True, slots=True)
class CompetencySignal:
    """One competency, as this sheet saw it."""

    competency_id: uuid.UUID
    band: MasteryBand
    score: float
    attempts: int
    wrong: int


@dataclass(frozen=True, slots=True)
class SheetPerformance:
    """One student's result on one sheet, with its own limits attached."""

    student_id: uuid.UUID
    signals: list[CompetencySignal]
    answered: int
    """Items on this sheet that became an attempt — graded, confident, real."""
    printed: int
    """Items the copy carried. `answered < printed` means partial evidence."""
    unattributed: int
    """Answered items no competency could be attributed to. Invisible to the
    roll-up above, so they have to be counted separately or the summary is
    silently about a different, smaller sheet."""

    @property
    def has_evidence(self) -> bool:
        return bool(self.signals)

    @property
    def is_partial(self) -> bool:
        """True when the sheet was only partly read back.

        Not a failure — a pile can be half-scanned, an answer can be blank — but
        the caller must be able to say "this is based on 3 of 12" rather than
        presenting a sliver as the whole story.
        """
        return self.answered < self.printed or self.unattributed > 0


def sheet_performance(
    db: Session,
    *,
    school_id: uuid.UUID,
    student_ids: Sequence[uuid.UUID],
    sheet_id: uuid.UUID,
    now: datetime | None = None,
) -> dict[uuid.UUID, SheetPerformance]:
    """Per-competency signals for each student, from one sheet's attempts only.

    Returns an entry for every requested student, including those with nothing:
    an absent student is a fact the caller has to handle (they fall back to
    mastery), not a missing key to trip over.

    Takes and returns ``student_id`` although the attempts are person-keyed
    since 0028: this reads ONE sheet, a sheet belongs to one class in one
    school year, and a student row is exactly that pupil-in-that-year. The
    translation is done here rather than at each caller so a printed count
    (``SheetInstance``, year-bound) and an answered count (``Attempt``,
    person-bound) cannot end up keyed differently in the same dict.
    """
    at = now or datetime.now(UTC)
    ids = list(student_ids)
    if not ids:
        return {}

    person_of: dict[uuid.UUID, uuid.UUID] = dict(
        db.execute(
            select(Student.id, Student.person_id)
            .where(Student.school_id == school_id)
            .where(Student.id.in_(ids))
        ).all()  # type: ignore[arg-type]  # SQLAlchemy Row pairs
    )
    student_of = {person_id: student_id for student_id, person_id in person_of.items()}

    grouped = load_attempt_inputs(
        db, school_id, list(person_of.values()), sheet_id=sheet_id, as_of=at
    )

    by_student: dict[uuid.UUID, list[CompetencySignal]] = {sid: [] for sid in ids}
    for (person_id, competency_id), attempts in grouped.items():
        student_id = student_of.get(person_id)
        if student_id is None or student_id not in by_student:
            continue
        result = compute_mastery(attempts, at)
        by_student[student_id].append(
            CompetencySignal(
                competency_id=competency_id,
                band=result.band,
                score=result.score,
                attempts=len(attempts),
                wrong=sum(1 for a in attempts if not a.correct),
            )
        )

    people = list(person_of.values())
    answered = _answered_per_person(db, school_id=school_id, person_ids=people, sheet_id=sheet_id)
    attributed = _attributed_per_person(
        db, school_id=school_id, person_ids=people, sheet_id=sheet_id
    )
    printed = _printed_per_student(db, school_id=school_id, student_ids=ids, sheet_id=sheet_id)

    def _for(sid: uuid.UUID, counts: dict[uuid.UUID, int]) -> int:
        person_id = person_of.get(sid)
        return counts.get(person_id, 0) if person_id is not None else 0

    return {
        sid: SheetPerformance(
            student_id=sid,
            # Worst first, so a caller that truncates keeps what matters.
            signals=sorted(by_student[sid], key=lambda s: (s.score, -s.wrong)),
            answered=_for(sid, answered),
            printed=printed.get(sid, 0),
            unattributed=max(0, _for(sid, answered) - _for(sid, attributed)),
        )
        for sid in ids
    }


def _answered_per_person(
    db: Session,
    *,
    school_id: uuid.UUID,
    person_ids: Sequence[uuid.UUID],
    sheet_id: uuid.UUID,
) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(Attempt.person_id, func.count(Attempt.id))
        .where(
            Attempt.school_id == school_id,
            Attempt.sheet_id == sheet_id,
            Attempt.person_id.in_(list(person_ids)),
        )
        .group_by(Attempt.person_id)
    )
    return {person_id: int(count) for person_id, count in rows}


def _attributed_per_person(
    db: Session,
    *,
    school_id: uuid.UUID,
    person_ids: Sequence[uuid.UUID],
    sheet_id: uuid.UUID,
) -> dict[uuid.UUID, int]:
    """Answered items that at least one competency could be attributed to.

    `distinct` on the attempt: the join fans out over the many-to-many, and this
    counts items, not (item, competency) pairs.
    """
    rows = db.execute(
        select(Attempt.person_id, func.count(func.distinct(Attempt.id)))
        .join(exercise_competency, exercise_competency.c.exercise_id == Attempt.exercise_id)
        .where(
            Attempt.school_id == school_id,
            Attempt.sheet_id == sheet_id,
            Attempt.person_id.in_(list(person_ids)),
        )
        .group_by(Attempt.person_id)
    )
    return {person_id: int(count) for person_id, count in rows}


def _printed_per_student(
    db: Session,
    *,
    school_id: uuid.UUID,
    student_ids: Sequence[uuid.UUID],
    sheet_id: uuid.UUID,
) -> dict[uuid.UUID, int]:
    """How many items each copy actually carried.

    Read off `SheetInstance.item_plan` rather than the sheet's own item list: a
    differentiated batch gives every child a different subset, so the sheet's
    length is not the child's.
    """
    rows = db.execute(
        select(SheetInstance.student_id, SheetInstance.item_plan).where(
            SheetInstance.school_id == school_id,
            SheetInstance.sheet_id == sheet_id,
            SheetInstance.student_id.in_(list(student_ids)),
        )
    )
    return {student_id: len(plan or []) for student_id, plan in rows}


__all__ = ["CompetencySignal", "SheetPerformance", "sheet_performance"]
