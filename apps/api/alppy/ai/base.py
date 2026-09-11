"""Provider-agnostic AI interfaces.

Two narrow protocols and nothing else. A Swiss school may require that no data
leaves EU/CH infrastructure, so the provider must be swappable by configuration
rather than by a refactor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ChatTruncatedError(RuntimeError):
    """The provider stopped because it ran out of output budget.

    Distinct from an unparsable response, and the distinction is the whole
    point: a truncated answer *is* unparsable, so without this the teacher is
    told "the model returned something unusable" when the cause is a number in
    the configuration they could change. It lives here, in the module that
    imports nothing, so the planner can classify it without importing a
    provider."""


@dataclass(frozen=True, slots=True)
class ImagePart:
    """One image shown to the model alongside the user text.

    Bytes, not a URL: the crop never leaves the process by any other route,
    and a provider that cannot look at pixels (the offline stand-in) simply
    ignores it. The text gate cannot inspect these; what keeps a name out of
    them is geometry — a crop is cut from the statement region only."""

    data: bytes
    media_type: str = "image/png"


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
    images: tuple[ImagePart, ...] = ()
    """Empty for every text-only caller, which is all of them but the vision
    grader — so no existing provider or test needs to know the field exists."""
    timeout_s: float | None = None
    """Per-call ceiling, overriding the client's own (audit 03, B10).

    ``None`` means "use the configured default", which is what every caller
    wants. It exists because a vision call over one crop and a batched
    generation call over eight plans are not comparable work, and giving them a
    single budget means either strangling the batch or letting one crop hang for
    three minutes. Only the batched generation path sets it."""


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
