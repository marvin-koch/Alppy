# Platform

**Status:** describes `main` as of 2026-09-09
**Audience:** developers, LLM agents, reviewers

---

## 1 · What it does

The ground every other feature stands on: who is signed in, which school's rows they may
see, where slow work runs, where bytes are stored, and what a failure looks like.

```
  browser
     │  alppy_session  — an itsdangerous timed signature, host-only cookie
     ▼
  api/deps.py::get_current_teacher ──▶ get_tenant ──▶ Scope(school_id, teacher_id)
     │                                                  │
     │  every handler takes it; scoped_get() is the     │
     │  one blessed way to fetch a row by id            │
     ▼                                                  ▼
  routers ──▶ services ──▶ models (every row carries school_id)
     │
     │  slow work? → write a Job row, worker/queue.enqueue(), return
     ▼
  Job(kind, status, progress, message, payload, result, error)
     │            arq / Redis
     ▼
  worker/tasks.py — the ONLY place a model call, OpenCV or Chromium runs
     │  loads the Job, running → progress callback → succeeded | failed
     ▼
  GET /jobs/{id}   the client polls

  storage.py   S3-compatible (MinIO / R2) in production, local filesystem in tests
  errors.py    one envelope for every failure, with a request id
```

### Key properties

1. **Tenancy is in the type system.** Everything below a router takes `school_id` as a
   required argument, so a handler that forgets the tenant does not type-check rather
   than leaking rows.
2. **Nothing blocks a request handler on a model call.** Long work goes to arq and
   reports progress through `Job`.
3. **The stack runs with one command**, offline, with a demo seed:
   `docker compose up`.

---

## 2 · Invariants (load-bearing)

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-platform-01 | The session is a **signed cookie**, no server-side store; a tampered cookie fails the signature. | `core/security.py`, `api/deps.py::get_current_teacher` | The tenant is resolved without a round trip, and cannot be forged | A tampered cookie selecting another school |
| I-platform-02 | **Every row carries `school_id`**, and `scoped_get` always adds it to the filter — 404, never 403. | `db/base.py::SchoolScopedMixin`, `deps.scoped_get` | Multi-tenant data in a shared corpus | One school reading another's classes, sheets or books |
| I-platform-03 | **Ownership is per teacher** where it is personal (`owned_class_ids`), on top of tenancy. | `services/enrollment.py` | A colleague's class is not your class | A staffroom-wide roster leak |
| I-platform-04 | Curriculum data (LP21, PER) is the **one deliberate exception** to tenancy. | `models`, D11 | It is public reference data shared by every tenant | Duplicated curricula per school |
| I-platform-05 | **Nothing blocks a request handler on a model call, OpenCV or Chromium.** | `worker/tasks.py`, every `POST` that returns a `Job` | A class of twenty inside a handler is a timeout with half-written state behind it | 504s and partial batches |
| I-platform-06 | A `Job` row **without an enqueue is a note nobody reads.** `JobKind` values *are* the task names, asserted at import. | `worker/queue.py::TASK_NAMES`, `enqueue` | The worker listens on Redis and never polls Postgres | A spinner that never stops |
| I-platform-07 | **A client-supplied filename never becomes a storage path.** | `storage.py::sanitise_filename`, `storage_key` | `../../etc/passwd` | Path traversal in an upload |
| I-platform-08 | **One error envelope for every failure**, carrying a request id; `message` is for developers, never a teacher-facing string. | `api/errors.py::install_error_handlers` | The client switches on `code`; teacher-facing text is localised client-side | An untranslated internal message shown to a teacher |
| I-platform-09 | A student's **UID is minted by their home class** (`Student.home_class_id`) and never changes when they are enrolled elsewhere. | `services/class_service.py::add_students`, `sheets/uid_code.py`, `uq_student_uid` | The UID is printed on paper and read by the detector; a UID that moved with enrollment would orphan every sheet already in a pile | Last term's pile decodes to the wrong child, or to nobody |
| I-platform-10 | **Enrollment widens who may read a student, never which school or year.** `enroll` asserts the student and the class share `school_id` **and** `school_year_id`. | `services/class_service.py::enroll`, `owned_class_ids` | I-platform-02 and I-platform-03 must survive a student belonging to several classes | A roster leak across the staffroom, or a UID whose per-year uniqueness no longer holds |
| I-platform-11 | **Ownership is assignment-based, and has two grains.** A teacher owns a class iff they are its `head_teacher_id` **or** hold a `class_teacher_subject` row in it. `owned_*` gates a class and its children; `taught_*` gates what a teacher makes or marks. Both live in one module. | `services/enrollment.py::owned_class_ids`, `::taught_here` | Who you may name is class-grained; what you may see about them is pair-grained | A co-teacher locked out of the class they teach, or a colleague's branch in your matrix |
| I-platform-12 | **An assignment widens who teaches, never which school.** `assign_branch` asserts the teacher, class and subject share a school, and declares the branch before assigning it. | `services/class_service.py::assign_branch`, `declare_subject`, `fk_class_teacher_subject_class_subject` | The table carries no `school_id`, so the write path is what closes that end (the I-platform-10 analogue) | A teacher from another school holding a branch in your class |
| I-platform-13 | **`class_subject` is what the class STUDIES; `class_teacher_subject` is who TEACHES it.** The Branch nav reads the first, narrowed by the second — never the second alone. | `class_service::taught_subject_ids_for_class` / `declared_subject_ids_for_class`, `tree_service.class_tree` | Deriving the branch list from staffing is D57's circularity in a new costume | A Branch vanishes from the nav the moment its teacher is unassigned, taking its Themes and sheets with it |
| I-platform-14 | **The tenant comes from the SESSION, not from the teacher's row.** `home_school_id` is where an account is based; `teacher_school` is where it may work; a cookie naming a school that is not a membership is refused at the door, by a `SELECT`. | `api/deps.py::get_membership` | A teacher may work at several schools, so their row cannot answer which one this request is for | A teacher who left a school goes on reading it, or one school's screen shows another's classes |
| I-platform-15 | **What a teacher makes or marks is pair-grained.** A sheet, a pile, an agenda entry and a home-card count are visible only in a branch the reader takes. The two carve-outs are deliberate: the roster (names and UIDs) and an unmatched pile (uploader-only, because it has no branch yet). | `services/enrollment.py::taught_here`, `sheet_service.get_sheet`, `scan_service._owned_scan`, `api/v1/timeline.py` | A colleague sharing a class is not a colleague sharing a subject | A history teacher's marking in a maths teacher's queue, or a pile that changes hands when its sheet is chosen |
| I-platform-16 | **Switching school is re-issuing the cookie**, and the membership is proved before it is minted. A school the teacher does not work at reads as *missing*, never forbidden. | `api/v1/auth.py::switch_school`, `class_service::schools_for_teacher` | The tenant lives in the session (I-platform-14), so nothing else has to change to move it | One school's screens showing another's classes, or a 403 confirming a school the caller may not open |
| I-platform-17 | **Renaming is not re-identifying.** A label may always change; `Subject.key`, `Student.uid`/`number` and — once a class has pupils — `Class.code` may not. Deleting a Student is the ONLY operation allowed to destroy evidence, it takes the pupil's uid typed back, and only the head teacher of their home class may do it. | `services/nouns_service.py`, `schemas` (the fields are absent, not guarded) | The identifier is printed on paper and the pile does not update (I-platform-09) | Last term's pile decodes to nobody, or the wrong child is erased from the wrong row |
| I-platform-18 | **The corpus is shared for reading, not for deleting.** Chapter and source deletes refuse a caller who does not hold that branch in any class of this school; every other delete refuses with a COUNT of what still points at it. | `nouns_service::_assert_teaches_subject`, `delete_chapter`, `delete_source` | `Exercise.source_id` is SET NULL, so deleting a textbook would silently strip provenance rather than fail | A term of worksheets off the tree, or exercises that no longer say which book they came from |

---

## 3 · Module map

| Path | Owns | Depends on |
|---|---|---|
| `alppy/core/security.py` | Argon2id password hashing, the signed session cookie | argon2-cffi, itsdangerous |
| `alppy/core/config.py` | `Settings` — providers, models, limits, storage, rate limits | pydantic-settings |
| `alppy/core/logging.py` | Structured logging | — |
| `alppy/core/uid.py` | `parse_uid` / `format_uid` — strict, because a misread UID files answers under the wrong child | — |
| `alppy/api/deps.py` | `get_db`, `get_current_teacher`, `get_tenant`, `Scope`, `scoped_get`, `UploadPayload`, the AI token bucket, `load_optional` | `security`, `models`, `storage` |
| `alppy/api/errors.py` | `ApiError` and friends, the four handlers, the envelope | FastAPI |
| `alppy/services/enrollment.py` | `owned_class_ids`, `enrolled_student_ids`, `enrolled_in_owned_classes` — the three subqueries every scoped read funnels through. Its own module because `class_service` imports `mastery_service`, and both sides of that edge need them | `models` only |
| `alppy/worker/queue.py` | `enqueue`, `TASK_NAMES` | arq, Redis |
| `alppy/worker/tasks.py` | Every long job: ingest, extract section, render, process scan, grade open answers, adaptive, feedback | the owning modules, **lazily imported** |
| `alppy/storage.py` | `Storage` protocol, `LocalStorage`, the S3 backend, `sanitise_filename`, `storage_key` | boto3 (optional) |
| `alppy/api/v1/health.py` | `/health`, reporting each dependency and never throwing | all of the above |
| `alppy/db/`, `alembic/versions/` | Session, `Base`, hand-checked migrations | SQLAlchemy 2 |
| `alppy/seed/`, `alppy/cli.py` | The demo seed, `backfill-events` | — |

---

## 4 · How to extend this feature

**Adding a long-running feature.** Write a pipeline function with the documented
signature, add a `JobKind` **whose value is the task function's name**, register the task,
and have the handler write a `Job` and call `enqueue`. The contract:

```python
def fn(db: Session, job: Job, *, on_progress: ProgressCB) -> dict[str, Any] | None
```

It may raise freely — any exception is caught, logged, written to `Job.error`, and the
job marked failed. It must **not** commit or close `db`: the task owns the transaction
boundary, and reads what it needs from `job.payload` and `job.school_id`.

Tasks import their owning module **lazily, inside the task**, so the worker still starts
if an optional native dependency is missing in a dev environment.

**Adding a migration.** Migrations reproduce the models, and the unit tests
**structurally cannot** catch a drift, because they build their schema with
`create_all()` from those same models. Run the drift gate against a disposable Postgres:

```bash
ALPPY_DATABASE_URL=postgresql+psycopg://... python scripts/check-schema-drift.py
```

### LLM checklist

- [ ] Read §2 — these are not suggestions
- [ ] Does the new query filter by `school_id`? Did you use `scoped_get`? (I-platform-02)
- [ ] Is personal data also scoped by teacher? (I-platform-03)
- [ ] Does a handler now await a model call, OpenCV or Chromium? (I-platform-05 — never)
- [ ] Did you write a `Job` **and** enqueue it? (I-platform-06)
- [ ] Does any path build a storage key from a client filename? (I-platform-07 — never)
- [ ] Does the new failure go through `ApiError`? (I-platform-08)
- [ ] Does this read the roster? Then it wants **enrolled** students, not the home class (I-platform-09)
- [ ] Does a new write create an enrollment? Then it asserts school **and** school year (I-platform-10)
- [ ] Did the schema change? Then the drift gate, on a real Postgres

---

## 5 · Privacy & safety

| Data | Where it is handled | Why |
|---|---|---|
| Password | Argon2id, OWASP-default parameters, `needs_rehash` for future migration | No password reset needed to change parameters |
| Session | Signed, host-only cookie; no server-side store | A tampered cookie fails the signature rather than selecting another school |
| Uploads | Type sniffed from content, size-capped, filename sanitised | I-platform-07 |
| Files | Tenant-scoped file route; object storage | A crop or page image is a child's handwriting |
| Rate limit | In-process token bucket per teacher on AI endpoints | A guard against one teacher holding the model budget, not a distributed limiter |
| Error messages | `message` is for logs and developers | Teacher-facing strings are localised client-side |

Cross-tenant reads return **404, not 403**: telling a stranger that a resource exists is
itself a leak.

---

## 6 · Testing strategy

| Invariant | Proved by |
|---|---|
| I-platform-01 | `test_api_auth.py::test_a_tampered_cookie_is_not_a_session`, `::test_login_does_not_distinguish_an_unknown_email`, `::test_logout_clears_the_session` |
| I-platform-02 | `test_api_tenancy.py::test_another_schools_class_reads_as_missing`, `::test_listings_never_cross_the_tenant_boundary`, `::test_a_sheet_cannot_reference_another_schools_exercise` |
| I-platform-03 | `test_api_tenancy.py::test_a_colleagues_class_is_not_listed`, `::test_a_colleagues_roster_never_reaches_another_teacher` |
| I-platform-04 | `test_api_tenancy.py::test_subjects_stay_shared_across_the_staffroom`, `test_api_infra.py::test_competencies_are_filterable` |
| I-platform-05 | `test_api_scans.py::test_upload_accepts_a_pdf_and_returns_without_detecting_anything`, `test_jobs_queue.py::test_uploading_a_source_enqueues_the_ingestion_job` |
| I-platform-06 | `test_jobs_queue.py::test_every_job_kind_names_a_task_the_worker_registers`, `::test_a_dead_queue_fails_the_job_instead_of_leaving_it_queued` |
| I-platform-07 | `test_api_scans.py::test_a_hostile_filename_never_becomes_a_storage_path`, `test_api_infra.py::test_storage_keys_cannot_escape_their_prefix`, `::test_the_file_route_is_tenant_scoped` |
| I-platform-08 | `test_api_infra.py::test_every_error_uses_the_same_envelope`, `::test_an_unroutable_path_still_returns_the_envelope`, `::test_the_request_id_is_echoed_when_the_caller_supplies_one` |
| I-platform-09 | `test_api_classes.py::test_a_co_enrolled_student_keeps_the_uid_their_home_class_minted`, `::test_a_roster_paste_numbers_around_a_visiting_student`, `::test_a_student_cannot_leave_the_class_that_minted_their_uid`, `test_scan_processing.py::test_a_co_enrolled_students_page_is_graded_not_flagged` |
| I-platform-10 | `test_api_tenancy.py::test_enrollment_never_crosses_a_school`, `::test_enrollment_never_crosses_a_school_year`, `::test_a_co_enrolled_student_is_readable_by_both_their_teachers` |
| Rate limit | `test_api_infra.py::test_the_token_bucket_refills_over_time`, `::test_the_bucket_is_per_teacher`, `::test_ai_endpoints_are_rate_limited`, `::test_scan_upload_is_rate_limited`, `::test_source_upload_is_rate_limited`, `::test_preview_uses_the_render_bucket_not_the_ai_one` |
| Health | `test_api_infra.py::test_health_never_throws_and_reports_each_dependency` |
| Schema | `scripts/check-schema-drift.py` — its own CI job, on a real Postgres |

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_api_auth.py \
  apps/api/tests/test_api_tenancy.py apps/api/tests/test_api_infra.py \
  apps/api/tests/test_jobs_queue.py apps/api/tests/test_uid.py -q
```

---

## Companion documents

- [`architecture.md`](architecture.md) — the request path, the job path, storage, errors
- [`decisions.md`](decisions.md) — D17, D18, D25, D39
- [`../../architecture.md`](../../architecture.md) — the system view
- [`../../deploy-cloudflare.md`](../../deploy-cloudflare.md) — the split deployment

**Last updated:** 2026-09-09
