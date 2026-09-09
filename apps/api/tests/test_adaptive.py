"""Adaptive per-student generation (F4) — the focal feature.

Three properties are load-bearing and each has a test that fails loudly if it
regresses:

1. **Retrieval comes first.** Generation only ever fills what the indexed
   corpus could not.
2. **Nothing AI-generated is printable until a teacher approves it.**
3. **No student name ever reaches a model provider.** The prompt carries the
   UID; the PII gate is armed with the real roster, and the test proves both
   that it is armed and that it would fire.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from test_retrieval import ROSTER, World, build_world, snapshot

from alppy.ai.base import ChatRequest, ChatResponse
from alppy.ai.client import AiClient
from alppy.ai.providers import EchoChatProvider
from alppy.ai.scrub import PiiLeakError, assert_no_pii, to_ref
from alppy.models import Exercise
from alppy.models.enums import ExerciseOrigin, MasteryBand
from alppy.services import adaptive_service, retrieval


@pytest.fixture
def world() -> World:
    return build_world()


# --------------------------------------------------------------------------
# A chat provider that records exactly what would have been sent
# --------------------------------------------------------------------------
class RecordingChat:
    """Wraps the offline provider and keeps every request for inspection."""

    name = "echo"

    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []
        self._inner = EchoChatProvider()

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return self._inner.complete(request)

    @property
    def sent_text(self) -> str:
        return "\n".join(f"{r.system}\n{r.user}" for r in self.requests)


@pytest.fixture
def chat(monkeypatch: pytest.MonkeyPatch) -> RecordingChat:
    recorder = RecordingChat()
    monkeypatch.setattr("alppy.ai.client.build_chat_provider", lambda: recorder)
    return recorder


def propose(
    world: World,
    *,
    student_uids: list[str] | None = None,
    items: int = 6,
    allow_generation: bool = True,
    language: str = "fr",
):  # type: ignore[no-untyped-def]
    return adaptive_service.propose_adaptive(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        student_ids=[world.student(u) for u in (student_uids or ["7B_01"])],
        items_per_student=items,
        allow_generation=allow_generation,
        language=language,
    )


# --------------------------------------------------------------------------
# Gap targeting
# --------------------------------------------------------------------------
def test_weakest_bands_come_first_and_solid_trails_as_stretch(world: World) -> None:
    snapshot(world, student_uid="7B_01", competency_code="MSN 32.1", score=0.95, band=MasteryBand.SOLID)
    snapshot(world, student_uid="7B_01", competency_code="MSN 33.3", score=0.80, band=MasteryBand.OK)
    snapshot(world, student_uid="7B_01", competency_code="MSN 34.1", score=0.66, band=MasteryBand.WEAK)
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.2", score=0.41, band=MasteryBand.FADING)
    snapshot(world, student_uid="7B_01", competency_code="MSN 33.4", score=0.0, band=MasteryBand.NONE)
    world.db.commit()

    gaps = adaptive_service.pick_gaps(
        adaptive_service.latest_snapshots(
            world.db, school_id=world.school_id, student_id=world.student("7B_01")
        )
    )
    codes = [g.band for g in gaps]
    # Real gaps first, weakest first; SOLID trails as the single stretch target.
    assert codes == [MasteryBand.FADING, MasteryBand.WEAK, MasteryBand.OK, MasteryBand.SOLID]
    assert gaps[0].competency_id == world.competency("MSN 31.2")
    assert gaps[-1].competency_id == world.competency("MSN 32.1")
    # NONE is an absence of evidence, not a gap: it is still never targeted.
    assert world.competency("MSN 33.4") not in {g.competency_id for g in gaps}


def test_stretch_never_crowds_out_real_gap_work(world: World) -> None:
    """Four fading competencies fill the sheet; the solid one waits."""
    for code in ("MSN 31.2", "MSN 33.3", "MSN 34.1", "MSN 34.2"):
        snapshot(world, student_uid="7B_01", competency_code=code, score=0.4, band=MasteryBand.FADING)
    snapshot(world, student_uid="7B_01", competency_code="MSN 32.1", score=0.95, band=MasteryBand.SOLID)
    world.db.commit()

    gaps = adaptive_service.pick_gaps(
        adaptive_service.latest_snapshots(
            world.db, school_id=world.school_id, student_id=world.student("7B_01")
        )
    )
    assert [g.band for g in gaps] == [MasteryBand.FADING] * 4
    assert world.competency("MSN 32.1") not in {g.competency_id for g in gaps}


def test_a_fully_mastered_student_gets_stretch_not_the_easy_diagnostic(world: World) -> None:
    """The anti-ZPD bug: SOLID used to be skipped, so a student who had
    mastered everything fell through to FALLBACK_DIFFICULTY — easier work than
    they could already do. The cap is lifted when there is no gap work to
    protect, and the stretch sits *above* the working level."""
    for code in ("MSN 32.1", "MSN 33.3"):
        snapshot(world, student_uid="7B_01", competency_code=code, score=0.95, band=MasteryBand.SOLID)
    world.db.commit()

    gaps = adaptive_service.pick_gaps(
        adaptive_service.latest_snapshots(
            world.db, school_id=world.school_id, student_id=world.student("7B_01")
        )
    )
    assert len(gaps) == 2, "a mastered student must not fall into the diagnostic branch"
    assert all(g.band is MasteryBand.SOLID for g in gaps)
    assert all(g.target_difficulty > adaptive_service.FALLBACK_DIFFICULTY for g in gaps)


def test_only_the_latest_snapshot_per_competency_counts(world: World) -> None:
    snapshot(
        world, student_uid="7B_01", competency_code="MSN 32.1",
        score=0.30, band=MasteryBand.FADING, days_ago=30,
    )
    snapshot(
        world, student_uid="7B_01", competency_code="MSN 32.1",
        score=0.92, band=MasteryBand.SOLID, days_ago=1,
    )
    world.db.commit()
    rows = adaptive_service.latest_snapshots(
        world.db, school_id=world.school_id, student_id=world.student("7B_01")
    )
    assert len(rows) == 1
    assert rows[0].band is MasteryBand.SOLID
    # The stale FADING row is gone, so the competency is targeted as stretch
    # rather than as the gap the 30-day-old snapshot would have made it.
    gaps = adaptive_service.pick_gaps(rows)
    assert [g.band for g in gaps] == [MasteryBand.SOLID]


def test_a_fading_competency_is_practised_one_level_below_a_fragile_one() -> None:
    """'Slightly below current level' for fading, 'at level' for fragile."""
    assert adaptive_service.target_difficulty(0.55, MasteryBand.FADING) == 2
    assert adaptive_service.target_difficulty(0.55, MasteryBand.WEAK) == 3
    assert adaptive_service.target_difficulty(0.85, MasteryBand.OK) == 4
    # Monotone in the score, and never outside the printable 1..5 range.
    assert adaptive_service.target_difficulty(0.0, MasteryBand.FADING) == 1
    assert adaptive_service.target_difficulty(1.0, MasteryBand.OK) == 4
    levels = [adaptive_service.target_difficulty(s / 10, MasteryBand.WEAK) for s in range(11)]
    assert levels == sorted(levels)


def test_gap_limit_keeps_a_sheet_focused(world: World) -> None:
    for code in ("MSN 32.1", "MSN 33.3", "MSN 34.1", "MSN 34.2", "MSN 31.2", "MSN 33.2"):
        snapshot(world, student_uid="7B_01", competency_code=code, score=0.5, band=MasteryBand.FADING)
    world.db.commit()
    gaps = adaptive_service.pick_gaps(
        adaptive_service.latest_snapshots(
            world.db, school_id=world.school_id, student_id=world.student("7B_01")
        )
    )
    assert len(gaps) == adaptive_service.MAX_TARGET_COMPETENCIES


# --------------------------------------------------------------------------
# 1. Retrieval first
# --------------------------------------------------------------------------
def test_retrieval_fills_the_sheet_and_the_model_is_never_called(
    world: World, chat: RecordingChat
) -> None:
    """MSN 32.1 has six indexed exercises; a four-item sheet needs no model."""
    snapshot(world, student_uid="7B_01", competency_code="MSN 32.1", score=0.62, band=MasteryBand.WEAK)
    world.db.commit()

    response = propose(world, items=4)
    plan = response.plans[0]

    assert len(plan.retrieved) == 4
    assert plan.generated == []
    assert response.generated_count == 0
    assert response.needs_approval is False
    assert chat.requests == [], "generation ran despite retrieval covering the sheet"
    assert all(
        p.exercise.origin is ExerciseOrigin.TEXTBOOK for p in plan.retrieved
    )


def test_retrieved_items_target_the_gap_and_say_so(world: World) -> None:
    snapshot(world, student_uid="7B_01", competency_code="MSN 32.1", score=0.62, band=MasteryBand.WEAK)
    world.db.commit()
    plan = propose(world, items=4).plans[0]
    assert plan.targeted_competency_ids == [world.competency("MSN 32.1")]
    for proposal in plan.retrieved:
        assert world.competency("MSN 32.1") in proposal.exercise.competency_ids
        assert "cible une compétence fragile" in proposal.provenance.reason
        assert proposal.provenance.page is not None


def test_a_student_with_no_mastery_data_gets_a_diagnostic_set(
    world: World, chat: RecordingChat
) -> None:
    """An empty sheet is the wrong answer for a student who has not been
    assessed yet: they get a gentle diagnostic set instead."""
    plan = propose(world, student_uids=["7B_02"], items=5).plans[0]
    assert plan.targeted_competency_ids == []
    assert len(plan.retrieved) == 5
    assert plan.generated == []
    assert chat.requests == []
    assert "aucune donnée de maîtrise" in plan.retrieved[0].provenance.reason


# --------------------------------------------------------------------------
# 2. Generation fills only the gap, and is never printable unapproved
# --------------------------------------------------------------------------
def test_generation_only_covers_the_shortfall(world: World, chat: RecordingChat) -> None:
    """MSN 31.3 has exactly one indexed exercise, so a six-item sheet has a
    five-item hole and that is what the model is asked for — no more."""
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    world.db.commit()

    response = propose(world, items=6)
    plan = response.plans[0]

    assert len(plan.retrieved) == 1
    assert plan.generated, "the shortfall was not generated"
    assert plan.total_items <= 6
    assert len(chat.requests) == 1
    assert "Number of exercises: 5" in chat.requests[0].user


def test_generated_items_are_persisted_unapproved_and_marked(
    world: World, chat: RecordingChat
) -> None:
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    world.db.commit()

    response = propose(world, items=6)
    plan = response.plans[0]
    assert response.generated_count == len(plan.generated)
    assert response.needs_approval is True

    for proposal in plan.generated:
        assert proposal.exercise.origin is ExerciseOrigin.AI_GENERATED
        assert proposal.exercise.approved_at is None
        row = world.db.get(Exercise, proposal.exercise.id)
        assert row is not None, "a generated exercise was returned but never persisted"
        assert row.origin is ExerciseOrigin.AI_GENERATED
        assert row.approved_at is None
        assert row.competencies  # tagged with the gap it was written for


def test_generated_items_cannot_be_printed_without_approval(
    world: World, chat: RecordingChat
) -> None:
    """The gate. `ensure_printable` is what the render path calls."""
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    world.db.commit()
    plan = propose(world, items=6).plans[0]
    rows = [world.db.get(Exercise, p.exercise.id) for p in plan.generated]
    assert rows

    with pytest.raises(adaptive_service.UnapprovedExerciseError):
        adaptive_service.ensure_printable([r for r in rows if r is not None])
    assert not any(adaptive_service.is_printable(r) for r in rows if r is not None)

    approved = adaptive_service.approve_exercises(
        world.db,
        school_id=world.school_id,
        exercise_ids=[p.exercise.id for p in plan.generated],
    )
    assert sorted(approved) == sorted(p.exercise.id for p in plan.generated)
    world.db.commit()
    adaptive_service.ensure_printable([r for r in rows if r is not None])
    assert all(adaptive_service.is_printable(r) for r in rows if r is not None)


def test_a_textbook_sheet_never_offers_the_unapproved_generated_items(
    world: World, chat: RecordingChat
) -> None:
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    world.db.commit()
    plan = propose(world, items=6).plans[0]
    generated_ids = {p.exercise.id for p in plan.generated}
    assert generated_ids

    proposals = retrieval.propose_exercises(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_ids=[],
        intent=None,
        count=32,
        language="fr",
        difficulty=None,
    )
    assert generated_ids.isdisjoint({p.exercise.id for p in proposals})


def test_generation_can_be_switched_off(world: World, chat: RecordingChat) -> None:
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    world.db.commit()
    response = propose(world, items=6, allow_generation=False)
    assert response.plans[0].generated == []
    assert response.generated_count == 0
    assert response.needs_approval is False
    assert chat.requests == []


def test_style_examples_come_from_the_retrieved_exercises(
    world: World, chat: RecordingChat
) -> None:
    """Generated items must match the register of the book, which is what the
    retrieved exercises are for."""
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    world.db.commit()
    plan = propose(world, items=6).plans[0]
    sent = chat.requests[0].user
    for proposal in plan.retrieved:
        assert " ".join(proposal.exercise.statement.split()) in sent


def test_generation_failure_degrades_to_a_shorter_sheet(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model outage must not lose the retrieved half of the sheet."""

    class Broken:
        name = "broken"

        def complete(self, request: ChatRequest) -> ChatResponse:
            raise RuntimeError("provider is down")

    monkeypatch.setattr("alppy.ai.client.build_chat_provider", lambda: Broken())
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    world.db.commit()

    response = propose(world, items=6)
    assert response.plans[0].retrieved
    assert response.plans[0].generated == []


# --------------------------------------------------------------------------
# 3. No student name ever reaches a model provider
# --------------------------------------------------------------------------
def test_no_roster_name_appears_in_a_generation_prompt(
    world: World, chat: RecordingChat
) -> None:
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    world.db.commit()
    propose(world, items=6)

    assert chat.requests, "nothing was sent, so this proves nothing"
    sent = chat.sent_text
    for first, last in ROSTER:
        assert first not in sent
        assert last not in sent
    # What is sent instead is the UID.
    assert "7B_01" in sent


def test_the_pii_gate_is_armed_with_the_real_roster(
    world: World, chat: RecordingChat, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proving the prompt happens to be clean is not enough: the caller must
    hand the gate the roster, so that a future edit which leaks a name fails
    here instead of at the provider."""
    seen: list[list[str] | None] = []
    real = assert_no_pii

    def spy(text: str, *, names: list[str] | None = None) -> None:
        seen.append(names)
        real(text, names=names)

    monkeypatch.setattr("alppy.ai.client.assert_no_pii", spy)
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    world.db.commit()
    propose(world, items=6)

    assert seen, "the gate was never reached"
    for names in seen:
        assert names is not None
        for first, last in ROSTER:
            assert first in names
            assert last in names


def test_the_armed_gate_would_actually_fire() -> None:
    """The other half of the proof: with that roster, a leaked name raises."""
    roster = [n for pair in ROSTER for n in pair]
    assert_no_pii("Target competencies: fractions. Student reference: 7B_1", names=roster)
    with pytest.raises(PiiLeakError):
        assert_no_pii("Write exercises for Livia Bernasconi", names=roster)


def test_generation_meta_records_the_uid_never_the_name(
    world: World, chat: RecordingChat
) -> None:
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    world.db.commit()
    plan = propose(world, items=6).plans[0]
    for proposal in plan.generated:
        row = world.db.get(Exercise, proposal.exercise.id)
        assert row is not None
        meta = row.generation_meta or {}
        assert meta["student_refs"] == ["7B_01"]
        assert str(to_ref("7B_01")) == "7B_01"
        blob = str(meta)
        for first, last in ROSTER:
            assert first not in blob
            assert last not in blob


# --------------------------------------------------------------------------
# Response shape
# --------------------------------------------------------------------------
def test_one_plan_per_requested_student_in_the_requested_order(world: World) -> None:
    response = propose(world, student_uids=["7B_03", "7B_01"], items=3)
    assert [p.student_uid for p in response.plans] == ["7B_03", "7B_01"]
    assert response.language == "fr"
    assert all(p.student_id == world.student(p.student_uid) for p in response.plans)


def test_retrieved_and_generated_are_reported_separately(
    world: World, chat: RecordingChat
) -> None:
    """The UI marks generated items with the accent colour, so the split must
    survive into the response rather than being merged into one list."""
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    world.db.commit()
    plan = propose(world, items=6).plans[0]
    assert plan.total_items == len(plan.retrieved) + len(plan.generated)
    assert {p.exercise.origin for p in plan.retrieved} == {ExerciseOrigin.TEXTBOOK}
    assert {p.exercise.origin for p in plan.generated} == {ExerciseOrigin.AI_GENERATED}
    for proposal in plan.generated:
        assert "validation requise" in proposal.provenance.reason
        assert proposal.provenance.source_id is None
        assert proposal.provenance.page is None


def test_generated_exercises_follow_the_language_of_the_material(
    world: World, chat: RecordingChat
) -> None:
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    world.db.commit()
    plan = propose(world, items=6, language="fr").plans[0]
    assert all(p.exercise.language == "fr" for p in plan.generated)
    assert "Language: fr" in chat.requests[0].user


def test_approving_nothing_is_a_no_op(world: World) -> None:
    assert (
        adaptive_service.approve_exercises(
            world.db, school_id=world.school_id, exercise_ids=[]
        )
        == []
    )
    assert (
        adaptive_service.approve_exercises(
            world.db, school_id=world.school_id, exercise_ids=[uuid.uuid4()]
        )
        == []
    )


def test_ensure_printable_accepts_approved_and_textbook_items(world: World) -> None:
    textbook = world.db.query(Exercise).first()
    assert textbook is not None
    adaptive_service.ensure_printable([textbook])

    approved = Exercise(
        id=uuid.uuid4(),
        school_id=world.school_id,
        subject_id=world.subject_id,
        type=textbook.type,
        origin=ExerciseOrigin.AI_GENERATED,
        language="fr",
        statement="Un item genere puis valide par l'enseignant.",
        difficulty=2,
        approved_at=datetime.now(UTC),
    )
    adaptive_service.ensure_printable([textbook, approved])


def test_a_shared_client_keeps_one_audit_trail(world: World, chat: RecordingChat) -> None:
    """A class batch shares one `AiClient`, so the audit rows for the whole
    export land in one place."""
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    snapshot(world, student_uid="7B_02", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    world.db.commit()
    client = AiClient()
    adaptive_service.propose_adaptive(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        student_ids=[world.student("7B_01"), world.student("7B_02")],
        items_per_student=6,
        allow_generation=True,
        language="fr",
        ai=client,
    )
    # One call, not two. Both students' plans are gathered before anything is
    # sent, so a class costs a call per chunk of plans rather than a call per
    # child — which is the whole point of batching, and is also what makes
    # "one client, one audit trail" easy to see rather than merely true.
    assert len(client.records) == 1
    assert all(r.purpose == "adaptive_generate_batch" for r in client.records)
    assert all(r.prompt_name == "generate_exercises_batch" for r in client.records)
