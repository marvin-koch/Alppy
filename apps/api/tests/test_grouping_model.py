"""A model may revise the partition. It may not be trusted with it.

D33 chose a deterministic rule because a teacher has to be able to state it to a
parent: students with the same principal gap go together, the smallest merge, the
largest splits. This adds a model as an opt-in second opinion, and every test
here is about the first opinion staying in charge — the seed is sent, the answer
is validated against the roster, and anything short of a real partition returns
the deterministic one.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_adaptive_fixes import ScriptedChat, use_chat
from test_retrieval import World, build_world, snapshot

from alppy.ai.base import ChatRequest
from alppy.ai.providers import TRANSCRIPTION_PURPOSES, EchoChatProvider
from alppy.models.enums import MasteryBand
from alppy.services import adaptive_service

UIDS = ["7B_01", "7B_02", "7B_03"]


@pytest.fixture
def world() -> World:
    return build_world()


@pytest.fixture
def gaps(world: World) -> World:
    """Three pupils, two distinct principal gaps, so a partition is meaningful."""
    for uid, code in zip(UIDS, ("MSN 31.3", "MSN 31.3", "MSN 32.1"), strict=True):
        snapshot(
            world, student_uid=uid, competency_code=code, score=0.45, band=MasteryBand.FADING
        )
    world.db.commit()
    return world


def _propose(world: World, **kwargs: Any) -> Any:
    params: dict[str, Any] = {
        "school_id": world.school_id,
        "class_id": world.class_id,
        "subject_id": world.subject_id,
        "student_ids": [world.student(u) for u in UIDS],
        "items_per_student": 4,
        "allow_generation": False,
        "n_groups": 2,
    }
    params.update(kwargs)
    return adaptive_service.propose_adaptive(world.db, **params)


def _partition(response: Any) -> list[set[str]]:
    return [set(g.student_uids) for g in response.groups]


def test_the_deterministic_partition_is_still_the_default(gaps: World) -> None:
    """Not asking must cost nothing — no call, no change, and the response says
    the groups did not come from a model."""
    chat = ScriptedChat()
    response = _propose(gaps)
    assert response.grouped_by_model is False
    assert len(response.groups) == 2
    assert chat.requests == []


def test_a_valid_partition_from_the_model_is_used_and_declared(
    gaps: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_chat(
        monkeypatch,
        ScriptedChat(
            {"groups": [{"index": 1, "students": ["S1"]}, {"index": 2, "students": ["S2", "S3"]}]}
        ),
    )
    response = _propose(gaps, llm_grouping=True)

    assert response.grouped_by_model is True
    assert _partition(response) == [{"7B_01"}, {"7B_02", "7B_03"}]


def test_a_partition_that_leaves_a_student_out_is_rejected(
    gaps: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not "nearly right" — a different question answered. The child who is
    missing would receive no sheet at all."""
    use_chat(
        monkeypatch,
        ScriptedChat(
            {"groups": [{"index": 1, "students": ["S1"]}, {"index": 2, "students": ["S2"]}]}
        ),
    )
    response = _propose(gaps, llm_grouping=True)

    assert response.grouped_by_model is False
    assert set().union(*_partition(response)) == set(UIDS)


def test_a_partition_that_seats_a_student_twice_is_rejected(
    gaps: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two sheets for one child, and one of them wrong."""
    use_chat(
        monkeypatch,
        ScriptedChat(
            {
                "groups": [
                    {"index": 1, "students": ["S1", "S2"]},
                    {"index": 2, "students": ["S2", "S3"]},
                ]
            }
        ),
    )
    assert _propose(gaps, llm_grouping=True).grouped_by_model is False


def test_a_partition_naming_a_pupil_who_is_not_in_the_class_is_rejected(
    gaps: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_chat(
        monkeypatch,
        ScriptedChat(
            {
                "groups": [
                    {"index": 1, "students": ["S1", "S99"]},
                    {"index": 2, "students": ["S2", "S3"]},
                ]
            }
        ),
    )
    assert _propose(gaps, llm_grouping=True).grouped_by_model is False


def test_an_empty_group_is_rejected(gaps: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """A group with nobody in it is a sheet nobody receives."""
    use_chat(
        monkeypatch,
        ScriptedChat(
            {"groups": [{"index": 1, "students": ["S1", "S2", "S3"]}, {"index": 2, "students": []}]}
        ),
    )
    assert _propose(gaps, llm_grouping=True).grouped_by_model is False


def test_the_wrong_number_of_groups_is_rejected(
    gaps: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The teacher asked for two. Three is not an improvement on two."""
    use_chat(
        monkeypatch,
        ScriptedChat(
            {
                "groups": [
                    {"index": 1, "students": ["S1"]},
                    {"index": 2, "students": ["S2"]},
                    {"index": 3, "students": ["S3"]},
                ]
            }
        ),
    )
    assert _propose(gaps, llm_grouping=True).grouped_by_model is False


def test_a_provider_failure_falls_back_rather_than_failing_the_proposal(
    gaps: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_chat(monkeypatch, ScriptedChat(RuntimeError("provider down")))
    response = _propose(gaps, llm_grouping=True)

    assert response.grouped_by_model is False
    assert len(response.groups) == 2
    assert set().union(*_partition(response)) == set(UIDS)


def test_an_unparsable_answer_falls_back(gaps: World, monkeypatch: pytest.MonkeyPatch) -> None:
    use_chat(monkeypatch, ScriptedChat("not json at all"))
    assert _propose(gaps, llm_grouping=True).grouped_by_model is False


def test_the_model_is_shown_the_deterministic_partition_as_a_starting_point(
    gaps: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revising a defensible answer, not inventing one from scratch."""
    chat = ScriptedChat({"groups": []})
    use_chat(monkeypatch, chat)
    _propose(gaps, llm_grouping=True)

    sent = chat.requests[0].user
    assert "Starting partition" in sent
    assert "Group 1:" in sent


def test_the_model_never_sees_a_uid_or_a_name(
    gaps: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row ids, not people. It does not need to know who anyone is to say who
    belongs with whom."""
    from test_retrieval import ROSTER

    chat = ScriptedChat({"groups": []})
    use_chat(monkeypatch, chat)
    _propose(gaps, llm_grouping=True)

    sent = f"{chat.requests[0].system}\n{chat.requests[0].user}"
    assert all(uid not in sent for uid in UIDS)
    assert all(first not in sent and last not in sent for first, last in ROSTER)
    assert "S1" in sent


def test_the_offline_provider_refuses_to_invent_a_partition() -> None:
    """An invented partition is a claim about which children belong together,
    drawn from a hash — and unlike a bad exercise, nobody reads it before it
    takes effect. So it is a transcription purpose, and the empty answer sends
    the caller to the deterministic rule."""
    assert "adaptive_cluster" in TRANSCRIPTION_PURPOSES
    response = EchoChatProvider().complete(
        ChatRequest(system="s", user="u", purpose="adaptive_cluster")
    )
    assert json.loads(response.text) == {"groups": []}


def test_an_offline_run_still_produces_a_complete_partition(gaps: World) -> None:
    """Which is what keeps CI deterministic *and* correct: the fallback is not a
    degraded answer, it is the answer D33 specified."""
    response = _propose(gaps, llm_grouping=True)
    assert response.grouped_by_model is False
    assert set().union(*_partition(response)) == set(UIDS)
