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

from alppy.ai.base import ChatRequest, ChatResponse, ImagePart
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
    "gpt-5": (1.1, 9.0),
    "gpt-5-mini": (0.23, 1.8),
    "gpt-5-nano": (0.045, 0.36),
    "gpt-4.1": (1.8, 7.2),
    "gpt-4.1-mini": (0.36, 1.44),
    "echo": (0.0, 0.0),
}
"""CHF per million tokens. Rough by construction: an estimate on the audit row,
never a bill. Vendors publish in USD, so a new row carries a conversion.

The ``gpt-*`` rows are UNVERIFIED placeholders. They must be checked against
OpenAI's published prices before the default provider moves — until then they
make the cost column plausible rather than correct, which is the one thing an
estimate must not be when someone budgets from it."""


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


@dataclass(slots=True)
class PromptTranscript:
    """What the *prompt log* stores: the call, with its content.

    The twin of ``CallRecord``, and the difference between them is the whole
    design. ``CallRecord`` is the audit row — content-free, safe to keep. This
    is the debugging row — content, opt-in, swept.

    Captured here rather than in a provider wrapper for two reasons. The prompt
    name and version live at this level and a wrapper would lose them; and a
    wrapper has to re-declare ``grounded`` on behalf of the provider it wraps,
    which is one forgotten attribute away from letting the offline stand-in
    claim it read a textbook page (I-ai-04).
    """

    provider: str
    model: str
    purpose: str
    prompt_name: str | None
    prompt_version: str | None
    prompt_sha256: str
    system_text: str | None
    user_text: str | None
    response_text: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    ok: bool
    error: str | None = None


def _clip(text: str | None, limit: int) -> str | None:
    """Truncate, and say so. A silently shortened prompt is worse than no prompt:
    it reads as the thing that was sent."""
    if text is None or len(text) <= limit:
        return text
    return f"{text[:limit]}\n\u2026[truncated at {limit} characters]"


def estimate_cost_chf(model: str, input_tokens: int | None, output_tokens: int | None) -> float:
    """The audit row's cost estimate. Zero for a model the table does not know.

    An unpriced model reports 0.00 CHF on every row, which reads as "this cost
    nothing" rather than "nobody told me the price" — and docs/privacy.md offers
    that column as budget accounting. So the gap is logged once per call rather
    than being invisible; the estimate still degrades to zero, because a wrong
    number would be worse than an absent one."""
    rates = _COST_PER_MTOK.get(model)
    if rates is None:
        log.warning("ai.cost.unknown_model", model=model)
        return 0.0
    rate_in, rate_out = rates
    return round(
        (input_tokens or 0) / 1e6 * rate_in + (output_tokens or 0) / 1e6 * rate_out, 6
    )


class AiClient:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._chat = build_chat_provider()
        self._embeddings = build_embeddings_provider()
        self.records: list[CallRecord] = []
        self.transcripts: list[PromptTranscript] = []
        self._drained_records = 0
        self._drained_transcripts = 0

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
        images: tuple[ImagePart, ...] = (),
    ) -> tuple[ChatResponse, CallRecord]:
        """One model call, gated and audited.

        ``images`` ride along for a vision purpose. The PII gate below reads
        text and only text; an image is kept clean by where it was cut from,
        not by inspection here — see ``ImagePart`` and docs/privacy.md."""
        system, user = prompt.render(**values)
        hasher = hashlib.sha256(f"{system}\n{user}".encode())
        for image in images:
            # The audit hash covers the image too: the same crop and the same
            # prompt are the same call, and a different crop is a different one.
            hasher.update(hashlib.sha256(image.data).digest())
        digest = hasher.hexdigest()
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
                    images=images,
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
            # No content on a failure, and deliberately none even when the
            # prompt log is on. The commonest failure here is the PII gate, and
            # the string that fired it is BY DEFINITION the one carrying a
            # roster name — writing it down would make the debugging aid the
            # leak the gate exists to prevent. `ModelCall` already proves the
            # gate fired (I-ai-07); that is what an investigation needs.
            self._transcribe(
                record,
                system=None,
                user=None,
                response_text=None,
            )
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
        self._transcribe(record, system=system, user=user, response_text=response.text)
        log.info(
            "ai.call",
            purpose=purpose,
            provider=self._chat.name,
            model=model,
            latency_ms=latency,
            prompt=f"{prompt.name}.{prompt.version}",
        )
        return response, record

    def drain(self) -> tuple[list[CallRecord], list[PromptTranscript]]:
        """Everything accumulated since the last drain, and mark it taken.

        A watermark rather than a clear, because ``records`` is read after the
        fact — ``_generate`` reaches for ``records[-1]`` to audit a call that
        then failed to parse. It also makes flushing idempotent, which is what
        lets one client be flushed per call *or* once per job without writing a
        row twice.
        """
        records = self.records[self._drained_records :]
        transcripts = self.transcripts[self._drained_transcripts :]
        self._drained_records = len(self.records)
        self._drained_transcripts = len(self.transcripts)
        return records, transcripts

    def _transcribe(
        self,
        record: CallRecord,
        *,
        system: str | None,
        user: str | None,
        response_text: str | None,
    ) -> None:
        """Accumulate the content row, when a school has turned the log on.

        Accumulated rather than written: the client must stay usable with no
        database (the seed loader and every test construct one directly), so the
        caller flushes — `ai.audit.flush`. Same split, and same reason, as
        `records` and `record_calls`."""
        if not self._settings.ai_prompt_log_enabled:
            return
        limit = self._settings.ai_prompt_log_max_chars
        self.transcripts.append(
            PromptTranscript(
                provider=record.provider,
                model=record.model,
                purpose=record.purpose,
                prompt_name=record.prompt_name,
                prompt_version=record.prompt_version,
                prompt_sha256=record.prompt_sha256,
                system_text=_clip(system, limit),
                user_text=_clip(user, limit),
                response_text=_clip(response_text, limit),
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                latency_ms=record.latency_ms,
                ok=record.ok,
                error=record.error,
            )
        )

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
