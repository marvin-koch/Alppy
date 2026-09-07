"""The mastery model and its band thresholds.

These tests encode the *pedagogical* claims the model makes, not just its
arithmetic. If a change here starts failing, the question to ask is whether the
teacher-facing meaning of a band has changed.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from alppy.mastery.model import (
    BAND_OK,
    BAND_SOLID,
    BAND_WEAK,
    HALF_LIFE_DAYS,
    RECENCY_FLOOR,
    AttemptInput,
    band_for,
    compute_accuracy,
    compute_mastery,
    compute_recency,
    days_until_review,
    decay,
    difficulty_weight,
)
from alppy.models.enums import BAND_ORDER, MasteryBand


def A(correct: bool, days: float, difficulty: int = 3, *, now: datetime) -> AttemptInput:
    return AttemptInput(correct=correct, answered_at=now - timedelta(days=days), difficulty=difficulty)


# --- decay ---------------------------------------------------------------
def test_decay_halves_at_the_half_life() -> None:
    assert decay(0) == pytest.approx(1.0)
    assert decay(HALF_LIFE_DAYS) == pytest.approx(0.5)
    assert decay(2 * HALF_LIFE_DAYS) == pytest.approx(0.25)


def test_difficulty_weight_is_monotonic_and_clamped() -> None:
    weights = [difficulty_weight(d) for d in range(1, 6)]
    assert weights == sorted(weights)
    assert difficulty_weight(0) == difficulty_weight(1)
    assert difficulty_weight(99) == difficulty_weight(5)


# --- bands ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("score", "band"),
    [
        (1.00, MasteryBand.SOLID),
        (0.90, MasteryBand.SOLID),
        (0.8999, MasteryBand.OK),
        (0.75, MasteryBand.OK),
        (0.7499, MasteryBand.WEAK),
        (0.60, MasteryBand.WEAK),
        (0.5999, MasteryBand.FADING),
        (0.00, MasteryBand.FADING),
    ],
)
def test_band_thresholds_are_exact(score: float, band: MasteryBand) -> None:
    """Thresholds are inclusive at the bottom of each band."""
    assert band_for(score) is band


def test_never_assessed_is_a_band_not_a_zero() -> None:
    """A competency nobody has tested is not the same as one a student fails."""
    assert band_for(0.0, has_attempts=False) is MasteryBand.NONE
    assert band_for(0.0, has_attempts=True) is MasteryBand.FADING


def test_band_order_is_best_to_worst() -> None:
    assert BAND_ORDER[0] is MasteryBand.SOLID
    assert BAND_ORDER[-1] is MasteryBand.NONE
    assert len(set(BAND_ORDER)) == len(MasteryBand)


def test_thresholds_are_ordered() -> None:
    assert BAND_SOLID > BAND_OK > BAND_WEAK > 0


# --- accuracy ------------------------------------------------------------
def test_recent_attempts_outweigh_old_ones(now: datetime) -> None:
    """A student who has turned it around reads as improving, not as average."""
    turned_around = [A(False, 60, now=now), A(False, 60, now=now), A(True, 0, now=now)]
    accuracy, _ = compute_accuracy(turned_around, now)
    assert accuracy > 0.75


def test_a_recent_collapse_shows_immediately(now: datetime) -> None:
    slipped = [A(True, 60, now=now), A(True, 60, now=now), A(False, 0, now=now)]
    accuracy, _ = compute_accuracy(slipped, now)
    assert accuracy < 0.30


def test_harder_items_carry_more_weight(now: datetime) -> None:
    easy_win = [A(True, 0, 1, now=now), A(False, 0, 5, now=now)]
    hard_win = [A(False, 0, 1, now=now), A(True, 0, 5, now=now)]
    assert compute_accuracy(hard_win, now)[0] > compute_accuracy(easy_win, now)[0]


def test_no_attempts_gives_zero_accuracy(now: datetime) -> None:
    assert compute_accuracy([], now) == (0.0, 0.0)


def test_future_timestamps_cannot_inflate_weight(now: datetime) -> None:
    """Clock skew on an uploaded scan must not produce a weight above 1."""
    future = [AttemptInput(correct=True, answered_at=now + timedelta(days=5))]
    _, effective_n = compute_accuracy(future, now)
    assert effective_n <= 1.0 + 1e-9


# --- recency -------------------------------------------------------------
def test_a_week_of_grace_before_anything_decays(now: datetime) -> None:
    """Practising on Monday must not make the matrix look worse on Friday."""
    assert compute_recency(now - timedelta(days=0), now) == 1.0
    assert compute_recency(now - timedelta(days=6), now) == 1.0


def test_recency_falls_after_the_grace_period(now: datetime) -> None:
    assert compute_recency(now - timedelta(days=20), now) < 1.0


def test_recency_never_falls_below_the_floor(now: datetime) -> None:
    """Stale evidence is stale, not void."""
    assert compute_recency(now - timedelta(days=3650), now) == pytest.approx(RECENCY_FLOOR)


def test_never_practised_has_no_recency(now: datetime) -> None:
    assert compute_recency(None, now) == 0.0


# --- the whole model -----------------------------------------------------
def test_empty_history_is_the_none_band(now: datetime) -> None:
    r = compute_mastery([], now)
    assert r.band is MasteryBand.NONE
    assert r.score == 0.0
    assert r.provisional is True
    assert r.days_until_review is None


def test_fresh_perfect_run_is_solid(now: datetime) -> None:
    r = compute_mastery([A(True, 0, now=now) for _ in range(5)], now)
    assert r.band is MasteryBand.SOLID
    assert r.score == pytest.approx(1.0)
    assert r.provisional is False


def test_fresh_failure_is_fading(now: datetime) -> None:
    r = compute_mastery([A(False, 0, now=now) for _ in range(5)], now)
    assert r.band is MasteryBand.FADING
    assert r.score == pytest.approx(0.0)


def test_mastery_fades_without_practice(now: datetime) -> None:
    """The central claim of the model: a perfect record decays through every
    band as the student stops practising. Without the recency factor the score
    would be scale-invariant and stay at 1.0 forever."""
    perfect = [A(True, 0, now=now) for _ in range(5)]
    bands = []
    for idle in (0, 10, 18, 23, 60, 200):
        aged = [
            AttemptInput(correct=a.correct, answered_at=a.answered_at - timedelta(days=idle))
            for a in perfect
        ]
        bands.append(compute_mastery(aged, now).band)
    assert bands[0] is MasteryBand.SOLID
    assert bands[-1] is MasteryBand.FADING
    # Monotonically non-improving as time passes.
    positions = [BAND_ORDER.index(b) for b in bands]
    assert positions == sorted(positions)


def test_score_always_within_the_unit_interval(now: datetime) -> None:
    for attempts in (
        [],
        [A(True, 0, 5, now=now)],
        [A(False, 500, 1, now=now)],
        [A(True, 0, now=now), A(False, 300, now=now)],
    ):
        r = compute_mastery(attempts, now)
        assert 0.0 <= r.score <= 1.0


def test_a_single_answer_is_flagged_provisional(now: datetime) -> None:
    """One lucky guess on one MCQ is not mastery, and the UI must be able to
    say so rather than painting a confident green cell."""
    r = compute_mastery([A(True, 0, now=now)], now)
    assert r.band is MasteryBand.SOLID
    assert r.provisional is True


def test_enough_evidence_clears_the_provisional_flag(now: datetime) -> None:
    r = compute_mastery([A(True, 0, now=now) for _ in range(3)], now)
    assert r.provisional is False


def test_review_prediction_is_sooner_for_a_weaker_score(now: datetime) -> None:
    strong = compute_mastery([A(True, 0, now=now) for _ in range(5)], now)
    weaker = compute_mastery(
        [A(True, 0, now=now), A(True, 0, now=now), A(True, 0, now=now), A(False, 0, now=now)], now
    )
    assert strong.days_until_review is not None
    assert weaker.days_until_review is not None
    assert weaker.days_until_review < strong.days_until_review


def test_already_below_threshold_is_due_now(now: datetime) -> None:
    r = compute_mastery([A(True, 90, now=now) for _ in range(3)], now)
    assert r.days_until_review == 0


def test_a_student_who_got_everything_wrong_is_due_now_not_never(now: datetime) -> None:
    """Zero accuracy is the most urgent case there is, not an exempt one.

    This used to return None, because the guard read ``accuracy <= 0.0`` as
    "nothing to predict". The profile then captioned the worst cells in the
    matrix with a neutral answer count instead of "due for review now".
    """
    r = compute_mastery([A(False, 1, now=now) for _ in range(5)], now)
    assert r.score == 0.0
    assert r.band is MasteryBand.FADING
    assert r.days_until_review == 0


def test_never_assessed_is_the_only_none_review_prediction(now: datetime) -> None:
    """None means "never assessed" and nothing else."""
    assert compute_mastery([], now).days_until_review is None
    assert days_until_review(0.0, None, now) is None
    # Every assessed competency, however strong, eventually comes due.
    for attempts in ([A(True, 0, now=now)], [A(True, 0, now=now) for _ in range(20)]):
        assert compute_mastery(attempts, now).days_until_review is not None


def test_the_recency_floor_never_holds_a_score_above_the_threshold() -> None:
    """The invariant that makes "never comes due" impossible.

    ``days_until_review`` scans forward a year and returns None if it never
    finds a day below the threshold. With the shipped constants that cannot
    happen: accuracy is at most 1.0, so the floor caps the eventual score at
    RECENCY_FLOOR, well under BAND_OK. If a future tuning breaks this, the
    scan starts returning None and the docs in §4 stop being true — so pin it.
    """
    assert 1.0 * RECENCY_FLOOR < BAND_OK


def test_percent_is_a_rounded_whole_number(now: datetime) -> None:
    r = compute_mastery([A(True, 0, now=now), A(False, 0, now=now)], now)
    assert r.percent == 50


# --- the two half-lives are different quantities -------------------------
def test_retention_half_life_is_longer_than_the_evidence_half_life() -> None:
    """These measure different things and must not be conflated.

    HALF_LIFE_DAYS is how fast an attempt loses weight *relative to a newer
    attempt*. RECENCY_HALF_LIFE_DAYS is how fast knowledge fades when nobody
    practises. Sharing one constant made a perfect record read as 'fragile'
    three weeks after the lesson, which is a normal gap before revision.
    """
    from alppy.mastery.model import RECENCY_HALF_LIFE_DAYS

    assert RECENCY_HALF_LIFE_DAYS > HALF_LIFE_DAYS


def test_a_perfect_record_walks_the_bands_the_way_the_names_describe(now: datetime) -> None:
    """Band names are a promise about time, and this pins the schedule down."""
    def band_after(idle_days: int) -> MasteryBand:
        attempts = [A(True, idle_days, now=now) for _ in range(5)]
        return compute_mastery(attempts, now).band

    assert band_after(0) is MasteryBand.SOLID
    assert band_after(7) is MasteryBand.SOLID       # a week later, still solid
    assert band_after(21) is MasteryBand.OK         # three weeks: due for review
    assert band_after(35) is MasteryBand.WEAK       # five weeks: fragile
    assert band_after(60) is MasteryBand.FADING     # two months: losing it


def test_evidence_ageing_is_unaffected_by_the_retention_constant(now: datetime) -> None:
    """Accuracy weighting uses the shorter half-life: a result from three weeks
    ago must count about half as much as today's."""
    old_then_new = [A(False, 21, now=now), A(True, 0, now=now)]
    accuracy, _ = compute_accuracy(old_then_new, now)
    assert accuracy == pytest.approx(1 / 1.5, abs=0.02)
