"""The AI facade.

Every model call in Alppy goes through ``AiClient``. It does four things that
scattered call sites would not do consistently:

1. loads prompts from versioned files rather than inline strings,
2. runs the PII gate before anything leaves the process,
3. writes an audit row for every call — provider, model, prompt hash, tokens,
   latency, cost estimate, and never the content,
4. keeps the provider swappable by configuration.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alppy.ai.base import ChatRequest, ChatResponse
from alppy.ai.providers import build_chat_provider, build_embeddings_provider
from alppy.ai.scrub import assert_no_pii
from alppy.core.config import get_settings
from alppy.core.logging import get_logger

log = get_logger(__name__)
PROMPT_DIR = Path(__file__).parent / "prompts"

# Rough public list prices, CHF per million tokens. Used only for the cost
# estimate in the audit log, never for billing.
_COST_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (13.5, 67.5),
    "claude-sonnet-5": (2.7, 13.5),
    "claude-haiku-4-5-20251001": (0.9, 4.5),
    "echo": (0.0, 0.0),
}


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    version: str
    system: str
    user_template: str

    def render(self, **values: Any) -> tuple[str, str]:
        return (
            _fill(self.system, values),
            _fill(self.user_template, values),
        )


def _fill(template: str, values: dict[str, Any]) -> str:
    def repl(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        if key not in values:
            raise KeyError(f"prompt placeholder {{{{{key}}}}} was not supplied")
        return str(values[key])

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", repl, template)


def load_prompt(name: str, version: str = "v1") -> Prompt:
    path = PROMPT_DIR / f"{name}.{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"no prompt file {path.name}")
    raw = path.read_text(encoding="utf-8")
    body = raw.split("---", 2)[-1] if raw.startswith("---") else raw
    if "SYSTEM:" not in body or "USER:" not in body:
        raise ValueError(f"prompt {path.name} must contain SYSTEM: and USER: sections")
    system_part, user_part = body.split("USER:", 1)
    system = system_part.split("SYSTEM:", 1)[1].strip()
    return Prompt(name=name, version=version, system=system, user_template=user_part.strip())


@dataclass(slots=True)
class CallRecord:
    """What the audit log stores. Deliberately contains no prompt content."""

    provider: str
    model: str
    purpose: str
    prompt_name: str | None
    prompt_version: str | None
    prompt_sha256: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    cost_estimate_chf: float | None
    ok: bool
    error: str | None = None


def estimate_cost_chf(model: str, input_tokens: int | None, output_tokens: int | None) -> float:
    rate_in, rate_out = _COST_PER_MTOK.get(model, (0.0, 0.0))
    return round(
        (input_tokens or 0) / 1e6 * rate_in + (output_tokens or 0) / 1e6 * rate_out, 6
    )


class AiClient:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._chat = build_chat_provider()
        self._embeddings = build_embeddings_provider()
        self.records: list[CallRecord] = []

    @property
    def embedding_dim(self) -> int:
        return self._embeddings.dimensions

    @property
    def chat_is_grounded(self) -> bool:
        """False when the chat provider does not read its prompt (the offline
        stand-in). Callers that transcribe a document check this before they
        start; see ``alppy.ingest.pipeline``."""
        return bool(getattr(self._chat, "grounded", True))

    def complete(
        self,
        *,
        prompt: Prompt,
        purpose: str,
        values: dict[str, Any],
        student_names: list[str] | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.4,
    ) -> tuple[ChatResponse, CallRecord]:
        system, user = prompt.render(**values)
        digest = hashlib.sha256(f"{system}\n{user}".encode()).hexdigest()
        started = time.perf_counter()
        try:
            # The gate, inside the try so a rejection is *audited* like any
            # other failed call. It still runs before the provider does, so
            # nothing leaves the process either way — but a silent gate is an
            # unfalsifiable one, and a prompt that was blocked is exactly the
            # event an audit trail exists to record.
            assert_no_pii(system, names=student_names)
            assert_no_pii(user, names=student_names)

            response = self._chat.complete(
                ChatRequest(
                    system=system,
                    user=user,
                    max_tokens=max_tokens or self._settings.ai_max_output_tokens,
                    temperature=temperature,
                    purpose=purpose,
                )
            )
        except Exception as exc:
            record = CallRecord(
                provider=self._chat.name,
                model=self._settings.ai_chat_model,
                purpose=purpose,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
                prompt_sha256=digest,
                input_tokens=None,
                output_tokens=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                cost_estimate_chf=None,
                ok=False,
                error=type(exc).__name__,
            )
            self.records.append(record)
            log.warning("ai.call.failed", purpose=purpose, provider=self._chat.name)
            raise

        latency = int((time.perf_counter() - started) * 1000)
        model = response.model or self._settings.ai_chat_model
        record = CallRecord(
            provider=self._chat.name,
            model=model,
            purpose=purpose,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            prompt_sha256=digest,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=latency,
            cost_estimate_chf=estimate_cost_chf(
                model, response.input_tokens, response.output_tokens
            ),
            ok=True,
        )
        self.records.append(record)
        log.info(
            "ai.call",
            purpose=purpose,
            provider=self._chat.name,
            model=model,
            latency_ms=latency,
            prompt=f"{prompt.name}.{prompt.version}",
        )
        return response, record

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = self._embeddings.embed(texts)
        return vectors


def parse_json_response(text: str) -> dict[str, Any]:
    """Models sometimes wrap JSON in a code fence despite instructions."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("model response contained no JSON object")
    parsed: dict[str, Any] = json.loads(cleaned[start : end + 1])
    return parsed
