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


#: The built-in development defaults for the two secrets below. Named here so
#: the field default and the check that refuses it cannot drift apart: a
#: renamed literal that only lived in one of the two places would turn the
#: guard off silently, which is the one failure this guard cannot have.
DEV_SECRET_KEY = "dev-only-change-me"
DEV_S3_SECRET_KEY = "alppy-secret"

#: Hosts that mean "this machine". A production database URL naming one of
#: these is not a database that merely happens to be nearby — it is a laptop's
#: `.env` that was copied to a server, or a server that never had one.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


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
    secret_key: str = Field(default=DEV_SECRET_KEY, min_length=8)
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
    admin_database_url: PostgresDsn | None = None
    """The schema owner's DSN — alembic, and the CLI commands that sweep every
    school (``seed``, ``backfill-events``, ``purge-prompt-logs``).

    ``database_url`` names the low-privilege runtime role instead: no DDL, no
    ``BYPASSRLS``, every read filtered by the tenant bound onto the session
    (D84, ``alppy/db/tenancy.py``). Keeping the two apart is what makes
    row-level security worth turning on — policies are not enforced against
    whoever owns the table.

    ``None`` falls back to ``database_url``, so a single-role development
    database needs no configuration; ``_refuse_unsafe_deployment`` is what
    stops that fallback reaching a real school."""

    db_statement_timeout_ms: int = 15_000
    """Per-connection ceiling on any single statement, 0 to leave it to the role.

    The role carries its own (``infra/postgres/init.sql``) and that one cannot
    be dropped by editing a connection string. This is the per-process override
    above it: the worker sets it higher because a scan pipeline and an embedding
    write are legitimately slower than anything a request handler may do."""

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
    s3_secret_key: str = DEV_S3_SECRET_KEY

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
    """Per teacher, per process. Uvicorn workers multiply it — see
    ``deps.enforce_ai_rate_limit``."""

    # Not AI, still expensive: headless Chromium and synchronous pagination.
    render_rate_limit_per_min: int = 12
    """Per teacher, per process, like the AI bucket. A render is a Chromium
    process and a preview paginates inside the request handler, so this guards
    the API box rather than the provider bill."""

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
    max_upload_files: int = 120
    """Files per upload, checked before a single byte is read.

    `read_upload` caps each file, but a scan upload is a *list* and every
    payload is held in memory at once (`UploadPayload` is bytes, never a path),
    so without a count the ceiling is unbounded. The pile this has to fit is a
    class set photographed page by page: 30 copies of a four-page sheet is 120
    files, which is the largest thing a teacher legitimately selects at once.
    Note the worst case is still `max_upload_files x max_upload_mb`; lower
    either on a small box.
    """
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


    @model_validator(mode="after")
    def _refuse_unsafe_deployment(self) -> Settings:
        """Refuse to boot a real deployment on a laptop's settings.

        Every value checked here is already an environment variable with a
        development-friendly default, and that combination is the hazard: a
        deployment gets them by *saying nothing*, so the failure is a silence,
        not a mistake anyone makes. Each one is separately capable of exposing a
        roster of children's real names (docs/privacy.md):

        * ``secret_key`` signs the session cookie. Left at the published
          default, anyone holding this repository can mint a valid session for
          any teacher in any school.
        * ``demo_mode`` answers a cookieless request as the demo teacher. It is
          the only bypass of that cookie, and outside a demo there is nothing
          for it to bypass *to*.
        * ``database_url`` pointing at localhost in production is a laptop's
          ``.env`` that reached a server — the case ``ALPPY_ENV`` exists to make
          visible, and one that otherwise surfaces as a confusing connection
          error rather than as the misconfiguration it is.
        * ``s3_secret_key`` at its default opens the bucket holding scanned
          answer sheets: photographs of children's handwriting, names included.
        * ``admin_database_url`` unset — or naming the same role as
          ``database_url`` — means the API connects as the schema owner, and
          row-level security is not enforced against a table's owner. The
          policies are all there and none of them apply, which is the worst of
          the three possible states because it reads as the safe one (D84).

        Startup is the only honest place for this. A check at the point of use
        fires on the first teacher's first request, which is to say after the
        deployment was announced as working; ``env`` is known before the first
        connection is opened. Every problem is collected and reported together,
        because a fresh deployment usually has more than one and finding them
        one restart at a time is how a checklist gets abandoned half-done.

        ``local`` and ``ci`` are exempt: the defaults are *for* them.
        """
        if self.env not in ("staging", "production"):
            return self

        problems: list[str] = []
        if self.secret_key == DEV_SECRET_KEY:
            problems.append(
                "ALPPY_SECRET_KEY is still the built-in development default; it signs "
                "the session cookie, so anyone with this repository can forge one"
            )
        if self.s3_secret_key == DEV_S3_SECRET_KEY:
            problems.append(
                "ALPPY_S3_SECRET_KEY is still the built-in development default; it "
                "opens the bucket holding scanned answer sheets"
            )
        if self.demo_mode:
            problems.append(
                "ALPPY_DEMO_MODE is on; it answers a request with no session cookie "
                "as the demo teacher, which outside a demo is an open roster"
            )
        # A Postgres DSN may name several hosts for failover, and any one of them
        # being local is the same mistake — so check them all, not just the first.
        local = sorted(
            {h["host"] for h in self.database_url.hosts() if h["host"] in _LOCAL_HOSTS}
        )
        if local:
            problems.append(
                f"ALPPY_DATABASE_URL points at {', '.join(local)}; a {self.env} "
                "deployment reading a local database is a development .env that "
                "reached a server"
            )

        # Row-level security is not enforced against the role that owns the
        # table. An API connecting as the owner therefore has policies on every
        # table and protection from none of them — and it looks exactly like a
        # working deployment right up until a missed `.where()` returns another
        # school's roster (D84).
        app_user = next((h["username"] for h in self.database_url.hosts()), None)
        admin_user = (
            next((h["username"] for h in self.admin_database_url.hosts()), None)
            if self.admin_database_url is not None
            else None
        )
        if self.admin_database_url is None:
            problems.append(
                "ALPPY_ADMIN_DATABASE_URL is unset, so migrations would run as the "
                "same role the API does; that role owns the tables, and row-level "
                "security does not apply to a table's owner"
            )
        elif app_user is not None and app_user == admin_user:
            problems.append(
                f"ALPPY_DATABASE_URL and ALPPY_ADMIN_DATABASE_URL both connect as "
                f"{app_user!r}; the API must use the low-privilege role, or every "
                "row-level security policy is decoration"
            )

        if problems:
            raise ValueError(
                f"ALPPY_ENV={self.env!r} refuses these settings:\n  - "
                + "\n  - ".join(problems)
                + "\nSet each one in the environment, or run with ALPPY_ENV=local."
            )
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()
