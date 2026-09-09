# Platform Architecture

## Component diagram

```
  ┌──────────────── request path ────────────────┐
  browser ──▶ Cloudflare Worker (apps/web)
                 │  /api/v1/* rewritten to ALPPY_API_ORIGIN — one origin,
                 │  so the host-only alppy_session cookie works with no CORS
                 ▼
            FastAPI (apps/api)
                 │
                 ├─ get_db()            request-scoped Session, engine built lazily
                 ├─ get_current_teacher() ── read_session(cookie) → Teacher
                 ├─ get_tenant()        → Scope(school_id, teacher_id)
                 ├─ scoped_get(Model,id,scope)  ALWAYS adds school_id → 404 otherwise
                 ├─ UploadPayload       sniffed type, size cap, sanitised filename
                 ├─ ai_limiter          in-process token bucket, one per teacher
                 └─ load_optional(...)  a workstream that may not be installed
                 │
                 ▼
            router → service → models          every row: school_id (+ teacher_id)
                 │
                 └─ slow? ─▶ Job(QUEUED) + queue.enqueue(kind, job_id) ─▶ Redis
                                                                            │
  ┌──────────── worker path ─────────────┐                                  │
  arq worker (worker/main.py) ◀──────────────────────────────────────────────┘
       worker/tasks.py::<job kind name>
          1. load the Job row
          2. status=running, started_at
          3. call the owning module — imported LAZILY, inside the task
          4. on_progress(pct, message) → Job.progress / Job.message
          5. succeeded | failed + finished_at (+ error), result stored on the Job
       │
       ├─ ingest_source · extract_section       (corpus)
       ├─ render_sheet                          (sheets — Chromium)
       ├─ process_scan → chains grade_open_answers   (scanning → grading)
       └─ generate_adaptive · generate_feedback  (adaptive, feedback)

  storage.py ──▶ MinIO / R2 (S3 API) in production · LocalStorage in tests
  errors.py  ──▶ one envelope, four handlers, a request id on every failure
```

## Data flow

### `Scope` — tenancy as a parameter

```python
@dataclass(frozen=True)
class Scope:
    school_id: UUID
    teacher_id: UUID
```

Everything below the router takes it. A handler that forgets the tenant does not
type-check, rather than leaking rows — that is the design, and it is why `scoped_get` is
the one blessed way to fetch a row by id:

```python
row = scoped_get(db, Sheet, sheet_id, scope)   # school_id is always in the filter
```

A cross-tenant read is a **404**, not a 403. Telling a stranger that a resource exists is
itself a leak.

Two layers, not one: `school_id` is the tenant; `owned_class_ids(...)` narrows personal
data to the teacher who owns it. Subjects and curricula are shared across the staffroom
on purpose (D11).

### `Job` — the contract between a handler and the worker

```python
def pipeline_fn(db: Session, job: Job, *, on_progress: ProgressCB) -> dict[str, Any] | None
```

- May raise freely; the task catches, logs, writes `Job.error`, marks it failed.
- Must **not** commit or close `db` — the task owns the transaction boundary.
- Reads what it needs from `job.payload` (`source_id`, `sheet_id`, `scan_id`) and
  `job.school_id` for scoping.

`JobKind` values **are** the task function names, so the mapping is the identity and
there is no table to keep in sync. `TASK_NAMES` asserts it at import time.

`enqueue` is sync on purpose: every handler that enqueues is a plain `def` handler, which
FastAPI runs in a threadpool, so there is no running loop and `asyncio.run` is safe. It
still checks for a loop and moves to a worker thread if it finds one, so an `async def`
caller cannot deadlock. The pool is short-lived — enqueueing happens a handful of times
per lesson, never in a hot path.

### Storage

```python
storage_key(kind, school_id, entity_id, filename)   # every segment is server-side
sanitise_filename("../../etc/passwd")               # → "etc_passwd"
```

`LocalStorage` exists so tests and a bare checkout exercise the upload paths with nothing
running. The ingest loader reads **object storage**, not the filesystem, so the worker
does not need to share a disk with the API.

### The error envelope

```json
{"error": {"code": "not_found", "message": "class not found",
           "details": {"class_id": "..."}, "request_id": "a1b2c3"}}
```

Four handlers cover every route out of the app: `ApiError`, Starlette `HTTPException`,
Pydantic validation, and unhandled exceptions. Even an unroutable path returns the
envelope. The client switches on `code`; `message` is for the log and the developer,
never a teacher-facing string.

## Component interaction

### Auth

Argon2id with argon2-cffi's defaults (the OWASP-recommended ones), plus `needs_rehash` so
the parameters can be migrated later without a password reset. The session is an
`itsdangerous` timed signature carrying the teacher id and the school id — no server-side
store, so a request resolves its tenant without a round trip, and a tampered cookie fails
the signature.

Login does not distinguish an unknown email from a wrong password.

### Rate limiting

An in-process token bucket, one per teacher, on the AI endpoints. **Deliberately not
distributed**: it is a guard against one teacher holding the model budget, not a
security boundary.

### Health

`/health` reports each dependency (database, Redis, storage, browser) and **never
throws** — a health endpoint that fails when a dependency fails tells you nothing you did
not already know.

### The split deployment

`apps/web` runs on Cloudflare Workers; `apps/api` cannot, and not for want of effort.
Workers' Python is Pyodide, so `opencv-python-headless`, `pymupdf` and `pillow-heif` have
no wheels; Chromium does not fit a Worker; there is no Postgres and therefore no pgvector;
and nothing on the free plan runs a persistent process, so arq has nowhere to live.
**The scanner is the reason the deployment is split** (D25).

## Edge cases

- **A dead Redis.** → the job is marked **failed** rather than left `QUEUED` forever.
- **A missing optional native dependency.** → the worker still starts; only that task
  fails, because imports are lazy and inside the task.
- **A missing module for an optional workstream** (`load_optional`). → the endpoint
  reports it is unavailable; the *approval gate* is never optional and is imported
  directly.
- **An upload lying about its type.** → rejected on content sniffing.
- **An oversized or empty upload.** → rejected with the envelope and a code.
- **A migration that does not reproduce the models.** → invisible to the unit suite by
  construction; caught only by `scripts/check-schema-drift.py` on a real Postgres.
- **No object storage configured.** → `LocalStorage`, so a bare checkout still works.

---

**Companion:** [`README.md`](README.md) §2 for the load-bearing rules.
