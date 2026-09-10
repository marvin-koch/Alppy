"""What one sheet says about a class, and the four ways that summary can lie.

The planner used to target `MasterySnapshot` — everything a child has ever done,
decayed. That is the right input for "what next term" and the wrong one for what
a teacher actually does: correct today's sheet and ask for the follow-up to
answer it. This is that input, and most of these tests are about its *limits*,
because a summary presented as "how they did on this sheet" when it was built
from three of twelve items is the same class of error as a short sheet with no
explanation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from test_retrieval import World, build_world, snapshot

from alppy.models import Attempt, Exercise, Sheet, SheetInstance
from alppy.models.enums import (
    ExerciseOrigin,
    ExerciseType,
    MasteryBand,
    SheetTarget,
)
from alppy.services.adaptive_service import gaps_for_student
from alppy.services.performance_summary import sheet_performance

NOW = datetime(2026, 9, 9, tzinfo=UTC)


@pytest.fixture
def world() -> World:
    return build_world()


def _sheet(world: World, *, uids: list[str], items_per_copy: int = 4) -> Sheet:
    """A common sheet, printed for the given students."""
    from alppy.services.chapter_service import ensure_unfiled_chapter

    chapter = ensure_unfiled_chapter(
        world.db, school_id=world.school_id, subject_id=world.subject_id
    )
    sheet = Sheet(
        id=uuid.uuid4(),
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_id=chapter.id,
        title="Fractions - controle",
        target=SheetTarget.CLASS,
        language="fr",
    )
    world.db.add(sheet)
    world.db.flush()
    for uid in uids:
        world.db.add(
            SheetInstance(
                id=uuid.uuid4(),
                school_id=world.school_id,
                sheet_id=sheet.id,
                student_id=world.student(uid),
                student_uid=uid,
                item_plan=[
                    {"exercise_id": str(uuid.uuid4()), "variant_id": None, "position": i}
                    for i in range(items_per_copy)
                ],
            )
        )
    world.db.flush()
    return sheet


def _exercise(world: World, *, competency_codes: list[str]) -> Exercise:
    from alppy.models import Competency

    exercise = Exercise(
        id=uuid.uuid4(),
        school_id=world.school_id,
        subject_id=world.subject_id,
        type=ExerciseType.MCQ,
        origin=ExerciseOrigin.TEXTBOOK,
        language="fr",
        statement="Calcule 3/4 + 1/4.",
        options=["1", "4/8", "3/8", "2"],
        answer_index=0,
        difficulty=3,
    )
    exercise.competencies = [
        world.db.get(Competency, world.competency(code)) for code in competency_codes
    ]
    world.db.add(exercise)
    world.db.flush()
    return exercise


def _attempt(world: World, *, uid: str, sheet: Sheet, exercise: Exercise, correct: bool) -> None:
    world.db.add(
        Attempt(
            id=uuid.uuid4(),
            school_id=world.school_id,
            person_id=world.person(uid),
            exercise_id=exercise.id,
            sheet_id=sheet.id,
            correct=correct,
            score=1.0 if correct else 0.0,
            difficulty=exercise.difficulty,
            answered_at=NOW - timedelta(days=1),
        )
    )
    world.db.flush()


def _perf(world: World, sheet: Sheet, uids: list[str]):
    return sheet_performance(
        world.db,
        school_id=world.school_id,
        student_ids=[world.student(u) for u in uids],
        sheet_id=sheet.id,
        now=NOW,
    )


def test_a_wrong_answer_shows_up_as_a_gap_on_the_competency_it_was_tagged_with(
    world: World,
) -> None:
    sheet = _sheet(world, uids=["7B_01"])
    exercise = _exercise(world, competency_codes=["MSN 32.1"])
    _attempt(world, uid="7B_01", sheet=sheet, exercise=exercise, correct=False)

    performance = _perf(world, sheet, ["7B_01"])[world.student("7B_01")]
    assert performance.has_evidence
    signal = performance.signals[0]
    assert signal.competency_id == world.competency("MSN 32.1")
    assert (signal.attempts, signal.wrong) == (1, 1)
    assert signal.band in (MasteryBand.FADING, MasteryBand.WEAK)


def test_the_summary_counts_an_item_once_per_competency_it_is_tagged_with(
    world: World,
) -> None:
    """The mapping is many-to-many on purpose, so a roll-up does not partition:
    one item can appear under two competencies. Percentages over the sheet would
    not sum, which is why the caller must say "the items touching X"."""
    sheet = _sheet(world, uids=["7B_01"])
    exercise = _exercise(world, competency_codes=["MSN 32.1", "MSN 32.2"])
    _attempt(world, uid="7B_01", sheet=sheet, exercise=exercise, correct=False)

    performance = _perf(world, sheet, ["7B_01"])[world.student("7B_01")]
    assert len(performance.signals) == 2
    assert sum(s.attempts for s in performance.signals) == 2  # one item, two pairs
    assert performance.answered == 1  # ...and still one item


def test_items_no_competency_could_be_attributed_to_are_counted_and_said_so(
    world: World,
) -> None:
    """The attempt join is an inner join. A student who got everything wrong on
    untagged items would otherwise produce an empty summary and read as fine —
    the summary lying by omission rather than by assertion."""
    sheet = _sheet(world, uids=["7B_01"])
    untagged = _exercise(world, competency_codes=[])
    _attempt(world, uid="7B_01", sheet=sheet, exercise=untagged, correct=False)

    performance = _perf(world, sheet, ["7B_01"])[world.student("7B_01")]
    assert performance.signals == []
    assert performance.answered == 1
    assert performance.unattributed == 1
    assert performance.is_partial


def test_a_sheet_read_only_in_part_is_reported_as_partial(world: World) -> None:
    """A pile can be half-scanned and an answer can be blank; neither becomes an
    attempt. Three of twelve items is a fact the teacher needs, not a rounding."""
    sheet = _sheet(world, uids=["7B_01"], items_per_copy=4)
    exercise = _exercise(world, competency_codes=["MSN 32.1"])
    _attempt(world, uid="7B_01", sheet=sheet, exercise=exercise, correct=False)

    performance = _perf(world, sheet, ["7B_01"])[world.student("7B_01")]
    assert (performance.answered, performance.printed) == (1, 4)
    assert performance.is_partial


def test_a_fully_read_sheet_is_not_reported_as_partial(world: World) -> None:
    sheet = _sheet(world, uids=["7B_01"], items_per_copy=2)
    for _ in range(2):
        _attempt(
            world,
            uid="7B_01",
            sheet=sheet,
            exercise=_exercise(world, competency_codes=["MSN 32.1"]),
            correct=True,
        )

    performance = _perf(world, sheet, ["7B_01"])[world.student("7B_01")]
    assert (performance.answered, performance.printed, performance.unattributed) == (2, 2, 0)
    assert not performance.is_partial


def test_another_sheets_results_never_leak_into_this_ones_summary(world: World) -> None:
    """`Attempt.sheet_id` is the whole filter. Without it this is just mastery
    again, and the feature does nothing while appearing to work."""
    corrected = _sheet(world, uids=["7B_01"])
    other = _sheet(world, uids=["7B_01"])
    _attempt(
        world,
        uid="7B_01",
        sheet=other,
        exercise=_exercise(world, competency_codes=["MSN 32.1"]),
        correct=False,
    )

    performance = _perf(world, corrected, ["7B_01"])[world.student("7B_01")]
    assert performance.signals == []
    assert performance.answered == 0


def test_a_student_who_never_handed_the_sheet_in_still_gets_an_entry(world: World) -> None:
    """An absent student is a case the caller handles, not a missing key."""
    sheet = _sheet(world, uids=["7B_01", "7B_02"])
    _attempt(
        world,
        uid="7B_01",
        sheet=sheet,
        exercise=_exercise(world, competency_codes=["MSN 32.1"]),
        correct=False,
    )

    performance = _perf(world, sheet, ["7B_01", "7B_02"])
    absent = performance[world.student("7B_02")]
    assert not absent.has_evidence
    assert absent.answered == 0


# --------------------------------------------------------------------------
# Which evidence the planner actually targets
# --------------------------------------------------------------------------
def test_the_sheet_the_teacher_corrected_wins_over_the_terms_average(world: World) -> None:
    """The two can disagree about the same child — the snapshot is built from
    the same attempts, unfiltered and decayed. The sheet is the more specific
    claim, and it is the one the teacher is holding."""
    sheet = _sheet(world, uids=["7B_01"])
    snapshot(
        world,
        student_uid="7B_01",
        competency_code="MSN 33.3",
        score=0.30,
        band=MasteryBand.FADING,
    )
    _attempt(
        world,
        uid="7B_01",
        sheet=sheet,
        exercise=_exercise(world, competency_codes=["MSN 32.1"]),
        correct=False,
    )
    performance = _perf(world, sheet, ["7B_01"])

    gaps, basis = gaps_for_student(
        world.db,
        school_id=world.school_id,
        person_id=world.person("7B_01"),
        performance=performance[world.student("7B_01")],
    )
    assert basis == "source_sheet"
    assert [g.competency_id for g in gaps] == [world.competency("MSN 32.1")]


def test_a_student_the_sheet_says_nothing_about_falls_back_to_their_mastery(
    world: World,
) -> None:
    """Absent, or their pile was never confirmed. Nobody gets an empty plan."""
    sheet = _sheet(world, uids=["7B_02"])
    snapshot(
        world,
        student_uid="7B_02",
        competency_code="MSN 33.3",
        score=0.30,
        band=MasteryBand.FADING,
    )
    performance = _perf(world, sheet, ["7B_02"])

    gaps, basis = gaps_for_student(
        world.db,
        school_id=world.school_id,
        person_id=world.person("7B_02"),
        performance=performance[world.student("7B_02")],
    )
    assert basis == "mastery"
    assert [g.competency_id for g in gaps] == [world.competency("MSN 33.3")]


def test_a_student_with_no_evidence_at_all_is_called_a_diagnostic_not_a_success(
    world: World,
) -> None:
    """No gaps because nothing is known is not the same as no gaps because
    everything is mastered, and the plan must not read as the second."""
    gaps, basis = gaps_for_student(
        world.db,
        school_id=world.school_id,
        person_id=world.person("7B_03"),
        performance=None,
    )
    assert (gaps, basis) == ([], "diagnostic")
