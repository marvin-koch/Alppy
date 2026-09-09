# Platform Decisions Log

D-numbers follow the repo-wide [`docs/decisions-log.md`](../../decisions-log.md).

---

## Tenancy is a required argument, not a convention

**Date:** M0 · **Affected invariants:** I-platform-02, I-platform-03

**Background.** Every row carries `school_id`. The question was how to make forgetting it
impossible rather than merely discouraged.

**Considered alternatives**
- A) *A global session filter / RLS-style middleware.* Rejected for the MVP: it makes the
  scoping invisible at the call site, so a reviewer cannot see whether a query is scoped.
- B) *Convention plus code review.* Rejected: this is exactly the class of rule that
  survives review once and slips the second time.
- C) **`Scope` as a required argument below the router, and `scoped_get` as the one
  blessed fetch-by-id.** Chosen — a handler that forgets the tenant does not type-check.

**Tradeoff**
- ✅ The scoping is visible in every signature
- ✅ Cross-tenant reads are 404s, so existence itself is not disclosed
- ❌ Every service function carries a parameter it mostly just passes along

---

## D11 · Curriculum data is not school-scoped

**Date:** M1 · **Affected invariant:** I-platform-04

LP21 and PER are public reference data shared by every tenant, and the one deliberate
exception to the rule above. Everything else carries `school_id`.

---

## D17 · Alembic gets one hand-checked initial migration, not autogenerate output

**Date:** M0 · **Affected invariant:** the migration discipline

Autogenerate misses pgvector's extension creation and mis-orders enum types. The initial
migration is diffed table-by-table against `Base.metadata` by hand.

---

## D18 · Tests run on SQLite with a test-only type swap for `Vector` / `JSONB`

**Date:** M0 · **Affected invariant:** the test strategy — and the reason D39 exists

CI stays fast and contributors need no Postgres for the unit suite. Integration tests that
exercise pgvector run against the Postgres service container.

**The cost, stated plainly:** the unit suite builds its schema with `create_all()` from
the models, which is precisely what the migrations are supposed to reproduce. It can
therefore never tell you they reproduce something different. That is not a gap in the
tests; it is a structural property of this choice, and D39 is the compensating control.

---

## D39 · Schema drift is a CI gate, because the unit tests structurally cannot see it

**Date:** 2026-09 · **Affected invariant:** the migration discipline

**Background.** Five index drifts accumulated silently across migrations 0003–0005:
`_fk()` declares `index=True` on every foreign key, and four of those indexes were never
created, while `ix_exercise_discarded` existed in the database and in no model.

**Why none of it was caught:** see D18. A test that constructs the schema from the models
can never tell you the migrations construct a different one.

**The damage was not a slow query.** It was that `alembic revision --autogenerate`
proposed the same five drifts every run, so a *real* change arrived buried in noise
nobody read any more.

**Fix.** Migration `0008` creates the four missing indexes. `ix_exercise_discarded` is
kept and declared in the model instead — it is a partial index (`subject_id` where
`discarded_at IS NOT NULL`) added deliberately in 0004, and dropping a working index to
satisfy a diff would be the wrong direction. `scripts/check-schema-drift.py` migrates a
disposable Postgres from nothing and diffs the result against `Base.metadata`, as its own
CI job.

**It needs a real Postgres.** SQLite cannot show this class of difference at all.

---

## D25 · The web app is hosted on Cloudflare Workers; the API is not

**Date:** 2026-09 · **Affected invariant:** none directly; it shapes everything

Hosting had to cost nothing for now, and Cloudflare's free plan can carry `apps/web` —
measured at **1.03 MiB gzipped against a 3 MiB ceiling**, with static chunks served from
Workers Assets without invoking the Worker at all.

It cannot carry `apps/api`, and **this is not a matter of effort**: Workers' Python is
Pyodide, so `opencv-python-headless`, `pymupdf` and `pillow-heif` have no wheels to load;
Chromium does not fit a Worker; there is no Postgres, so no pgvector; and nothing on the
free plan runs a persistent process, so the arq worker has nowhere to live. **The scanner
is the reason the deployment is split.** R2 is the one Cloudflare piece the API does use,
in MinIO's place.

The Worker doubles as the reverse proxy `next.config.ts` had always assumed: `/api/v1/*`
is rewritten to `ALPPY_API_ORIGIN`, so the browser sees one origin and the host-only
`alppy_session` cookie keeps working with no CORS and no `SameSite=None`.

**Costs:** the API's address is compiled into the routes manifest (moving the API is a
rebuild, not a variable edit), and the origin cannot carry a port, because the route
compiler reads `:8443` as a path parameter. Both in
[`deploy-cloudflare.md`](../../deploy-cloudflare.md) §4.

**Revisit if** the Worker outgrows 3 MiB, if a screen starts rendering data on the
server, or if a school requires Swiss data residency — the Worker serves only the UI
shell, but it **proxies every API call**, so [`privacy.md`](../../privacy.md) makes that a
change to this decision and not just to the API's host.

---

## Nothing blocks a request handler on a model call

**Date:** M1 · **Affected invariants:** I-platform-05, I-platform-06

Stated in `CLAUDE.md` as a convention; enforced by shape. Every slow path writes a `Job`
and enqueues. The corollary that has bitten once: **a `Job` row without an enqueue is a
note nobody reads.** The worker listens on Redis and never looks at Postgres, so a job
that is only written to the database stays `QUEUED` forever and the teacher watches a
spinner that will never stop. A dead queue now **fails** the job instead.

---

## When policy changes

```json
{
  "change": "run the vision grader inline in POST /scans/{id}/confirm",
  "reason": "one fewer moving part",
  "date": "YYYY-MM-DD",
  "decision": "rejected — violates I-platform-05",
  "rationale": "a class of 24 written answers is 24 model calls. Inline, that is a
                gateway timeout with a half-graded pile behind it, and the grader's
                own rule (nothing stays PENDING) then has no job to settle it."
}
```
