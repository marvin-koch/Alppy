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

from alppy.ai.base import ChatRequest, ChatResponse
from alppy.core.config import get_settings


class EchoChatProvider:
    """Offline stand-in. Produces structurally valid exercise JSON so the
    adaptive-generation flow is demonstrable without a key or a network."""

    name = "echo"

    def complete(self, request: ChatRequest) -> ChatResponse:
        seed = hashlib.sha256(request.user.encode()).hexdigest()
        n = int(seed[:2], 16) % 3 + 2
        language = "de" if "language: de" in request.user else "fr"
        items = [_offline_item(seed, i, language) for i in range(n)]
        text = json.dumps({"exercises": items}, ensure_ascii=False)
        return ChatResponse(
            text=text,
            input_tokens=len(request.user) // 4,
            output_tokens=len(text) // 4,
            model="echo",
        )


def _offline_item(seed: str, i: int, language: str) -> dict[str, object]:
    a = int(seed[i * 2 : i * 2 + 2], 16) % 9 + 2
    b = int(seed[i * 2 + 4 : i * 2 + 6], 16) % 9 + 2
    product = a * b
    if language == "de":
        statement = f"Berechne {a} × {b}."
    else:
        statement = f"Calcule {a} × {b}."
    distractors = [product + a, product - b, product + 1]
    return {
        "type": "mcq",
        "statement": statement,
        "options": [str(product), *[str(d) for d in distractors]],
        "answer_index": 0,
        "explanation": f"{a} × {b} = {product}",
        "difficulty": 2,
    }


class AnthropicChatProvider:
    """Default generation provider."""

    name = "anthropic"

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
        tokens = _TOKEN_RE.findall(text.lower())
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


def build_chat_provider():  # type: ignore[no-untyped-def]
    s = get_settings()
    if s.ai_chat_provider == "anthropic" and s.anthropic_api_key:
        return AnthropicChatProvider(s.anthropic_api_key, s.ai_chat_model)
    return EchoChatProvider()


def build_embeddings_provider():  # type: ignore[no-untyped-def]
    s = get_settings()
    return HashEmbeddingsProvider(s.embedding_dim)
