"""Application settings. Every secret arrives via the environment; see .env.example."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

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

    secret_key_fallbacks: tuple[str, ...] = ()
    """Retired signing keys that are still ACCEPTED, never used to sign (D24).

    Without this, rotating `ALPPY_SECRET_KEY` invalidates every live session at
    the instant the new value is deployed: every teacher in every school is
    logged out mid-lesson, mid-scan, mid-review. A key that can only be rotated
    by causing an outage is a key that is never rotated, which is the state a
    leaked one must not find us in.

    With it, rotation is a procedure rather than an incident. Set the new key as
    `ALPPY_SECRET_KEY` and move the old one into this list, deploy, wait out
    `session_max_age_s` (12 hours — so, overnight), then remove it. Cookies
    signed with the old key keep working for exactly as long as they would have
    anyway, and new ones are signed with the new key from the first request.

    `itsdangerous` takes the key ring as a list on `secret_key`, where the LAST
    entry signs and every entry verifies — which is why `_serializer` builds
    `[*fallbacks, primary]` in that order. (Its `fallback_signers` argument is
    for rotating the *algorithm*, not the key; we name the digest explicitly and
    have never changed it.)

    JSON list in the environment, like `ALPPY_CORS_ORIGINS`:
    `ALPPY_SECRET_KEY_FALLBACKS='["the-previous-key"]'`."""

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

    db_pool_size: int = 10
    """Connections kept open per process (audit 03, B30).

    SQLAlchemy's default is 5, which the worker outgrows immediately: `max_jobs`
    is 4 and each job holds its session for the job's whole life — a scan
    pipeline is minutes, not milliseconds — so four concurrent jobs plus the
    heartbeat commits leave almost nothing for anything else."""

    db_max_overflow: int = 10
    db_pool_timeout_s: int = 30
    """How long a caller waits for a connection before failing loudly.

    Failing is the point. The default is also 30, and it is named here so that
    "the pool is exhausted" surfaces as an error with a number behind it rather
    than as a request that hangs."""

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

    production_s3_bucket: str | None = None
    """The production bucket's name, so staging can be refused if it matches.

    The one asset the PII gate cannot inspect. `alppy/ai/scrub.py` reads text
    and raises on a name; a scanned answer sheet is a photograph of a child's
    handwriting with their name written at the top, and no gate reads it — what
    keeps it safe is that it is only ever in one place. A staging deployment
    pointed at the production bucket puts test traffic, test credentials and a
    seeded fake roster in the same store as real children's work, and nothing
    downstream would notice. Set this on the staging deployment and the startup
    validator refuses the overlap."""

    storage_backend: Literal["local", "s3"] | None = None
    """Which object store to use. ``None`` means "decide from ``env``".

    It was read straight off ``os.environ`` in `alppy/storage.py`, which put it
    outside every check this class performs (audit 03, B25) — including the one
    below. A production deployment that never set it, or misspelled it, fell
    back to `local`: scanned answer sheets written to a container's temporary
    directory, working perfectly until the container restarted and every
    photograph of every child's handwriting was gone, with nothing anywhere
    saying so. That is now a refusal at startup."""

    storage_dir: str | None = None
    """Where the local backend keeps its files. ``None`` is a temp directory."""

    render_dir: str = "var/renders"
    """Where rendered PDFs are written before they are stored."""

    design_css_dir: str | None = None
    """Override for the print stylesheet directory, for tests and tooling."""

    seed_teacher_password: str | None = None
    """Password for the accounts `python -m alppy.cli seed --allow-staging`
    creates. Required in staging: the demo constants are published in this
    repository, so seeding staging with them would put two known logins in
    front of whatever staging can reach."""

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

    # --- Signing in ------------------------------------------------------
    # The only unauthenticated endpoint, and it was the only unlimited one:
    # every other bucket keys on a teacher id, which a caller who has not
    # signed in does not have. Two threats, two buckets, and both count
    # FAILURES rather than attempts — a teacher who types their own password
    # correctly is never throttled, however often they do it.
    login_rate_limit_per_min: int = 5
    """Failed sign-ins per account per minute. The primary guard: it bounds
    brute-forcing one teacher's password no matter how many addresses the
    attempts come from. A success clears the account's bucket, so this cannot
    be used to lock a teacher out of their own account for longer than it takes
    them to type the right password."""

    login_ip_rate_limit_per_min: int = 20
    """Failed sign-ins per client address per minute. Bounds credential
    stuffing across many accounts from one source, and with it the CPU cost:
    every attempt runs Argon2id by design, so an unlimited login endpoint is
    also a cheap way to exhaust the box the API is served from.

    Read `trusted_proxy_hops` before tuning this. With no proxy configuration
    every request appears to come from the reverse proxy, which collapses this
    into a single shared bucket for the whole school — which is why it is
    generous, and why the per-account bucket above is the primary guard rather
    than this one."""

    trusted_proxy_hops: int = 0
    """How many reverse proxies sit in front of the API.

    `X-Forwarded-For` is client-supplied and trivially spoofed, so it is
    ignored entirely at 0 (the default) and the socket address is used. Set it
    to the real number of hops — 1 behind a single load balancer — and the
    address that many places from the right of the chain is taken, which is the
    last one a proxy we control wrote. Never set it higher than the number of
    proxies actually in front: each extra hop is one entry of attacker-supplied
    text treated as a client address."""

    ai_daily_cap_chf: float = 20.0
    ai_monthly_cap_chf: float = 200.0
    """Per school, rolling 24 hours and rolling 30 days. 0 means no ceiling.

    There was no spend limit of any kind (D21): `cost_estimate_chf` was written
    on every call and never summed. The shapes that make that expensive are in
    the product already — one call per pupil for feedback, one per crop for
    open-answer grading, thousands for a textbook ingest.

    The numbers are chosen to bound a runaway without blocking real work: a
    full textbook ingest is on the order of 10 CHF, so 20 a day leaves room for
    one and refuses a loop that would do forty. Rolling windows rather than
    calendar ones, because a calendar month resets at midnight on the 1st,
    which is the one moment a runaway is guaranteed to be forgiven.

    Enforced at the API boundary (`deps.enforce_ai_budget`), which bounds what
    can be STARTED. A job already queued when the cap is reached runs to
    completion — the alternative abandons a class set half-graded, which is a
    worse thing to hand a teacher than a slightly overshot ceiling."""

    rate_limit_backend: Literal["auto", "memory", "redis"] = "auto"
    """Where a rate-limit bucket lives (D30).

    `memory` is a dict in this process: correct for one uvicorn worker, and
    silently worth N times its stated value for N workers, because each worker
    holds its own and the same teacher is load-balanced across all of them. A
    limit that is still configured, still enforced, and worth twice what it says
    is the worst of the three states.

    `redis` is one bucket per teacher shared by every process, refilled against
    Redis's own clock.

    `auto` — the default — means `redis` on a real deployment and `memory`
    everywhere else, so local development and the test suite need nothing
    running and a deployment gets the one that survives a second worker.
    `_refuse_unsafe_deployment` refuses `api_workers > 1` on `memory`."""

    api_workers: int = 1
    """uvicorn worker processes (D19).

    One process was serving a whole establishment: every teacher in a school
    printing between lessons, through a single event loop in front of
    synchronous SQLAlchemy. It stays 1 by default because that is right for
    `docker compose up` and for CI, and because raising it is a deliberate act
    with a prerequisite — see `rate_limit_backend`, which must not still be
    `memory` when this is raised. Size it against the container's CPU
    allocation, not against optimism: each worker is a full copy of the app."""

    # Not AI, still expensive: headless Chromium and synchronous pagination.
    render_rate_limit_per_min: int = 12
    """Per teacher, per process, like the AI bucket. A render is a Chromium
    process and a preview paginates inside the request handler, so this guards
    the API box rather than the provider bill."""

    # --- Access log (the read audit trail) -------------------------------
    #: Days to keep `AccessLog`. 0 or less means keep forever.
    #:
    #: 365, not the prompt log's 30, and opt-OUT rather than opt-in: a trail
    #: that expires inside a school year cannot answer a question asked at the
    #: end of one, and "who read my child's file" is asked late or not at all.
    access_log_retention_days: int = 365

    #: Days to keep `ModelCall`. 0 or less means keep forever.
    #:
    #: 1095 — three years — and opt-OUT like the access log, for the same
    #: reason and then some. This is the table a school shows an auditor to
    #: answer "did any of our data go to provider X", and that question arrives
    #: late or not at all: a trail that expired inside a school year cannot
    #: answer one asked at the end of one, and a procurement review asks about
    #: the year before last.
    #:
    #: It can afford to be long because the row is content-free by construction
    #: — provider, model, purpose, a hash of the prompt, token counts, a cost
    #: estimate. Never the prompt, never a name. The thing that holds content is
    #: `PromptLog`, which is off by default, capped, and swept at 30 days.
    #:
    #: A number rather than "forever" because an unbounded table is a decision
    #: nobody took: this one is written on EVERY model call, so a school running
    #: full ingests accumulates millions of rows against a question that is
    #: never asked about 2029.
    model_call_retention_days: int = 1095

    # --- Prompt log (debugging; NOT the audit trail) ---------------------
    # `ModelCall` stays content-free whatever these say. This is the separate,
    # opt-in store of what was actually sent — see models.PromptLog.
    ai_prompt_log_enabled: bool = False
    ai_prompt_log_retention_days: int = 30
    ai_prompt_log_max_chars: int = 20_000
    """Per field, not per row. An `extract_exercises` prompt carries a whole
    textbook chunk and a full ingest is thousands of calls; without a cap the
    debugging aid becomes the largest table in the database."""

    # --- Jobs and the clients they hold open ----------------------------
    job_timeout_s: int = 600
    """How long the worker gives one job before arq cancels it.

    Read by ``WorkerSettings`` and, just as importantly, by the code that has
    to decide whether a ``RUNNING`` row still has anybody behind it. A job
    cancelled at this ceiling leaves its ``asyncio.to_thread`` thread running
    with nothing recording the fact, so ``RUNNING`` outlives the process that
    wrote it (audit 03, B9)."""

    job_stale_after_s: int = 1_200
    """When a ``RUNNING`` job with no recent heartbeat is presumed dead.

    Twice ``job_timeout_s`` by default — comfortably past the point where arq
    would have cancelled the job — so a slow-but-alive job is never reaped out
    from under itself. Confirmation reads this: `grading_in_progress` refused a
    pile indefinitely because a stuck row said a grader was still coming, and
    there was no route to clear it."""

    sentry_dsn: str | None = None
    """Error tracking (D8). Unset — the default — installs nothing at all.

    There is no error tracker, no metrics and no alerting: a failure during a
    lesson is unrecoverable for that lesson, and the only way anybody learns of
    one today is a teacher mentioning it afterwards. `core/observability.py` is
    the integration, complete and inert until this is set; the vendor account is
    a human act and there is no reason the two should wait for each other.

    Read `observability.before_send` before turning this on. A
    default-configured tracker sends the request body, and on this API that body
    is transcriptions of what a named child wrote, presigned links to
    photographs of their handwriting, roster names, or a password."""

    sentry_traces_sample_rate: float = 0.05
    """Performance traces, if any. Low on purpose: a scan pipeline is hundreds
    of spans and what is missing here is error reporting, not an APM product."""

    health_detail_token: str | None = None
    """Shared secret for `GET /api/v1/health/detail` (D35).

    `/health` answers `ok` or `degraded` to anyone, because a load balancer
    carries no cookie and a readiness probe that needs one is a readiness probe
    that fails. It used to answer with the *breakdown* as well — which of
    Postgres, Redis and the object store was down — and that is a map of the
    deployment's internals handed to an unauthenticated reader, most useful at
    exactly the moment we are least able to respond.

    So the breakdown moved to its own route, and this is what opens it. Unset,
    the route answers 404 outside `local`/`ci` — the same shape as the OpenAPI
    document, and for the same reason: a thing that does not exist cannot be
    probed. `local` and `ci` leave it open, because that is where it is read.

    A token rather than a network check on purpose. Behind a reverse proxy every
    request arrives from the proxy, so "is the peer on a private address" is
    true for the whole internet; a real internal-only path is an infrastructure
    decision (a second listener, a private service port) that does not exist yet
    — see docs/audits/07, Phase 3."""

    worker_max_jobs: int = 4
    """How many jobs one arq worker process runs at once.

    A deliberate, visible number rather than a literal in ``WorkerSettings``
    (D22). It is load-bearing twice over: ``db_pool_size`` is sized against it
    (each job holds a session for its whole life), and a scan pipeline pins a
    core in OpenCV, so raising it past the container's CPU allocation buys
    contention rather than throughput. Raise the pool with it or the worker
    blocks on itself while Postgres sits idle."""

    provider_timeout_s: float = 60.0
    """Per-request ceiling on a chat/vision provider call.

    The SDKs default to 600s with 2 retries, so ONE logical call could hold for
    about half an hour inside a job whose own ceiling is 600s — the job is
    cancelled long before the HTTP call gives up, which is how a provider blip
    became a stuck ``RUNNING`` row rather than a visible failure (B10)."""

    provider_connect_timeout_s: float = 10.0
    provider_max_retries: int = 1

    provider_batch_timeout_s: float = 180.0
    """The ceiling for a batched generation call.

    Separate because the work is not comparable: a vision call over one crop
    and a generation call over eight plans do not deserve the same budget, and
    giving them one means either strangling the batch or letting a single crop
    hang for three minutes."""

    storage_connect_timeout_s: float = 5.0
    storage_read_timeout_s: float = 30.0
    storage_max_retries: int = 3

    # --- Uploads --------------------------------------------------------
    scan_image_retention_days: int = 400
    """How long a scanned page image is kept. 0 or less means keep forever.

    **400 days: a school year plus one term** (audit 07, D3). This used to
    default to 0, and that was the right call for exactly as long as nothing was
    scheduled to enforce any number — a window a developer invented would have
    silently destroyed the evidence behind a mark the week before a parent
    contested it. What changed is that the alternative stopped being "no
    deletion yet" and started being "an unbounded, permanently growing store of
    photographs of named children's handwriting", which fails nLPD
    proportionality on the first pilot day and is the one liability that grows
    on its own.

    So: a default, deliberately on the generous side, chosen so a mark given in
    June is still appealable against the page the following spring, and a
    pupil's October copy is gone the November after. It is a starting position,
    not a school's policy — a school that states its own sets
    `ALPPY_SCAN_IMAGE_RETENTION_DAYS`, and a shorter one is the easier argument
    to make, not the harder.

    Per-school and per-canton windows are NOT supported: this is one number for
    the deployment. Making it vary is a schema change (a column on `School`,
    read by `purge-scan-images` per pile) and belongs with the data model rather
    than here — flagged, not built.

    Note what a purge does and does not take. The grade, the transcription and
    the verdict live on `Detection` and survive: what is lost is the ability to
    re-crop or to look at the page again. B7's generation pinning is what makes
    re-cropping unnecessary, so this is a narrower loss than it was.

    Enforced nightly at 03:30 by `alppy/worker/cron.py` (D2). Before that
    landed, setting this changed nothing at all."""

    max_image_pixels: int = 50_000_000
    """Ceiling on an uploaded image's DECLARED pixel count (audit 03, B15).

    The byte cap below cannot stand in for this: `cv2.imdecode` allocates the
    decoded raster, so a 40 KB PNG declaring 60000x60000 asks for about 10 GB
    and takes the worker with it — and compression is precisely what makes the
    file small. 50 Mpx is comfortably above any phone or flatbed a teacher will
    use (a 48 Mpx phone photograph is ~12 Mpx by default) and far below
    anything that threatens the worker."""

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
    """Browser origins allowed to call the API *with the session cookie*.

    `main.create_app` passes these to `CORSMiddleware` with
    `allow_credentials=True`, which is what lets the web app authenticate at
    all — and what makes this list a trust boundary rather than a convenience.
    `_refuse_unsafe_deployment` is why the development default here is safe to
    ship.
    """

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def resolved_storage_backend(self) -> str:
        """The backend actually in force, with the env-derived default applied.

        One place, so `build_storage` and `_refuse_unsafe_deployment` cannot
        disagree about what is configured — the whole failure mode of B25 was a
        setting the safety check could not see."""
        if self.storage_backend is not None:
            return self.storage_backend
        return "local" if self.env == "ci" else "s3"

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
        * ``cors_origins`` is handed to the CORS middleware with
          ``allow_credentials=True``, so it decides which sites may make a
          browser send the session cookie to us. A wildcard, or a leftover
          ``localhost``, is the roster read cross-origin from the teacher's own
          logged-in browser.
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
        if self.api_workers > 1 and self.rate_limit_backend == "memory":
            problems.append(
                f"ALPPY_API_WORKERS is {self.api_workers} while ALPPY_RATE_LIMIT_BACKEND is "
                "'memory'; each worker would hold its own buckets, so every rate limit — "
                "including the one in front of sign-in — is silently multiplied by the "
                "worker count. Use 'redis' (or 'auto') when running more than one worker"
            )
        if DEV_SECRET_KEY in self.secret_key_fallbacks:
            problems.append(
                "ALPPY_SECRET_KEY_FALLBACKS contains the built-in development default; a "
                "retired key in that list is still ACCEPTED, so this forges sessions exactly "
                "as well as setting it as the primary would"
            )
        if self.s3_secret_key == DEV_S3_SECRET_KEY:
            problems.append(
                "ALPPY_S3_SECRET_KEY is still the built-in development default; it "
                "opens the bucket holding scanned answer sheets"
            )
        if self.resolved_storage_backend == "local":
            problems.append(
                "ALPPY_STORAGE_BACKEND resolves to 'local', so scanned answer sheets "
                "are written to a temporary directory that does not survive a "
                "container restart — set it to 's3'"
            )
        if self.demo_mode:
            problems.append(
                "ALPPY_DEMO_MODE is on; it answers a request with no session cookie "
                "as the demo teacher, which outside a demo is an open roster"
            )
        # `allow_credentials=True` is not optional for us — the session cookie is
        # the only authentication the web app has — and it makes this list the
        # whole of the cross-origin boundary. Starlette does not silently protect
        # us from a wildcard here: with credentials on, `"*"` makes it *reflect*
        # the requesting origin, so any page on the internet can read a teacher's
        # roster in the teacher's own browser. That is the same exposure
        # `demo_mode` is refused for, reached without touching a session.
        for origin in self.cors_origins:
            host = urlsplit(origin).hostname
            if "*" in origin:
                problems.append(
                    f"ALPPY_CORS_ORIGINS contains {origin!r}; the cookie is sent with "
                    "cross-origin requests, so a wildcard lets any site read a "
                    "teacher's roster from the teacher's own browser (and Starlette "
                    "matches an origin literally — a pattern that is not exactly '*' "
                    "additionally matches nothing at all)"
                )
            elif host in _LOCAL_HOSTS:
                problems.append(
                    f"ALPPY_CORS_ORIGINS contains {origin!r}; a {self.env} deployment "
                    "trusting a developer's machine is a development .env that reached "
                    "a server"
                )
        if not self.cors_origins:
            # Fails closed rather than open, and is still refused: nobody sets it
            # to nothing on purpose, and the symptom is every browser request from
            # the web app failing CORS with a healthy-looking API behind it.
            problems.append(
                "ALPPY_CORS_ORIGINS is empty, so the web app cannot call the API at "
                "all; name the origins it is served from"
            )

        # Scanned answer sheets. Staging generates its own roster and its own
        # scans; if it writes them into production's bucket, the two are mixed
        # in the one store whose contents no gate can read (docs/privacy.md).
        if self.production_s3_bucket and self.s3_bucket == self.production_s3_bucket:
            problems.append(
                f"ALPPY_S3_BUCKET is {self.s3_bucket!r}, the same bucket as "
                "ALPPY_PRODUCTION_S3_BUCKET; scanned answer sheets are photographs "
                "of children's handwriting and the two environments must not share "
                "the store that holds them"
            )
        if self.env == "staging" and self.production_s3_bucket is None:
            problems.append(
                "ALPPY_PRODUCTION_S3_BUCKET is unset on a staging deployment, so "
                "nothing can tell whether ALPPY_S3_BUCKET points at production's "
                "store of scanned answer sheets; name it even if it differs"
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
