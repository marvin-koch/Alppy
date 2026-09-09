"""Regression tests for the F4 review findings.

One test (or one table) per finding, named after what it protects rather than
after the function it calls. Each of these failed before the fix; if one starts
passing for the wrong reason, the comment says what it was actually watching.

Findings covered: F1 (client/server contract for the batch), F2 (the print gate
is wired), F3 (approval is a server fact), F4 (language follows the source),
F5 (failures are reported and the PII gate no longer trips on textbook names),
F6 (the answer key), F7 (the generated-item schema), plus the two requirements
that had no implementation at all: R6 (edit / regenerate / discard) and R7
(group sheets).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError
from test_retrieval import ROSTER, World, build_world, snapshot

from alppy.ai.base import ChatRequest, ChatResponse
from alppy.ai.client import AiClient
from alppy.ai.providers import EchoChatProvider
from alppy.ai.scrub import PiiLeakError
from alppy.models import Exercise, ModelCall
from alppy.models.enums import ExerciseOrigin, ExerciseType, MasteryBand
from alppy.services import adaptive_service, retrieval
from alppy.services.approval import (
    UnapprovedExerciseError,
    approve_exercises,
    discard_exercises,
    ensure_printable,
)
from alppy.sheets.layout import MAX_OPTIONS


@pytest.fixture
def world() -> World:
    return build_world()


class ScriptedChat:
    """Returns whatever JSON the test hands it, once per call."""

    name = "scripted"
    grounded = True

    def __init__(self, *payloads: Any) -> None:
        self.payloads = list(payloads)
        self.requests: list[ChatRequest] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        payload = self.payloads.pop(0) if self.payloads else {"exercises": []}
        if isinstance(payload, Exception):
            raise payload
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return ChatResponse(text=text, input_tokens=10, output_tokens=20, model="scripted")


def use_chat(monkeypatch: pytest.MonkeyPatch, provider: Any) -> None:
    monkeypatch.setattr("alppy.ai.client.build_chat_provider", lambda: provider)


def gap(world: World, uid: str = "7B_01", code: str = "MSN 31.3") -> None:
    snapshot(world, student_uid=uid, competency_code=code, score=0.45, band=MasteryBand.FADING)
    world.db.commit()


def propose(world: World, **kwargs: Any) -> Any:
    params: dict[str, Any] = {
        "school_id": world.school_id,
        "class_id": world.class_id,
        "subject_id": world.subject_id,
        "student_ids": [world.student("7B_01")],
        "items_per_student": 6,
        "allow_generation": True,
    }
    params.update(kwargs)
    return adaptive_service.propose_adaptive(world.db, **params)


# ==========================================================================
# F7 · the generated-item schema
# ==========================================================================
GOOD_MCQ = {
    "type": "mcq",
    "statement": "Combien font 12 × 4 ?",
    "options": ["48", "44", "36", "16"],
    "answer_index": 0,
    "difficulty": 3,
}

#: Every row is something that reached paper before the schema was strict.
BAD_ITEMS: list[tuple[str, dict[str, Any]]] = [
    ("open is not auto-gradable", {"type": "open", "statement": "Explique le théorème."}),
    ("unknown type", {"type": "essay", "statement": "Une dissertation sur les fractions."}),
    ("no type at all", {"statement": "Combien font 6 × 7 ?", "options": ["42", "40"], "answer_index": 0}),
    ("unknown extra field", {**GOOD_MCQ, "surprise": "boom"}),
    ("two identical options", {**GOOD_MCQ, "options": ["49", "49", "48"], "answer_index": 0}),
    ("a blank option", {**GOOD_MCQ, "options": ["48", ""], "answer_index": 0}),
    ("more options than bubbles", {**GOOD_MCQ, "options": [str(i) for i in range(MAX_OPTIONS + 1)], "answer_index": 0}),
    ("only one option", {**GOOD_MCQ, "options": ["48"], "answer_index": 0}),
    ("answer_index out of range", {**GOOD_MCQ, "answer_index": 9}),
    ("answer_index missing", {k: v for k, v in GOOD_MCQ.items() if k != "answer_index"}),
    ("statement too short", {**GOOD_MCQ, "statement": "x"}),
    ("true/false with no truth value", {"type": "true_false", "statement": "Un triangle a trois côtés."}),
    ("true/false with a string truth value", {"type": "true_false", "statement": "Un carré a quatre côtés.", "answer_bool": "oui"}),
    ("true/false carrying options", {"type": "true_false", "statement": "Un carré a quatre côtés.", "answer_bool": True, "options": ["V", "F"]}),
]


@pytest.mark.parametrize("label,item", BAD_ITEMS, ids=[label for label, _ in BAD_ITEMS])
def test_the_schema_rejects_items_that_could_not_be_printed_or_graded(
    label: str, item: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        adaptive_service.GeneratedExerciseIn.model_validate(item)


def test_the_schema_accepts_a_well_formed_item_of_each_kind() -> None:
    mcq = adaptive_service.GeneratedExerciseIn.model_validate(GOOD_MCQ)
    assert mcq.type == "mcq" and mcq.answer_index == 0 and mcq.answer_bool is None

    tf = adaptive_service.GeneratedExerciseIn.model_validate(
        {"type": "true_false", "statement": "Un carré a quatre côtés.", "answer_bool": True}
    )
    assert tf.answer_bool is True and tf.options is None and tf.answer_index is None


def test_a_bad_item_does_not_poison_the_good_ones_beside_it(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One malformed exercise must cost one slot, not the whole sheet."""
    chat = ScriptedChat(
        {
            "exercises": [
                GOOD_MCQ,
                {**GOOD_MCQ, "statement": "Combien font 5 × 5 ?", "answer_index": 99},
                {**GOOD_MCQ, "statement": "Combien font 7 × 3 ?", "type": "open"},
            ]
        }
    )
    use_chat(monkeypatch, chat)
    gap(world)
    plan = propose(world, items_per_student=4).plans[0]
    statements = [p.exercise.statement for p in plan.generated]
    assert "Combien font 12 × 4 ?" in statements
    assert not any("5 × 5" in s or "7 × 3" in s for s in statements)


def test_more_options_than_bubbles_never_becomes_a_row(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug this protects: six options printed, four bubbles drawn, the key
    on an option with no hole to fill — every child marked wrong."""
    use_chat(
        monkeypatch,
        ScriptedChat(
            {"exercises": [{**GOOD_MCQ, "options": ["a", "b", "c", "d", "e", "f"], "answer_index": 5}]}
        ),
    )
    gap(world)
    plan = propose(world, items_per_student=4).plans[0]
    assert plan.generated == []
    for row in world.db.query(Exercise).filter(Exercise.origin == ExerciseOrigin.AI_GENERATED):
        assert row.options is None or len(row.options) <= MAX_OPTIONS


# ==========================================================================
# F4 · the language follows the source material, never the UI locale
# ==========================================================================
def test_the_sheet_language_is_read_off_the_corpus_not_the_teacher_locale(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A teacher reading Alppy in English whose class works in French must not
    be handed English exercises."""
    use_chat(monkeypatch, EchoChatProvider())
    gap(world)
    response = propose(world, language=None, fallback_language="en")
    assert response.language == "fr"
    assert all(p.exercise.language == "fr" for plan in response.plans for p in plan.generated)


def test_source_language_prefers_the_modal_textbook_language(world: World) -> None:
    resolved = adaptive_service.source_language(
        world.db, school_id=world.school_id, subject_id=world.subject_id, fallback="en"
    )
    languages = {
        row.language
        for row in world.db.query(Exercise).filter(
            Exercise.subject_id == world.subject_id,
            Exercise.origin == ExerciseOrigin.TEXTBOOK,
        )
    }
    assert resolved in languages
    assert resolved != "en" or "en" in languages


def test_an_empty_corpus_falls_back_to_the_teachers_locale(world: World) -> None:
    empty_subject = uuid.uuid4()
    assert (
        adaptive_service.source_language(
            world.db, school_id=world.school_id, subject_id=empty_subject, fallback="de"
        )
        == "de"
    )


def test_the_generated_row_is_labelled_with_the_language_it_is_written_in(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Exercise.language` picks the printed true/false glyphs (V/F · R/F · T/F),
    so a wrong label prints the wrong letters beside the right holes."""
    use_chat(monkeypatch, EchoChatProvider())
    gap(world)
    plan = propose(world, language="de", items_per_student=6).plans[0]
    assert plan.generated
    for proposal in plan.generated:
        assert proposal.exercise.language == "de"
        # The offline provider answers in the language it was asked for, so a
        # regression in the language path shows up in the text as well.
        assert "Berechne" in proposal.exercise.statement


# ==========================================================================
# F5 · failures are reported, and textbook names no longer kill generation
# ==========================================================================
def test_a_roster_name_in_a_textbook_statement_does_not_kill_generation(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The style examples are the class's own textbook prose, and Swiss textbook
    prose is full of the same first names as the class. Redact, do not abort."""
    first, last = ROSTER[0]
    victim = world.db.get(Exercise, world.exercises[next(iter(world.exercises))])
    assert victim is not None
    victim.statement = f"{first} {last} partage une pizza en parts égales entre 5 amis."
    world.db.commit()

    chat = ScriptedChat({"exercises": [GOOD_MCQ]})
    use_chat(monkeypatch, chat)
    gap(world)
    response = propose(world, items_per_student=6)

    assert response.generated_count >= 1
    assert not any(f.reason == "pii_gate" for f in response.failures)
    # Redacted, not merely allowed through: the name never reaches the provider.
    sent = "\n".join(f"{r.system}\n{r.user}" for r in chat.requests)
    assert first not in sent
    assert last not in sent


def test_the_pii_gate_still_fires_on_a_name_the_scrub_did_not_see(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redacting the style examples must not disarm the final assertion."""
    from alppy.ai.scrub import assert_no_pii

    roster = [f"{first} {last}" for first, last in ROSTER]
    assert_no_pii("Calcule 3 × 4.", names=roster)
    with pytest.raises(PiiLeakError):
        assert_no_pii(f"Write exercises for {ROSTER[0][0]} {ROSTER[0][1]}", names=roster)


def test_a_provider_failure_is_reported_rather_than_silently_shortening_a_sheet(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_chat(monkeypatch, ScriptedChat(RuntimeError("provider returned HTTP 502")))
    gap(world)
    response = propose(world, items_per_student=6)

    assert response.generated_count == 0
    assert len(response.failures) == 1
    failure = response.failures[0]
    assert failure.reason == "provider_error"
    assert failure.student_uid == "7B_01"
    assert failure.requested > 0 and failure.produced == 0


def test_an_unparsable_response_is_reported_and_writes_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_chat(monkeypatch, ScriptedChat("I'm sorry, I can't do that."))
    before = world.db.query(Exercise).filter(
        Exercise.origin == ExerciseOrigin.AI_GENERATED
    ).count()
    gap(world)
    response = propose(world, items_per_student=6)

    assert [f.reason for f in response.failures] == ["unparsable_response"]
    after = world.db.query(Exercise).filter(
        Exercise.origin == ExerciseOrigin.AI_GENERATED
    ).count()
    assert after == before


def test_one_students_failure_does_not_cost_the_rest_of_the_batch(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The provider falls over on the second student; the other two still get a
    full sheet, and the failed one is named."""
    use_chat(
        monkeypatch,
        ScriptedChat(
            {"exercises": [GOOD_MCQ]},
            RuntimeError("provider fell over mid-batch"),
            {"exercises": [{**GOOD_MCQ, "statement": "Combien font 9 × 9 ?"}]},
        ),
    )
    for uid in ("7B_01", "7B_02", "7B_03"):
        snapshot(
            world, student_uid=uid, competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING
        )
    world.db.commit()

    response = propose(
        world,
        student_ids=[world.student(u) for u in ("7B_01", "7B_02", "7B_03")],
        items_per_student=6,
    )
    assert len(response.plans) == 3
    assert response.generated_count == 2
    assert [f.student_uid for f in response.failures if f.reason == "provider_error"] == ["7B_02"]


def test_a_blocked_prompt_is_written_to_the_audit_log(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gate rejection is exactly the event an audit trail exists to record.
    It used to raise before the CallRecord was built, leaving a silent gap."""

    class Leaky:
        name = "leaky"
        grounded = True

        def complete(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
            raise AssertionError("the gate must fire before the provider is reached")

    use_chat(monkeypatch, Leaky())
    # Force a leak: a competency label carrying a roster name reaches the prompt
    # untouched, because only the style examples are scrubbed.
    monkeypatch.setattr(
        adaptive_service,
        "_competency_labels",
        lambda *a, **k: {uuid.uuid4(): f"{ROSTER[0][0]} {ROSTER[0][1]}"},
    )
    gap(world)
    response = propose(world, items_per_student=6)

    assert [f.reason for f in response.failures] == ["pii_gate"]
    rows = list(
        world.db.query(ModelCall).filter(
            ModelCall.purpose == "adaptive_generate", ModelCall.ok.is_(False)
        )
    )
    assert rows, "a blocked call must still leave an audit row"
    assert rows[0].error == "PiiLeakError"
    blob = " ".join(str(getattr(rows[0], c)) for c in ("provider", "model", "purpose", "error"))
    for first, last in ROSTER:
        assert first not in blob and last not in blob


def test_an_incomplete_response_reports_how_short_it_came(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_chat(monkeypatch, ScriptedChat({"exercises": [GOOD_MCQ]}))
    gap(world)
    response = propose(world, items_per_student=8)
    incomplete = [f for f in response.failures if f.reason == "incomplete"]
    assert incomplete
    assert incomplete[0].produced < incomplete[0].requested


# ==========================================================================
# F2 / F3 · the print gate is wired, and approval is a server fact
# ==========================================================================
def test_a_batch_cannot_be_built_out_of_unapproved_items(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_chat(monkeypatch, ScriptedChat({"exercises": [GOOD_MCQ]}))
    gap(world)
    plan = propose(world, items_per_student=6).plans[0]
    rows = [world.db.get(Exercise, p.exercise.id) for p in plan.generated]
    assert rows and all(r is not None for r in rows)

    with pytest.raises(UnapprovedExerciseError) as excinfo:
        ensure_printable([r for r in rows if r is not None])
    # The error names the offenders: a teacher needs to know which items are
    # waiting, not merely that something is.
    assert excinfo.value.exercise_ids


def test_approval_is_what_unlocks_printing_and_only_touches_generated_rows(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_chat(monkeypatch, ScriptedChat({"exercises": [GOOD_MCQ]}))
    gap(world)
    plan = propose(world, items_per_student=6).plans[0]
    generated = [p.exercise.id for p in plan.generated]
    textbook = plan.retrieved[0].exercise.id

    approved = approve_exercises(
        world.db, school_id=world.school_id, exercise_ids=[*generated, textbook]
    )
    world.db.commit()
    # The textbook exercise was asked for and deliberately not stamped.
    assert sorted(approved) == sorted(generated)
    row = world.db.get(Exercise, textbook)
    assert row is not None and row.approved_at is None

    ensure_printable([world.db.get(Exercise, i) for i in generated])  # type: ignore[arg-type]


def test_approval_from_another_school_does_nothing(world: World) -> None:
    other = build_world()
    victim = next(iter(other.exercises.values()))
    assert (
        approve_exercises(world.db, school_id=world.school_id, exercise_ids=[victim]) == []
    )


# ==========================================================================
# R6 · edit, regenerate, discard
# ==========================================================================
def test_a_regenerated_item_replaces_the_one_it_came_from(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_chat(
        monkeypatch,
        ScriptedChat(
            {"exercises": [GOOD_MCQ]},
            {"exercises": [{**GOOD_MCQ, "statement": "Combien font 11 × 11 ?"}]},
        ),
    )
    gap(world)
    plan = propose(world, items_per_student=6).plans[0]
    original = plan.generated[0].exercise.id

    replacement = adaptive_service.regenerate_exercise(
        world.db, school_id=world.school_id, exercise_id=original
    )

    assert replacement.exercise.id != original
    assert replacement.exercise.statement == "Combien font 11 × 11 ?"
    # Replaces, never appends: the old row is discarded in the same transaction.
    old = world.db.get(Exercise, original)
    assert old is not None and old.discarded_at is not None
    assert old.approved_at is None
    # And the replacement still needs approving.
    fresh = world.db.get(Exercise, replacement.exercise.id)
    assert fresh is not None and fresh.approved_at is None


def test_a_discarded_item_is_never_proposed_again(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_chat(monkeypatch, ScriptedChat({"exercises": [GOOD_MCQ]}, {"exercises": [GOOD_MCQ]}))
    gap(world)
    first = propose(world, items_per_student=6).plans[0]
    rejected = first.generated[0].exercise.id
    rejected_statement = first.generated[0].exercise.statement

    discard_exercises(world.db, school_id=world.school_id, exercise_ids=[rejected])
    world.db.commit()

    second = propose(world, items_per_student=6).plans[0]
    offered = [p.exercise.statement for p in [*second.retrieved, *second.generated]]
    assert rejected_statement not in offered


def test_a_discarded_item_is_not_retrievable_even_once_approved(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_chat(monkeypatch, ScriptedChat({"exercises": [GOOD_MCQ]}))
    gap(world)
    plan = propose(world, items_per_student=6).plans[0]
    target = plan.generated[0].exercise.id

    approve_exercises(world.db, school_id=world.school_id, exercise_ids=[target])
    discard_exercises(world.db, school_id=world.school_id, exercise_ids=[target])
    world.db.commit()

    row = world.db.get(Exercise, target)
    assert row is not None and row.approved_at is None  # discarding un-approves

    candidates = retrieval.gather_candidates(
        world.db,
        school_id=world.school_id,
        subject_id=world.subject_id,
        language="fr",
        include_unapproved=True,
    )
    assert target not in {c.exercise.id for c in candidates}


def test_regenerating_something_that_is_not_generated_is_refused(world: World) -> None:
    textbook = next(iter(world.exercises.values()))
    with pytest.raises(adaptive_service.AdaptiveGenerationError):
        adaptive_service.regenerate_exercise(
            world.db, school_id=world.school_id, exercise_id=textbook
        )


def test_a_failed_regeneration_leaves_the_original_alone(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Throwing away the teacher's only version and handing back nothing is
    worse than a bad item."""
    use_chat(
        monkeypatch,
        ScriptedChat({"exercises": [GOOD_MCQ]}, RuntimeError("provider is down")),
    )
    gap(world)
    plan = propose(world, items_per_student=6).plans[0]
    original = plan.generated[0].exercise.id

    with pytest.raises(adaptive_service.AdaptiveGenerationError):
        adaptive_service.regenerate_exercise(
            world.db, school_id=world.school_id, exercise_id=original
        )
    row = world.db.get(Exercise, original)
    assert row is not None and row.discarded_at is None


# ==========================================================================
# R7 · the group sheet
# ==========================================================================
def test_a_group_sheet_targets_the_union_and_says_who_each_item_is_for(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_chat(monkeypatch, EchoChatProvider())
    # Two students share one gap; the third has a different one.
    snapshot(world, student_uid="7B_01", competency_code="MSN 31.3", score=0.45, band=MasteryBand.FADING)
    snapshot(world, student_uid="7B_02", competency_code="MSN 31.3", score=0.50, band=MasteryBand.FADING)
    snapshot(world, student_uid="7B_03", competency_code="MSN 32.1", score=0.66, band=MasteryBand.WEAK)
    world.db.commit()

    response = propose(
        world,
        student_ids=[world.student(u) for u in ("7B_01", "7B_02", "7B_03")],
        items_per_student=6,
        group=True,
    )
    assert response.group is not None
    group = response.group
    assert group.student_uids == ["7B_01", "7B_02", "7B_03"]

    shared = world.competencies["MSN 31.3"]
    # The competency two of the three need is targeted ahead of the lone one.
    assert group.targeted_competency_ids[0] == shared

    # Every child still gets their own plan, so the batch export is unchanged
    # and every page still carries its own UID grid.
    assert [p.student_uid for p in response.plans] == ["7B_01", "7B_02", "7B_03"]
    shared_ids = {p.exercise.id for p in [*group.retrieved, *group.generated]}
    for plan in response.plans:
        assert {p.exercise.id for p in [*plan.retrieved, *plan.generated]} == shared_ids

    # And the UI can say which student each item is for.
    assert group.items
    assert all(item.for_student_uids for item in group.items)
    attributed = {u for item in group.items for u in item.for_student_uids}
    assert attributed <= {"7B_01", "7B_02", "7B_03"}


def test_a_group_of_one_still_works(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    use_chat(monkeypatch, EchoChatProvider())
    gap(world)
    response = propose(world, items_per_student=4, group=True)
    assert response.group is not None
    assert response.group.student_uids == ["7B_01"]
    assert len(response.plans) == 1


# ==========================================================================
# F6 · the answer key travels with the batch
# ==========================================================================
def test_the_batch_renderer_produces_both_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    """DESIGN.md §9: always two sheets. A differentiated pile is the one case a
    teacher cannot correct from memory — no two children answered the same
    questions."""
    from alppy.sheets import render

    world = build_world()
    student = world.db.get(Exercise, next(iter(world.exercises.values())))
    assert student is not None

    calls: list[str] = []

    def fake_pdf(html: str, **_: Any) -> bytes:
        calls.append("key" if "sheet-key-answer" in html or "is_key" in html else "blank")
        return b"%PDF-1.4 fake"

    stored: dict[str, bytes] = {}

    def fake_store(payload: bytes, key: str) -> str:
        stored[key] = payload
        return key

    monkeypatch.setattr(render, "html_to_pdf", fake_pdf)
    monkeypatch.setattr(render, "store_pdf", fake_store)

    sheet = _adaptive_sheet(world)
    blank_key, answer_key = render.render_adaptive_batch(world.db, sheet_id=sheet.id)

    assert blank_key != answer_key
    assert "adaptive-batch.pdf" in blank_key
    assert "answer-key" in answer_key
    assert sheet.blank_pdf_key == blank_key
    assert sheet.answer_key_pdf_key == answer_key
    assert len(stored) == 2


def test_the_render_path_refuses_an_unapproved_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """The last door. A sheet can be built before the gate existed, or an item
    un-approved after the sheet was built."""
    from alppy.sheets import render

    world = build_world()
    sheet = _adaptive_sheet(world)
    # Turn one of its items into an unapproved generated exercise.
    victim = sheet.items[0].exercise
    victim.origin = ExerciseOrigin.AI_GENERATED
    victim.approved_at = None
    world.db.flush()

    monkeypatch.setattr(render, "html_to_pdf", lambda html, **_: b"%PDF")
    monkeypatch.setattr(render, "store_pdf", lambda payload, key: key)

    with pytest.raises(render.SheetRenderError) as excinfo:
        render.render_adaptive_batch(world.db, sheet_id=sheet.id)
    assert "not approved" in str(excinfo.value)

    victim.approved_at = datetime.now(UTC)
    world.db.flush()
    blank_key, answer_key = render.render_adaptive_batch(world.db, sheet_id=sheet.id)
    assert blank_key and answer_key


def _adaptive_sheet(world: World) -> Any:
    """A minimal differentiated sheet: two students, two items each."""
    from alppy.models import Sheet, SheetInstance, SheetItem
    from alppy.models.enums import SheetTarget
    from alppy.services.chapter_service import ensure_unfiled_chapter
    from alppy.sheets.layout import LAYOUT_VERSION

    ids = list(world.exercises.values())[:2]
    sheet = Sheet(
        id=uuid.uuid4(),
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_id=ensure_unfiled_chapter(
            world.db, school_id=world.school_id, subject_id=world.subject_id
        ).id,
        title="Batch",
        target=SheetTarget.STUDENT,
        language="fr",
        layout_version=LAYOUT_VERSION,
    )
    world.db.add(sheet)
    world.db.flush()
    for position, exercise_id in enumerate(ids):
        world.db.add(
            SheetItem(
                id=uuid.uuid4(),
                school_id=world.school_id,
                sheet_id=sheet.id,
                exercise_id=exercise_id,
                position=position,
            )
        )
    for uid in ("7B_01", "7B_02"):
        world.db.add(
            SheetInstance(
                id=uuid.uuid4(),
                school_id=world.school_id,
                sheet_id=sheet.id,
                student_id=world.student(uid),
                student_uid=uid,
            )
        )
    world.db.flush()
    world.db.refresh(sheet)
    return sheet


# ==========================================================================
# The offline provider is a faithful stand-in
# ==========================================================================
def test_the_offline_provider_answers_in_the_language_it_was_asked_for() -> None:
    """It used to test for `language: de` while the prompt emits `Language: de`,
    so every offline run came back French and no test could see the difference."""
    provider = EchoChatProvider()
    for language, marker in (("fr", "Calcule"), ("de", "Berechne"), ("en", "Work out")):
        response = provider.complete(
            ChatRequest(
                system="",
                user=f"Number of exercises: 2\nLanguage: {language}\nDifficulty: 3",
                max_tokens=512,
                temperature=0.4,
                purpose="adaptive_generate",
            )
        )
        payload = json.loads(response.text)
        assert len(payload["exercises"]) == 2
        assert all(marker in item["statement"] for item in payload["exercises"])
        assert all(item["difficulty"] == 3 for item in payload["exercises"])


def test_the_offline_provider_moves_the_correct_answer_around() -> None:
    """Every generated key used to be option A: a column of A bubbles a child
    could fill without doing any arithmetic."""
    provider = EchoChatProvider()
    seen: set[int] = set()
    for n in range(24):
        response = provider.complete(
            ChatRequest(
                system="",
                user=f"Number of exercises: 3\nLanguage: fr\nDifficulty: 2\nSeed {n}",
                max_tokens=512,
                temperature=0.4,
                purpose="adaptive_generate",
            )
        )
        for item in json.loads(response.text)["exercises"]:
            seen.add(int(item["answer_index"]))
            # The key must still point at the right number.
            a, b = (int(x) for x in item["explanation"].split(" = ")[0].split(" × "))
            assert item["options"][item["answer_index"]] == str(a * b)
    assert len(seen) > 1, f"the answer never moved: always option {seen}"


def test_a_generated_exercise_never_claims_more_bubbles_than_the_grid_draws(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Exercise.option_count` and `pagination.Item.option_count` must agree, or
    the answer key addresses a bubble that is not on the paper."""
    from alppy.sheets.pagination import Item

    use_chat(monkeypatch, EchoChatProvider())
    gap(world)
    plan = propose(world, items_per_student=6).plans[0]
    for proposal in plan.generated:
        row = world.db.get(Exercise, proposal.exercise.id)
        assert row is not None
        item = Item(
            key=str(row.id),
            type=ExerciseType(row.type),
            statement=row.statement,
            options=tuple(row.options or ()),
            answer_index=row.answer_index,
            language=row.language,
        )
        assert row.option_count == item.option_count <= MAX_OPTIONS
        assert row.answer_index is not None
        assert row.answer_index < item.option_count


def test_the_client_records_a_failed_call_before_re_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Broken:
        name = "broken"
        grounded = True

        def complete(self, request: ChatRequest) -> ChatResponse:
            raise RuntimeError("boom")

    use_chat(monkeypatch, Broken())
    client = AiClient()
    from alppy.ai.client import load_prompt

    with pytest.raises(RuntimeError):
        client.complete(
            prompt=load_prompt("generate_exercises"),
            purpose="adaptive_generate",
            values={
                "language": "fr",
                "competency_labels": "—",
                "difficulty": 3,
                "count": 2,
                "max_options": MAX_OPTIONS,
                "style_examples": "-",
                "student_ref": "7B_01",
            },
        )
    assert len(client.records) == 1
    assert client.records[0].ok is False
    assert client.records[0].prompt_sha256
