"""The mastery model.

Deliberately simple and fully explainable: a teacher must be able to understand
why a cell is amber, and we must be able to write that explanation down. No
Bayesian knowledge tracing in the MVP — see docs/mastery-model.md for the
rationale and for the worked examples these constants were tuned against.

The score has two factors:

  accuracy   weighted recent correctness. Recent attempts count more than old
             ones, and harder exercises count more than easy ones.

  recency    how much we still trust that accuracy given how long it has been
             since the student last practised the competency. This is what
             makes a band "fade": accuracy alone is scale-invariant under
             uniform time decay, so without this factor a student who was
             perfect a year ago would still read as mastered forever.

  score = accuracy x recency          in [0, 1]

Both factors are pure functions of the attempt list, so the whole model is
unit-testable without a database.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from alppy.models.enums import MasteryBand

# --- Tunable constants. Every one of these is documented in docs/mastery-model.md.
HALF_LIFE_DAYS: Final = 21.0
"""Evidence half-life: after 21 days an attempt carries half the weight of a
fresh one when computing accuracy. This governs how quickly a *new* result
overtakes an old one — roughly the span over which a class moves through a
chapter."""

RECENCY_HALF_LIFE_DAYS: Final = 45.0
"""Retention half-life: how fast we stop trusting an accuracy the student has
not refreshed.

This is deliberately NOT the same constant as HALF_LIFE_DAYS, and the two were
briefly conflated. They measure different things: one is how fast evidence
*ages* relative to newer evidence, the other is how fast knowledge *fades*.
Sharing the 21-day value made a student with a perfect record read as 'fragile'
three weeks after the lesson, which is far too harsh — three weeks is a normal
gap between a chapter and its revision.

At 45 days a perfect record walks down the bands the way the band names
describe: solid for about two weeks, to-review by three, fragile by five,
fading by nine."""

RECENCY_GRACE_DAYS: Final = 7.0
"""No decay at all in the first week. Practising on Monday should not make the
matrix look worse on Friday."""

RECENCY_FLOOR: Final = 0.55
"""Recency never drives the score to zero. Evidence of past success is still
evidence; it is stale, not void. The floor is what makes a long-unpractised but
once-mastered competency read as 'fading' rather than 'never seen'."""

DIFFICULTY_WEIGHTS: Final[dict[int, float]] = {1: 0.8, 2: 0.9, 3: 1.0, 4: 1.2, 5: 1.4}
"""A correct answer on a difficulty-5 item is stronger evidence than on a
difficulty-1 item, and a wrong answer on an easy item is worse news."""

MIN_EVIDENCE: Final = 1.5
"""Effective sample size below which a band is provisional. One lucky guess on
one MCQ is not mastery; the UI marks these cells as provisional."""

REVIEW_HORIZON_DAYS: Final = 366
"""How far ahead ``days_until_review`` will look before giving up. A year is
past the point where the answer is actionable for a teacher."""

# --- Band thresholds. Ordered, and the order is meaningful.
BAND_SOLID: Final = 0.90
BAND_OK: Final = 0.75
BAND_WEAK: Final = 0.60


@dataclass(frozen=True, slots=True)
class AttemptInput:
    """One graded item. Deliberately not a SQLAlchemy row: the model is pure."""

    correct: bool
    answered_at: datetime
    difficulty: int = 3


@dataclass(frozen=True, slots=True)
class MasteryResult:
    score: float
    band: MasteryBand
    accuracy: float
    recency: float
    attempts_count: int
    effective_n: float
    provisional: bool
    last_attempt_at: datetime | None
    days_until_review: int | None

    @property
    def percent(self) -> int:
        return round(self.score * 100)


def difficulty_weight(difficulty: int) -> float:
    return DIFFICULTY_WEIGHTS.get(max(1, min(5, difficulty)), 1.0)


def _age_days(at: datetime, now: datetime) -> float:
    """Age in days, floored at 0 so a clock skew cannot produce a >1 weight."""
    return max(0.0, (now - at).total_seconds() / 86_400.0)


def decay(age_days: float, half_life: float = HALF_LIFE_DAYS) -> float:
    """Exponential decay with a half-life. ``decay(half_life) == 0.5``."""
    return math.exp(-math.log(2.0) * age_days / half_life)


def compute_accuracy(attempts: Sequence[AttemptInput], now: datetime) -> tuple[float, float]:
    """Weighted recent accuracy and the effective sample size behind it.

    Returns ``(accuracy, effective_n)``. ``effective_n`` is the sum of weights
    expressed in units of a fresh difficulty-3 attempt, which is what tells us
    whether we have enough evidence to trust the number at all.
    """
    total_w = 0.0
    correct_w = 0.0
    for a in attempts:
        w = decay(_age_days(a.answered_at, now)) * difficulty_weight(a.difficulty)
        total_w += w
        if a.correct:
            correct_w += w
    if total_w == 0.0:
        return (0.0, 0.0)
    return (correct_w / total_w, total_w)


def compute_recency(last_attempt_at: datetime | None, now: datetime) -> float:
    """How much we still trust the accuracy, given time since last practice."""
    if last_attempt_at is None:
        return 0.0
    idle = _age_days(last_attempt_at, now) - RECENCY_GRACE_DAYS
    if idle <= 0:
        return 1.0
    return max(RECENCY_FLOOR, decay(idle, RECENCY_HALF_LIFE_DAYS))


def band_for(score: float, *, has_attempts: bool = True) -> MasteryBand:
    """Map a score to its band. Never-assessed is a band, not a zero."""
    if not has_attempts:
        return MasteryBand.NONE
    if score >= BAND_SOLID:
        return MasteryBand.SOLID
    if score >= BAND_OK:
        return MasteryBand.OK
    if score >= BAND_WEAK:
        return MasteryBand.WEAK
    return MasteryBand.FADING


def days_until_review(accuracy: float, last_attempt_at: datetime | None, now: datetime) -> int | None:
    """Days until this competency is predicted to drop below the OK threshold.

    This is what the MasteryMeter caption ("62 % · revision dans 2 jours")
    shows. Returns 0 when it is already due — which includes an accuracy of
    zero, the single most urgent case there is — and None only when the
    competency has never been assessed and there is therefore nothing to
    predict.

    A zero accuracy used to return None here, which sent the worst cells in the
    matrix to the neutral "n answers" caption instead of "due for review now".
    """
    if last_attempt_at is None:
        return None
    for d in range(0, REVIEW_HORIZON_DAYS):
        if accuracy * compute_recency(last_attempt_at, now + timedelta(days=d)) < BAND_OK:
            return d
    # Only reachable if the constants are changed so that the recency floor
    # holds the score above the threshold forever, i.e. accuracy * RECENCY_FLOOR
    # >= BAND_OK. With the shipped values the maximum is 1.0 * 0.55 = 0.55,
    # comfortably under 0.75, so every competency eventually comes due;
    # test_the_recency_floor_never_holds_a_score_above_the_threshold pins that.
    return None


def compute_mastery(attempts: Sequence[AttemptInput], now: datetime) -> MasteryResult:
    """The whole model, in one call."""
    if not attempts:
        return MasteryResult(
            score=0.0,
            band=MasteryBand.NONE,
            accuracy=0.0,
            recency=0.0,
            attempts_count=0,
            effective_n=0.0,
            provisional=True,
            last_attempt_at=None,
            days_until_review=None,
        )

    last = max(a.answered_at for a in attempts)
    accuracy, effective_n = compute_accuracy(attempts, now)
    recency = compute_recency(last, now)
    score = max(0.0, min(1.0, accuracy * recency))

    return MasteryResult(
        score=score,
        band=band_for(score, has_attempts=True),
        accuracy=accuracy,
        recency=recency,
        attempts_count=len(attempts),
        effective_n=effective_n,
        provisional=effective_n < MIN_EVIDENCE,
        last_attempt_at=last,
        days_until_review=days_until_review(accuracy, last, now),
    )


def roll_up_mastery(children: Sequence[MasteryResult]) -> MasteryResult:
    """Combine several competency results into one, for a Theme or a Branch.

    Applied recursively: Theme = roll-up of its competencies, Competence =
    roll-up of its Themes, Branch = roll-up of its Competences. One rule, three
    levels, so a teacher who trusts a cell does not have to learn a second
    philosophy for the row above it.

    **Evidence-weighted mean of the children's scores**, weighted by
    ``effective_n``. Two alternatives were rejected (D58):

    *Worst-band-wins* would make every Theme read as the worst thing inside it.
    With three or four competencies per chapter that is "amber or red, always",
    which is a constant rather than a signal. ``_weakest_first`` sorts STUDENTS
    by their weakest cell — that is a triage order, not a claim that a group's
    mastery equals its minimum.

    *Plain mean* would let a competency backed by one lucky guess pull the
    aggregate exactly as hard as one backed by twenty confirmed attempts.
    ``compute_mastery`` already refuses to do that a level down — it is what
    ``effective_n`` and ``MIN_EVIDENCE`` are for — so an unweighted parent
    would reintroduce the problem the leaf model was built to avoid.

    A never-assessed child has ``effective_n == 0`` and so contributes no
    weight at all: "not yet seen is a band, not a zero" (docs/mastery-model.md
    §2) holds one level up unchanged. When every child is unassessed the
    roll-up is itself ``NONE``, via the same ``band_for(has_attempts=False)``
    path the leaf uses — literally the same code, not a parallel rule.

    Two honest breaks, documented rather than hidden, both in
    docs/mastery-model.md §6:

    * ``score == accuracy * recency`` holds at a leaf and **not** here.
      ``score`` is the weighted mean of the children's already-decayed scores;
      ``accuracy`` and ``recency`` are weighted means of theirs, kept for
      display only. Re-multiplying them would decay the evidence twice.
    * ``days_until_review`` is the EARLIEST of the assessed children's, not a
      re-derivation. A weighted mix of differently-aged decay curves has no
      closed form worth shipping, and "this Theme's next revision is whichever
      competency inside it comes due first" is both a defensible bound and the
      more useful thing for a teacher to act on.
    """
    assessed = [c for c in children if c.effective_n > 0.0]
    if not assessed:
        return MasteryResult(
            score=0.0,
            band=MasteryBand.NONE,
            accuracy=0.0,
            recency=0.0,
            attempts_count=sum(c.attempts_count for c in children),
            effective_n=0.0,
            provisional=True,
            last_attempt_at=None,
            days_until_review=None,
        )

    total_w = sum(c.effective_n for c in assessed)
    score = sum(c.score * c.effective_n for c in assessed) / total_w
    accuracy = sum(c.accuracy * c.effective_n for c in assessed) / total_w
    recency = sum(c.recency * c.effective_n for c in assessed) / total_w

    lasts = [c.last_attempt_at for c in assessed if c.last_attempt_at is not None]
    dues = [c.days_until_review for c in assessed if c.days_until_review is not None]

    return MasteryResult(
        score=max(0.0, min(1.0, score)),
        band=band_for(score, has_attempts=True),
        accuracy=accuracy,
        recency=recency,
        attempts_count=sum(c.attempts_count for c in children),
        effective_n=total_w,
        # The same constant as a leaf, against the SUMMED evidence: a Theme
        # whose competencies are each provisional on their own may well have
        # enough evidence together, and one built from a single lucky guess
        # still says so.
        provisional=total_w < MIN_EVIDENCE,
        last_attempt_at=max(lasts) if lasts else None,
        days_until_review=min(dues) if dues else None,
    )
