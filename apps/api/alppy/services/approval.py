"""The approval gate: what may and may not reach paper.

`ExerciseOrigin.AI_GENERATED` + `approved_at IS NULL` is the one state that must
never be printed. CLAUDE.md states it as a rule a reviewer has to enforce by
reading, so it is enforced here instead, at every door into the print path:

* `sheet_service.create_adaptive_sheet` — a batch cannot even be *built* out of
  unapproved items, so the teacher finds out at the moment of the mistake;
* `sheets.render.render_adaptive_batch` and `render_sheet_pdfs` — because a
  sheet built before this gate existed, or an exercise un-approved after the
  sheet was built, must not slip through on a re-render.

It lives in its own module rather than in `adaptive_service` on purpose. The
routers treat adaptive planning as an optional workstream loaded through
`deps.load_optional`, and the *gate* must never be optional: the render path has
to be able to import it with no chance of an ImportError turning the rule off.
It has no dependency beyond the model.

The gate raises rather than filtering. A sheet quietly missing three of its
twelve items is a worse outcome for a teacher standing at a photocopier than an
error that says exactly which items are waiting for a decision.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.models import Exercise
from alppy.models.enums import ExerciseOrigin


class UnapprovedExerciseError(RuntimeError):
    """An AI-generated exercise reached the print path without approval.

    Carries the offending ids so the caller can name them to the teacher rather
    than saying "something is wrong".
    """

    def __init__(self, exercise_ids: Sequence[uuid.UUID]) -> None:
        self.exercise_ids = list(exercise_ids)
        shown = ", ".join(str(i) for i in self.exercise_ids[:5])
        more = "" if len(self.exercise_ids) <= 5 else f" (+{len(self.exercise_ids) - 5} more)"
        super().__init__(
            f"{len(self.exercise_ids)} AI-generated exercise(s) are not approved and "
            f"cannot be printed: {shown}{more}"
        )


def is_printable(exercise: Exercise) -> bool:
    """True unless this is an AI-generated exercise no teacher has approved."""
    return not (
        exercise.origin is ExerciseOrigin.AI_GENERATED and exercise.approved_at is None
    )


def ensure_printable(exercises: Iterable[Exercise]) -> None:
    """The gate. Raises `UnapprovedExerciseError` unless every item may print."""
    offenders = [ex.id for ex in exercises if not is_printable(ex)]
    if offenders:
        raise UnapprovedExerciseError(offenders)


def approve_exercises(
    db: Session,
    *,
    school_id: uuid.UUID,
    exercise_ids: Sequence[uuid.UUID],
    at: datetime | None = None,
) -> list[uuid.UUID]:
    """Teacher approval. The only way an AI-generated item becomes printable.

    Returns the ids actually stamped. Only AI-generated rows are touched:
    approving a textbook exercise is meaningless, and silently accepting the
    request would let a caller believe it had done something it had not.
    """
    if not exercise_ids:
        return []
    stamp = at or datetime.now(UTC)
    rows = db.scalars(
        select(Exercise).where(
            Exercise.school_id == school_id,
            Exercise.id.in_(list(exercise_ids)),
            Exercise.origin == ExerciseOrigin.AI_GENERATED,
        )
    )
    approved: list[uuid.UUID] = []
    for row in rows:
        row.approved_at = stamp
        approved.append(row.id)
    db.flush()
    return approved


def discard_exercises(
    db: Session,
    *,
    school_id: uuid.UUID,
    exercise_ids: Sequence[uuid.UUID],
    at: datetime | None = None,
) -> list[uuid.UUID]:
    """Throw a generated item away. It is never proposed or printed again.

    A discard is kept rather than deleted: the next run needs to know what the
    teacher already rejected, and `Attempt` rows may point at it if an earlier
    version of the sheet was printed.
    """
    if not exercise_ids:
        return []
    stamp = at or datetime.now(UTC)
    rows = db.scalars(
        select(Exercise).where(
            Exercise.school_id == school_id,
            Exercise.id.in_(list(exercise_ids)),
            Exercise.origin == ExerciseOrigin.AI_GENERATED,
        )
    )
    discarded: list[uuid.UUID] = []
    for row in rows:
        row.discarded_at = stamp
        row.approved_at = None  # a discarded item is never printable again
        discarded.append(row.id)
    db.flush()
    return discarded


__all__ = [
    "UnapprovedExerciseError",
    "approve_exercises",
    "discard_exercises",
    "ensure_printable",
    "is_printable",
]
