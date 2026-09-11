"""Concrete providers.

``EchoChatProvider`` and ``HashEmbeddingsProvider`` are not toys: they are what
lets the whole product run in ``docker compose up`` on a clean machine with no
API key, which is a requirement of the definition of done. They are
deterministic, so tests and the demo seed are reproducible.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import unicodedata
from typing import TYPE_CHECKING, Any, cast

from alppy.ai.base import (
    ChatProvider,
    ChatRequest,
    ChatResponse,
    ChatTruncatedError,
    EmbeddingsProvider,
)
from alppy.core.config import get_settings
from alppy.core.logging import get_logger

log = get_logger(__name__)

if TYPE_CHECKING:  # the SDK is optional at runtime
    from openai import Omit
    from openai.types.responses import ResponseInputParam

#: Purposes whose output must come from the prompt. An ungrounded provider
#: returns nothing for these rather than inventing content that would be stored
#: with the source document's provenance.
#:
#: ``adaptive_feedback`` belongs here for a different reason than
#: ``extract_exercises`` and a stronger one. An invented exercise is a bad
#: question a teacher can read and reject. An invented misconception is a claim
#: about how one named child thinks, printed and handed to that child — and the
#: echo provider cannot read the prompt, so anything it said about a student's
#: mistakes would be fiction with a UID attached. Better an honest empty note.
#:
#: ``grade_open_answer`` is the strongest case of the three. It reads a child's
#: handwriting and says whether the answer is right; a stand-in that cannot see
#: the image and answered anyway would be a verdict on a real student drawn
#: from a hash. It returns the empty shape, and the caller records "no verdict".
#: ``adaptive_cluster`` belongs here for the same reason as ``adaptive_feedback``.
#: An invented partition is a claim about which children belong together, drawn
#: from a hash — and unlike a bad exercise, nobody reads it before it takes
#: effect. Returning the empty shape sends the caller to the deterministic
#: partition, which is both the honest answer and the correct one.
TRANSCRIPTION_PURPOSES: frozenset[str] = frozenset(
    {"extract_exercises", "adaptive_feedback", "grade_open_answer", "adaptive_cluster"}
)

#: What an ungrounded provider answers for each transcription purpose: the
#: shape the caller parses, with nothing in it.
_EMPTY_SHAPES: dict[str, dict[str, object]] = {
    "extract_exercises": {"exercises": []},
    "adaptive_feedback": {"notes": []},
    "grade_open_answer": {
        "transcription": None,
        "written": None,
        "correct": None,
        "confidence": 0.0,
    },
    "adaptive_cluster": {"groups": []},
}


class EchoChatProvider:
    """Offline stand-in. Produces structurally valid exercise JSON so the
    adaptive-generation flow is demonstrable without a key or a network.

    It does not read the prompt — the output is a function of its hash — so it
    is ``grounded = False`` and returns an empty list for any transcription
    purpose. Inventing exercises there would store them under the teacher's own
    filename and page number, with no mark saying a model wrote them.
    """

    name = "echo"
    grounded = False

    def complete(self, request: ChatRequest) -> ChatResponse:
        if request.purpose in TRANSCRIPTION_PURPOSES:
            # Empty, in the shape the caller parses. A feedback caller reading
            # `{"exercises": []}` would report "the model did not return usable
            # JSON", which blames the provider for a refusal that is correct.
            text = json.dumps(_EMPTY_SHAPES[request.purpose])
            return ChatResponse(
                text=text,
                input_tokens=len(request.user) // 4,
                output_tokens=len(text) // 4,
                model="echo",
            )
        language = _asked(request.user, "Language", default="fr")
        if request.purpose == "adaptive_generate_batch":
            payload: dict[str, object] = {"plans": _offline_plans(request.user, language)}
        else:
            seed = hashlib.sha256(request.user.encode()).hexdigest()
            n = _asked_int(request.user, "Number of exercises", default=3, lo=1, hi=16)
            difficulty = _asked_int(request.user, "Difficulty", default=2, lo=1, hi=5)
            payload = {"exercises": [_offline_item(seed, i, language, difficulty) for i in range(n)]}
        text = json.dumps(payload, ensure_ascii=False)
        return ChatResponse(
            text=text,
            input_tokens=len(request.user) // 4,
            output_tokens=len(text) // 4,
            model="echo",
        )


#: The offline provider answers in whatever language it was asked for. It reads
#: the prompt for this one value only — it is still ungrounded, and still says
#: so — because a stand-in that silently ignores the language would let a bug in
#: the language path pass every offline test.
_OFFLINE_STEMS: dict[str, str] = {
    "fr": "Calcule {a} × {b}.",
    "de": "Berechne {a} × {b}.",
    "en": "Work out {a} × {b}.",
}


def _asked(user: str, field: str, *, default: str) -> str:
    match = re.search(rf"^{field}:\s*(\S+)", user, re.MULTILINE)
    return match.group(1) if match else default


def _asked_int(user: str, field: str, *, default: int, lo: int, hi: int) -> int:
    match = re.search(rf"^{field}:\s*(\d+)", user, re.MULTILINE)
    if not match:
        return default
    return max(lo, min(hi, int(match.group(1))))


#: One plan line of a batched request: "[P2] competencies: C1,C3 | difficulty: 4
#: | count: 2". Read line by line rather than by parsing JSON out of the prompt —
#: the moment the stand-in has to understand structure it stops being a hash
#: function and becomes a second implementation to keep in step.
_PLAN_LINE_RE = re.compile(
    r"^\[(?P<plan>P\d+)\]\s*competencies:.*?\|\s*difficulty:\s*(?P<difficulty>\d+)"
    r"\s*\|\s*count:\s*(?P<count>\d+)",
    re.MULTILINE,
)


def _offline_plans(user: str, language: str) -> list[dict[str, object]]:
    """One entry per plan, each with its own items.

    The seed folds in the plan id. Without it every plan in a batch would get
    byte-identical statements, the shared duplicate check would drop all but the
    first, and it would present as a bug in the dedupe rather than in the
    stand-in.

    `_asked_int` is first-match-wins over the whole prompt, which is exactly
    wrong here — a batched request has one `count:` per plan. Hence the per-line
    read.
    """
    plans: list[dict[str, object]] = []
    for match in _PLAN_LINE_RE.finditer(user):
        plan_id = match.group("plan")
        count = max(1, min(16, int(match.group("count"))))
        difficulty = max(1, min(5, int(match.group("difficulty"))))
        seed = hashlib.sha256(f"{plan_id}:{user}".encode()).hexdigest()
        plans.append(
            {
                "plan_id": plan_id,
                "exercises": [
                    _offline_item(seed, i, language, difficulty) for i in range(count)
                ],
            }
        )
    return plans


def _offline_item(seed: str, i: int, language: str, difficulty: int) -> dict[str, object]:
    a = int(seed[i * 2 : i * 2 + 2], 16) % 9 + 2
    b = int(seed[i * 2 + 4 : i * 2 + 6], 16) % 9 + 2
    product = a * b
    stem = _OFFLINE_STEMS.get(language, _OFFLINE_STEMS["fr"])
    distractors = [product + a, product - b, product + 1]
    options = [str(product), *[str(d) for d in distractors]]
    # The correct answer moves. A stub that always keyed option A trained the
    # whole pipeline — and every test over it — on a sheet a child could pass by
    # filling the first bubble sixteen times.
    key = int(seed[i * 2 + 8 : i * 2 + 10] or "0", 16) % len(options)
    options[0], options[key] = options[key], options[0]
    return {
        "type": "mcq",
        "statement": stem.format(a=a, b=b),
        "options": options,
        "answer_index": key,
        "explanation": f"{a} × {b} = {product}",
        "difficulty": difficulty,
    }


class AnthropicChatProvider:
    """Default generation provider."""

    name = "anthropic"
    grounded = True

    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        from anthropic import Anthropic  # imported lazily: optional at runtime

        # Explicit budgets, because the SDK defaults are 600 s with 2 retries —
        # about half an hour for one logical call, inside a job whose own
        # ceiling is `job_timeout_s` (600 s by default). The job is cancelled
        # long before the HTTP call gives up, which is precisely how a provider
        # blip became a stuck RUNNING row instead of a visible failure
        # (audit 03, B10).
        settings = get_settings()
        self._client = Anthropic(
            api_key=api_key,
            timeout=settings.provider_timeout_s,
            max_retries=settings.provider_max_retries,
        )

    def complete(self, request: ChatRequest) -> ChatResponse:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            system=request.system,
            messages=[{"role": "user", "content": _user_content(request)}],
            **({"stop_sequences": list(request.stop)} if request.stop else {}),
            **({"timeout": request.timeout_s} if request.timeout_s else {}),
        )
        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )
        return ChatResponse(
            text=text,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            # What ANSWERED, not what was asked for (audit 03, B19). An alias
            # like `claude-sonnet-5` resolves to a dated build that changes
            # underneath it, so a disputed grade traced back to the configured
            # string names a model that may never have seen the paper. The
            # configured value is the fallback, for a response that carries none.
            model=str(getattr(message, "model", "") or self._model),
        )


def _user_content(request: ChatRequest) -> str | list[dict[str, object]]:
    """The user turn: a plain string for text, content blocks with the images
    first when there are any. Images before the text is the order the model
    reads best — it looks, then it is told what to do with what it saw."""
    if not request.images:
        return request.user
    blocks: list[dict[str, object]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image.media_type,
                "data": base64.b64encode(image.data).decode("ascii"),
            },
        }
        for image in request.images
    ]
    blocks.append({"type": "text", "text": request.user})
    return blocks


#: Models that reject a non-default ``temperature``. Reasoning models take the
#: sampling decision themselves and 400 on the parameter.
#:
#: This is a property of the model id, not a deployment choice, so it lives here
#: rather than in configuration — and it must be rechecked whenever the default
#: model moves. It is not cosmetic: ``grade_open_answer.v2.md`` states
#: "temperature 0.0 — a grade must be reproducible, never creative", so a model
#: on this list cannot honour the grading prompt's own stated contract.
_MODELS_WITHOUT_TEMPERATURE: tuple[str, ...] = ("o1", "o3", "o4")


def _accepts_temperature(model: str) -> bool:
    return not model.startswith(_MODELS_WITHOUT_TEMPERATURE)


class OpenAiChatProvider:
    """OpenAI, through the Responses API.

    Deliberately shaped like ``AnthropicChatProvider`` rather than sharing code
    with it: the two wire formats agree on nothing. The system prompt is
    ``instructions`` rather than a message, an image is a data URL rather than a
    base64 source block, and the text comes back through an aggregator because
    ``output[0]`` is a reasoning item on a reasoning model, not the answer.
    """

    name = "openai"
    grounded = True

    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._temperature_refused = not _accepts_temperature(model)
        """Learned as well as declared.

        The prefix table below is a fast path for the models we know about, but
        the lineup moves faster than this file does. If the API refuses the
        parameter anyway, that is remembered here and the next call goes without
        it — one wasted request per process rather than a wrong default table
        breaking every call in the product."""
        from openai import OpenAI  # imported lazily: optional at runtime

        # See the note on the Anthropic provider: explicit budgets rather than
        # the SDK's 600 s × 3 attempts (audit 03, B10).
        settings = get_settings()
        self._client = OpenAI(
            api_key=api_key,
            timeout=settings.provider_timeout_s,
            max_retries=settings.provider_max_retries,
        )

    def complete(self, request: ChatRequest) -> ChatResponse:
        if request.stop:
            # The Responses API has no stop-sequence parameter. Nothing in the
            # codebase sets this today; silently dropping it would give the
            # first caller who does a subtly wrong result on one provider only.
            raise NotImplementedError(
                "stop sequences are not supported by the OpenAI Responses provider"
            )
        from openai import NOT_GIVEN, omit

        # cast, not ignore: the blocks are built by hand below and the SDK's
        # TypedDict union cannot narrow a plain dict.
        content = cast(
            "ResponseInputParam",
            [{"role": "user", "content": _openai_content(request)}],
        )

        def _send(temperature: float | Omit) -> Any:
            return self._client.responses.create(
                model=self._model,
                instructions=request.system,
                input=content,
                # Covers reasoning *and* visible output on a reasoning model, so
                # a budget spent thinking returns nothing — see the check below.
                max_output_tokens=request.max_tokens,
                temperature=temperature,
                # Explicit rather than a `**{}` splat: the overloads on
                # `responses.create` do not resolve through unpacking. `timeout`
                # takes `NOT_GIVEN` rather than the `omit` sentinel
                # `temperature` uses — two different "leave it alone" values in
                # one call, which is the SDK's choice and not ours.
                timeout=request.timeout_s if request.timeout_s else NOT_GIVEN,
            )

        if self._temperature_refused:
            self._warn_dropped(request)
            response = _send(omit)
        else:
            try:
                response = _send(request.temperature)
            except Exception as exc:
                if not _is_temperature_refusal(exc):
                    raise
                # Learn it once, for the life of the process.
                self._temperature_refused = True
                self._warn_dropped(request)
                response = _send(omit)

        text: str = getattr(response, "output_text", "") or ""
        if not text and _hit_the_output_cap(response):
            raise ChatTruncatedError(
                f"{self._model} stopped at the {request.max_tokens}-token output cap "
                f"for purpose {request.purpose!r} without producing an answer"
            )
        usage = getattr(response, "usage", None)
        return ChatResponse(
            text=text,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            # See the note on the Anthropic provider: the responding model, with
            # the configured one as the fallback (audit 03, B19).
            model=str(getattr(response, "model", "") or self._model),
        )

    def _warn_dropped(self, request: ChatRequest) -> None:
        """Say so, every time. `grade_open_answer.v2.md` states "temperature 0.0
        — a grade must be reproducible, never creative", and a model that will
        not take the parameter cannot honour that. The call still happens; the
        log is what lets somebody notice the contract is not being kept."""
        log.warning(
            "ai.temperature.dropped",
            provider=self.name,
            model=self._model,
            purpose=request.purpose,
            requested=request.temperature,
        )


def _is_temperature_refusal(exc: Exception) -> bool:
    """True when the provider rejected the *parameter*, not the request.

    Matched on the message because the SDK models this as a generic 400. Kept
    narrow — it must never swallow a real bad-request — and it only ever costs
    one extra call before the answer is remembered."""
    text = str(exc).lower()
    return "temperature" in text and (
        "unsupported" in text or "not support" in text or "unknown parameter" in text
    )


def _hit_the_output_cap(response: object) -> bool:
    """True when the run stopped on ``max_output_tokens`` rather than finishing."""
    if getattr(response, "status", None) != "incomplete":
        return False
    details = getattr(response, "incomplete_details", None)
    return getattr(details, "reason", None) == "max_output_tokens"


def _openai_content(request: ChatRequest) -> list[dict[str, object]]:
    """Images first, then the text — the order the model reads best, and the
    same order ``_user_content`` uses for Anthropic. The part types differ:
    ``input_text`` / ``input_image``, not ``text`` / ``image``."""
    blocks: list[dict[str, object]] = [
        {
            "type": "input_image",
            "image_url": (
                f"data:{image.media_type};base64,"
                f"{base64.b64encode(image.data).decode('ascii')}"
            ),
        }
        for image in request.images
    ]
    blocks.append({"type": "input_text", "text": request.user})
    return blocks


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _fold_accents(token: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", token) if unicodedata.category(c) != "Mn"
    )


_STEM_MIN = 4
"""Below this a token is left alone: short maths words are already roots, and
stemming them only creates collisions."""

_PLURAL_SUFFIXES = ("s",)
"""Just the plural "s", and deliberately nothing else.

The stem has to be a fixed point — `stem(stem(w)) == stem(w)` — or the singular
and the plural land in different buckets and the whole exercise is pointless.
Every richer rule tried here broke that on the words teachers actually type:
stripping "n" turns "fraction" into "fractio" while "fractions" becomes
"fraction"; stripping "es" turns "angles" into "angl" while "angle" stays
"angle". A bare "s" converges for fr and en plurals, which is what the default
locale needs. German plurals are not covered — ADR 0001's real embedder is what
fixes that, not a bigger suffix table."""


def _token_forms(token: str) -> tuple[str, ...]:
    """The forms a token is hashed under: itself, accent-folded, and a stem.

    A pure bag-of-words hash gives *no* credit for "fractions" against
    "fraction" — different strings, different buckets, cosine 0.0 — which made
    the single most obvious teacher query rank a symmetry exercise first.
    Hashing a crude stem alongside the token buys plural and accent robustness
    without pretending to be a lemmatiser; ADR 0001's real embedder is what
    actually fixes retrieval. Duplicates are dropped so a token that is already
    its own stem is not counted twice.
    """
    folded = _fold_accents(token)
    forms = [token, folded]
    if len(folded) >= _STEM_MIN:
        stem = folded
        for suffix in _PLURAL_SUFFIXES:
            if stem.endswith(suffix) and len(stem) - len(suffix) >= _STEM_MIN:
                stem = stem[: -len(suffix)]
                break
        forms.append(f"stem:{stem}")
    return tuple(dict.fromkeys(forms))


class HashEmbeddingsProvider:
    """Deterministic hashed bag-of-words embedding.

    Not a semantic model — a hashing trick with L2 normalisation. It exists so
    that retrieval, pgvector indexing and the whole RAG path are exercisable
    offline and in CI. ADR 0001 records the real choice (a self-hosted
    multilingual model) and this class implements the same interface, so
    swapping it is a config change.
    """

    name = "hash"

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        for token in _TOKEN_RE.findall(text.lower()):
            for form in _token_forms(token):
                digest = hashlib.blake2b(form.encode("utf-8"), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimensions
                sign = 1.0 if digest[4] & 1 else -1.0
                vec[index] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


#: The key each provider needs, by name. A provider with no key cannot be built.
def _api_key_for(provider: str) -> str | None:
    s = get_settings()
    return {"anthropic": s.anthropic_api_key, "openai": s.openai_api_key}.get(provider)


def build_chat_provider() -> ChatProvider:
    """The configured provider when its key is present, the echo otherwise.

    The fallback is not a stub: it is what lets `docker compose up` run the
    whole product with no account anywhere.

    It is also the sharpest edge in this module, and it grew sharper the moment
    there was more than one real provider. A deployment holding the *other*
    provider's key falls through to a stand-in that answers multiplication
    tables derived from a hash — structurally valid, pedagogically meaningless,
    and marked only as "generated". So the fall-through says so, loudly, once,
    naming what was configured and what was missing.
    """
    s = get_settings()
    provider = s.ai_chat_provider
    if provider != "echo":
        key = _api_key_for(provider)
        if key:
            if provider == "openai":
                return OpenAiChatProvider(key, s.ai_chat_model)
            return AnthropicChatProvider(key, s.ai_chat_model)
        log.warning(
            "ai.provider.no_key",
            provider=provider,
            model=s.ai_chat_model,
            detail=(
                f"ALPPY_AI_CHAT_PROVIDER={provider} but no key was configured; "
                f"falling back to the offline echo provider. Nothing this process "
                f"generates comes from a model."
            ),
        )
    return EchoChatProvider()


def build_embeddings_provider() -> EmbeddingsProvider:
    s = get_settings()
    return HashEmbeddingsProvider(s.embedding_dim)
