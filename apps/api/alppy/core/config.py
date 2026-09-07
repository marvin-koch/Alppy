"""Application settings. Every secret arrives via the environment; see .env.example."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

Locale = Literal["fr", "de", "en"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="ALPPY_", extra="ignore", case_sensitive=False
    )

    env: Literal["local", "ci", "staging", "production"] = "local"
    debug: bool = False
    secret_key: str = Field(default="dev-only-change-me", min_length=8)
    session_cookie: str = "alppy_session"
    session_max_age_s: int = 60 * 60 * 12

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
    ai_chat_provider: Literal["anthropic", "echo"] = "anthropic"
    ai_chat_model: str = "claude-sonnet-5"
    anthropic_api_key: str | None = None

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
    ai_rate_limit_per_min: int = 20

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
