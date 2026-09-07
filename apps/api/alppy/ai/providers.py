"""Concrete providers.

``EchoChatProvider`` and ``HashEmbeddingsProvider`` are not toys: they are what
lets the whole product run in ``docker compose up`` on a clean machine with no
API key, which is a requirement of the definition of done. They are
deterministic, so tests and the demo seed are reproducible.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata

from alppy.ai.base import ChatProvider, ChatRequest, ChatResponse, EmbeddingsProvider
from alppy.core.config import get_settings

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
TRANSCRIPTION_PURPOSES: frozenset[str] = frozenset({"extract_exercises", "adaptive_feedback"})


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
            empty: dict[str, list[str]] = (
                {"notes": []} if request.purpose == "adaptive_feedback" else {"exercises": []}
            )
            text = json.dumps(empty)
            return ChatResponse(
                text=text,
                input_tokens=len(request.user) // 4,
                output_tokens=len(text) // 4,
                model="echo",
            )
        seed = hashlib.sha256(request.user.encode()).hexdigest()
        language = _asked(request.user, "Language", default="fr")
        n = _asked_int(request.user, "Number of exercises", default=3, lo=1, hi=16)
        difficulty = _asked_int(request.user, "Difficulty", default=2, lo=1, hi=5)
        items = [_offline_item(seed, i, language, difficulty) for i in range(n)]
        text = json.dumps({"exercises": items}, ensure_ascii=False)
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

        self._client = Anthropic(api_key=api_key)

    def complete(self, request: ChatRequest) -> ChatResponse:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            system=request.system,
            messages=[{"role": "user", "content": request.user}],
            **({"stop_sequences": list(request.stop)} if request.stop else {}),
        )
        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )
        return ChatResponse(
            text=text,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            model=self._model,
        )


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


def build_chat_provider() -> ChatProvider:
    """Anthropic when a key is configured, the deterministic echo otherwise.

    The fallback is not a stub: it is what lets `docker compose up` run the
    whole product with no account anywhere.
    """
    s = get_settings()
    if s.ai_chat_provider == "anthropic" and s.anthropic_api_key:
        return AnthropicChatProvider(s.anthropic_api_key, s.ai_chat_model)
    return EchoChatProvider()


def build_embeddings_provider() -> EmbeddingsProvider:
    s = get_settings()
    return HashEmbeddingsProvider(s.embedding_dim)
