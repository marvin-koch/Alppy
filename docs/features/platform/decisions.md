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

## D69 · Enrollment is a join table; the home class is a column

`Student` answered "which class?" with one NOT NULL FK, which was two questions wearing
one answer: the class that **minted** the pupil's `uid` and `number`, and the classes the
pupil **attends**. Splitting them is D56's shape — `home_class_id` is where the row sits,
`class_student` is what it belongs to.

Everything a teacher browses reads enrollment: `list_students`, `student_counts`,
`class_matrix`, `class_tree`, the printed pile, adaptive targeting, the students offered
for manual scan assignment. Two things read the home class, and only two: the roster
paste, because it mints the UID, and `adaptive_service._class_of`, a legacy fallback that
has to name exactly one.

Two traps this created, both now covered by tests named after them:

* **`scan_processing.wrong_class`.** Comparing `home_class_id` to `sheet.class_id` would
  flag a legitimately co-enrolled pupil's page as foreign, and the branch below it clears
  `result.detections` — the child's answers silently discarded, no error raised
  (`I-platform-09`).
* **`add_students`' `taken` set.** Computed over the enrolled roster, a visiting pupil
  carrying number 4 from their own class would 409 a new pupil out of number 4 in a class
  where `7B_04` is free. It reads `home_students` for exactly that reason.

`owned_class_ids` gained a student-side twin, `enrolled_in_owned_classes`, and both live
in `services/enrollment.py` rather than `class_service` — `class_service` imports
`mastery_service`, and `mastery_service` needs the same subqueries, so a shared module is
what keeps the edge acyclic without either side inventing a laxer rule.

**Rejected:** keeping the column name. Twelve read sites needed judging individually, and
an unreviewed site under the old name keeps working with the old meaning. Renamed, it is
an `AttributeError`.

**Rejected:** `left_at`, `role`, or any other per-enrollment state. `enrolled_at` is
provenance and costs nothing; a temporal column makes every roster read a point-in-time
query.

## D73 · A teacher is assigned a branch in a class, and ownership is a union

**Affected invariant:** I-platform-11, I-platform-13 (new); I-platform-03 (reworded)

`class.teacher_id` carried two facts that only looked like one while a class had a single
teacher: *who may read this class* and *who is its maître de classe*. Split the way D69 split
`Student` — `head_teacher_id` is the column, `class_teacher_subject` is the join table.

**Considered alternatives.** (A) Put `teacher_id` on `class_subject`: rejected, because
`position` is the class's nav order and a table grained by teacher gives two co-teachers'
rows nothing forcing their order to agree. (B) Derive the branch list from staffing:
rejected, D57's circularity in a new costume — a Branch would vanish from the navigation the
moment its teacher was unassigned. **(C) A join table beside `class_subject`, with a
composite FK onto it** — chosen; the FK makes "you cannot teach a branch this class does not
study" a database fact.

**Ownership is a union**, head teacher OR any assignment. The head-teacher arm keeps a class
with no declared branches visible to its own teacher, and is what makes the 0021 backfill
provably behaviour-preserving.

✅ One rule, in one place (`enrollment.owned_class_ids`), which is what I-platform-03 claimed
and did not deliver. ❌ Two grains to keep straight; the module docstring names them.

## D74 · One teacher, several staffrooms; the tenant comes from the session

**Affected invariant:** I-platform-14 (new), I-platform-02 (second documented exception)

`teacher.school_id` was the tenant boundary. A teacher splitting their load between two
establishments belongs to both, so the fact moved to `teacher_school` and the column became
`home_school_id` — where the account is based, and what `login` mints the first cookie for.

**Considered alternatives.** (A) Keep one school and duplicate the account: rejected, two
password hashes and two preference sets for one person, and `login` looks up by email alone.
(B) Drop `home_school_id` entirely: purer by §2's own test, but takes `Teacher` out of
`SchoolScopedMixin` *and* leaves `login` with no default school. **(C) Column plus join** —
chosen, the shape D56 and D69 already established.

✅ Every service query is untouched: they filter on `scope.school_id`, which simply stops
coming from a row. ❌ `Teacher` becomes the second documented exception to I-platform-02
after the curriculum (D11) — honest, since a teacher at two schools no longer belongs to one
tenant.

## D75 · A teacher sees only what they teach

**Affected invariant:** I-platform-15 (new)

Reads narrow to the branches a teacher takes, wherever a branch exists. Two carve-outs, both
because a branch does not exist there even in principle: the **roster** (names and UIDs a
co-teacher already knows by standing in the room) and an **unmatched pile** (no subject at
all until a sheet is attached).

**The carve-out that nearly sank it.** A pile gaining a subject later would change visibility
mid-workflow. Closed structurally rather than special-cased: the sheet is attached through the
now pair-grained `get_sheet`, so a teacher can only ever attach a sheet they already teach.

**Rejected: narrowing the student profile.** `_owned_student` is D69's widening, and a maths
teacher noticing a child sinking across every branch is a feature of this product.

## D76 · The teacher edits their own school's nouns

**Affected invariant:** I-platform-17 (new)

Renaming is not re-identifying: a label always, a `key`/`code`/`uid` never once paper has been
printed from it. `Class.code` is editable only before a roster exists.
`School.default_curriculum` is not editable at all (D56).

Deleting a Student is the only operation allowed to destroy evidence, takes the pupil's uid
typed back, and is restricted to the head teacher of their home class. **The first
implementation gated on `get_class`, which is class-grained, so a co-teacher passed — the
test written for it is what caught that.**

## D77 · The corpus is shared for reading, not for deleting

**Affected invariant:** I-platform-18 (new)

`delete_chapter` and `delete_source` refuse a caller who does not hold that branch anywhere in
the school. Reads stay school-wide, which is what makes the staffroom a staffroom.

**Revisit when** a `role` column lands on `teacher_school`: this is the same question as who
may assign a colleague (D75) and who may rename the school (D76), and it deserves one
decision rather than three. "You teach it" is the narrowest rule that already exists in data.

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
