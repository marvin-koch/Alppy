"""Generation for several plans in one call, and the isolation that survives it.

Batching is the one change in this feature that trades against a load-bearing
invariant. I-adaptive-09 says a plan's failure is its own; a shared call makes
that untrue by construction, so it is bought back two ways — per-plan for a
content failure, and a split retry for a transport one. Most of this file is
about those two, and about the offline provider that has to answer a batched
prompt for CI to stay deterministic.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_adaptive_fixes import GOOD_MCQ, ScriptedChat, propose, use_chat
from test_retrieval import World, build_world, snapshot

from alppy.ai.base import ChatRequest, ChatResponse, ChatTruncatedError
from alppy.ai.providers import EchoChatProvider
from alppy.models.enums import MasteryBand
from alppy.services import adaptive_service


@pytest.fixture
def world() -> World:
    return build_world()


def _batch(*plans: dict[str, Any]) -> dict[str, Any]:
    return {"plans": list(plans)}


def _item(statement: str) -> dict[str, Any]:
    return {**GOOD_MCQ, "statement": statement}


def _gaps_for(world: World, uids: list[str]) -> None:
    for uid in uids:
        snapshot(
            world,
            student_uid=uid,
            competency_code="MSN 31.3",
            score=0.45,
            band=MasteryBand.FADING,
        )
    world.db.commit()


# --------------------------------------------------------------------------
# One call, several plans
# --------------------------------------------------------------------------
def test_a_class_costs_one_call_rather_than_one_call_per_child(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of the change. Three students used to be three requests, each
    repeating the same system block and the same style examples."""
    chat = ScriptedChat(
        _batch(
            {"plan_id": "P1", "exercises": [_item("Combien font 2 × 8 ?")]},
            {"plan_id": "P2", "exercises": [_item("Combien font 3 × 8 ?")]},
            {"plan_id": "P3", "exercises": [_item("Combien font 4 × 8 ?")]},
        )
    )
    use_chat(monkeypatch, chat)
    _gaps_for(world, ["7B_01", "7B_02", "7B_03"])

    response = propose(
        world,
        student_ids=[world.student(u) for u in ("7B_01", "7B_02", "7B_03")],
        items_per_student=6,
    )
    assert len(chat.requests) == 1
    assert chat.requests[0].purpose == "adaptive_generate_batch"
    assert response.generated_count == 3


def test_each_plan_asks_for_its_own_shortfall_not_the_sheet_length(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retrieval fills what it can first (I-adaptive-01), so every plan asks for
    a different number. A single `count` in the prompt would be wrong for all
    but one of them."""
    chat = ScriptedChat(_batch())
    use_chat(monkeypatch, chat)
    _gaps_for(world, ["7B_01", "7B_02"])
    propose(
        world,
        student_ids=[world.student(u) for u in ("7B_01", "7B_02")],
        items_per_student=6,
    )

    sent = chat.requests[0].user
    # One plan line per plan, each carrying its own count.
    assert sent.count("| count:") == 2


def test_the_competency_legend_is_written_once_and_referenced(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The saving that is actually worth having: in per-student mode two dozen
    plans usually share the same handful of competencies."""
    chat = ScriptedChat(_batch())
    use_chat(monkeypatch, chat)
    _gaps_for(world, ["7B_01", "7B_02", "7B_03"])
    propose(
        world,
        student_ids=[world.student(u) for u in ("7B_01", "7B_02", "7B_03")],
        items_per_student=6,
    )

    sent = chat.requests[0].user
    assert "C1 = " in sent
    # Three plans, one legend entry between them.
    assert sent.count("C1 = ") == 1
    assert sent.count("[P") == 3


def test_no_student_reference_reaches_the_provider_in_a_batched_call(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan ids are opaque — P1, not 7B_15. Shorter, and it means the batched
    path sends no student identifier at all, not even a pseudonymous one."""
    chat = ScriptedChat(_batch())
    use_chat(monkeypatch, chat)
    _gaps_for(world, ["7B_01", "7B_02"])
    propose(
        world,
        student_ids=[world.student(u) for u in ("7B_01", "7B_02")],
        items_per_student=6,
    )

    sent = f"{chat.requests[0].system}\n{chat.requests[0].user}"
    assert "7B_01" not in sent and "7B_02" not in sent
    assert "[P1]" in sent


# --------------------------------------------------------------------------
# Failure isolation — the invariant batching endangers
# --------------------------------------------------------------------------
def test_a_plan_missing_from_the_response_is_reported_and_the_others_survive(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A content failure is isolated by plan id: the model simply did not answer
    for P2. This is I-adaptive-08's per-item drop rule, one level up."""
    use_chat(
        monkeypatch,
        ScriptedChat(
            _batch(
                {"plan_id": "P1", "exercises": [_item("Combien font 2 × 8 ?")]},
                {"plan_id": "P3", "exercises": [_item("Combien font 4 × 8 ?")]},
            )
        ),
    )
    _gaps_for(world, ["7B_01", "7B_02", "7B_03"])

    response = propose(
        world,
        student_ids=[world.student(u) for u in ("7B_01", "7B_02", "7B_03")],
        items_per_student=6,
    )
    assert response.generated_count == 2
    # 7B_02's plan produced nothing at all; the other two produced an item each.
    empty = [f.student_uid for f in response.failures if f.produced == 0]
    assert empty == ["7B_02"]
    assert [len(p.generated) for p in response.plans] == [1, 0, 1]


def test_a_failed_batch_is_split_into_one_call_per_plan_rather_than_shortening_everyone(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The transport case. A provider error inside one shared call would cost
    every plan in it, which is precisely what I-adaptive-09 forbids — so the
    chunk is retried once, split."""
    chat = ScriptedChat(
        RuntimeError("the batched call fell over"),
        {"exercises": [_item("Combien font 2 × 8 ?")]},
        {"exercises": [_item("Combien font 3 × 8 ?")]},
    )
    use_chat(monkeypatch, chat)
    _gaps_for(world, ["7B_01", "7B_02"])

    response = propose(
        world,
        student_ids=[world.student(u) for u in ("7B_01", "7B_02")],
        items_per_student=6,
    )
    # One batched attempt, then one call per plan.
    assert len(chat.requests) == 3
    assert chat.requests[0].purpose == "adaptive_generate_batch"
    assert all(r.purpose == "adaptive_generate" for r in chat.requests[1:])
    assert response.generated_count == 2
    # The split repaired the transport failure. What remains is only the honest
    # "the model returned fewer than were asked for" — never a provider error.
    assert {f.reason for f in response.failures} <= {"incomplete"}


def test_a_truncated_batch_is_named_as_truncated_not_as_an_unusable_answer(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cut-off answer looks exactly like an unparsable one from outside, and
    the teacher would be told the model misbehaved when the cause is a
    configured limit they could raise."""

    class _Truncating:
        name = "truncating"
        grounded = True

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, request: ChatRequest) -> ChatResponse:
            self.calls += 1
            raise ChatTruncatedError("cut off at the output cap")

    use_chat(monkeypatch, _Truncating())
    _gaps_for(world, ["7B_01", "7B_02"])

    response = propose(
        world,
        student_ids=[world.student(u) for u in ("7B_01", "7B_02")],
        items_per_student=6,
    )
    assert {f.reason for f in response.failures} == {"truncated"}
    assert len(response.failures) == 2, "each plan is told, not just the first"


def test_a_persistent_failure_still_names_every_plan_it_cost(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The split retry is one round, not a loop. When it fails too, the report
    is per plan — the same report the single-call path always produced."""
    use_chat(
        monkeypatch,
        ScriptedChat(
            RuntimeError("batch"),
            RuntimeError("still down"),
            RuntimeError("still down"),
        ),
    )
    _gaps_for(world, ["7B_01", "7B_02"])

    response = propose(
        world,
        student_ids=[world.student(u) for u in ("7B_01", "7B_02")],
        items_per_student=6,
    )
    assert sorted(f.student_uid for f in response.failures) == ["7B_01", "7B_02"]
    assert {f.reason for f in response.failures} == {"provider_error"}


def test_a_bad_item_in_one_plan_does_not_cost_the_good_items_beside_it(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_chat(
        monkeypatch,
        ScriptedChat(
            _batch(
                {
                    "plan_id": "P1",
                    "exercises": [
                        _item("Combien font 2 × 8 ?"),
                        {**GOOD_MCQ, "statement": "Combien font 5 × 5 ?", "answer_index": 99},
                    ],
                },
                {"plan_id": "P2", "exercises": [_item("Combien font 9 × 9 ?")]},
            )
        ),
    )
    _gaps_for(world, ["7B_01", "7B_02"])
    plan = propose(
        world,
        student_ids=[world.student(u) for u in ("7B_01", "7B_02")],
        items_per_student=6,
    ).plans[0]
    statements = [p.exercise.statement for p in plan.generated]
    assert "Combien font 2 × 8 ?" in statements
    assert not any("5 × 5" in s for s in statements)


# --------------------------------------------------------------------------
# The shared duplicate check
# --------------------------------------------------------------------------
def test_two_plans_in_one_run_never_get_the_same_statement(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`seen` used to be rebuilt per call, so two plans in one proposal could
    each be handed the identical exercise. The teacher reads it twice and has no
    way to tell which sheet it belongs to."""
    use_chat(
        monkeypatch,
        ScriptedChat(
            _batch(
                {"plan_id": "P1", "exercises": [_item("Combien font 2 × 8 ?")]},
                {"plan_id": "P2", "exercises": [_item("Combien font 2 × 8 ?")]},
            )
        ),
    )
    _gaps_for(world, ["7B_01", "7B_02"])

    response = propose(
        world,
        student_ids=[world.student(u) for u in ("7B_01", "7B_02")],
        items_per_student=6,
    )
    assert response.generated_count == 1
    # The second plan's copy was dropped as a duplicate, so it produced nothing.
    assert [len(p.generated) for p in response.plans] == [1, 0]
    assert [f.student_uid for f in response.failures if f.produced == 0] == ["7B_02"]


# --------------------------------------------------------------------------
# The offline provider must answer a batched prompt
# --------------------------------------------------------------------------
def test_the_offline_provider_answers_every_plan_in_the_batch_separately() -> None:
    """`_asked_int` is first-match-wins over the whole prompt, which is exactly
    wrong for a request carrying one `count:` per plan. Without a per-line read
    the offline run returns one plan's worth of items for the whole class, and
    the demo comes out empty."""
    user = (
        "Language: fr\n"
        "Max options: 4\n"
        "Plans:\n"
        "[P1] competencies: C1 | difficulty: 3 | count: 2\n"
        "[P2] competencies: C2 | difficulty: 4 | count: 3\n"
    )
    response = EchoChatProvider().complete(
        ChatRequest(system="s", user=user, purpose="adaptive_generate_batch")
    )
    plans = json.loads(response.text)["plans"]
    assert [p["plan_id"] for p in plans] == ["P1", "P2"]
    assert [len(p["exercises"]) for p in plans] == [2, 3]
    assert plans[1]["exercises"][0]["difficulty"] == 4


def test_the_offline_provider_gives_each_plan_its_own_statements() -> None:
    """The seed folds in the plan id. Without it every plan in a batch gets
    byte-identical items, the shared duplicate check drops all but the first,
    and it presents as a bug in the dedupe rather than in the stand-in."""
    user = (
        "Language: fr\nMax options: 4\nPlans:\n"
        "[P1] competencies: C1 | difficulty: 3 | count: 2\n"
        "[P2] competencies: C1 | difficulty: 3 | count: 2\n"
    )
    plans = json.loads(
        EchoChatProvider()
        .complete(ChatRequest(system="s", user=user, purpose="adaptive_generate_batch"))
        .text
    )["plans"]
    first = {e["statement"] for e in plans[0]["exercises"]}
    second = {e["statement"] for e in plans[1]["exercises"]}
    assert not (first & second)


def test_the_offline_provider_still_answers_the_single_plan_prompt() -> None:
    """The old shape is still in use — regeneration is always one item for one
    plan, and it is the split retry's shape too."""
    response = EchoChatProvider().complete(
        ChatRequest(
            system="s",
            user="Language: de\nNumber of exercises: 2\nDifficulty: 4\n",
            purpose="adaptive_generate",
        )
    )
    payload = json.loads(response.text)
    assert len(payload["exercises"]) == 2
    assert "Berechne" in payload["exercises"][0]["statement"]


def test_the_batch_size_bounds_what_one_failure_can_cost() -> None:
    """Not a tuning knob so much as a blast radius: everything in one call
    shares one output budget and one failure."""
    assert adaptive_service.ADAPTIVE_BATCH_MAX_PLANS <= 8
