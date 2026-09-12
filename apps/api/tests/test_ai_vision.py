"""An image on a chat request: carried by the real provider, refused by the
stand-in, hashed into the audit trail."""

from __future__ import annotations

import json
from typing import Any

import pytest

from alppy.ai import providers
from alppy.ai.base import ChatRequest, ImagePart
from alppy.ai.client import AiClient, load_prompt
from alppy.ai.providers import AnthropicChatProvider, EchoChatProvider

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_the_offline_provider_never_invents_a_verdict() -> None:
    """It cannot see the image, so it says nothing — in the shape the caller
    parses, with the verdict null and the confidence zero."""
    response = EchoChatProvider().complete(
        ChatRequest(system="s", user="u", purpose="grade_open_answer", images=(ImagePart(PNG),))
    )
    parsed = json.loads(response.text)
    assert parsed == {"transcription": None, "written": None, "correct": None, "confidence": 0.0}


class _FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)

        class _Block:
            type = "text"
            text = '{"transcription": "7/8", "written": true, "correct": true, "confidence": 0.9}'

        class _Usage:
            input_tokens = 12
            output_tokens = 4

        class _Message:
            def __init__(self) -> None:
                self.content = [_Block()]
                self.usage = _Usage()

        return _Message()


def _anthropic_with_fake_client() -> tuple[AnthropicChatProvider, _FakeMessages]:
    provider = object.__new__(AnthropicChatProvider)
    provider._model = "claude-sonnet-5"
    messages = _FakeMessages()

    class _Client:
        pass

    client = _Client()
    client.messages = messages  # type: ignore[attr-defined]  # test double
    provider._client = client
    return provider, messages


def test_the_anthropic_provider_sends_the_image_before_the_text() -> None:
    provider, messages = _anthropic_with_fake_client()
    provider.complete(
        ChatRequest(system="s", user="Question: x", purpose="grade_open_answer", images=(ImagePart(PNG),))
    )
    content = messages.calls[0]["messages"][0]["content"]
    assert [block["type"] for block in content] == ["image", "text"]
    assert content[0]["source"]["media_type"] == "image/png"
    assert content[0]["source"]["type"] == "base64"
    assert content[1]["text"] == "Question: x"


def test_a_text_only_request_is_still_a_plain_string() -> None:
    """Every existing caller is text-only; their wire shape must not change."""
    provider, messages = _anthropic_with_fake_client()
    provider.complete(ChatRequest(system="s", user="hello"))
    assert messages.calls[0]["messages"][0]["content"] == "hello"


def test_the_client_hashes_the_image_into_the_audit_record(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(providers, "build_chat_provider", EchoChatProvider)
    monkeypatch.setattr("alppy.ai.client.build_chat_provider", EchoChatProvider)
    client = AiClient()
    prompt = load_prompt("grade_open_answer", "v1")
    values = {"language": "fr", "statement": "Calcule.", "expected_answer": "7/8", "fill": "lines"}
    _, one = client.complete(prompt=prompt, purpose="grade_open_answer", values=values,
                             images=(ImagePart(PNG),))
    _, two = client.complete(prompt=prompt, purpose="grade_open_answer", values=values,
                             images=(ImagePart(PNG + b"x"),))
    _, same = client.complete(prompt=prompt, purpose="grade_open_answer", values=values,
                              images=(ImagePart(PNG),))
    assert one.prompt_sha256 == same.prompt_sha256
    assert one.prompt_sha256 != two.prompt_sha256
    assert one.ok and one.purpose == "grade_open_answer"


def test_the_grading_prompt_names_every_input() -> None:
    prompt = load_prompt("grade_open_answer", "v1")
    system, user = prompt.render(language="fr", statement="Q", expected_answer="7/8", fill="lines")
    assert "7/8" in user and "Q" in user
    assert "never" in system.lower() and "json" in system.lower()


def test_the_v2_grading_prompt_carries_the_reference_block() -> None:
    """v2 replaces the expected answer with a reference block, so the same
    prompt grades against the teacher's answer or tells the model to work one
    out. Both branches must be named in the system text."""
    from alppy.services.open_answer_grading import NO_EXPECTED_ANSWER, PROMPT_VERSION

    prompt = load_prompt("grade_open_answer", PROMPT_VERSION)
    system, user = prompt.render(language="fr", statement="Q", reference="7/8", fill="lines")
    assert "7/8" in user and "Q" in user
    assert "expected answer" in system.lower() and "work the question out" in system.lower()
    assert '"reference"' in user
    _, without = prompt.render(language="fr", statement="Q", reference=NO_EXPECTED_ANSWER, fill="lines")
    assert NO_EXPECTED_ANSWER in without


def test_every_argument_the_anthropic_provider_sends_exists_on_the_installed_sdk() -> None:
    """The test double is more permissive than the SDK, so it hid a hard break.

    `_FakeMessages.create` takes `**kwargs` and accepts anything. The real
    `Messages.create` takes named parameters and NO `**kwargs`, and
    `temperature` was removed from it — `pyproject.toml` asks for
    `anthropic>=0.40.0` and does not pin, so a current install raised
    `TypeError: Messages.create() got an unexpected keyword argument
    'temperature'` before reaching the network, and every Anthropic call
    failed. Every test here stayed green, because every test here talks to the
    double.

    Nothing else would have noticed either: the default provider is `echo`
    (`docker compose up` must work with no account anywhere), so this path only
    runs at a school that configured a key.

    Checking the arguments against the INSTALLED signature is the invariant —
    it costs no network call and no API key, and it covers the next parameter
    to be removed as well as this one.
    """
    import inspect

    anthropic = pytest.importorskip("anthropic", reason="the SDK is an optional dependency")
    create = inspect.signature(anthropic.resources.messages.Messages.create)
    assert not any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in create.parameters.values()
    ), "the SDK grew **kwargs; this test can no longer catch an unknown argument"

    provider, messages = _anthropic_with_fake_client()
    provider.complete(
        ChatRequest(
            system="s",
            user="Question: x",
            purpose="grade_open_answer",
            temperature=0.0,
            stop=("STOP",),
            images=(ImagePart(PNG),),
        )
    )
    sent = set(messages.calls[0])
    unknown = sent - set(create.parameters)
    assert not unknown, f"the provider sends arguments this SDK does not accept: {sorted(unknown)}"


def test_a_dropped_temperature_is_never_silent() -> None:
    """`grade_open_answer.v2.md` states "temperature 0.0 — a grade must be
    reproducible, never creative". When the SDK will not carry the parameter
    the call still happens, so the log is the only thing that can tell a school
    the grading contract is not being kept."""
    provider, messages = _anthropic_with_fake_client()
    request = ChatRequest(
        system="s", user="x", purpose="grade_open_answer", temperature=0.0
    )

    if providers._anthropic_accepts_temperature():
        provider.complete(request)
        assert messages.calls[0]["temperature"] == 0.0
        return

    warned: list[dict[str, Any]] = []
    original = providers.log.warning
    providers.log.warning = lambda event, **kw: warned.append({"event": event, **kw})  # type: ignore[assignment]
    try:
        provider.complete(request)
    finally:
        providers.log.warning = original  # type: ignore[assignment]

    assert "temperature" not in messages.calls[0]
    assert [w["event"] for w in warned] == ["ai.temperature.dropped"]
    assert warned[0]["provider"] == "anthropic" and warned[0]["requested"] == 0.0
