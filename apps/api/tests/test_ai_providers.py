"""The OpenAI provider, and the two ways a provider choice goes wrong silently.

Nothing here touches the network: the SDK client is replaced by a fake that
records what it was handed. What is being tested is the *translation* — the
Responses API agrees with the Anthropic one on nothing, and every place the two
differ is a place a crop, a system prompt or a token count can be dropped
without anything raising.
"""

from __future__ import annotations

from typing import Any

import pytest

from alppy.ai.base import ChatRequest, ChatTruncatedError, ImagePart
from alppy.ai.client import estimate_cost_chf
from alppy.ai.providers import (
    AnthropicChatProvider,
    EchoChatProvider,
    OpenAiChatProvider,
    _accepts_temperature,
    build_chat_provider,
)
from alppy.core.config import Settings

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class _FakeResponses:
    """Stands in for ``client.responses``. Records the call, returns a canned run."""

    def __init__(self, *, text: str = '{"exercises": []}', status: str = "completed") -> None:
        self.calls: list[dict[str, Any]] = []
        self._text = text
        self._status = status

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        fake = self

        class _Usage:
            input_tokens = 120
            output_tokens = 34

        class _Incomplete:
            reason = "max_output_tokens"

        class _Response:
            output_text = fake._text
            status = fake._status
            incomplete_details = _Incomplete()
            usage = _Usage()

        return _Response()


def _provider(model: str = "gpt-5", **kwargs: Any) -> tuple[OpenAiChatProvider, _FakeResponses]:
    provider = OpenAiChatProvider.__new__(OpenAiChatProvider)
    provider._model = model
    provider._temperature_refused = not _accepts_temperature(model)
    responses = _FakeResponses(**kwargs)

    class _Client:
        pass

    client = _Client()
    client.responses = responses  # type: ignore[attr-defined]
    provider._client = client
    return provider, responses


def test_the_openai_provider_sends_the_system_prompt_as_instructions_not_as_a_message() -> None:
    """`instructions` keeps `input` purely user content. A system turn smuggled
    into the message list is a different prompt from the one the audit hash
    covers."""
    provider, responses = _provider()
    provider.complete(ChatRequest(system="you write exercises", user="go", purpose="p"))

    sent = responses.calls[0]
    assert sent["instructions"] == "you write exercises"
    assert sent["input"] == [{"role": "user", "content": [{"type": "input_text", "text": "go"}]}]


def test_a_crop_is_sent_as_an_input_image_part_before_the_text() -> None:
    """Anthropic takes a base64 source block, OpenAI takes a data URL, and the
    grading path depends on this one difference. Images first: the model looks,
    then it is told what to do with what it saw."""
    provider, responses = _provider()
    provider.complete(
        ChatRequest(system="s", user="grade it", purpose="grade_open_answer",
                    images=(ImagePart(PNG),))
    )

    blocks = responses.calls[0]["input"][0]["content"]
    assert blocks[0]["type"] == "input_image"
    assert blocks[0]["image_url"].startswith("data:image/png;base64,")
    assert blocks[-1] == {"type": "input_text", "text": "grade it"}


def test_the_answer_is_read_out_of_output_text_not_the_first_output_item() -> None:
    """On a reasoning model `output[0]` is a reasoning item, not the answer, so
    indexing into it returns nothing or raises. `output_text` is the aggregator."""
    provider, _ = _provider(text='{"exercises": [1]}')
    assert provider.complete(ChatRequest(system="s", user="u", purpose="p")).text == (
        '{"exercises": [1]}'
    )


def test_a_model_that_spent_its_whole_budget_thinking_is_reported_not_returned_empty() -> None:
    """An empty string flows into `parse_json_response` and surfaces to the
    teacher as "the provider returned something unusable" — when the cause is a
    number in the configuration they could change."""
    provider, _ = _provider(text="", status="incomplete")
    with pytest.raises(ChatTruncatedError):
        provider.complete(ChatRequest(system="s", user="u", purpose="p", max_tokens=16))


def test_a_reasoning_model_is_not_sent_a_temperature_it_would_refuse() -> None:
    """Reasoning models 400 on the parameter. Every call site passes one."""
    provider, responses = _provider(model="o3")
    provider.complete(ChatRequest(system="s", user="u", purpose="p", temperature=0.6))

    from openai import omit

    assert responses.calls[0]["temperature"] is omit


def test_a_model_that_takes_a_temperature_is_sent_the_one_that_was_asked_for() -> None:
    """`grade_open_answer.v2.md` states temperature 0.0 — a grade must be
    reproducible. Dropping it silently would break that contract."""
    provider, responses = _provider(model="gpt-5")
    provider.complete(ChatRequest(system="s", user="u", purpose="grade_open_answer",
                                  temperature=0.0))
    assert responses.calls[0]["temperature"] == 0.0


def test_a_stop_sequence_is_refused_rather_than_dropped_on_the_floor() -> None:
    """The Responses API has no equivalent. Nothing sets this today; the first
    caller who does must not get a subtly wrong result on one provider only."""
    provider, _ = _provider()
    with pytest.raises(NotImplementedError):
        provider.complete(ChatRequest(system="s", user="u", purpose="p", stop=("STOP",)))


def test_the_token_counts_land_on_the_response_the_audit_row_is_built_from() -> None:
    provider, _ = _provider()
    response = provider.complete(ChatRequest(system="s", user="u", purpose="p"))
    assert (response.input_tokens, response.output_tokens) == (120, 34)
    assert response.model == "gpt-5"


def test_every_grounded_provider_says_so_and_the_offline_one_does_not() -> None:
    """`grounded` is a claim about whether the output derives from the input.
    A provider that got this wrong would let extraction store invented exercises
    against a real page of a teacher's book (I-ai-04)."""
    assert OpenAiChatProvider.grounded is True
    assert AnthropicChatProvider.grounded is True
    assert EchoChatProvider.grounded is False
    assert OpenAiChatProvider.name == "openai"


def test_a_model_whose_price_the_table_does_not_know_costs_zero_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """docs/privacy.md offers the cost column as budget accounting. An unpriced
    model reports 0.00 on every row, which reads as "free" rather than
    "unknown"."""
    assert estimate_cost_chf("some-unlisted-model", 1_000_000, 1_000_000) == 0.0
    assert estimate_cost_chf("gpt-5", 1_000_000, 0) > 0.0


def test_a_provider_and_a_model_that_do_not_belong_together_fail_at_startup() -> None:
    """A Claude id sent to OpenAI 404s every generation, extraction and grade —
    and the failure path records `ai_chat_model` on the audit row, so the trail
    would name a model that was never called."""
    with pytest.raises(ValueError, match="anthropic model"):
        Settings(_env_file=None, ai_chat_provider="openai", ai_chat_model="claude-sonnet-5")


def test_leaving_the_model_empty_takes_the_configured_providers_default() -> None:
    assert Settings(_env_file=None, ai_chat_provider="openai").ai_chat_model == "gpt-5"
    assert Settings(_env_file=None, ai_chat_provider="anthropic").ai_chat_model == (
        "claude-sonnet-5"
    )


def test_an_unrecognised_model_id_is_left_alone_rather_than_guessed_at() -> None:
    """Azure deployment names and fine-tune ids are legitimate and unguessable.
    The pair check refuses only a *known-foreign* prefix."""
    settings = Settings(
        _env_file=None, ai_chat_provider="openai", ai_chat_model="ft:school-tuned-v3"
    )
    assert settings.ai_chat_model == "ft:school-tuned-v3"


def test_a_deployment_holding_the_wrong_providers_key_says_so_rather_than_going_quiet(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The echo fallback exists for *no* key. With more than one real provider it
    also catches the deployment that has the other one's key — and then answers
    hash-derived multiplication tables that are marked only as "generated"."""
    settings = Settings(
        _env_file=None,
        ai_chat_provider="openai",
        anthropic_api_key="sk-ant-set-but-useless-here",
        openai_api_key=None,
    )
    monkeypatch.setattr("alppy.ai.providers.get_settings", lambda: settings)

    assert isinstance(build_chat_provider(), EchoChatProvider)


def test_the_configured_provider_is_built_when_its_own_key_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, ai_chat_provider="openai", openai_api_key="sk-test")
    monkeypatch.setattr("alppy.ai.providers.get_settings", lambda: settings)

    provider = build_chat_provider()
    assert provider.name == "openai"


class _RefusesTemperature:
    """Rejects the parameter the way the API does, then answers without it."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        from openai import omit

        if kwargs.get("temperature") is not omit:
            raise RuntimeError(
                "400: Unsupported parameter: 'temperature' is not supported with this model."
            )

        class _Usage:
            input_tokens = 1
            output_tokens = 1

        class _Response:
            output_text = "{}"
            status = "completed"
            usage = _Usage()

        return _Response()


def test_a_model_that_turns_out_to_refuse_a_temperature_is_retried_without_one() -> None:
    """The prefix table is a fast path, not an oracle: the model lineup moves
    faster than this file does. A wrong table entry must not break every call in
    the product, so a refusal is learned at runtime."""
    provider, _ = _provider(model="gpt-5")
    refusing = _RefusesTemperature()
    provider._client.responses = refusing  # type: ignore[attr-defined]

    response = provider.complete(ChatRequest(system="s", user="u", purpose="p", temperature=0.4))
    assert response.text == "{}"
    assert len(refusing.calls) == 2, "one refused attempt, then one without"


def test_the_refusal_is_learned_once_and_not_paid_for_again() -> None:
    """One wasted request per process, not per call."""
    provider, _ = _provider(model="gpt-5")
    refusing = _RefusesTemperature()
    provider._client.responses = refusing  # type: ignore[attr-defined]

    provider.complete(ChatRequest(system="s", user="u", purpose="p", temperature=0.4))
    provider.complete(ChatRequest(system="s", user="u", purpose="p", temperature=0.4))
    assert len(refusing.calls) == 3, "two attempts on the first call, one on the second"


def test_a_real_bad_request_is_not_mistaken_for_a_temperature_refusal() -> None:
    """The match is on the message, so it has to stay narrow — swallowing a
    genuine 400 would turn a caller's bug into a silent second attempt."""

    class _Broken:
        def create(self, **kwargs: Any) -> Any:
            raise RuntimeError("400: model not found")

    provider, _ = _provider(model="gpt-5")
    provider._client.responses = _Broken()  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError, match="model not found"):
        provider.complete(ChatRequest(system="s", user="u", purpose="p"))
