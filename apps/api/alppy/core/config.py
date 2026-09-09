"""Application settings. Every secret arrives via the environment; see .env.example."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Locale = Literal["fr", "de", "en"]

#: What each provider is asked for when ``ai_chat_model`` is left empty.
_DEFAULT_CHAT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-5",
    "echo": "echo",
}

#: Model-id prefixes that belong unmistakably to one provider. Used only to
#: refuse a *known-foreign* pair — an unrecognised prefix is left alone, because
#: Azure deployment names and fine-tune ids are legitimate and unguessable.
_MODEL_PREFIX_OWNER: tuple[tuple[str, str], ...] = (
    ("claude-", "anthropic"),
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
)


def _known_owner(model: str) -> str | None:
    for prefix, owner in _MODEL_PREFIX_OWNER:
        if model.startswith(prefix):
            return owner
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="ALPPY_", extra="ignore", case_sensitive=False
    )

    env: Literal["local", "ci", "staging", "production"] = "local"
    debug: bool = False
    secret_key: str = Field(default="dev-only-change-me", min_length=8)
    session_cookie: str = "alppy_session"
    session_max_age_s: int = 60 * 60 * 12

    # --- Demo mode. OFF unless explicitly switched on.
    #
    # A request with no session cookie resolves to `demo_teacher_email` instead
    # of 401, so a demo instance can be clicked through without an account.
    #
    # Default False, and deliberately not derived from `env` or `debug`: the
    # thing this disables is the only guard between an open URL and a roster of
    # children's real first and last names (`Student.first_name`,
    # docs/privacy.md). A flag that could switch itself on from some other
    # signal is one that will eventually switch itself on somewhere real.
    demo_mode: bool = False
    demo_teacher_email: str = "demo@alppy.ch"

    # Declared as strings and validated into DSNs by pydantic on load; the
    # annotations describe the parsed value, not the literal default.
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+psycopg://alppy:alppy@localhost:5432/alppy")
    )
    redis_url: RedisDsn = Field(default=RedisDsn("redis://localhost:6379/0"))

    # S3-compatible object storage (MinIO locally).
    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_endpoint_url: str | None = None
    """Host-visible object-storage origin, when it differs from the internal one.

    In Docker the API reaches MinIO at ``http://minio:9000``, and it signs
    download URLs against that — a hostname that only exists on the compose
    network. The teacher's browser resolves nothing and the download fails. Set
    this to the origin the browser can reach (``http://localhost:9000``) and the
    host is swapped after signing; SigV4 does not cover the Host header for a
    presigned GET, so the signature stays valid."""
    s3_region: str = "eu-central-1"
    s3_bucket: str = "alppy"
    s3_access_key: str = "alppy"
    s3_secret_key: str = "alppy-secret"

    # --- AI layer -------------------------------------------------------
    # Provider is configurable by design: a Swiss school may require that no
    # data leaves EU/CH infrastructure (docs/privacy.md).
    ai_chat_provider: Literal["openai", "anthropic", "echo"] = "openai"
    ai_chat_model: str = ""
    """Empty means "whatever this provider's default is" — see
    ``_DEFAULT_CHAT_MODELS`` and the validator below.

    It is empty rather than a literal because the provider and the model are one
    setting wearing two names. A literal default here means that changing
    ``ai_chat_provider`` alone ships a Claude model id to OpenAI, which 404s every
    call in the product — and the failure path in ``AiClient.complete`` records
    ``settings.ai_chat_model`` on the audit row, so the trail would name a model
    that was never called."""
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    ai_embeddings_provider: Literal["local", "hash"] = "hash"
    ai_embeddings_model: str = "intfloat/multilingual-e5-large"
    embedding_dim: int = 1024

    # --- Background work ------------------------------------------------
    # False runs the API with no worker behind it: jobs are written but never
    # queued. Only the test suite and a deliberate single-process deployment
    # should turn this off — with it off, nothing a teacher uploads is ever
    # ingested.
    job_queue_enabled: bool = True

    # Hard cap so a runaway prompt cannot bill the school.
    ai_max_output_tokens: int = 2048
    ai_max_output_tokens_batch: int = 8192
    """The cap for one call that answers several plans at once.

    The per-call cap above is sized for one student's handful of exercises. A
    batched generation call carries every plan in the run, and 2048 tokens does
    not hold eight plans of four multiple-choice items — the response comes back
    truncated, which is to say unparsable, and the whole class gets nothing. The
    batch path sizes its own budget and clamps it here."""
    ai_rate_limit_per_min: int = 20

    # --- Prompt log (debugging; NOT the audit trail) ---------------------
    # `ModelCall` stays content-free whatever these say. This is the separate,
    # opt-in store of what was actually sent — see models.PromptLog.
    ai_prompt_log_enabled: bool = False
    ai_prompt_log_retention_days: int = 30
    ai_prompt_log_max_chars: int = 20_000
    """Per field, not per row. An `extract_exercises` prompt carries a whole
    textbook chunk and a full ingest is thousands of calls; without a cap the
    debugging aid becomes the largest table in the database."""

    # --- Uploads --------------------------------------------------------
    max_upload_mb: int = 50
    allowed_upload_types: tuple[str, ...] = (
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        # An iPhone photographs in HEIC unless it is told otherwise, and
        # photographing the copies is the workflow, not a fallback.
        "image/heic",
        "image/heif",
    )

    default_locale: Locale = "fr"
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @model_validator(mode="after")
    def _resolve_chat_model(self) -> Settings:
        """Fill the model from the provider, and refuse a pair that cannot work.

        Startup is the only place this can be caught cheaply. A Claude model id
        sent to OpenAI is a 404 on every generation, every extraction and every
        grade — and because the offline provider is the fallback for a *missing*
        key rather than a wrong one, nothing degrades gracefully. A `Literal`
        already makes a misspelled provider a startup crash; this makes a
        mismatched pair one too.
        """
        if not self.ai_chat_model:
            self.ai_chat_model = _DEFAULT_CHAT_MODELS[self.ai_chat_provider]
            return self
        owner = _known_owner(self.ai_chat_model)
        if owner is not None and owner != self.ai_chat_provider:
            raise ValueError(
                f"ALPPY_AI_CHAT_MODEL={self.ai_chat_model!r} is a {owner} model, but "
                f"ALPPY_AI_CHAT_PROVIDER is {self.ai_chat_provider!r}. Set both, or "
                f"leave the model empty to take that provider's default."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
