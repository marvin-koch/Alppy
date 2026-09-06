"""Provider-agnostic AI interfaces.

Two narrow protocols and nothing else. A Swiss school may require that no data
leaves EU/CH infrastructure, so the provider must be swappable by configuration
rather than by a refactor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ChatRequest:
    system: str
    user: str
    max_tokens: int = 2048
    temperature: float = 0.4
    stop: tuple[str, ...] = ()
    purpose: str = ""
    """What the call is for, e.g. ``extract_exercises``. A provider that cannot
    actually read the prompt needs this to refuse the jobs where inventing an
    answer would be a lie rather than a demo."""


@dataclass(frozen=True, slots=True)
class ChatResponse:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str = ""
    raw: dict[str, object] = field(default_factory=dict)


class ChatProvider(Protocol):
    name: str

    grounded: bool
    """True when the provider's output is derived from the prompt it was given.

    False for the offline stand-in, whose text is a deterministic function of a
    hash. Anything that *transcribes* a document — extraction — must refuse to
    run on an ungrounded provider, or it will attribute invented exercises to a
    real page of a teacher's textbook."""

    def complete(self, request: ChatRequest) -> ChatResponse: ...


class EmbeddingsProvider(Protocol):
    name: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...
