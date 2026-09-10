# Phase 2 audit — API design

**Scope:** the HTTP contract of Alppy as it stands on `main` at 2026-09-10, `alppy.api.v1`
(3 664 lines across 12 routers, `deps.py` and `errors.py`), `alppy/schemas/__init__.py`
(1 419 lines), the service layer's ownership predicates (`services/enrollment.py`,
`class_service`, `sheet_service`, `scan_service`, `mastery_service`), and the client-side
API layer (`apps/web/src/lib/api/`).
**Method:** read-only. Every route module read in full; the surface reconstructed from the
routing code with a script over the `@router.*` decorators, not from `docs/plan.md` §4;
every finding below traced to a line. No file was written except this one. No server was
started and no test was run — where I say a test cannot catch something, that is from
reading the fixture, not from watching it fail (§9).

Two brief parameters were left as placeholders and are answered by the repo rather than
assumed: **stack** is FastAPI + Pydantic v2 + SQLAlchemy 2 (not Fastify/Zod or NestJS),
**API style** is REST-over-JSON with cookie sessions and no GraphQL anywhere.
**Cantonal scope** remains an open question, inherited unanswered from Phase 1 (§8).

Phase 1 (`docs/audits/01-database-audit.md`) was read first. Its findings that are now
cemented into the public contract are re-raised here with the endpoints that propagate
them (§6).

---

## 1 · Verdict

**Not yet — three days of work short of it, and none of the three is a redesign.**

The contract is better than most of what it will be built against. There is exactly one
error envelope and every failure in the app arrives in it; the tenant is resolved once per
request in one dependency and bound into a Postgres GUC; ownership has *two* grains
(`owned_*` class-grained, `taught_*` pair-grained) and the distinction is argued in
`services/enrollment.py` rather than left to each handler's judgement; every ownership
failure is a 404 and never a 403, deliberately and consistently; the long operations are
job resources with a poll endpoint and per-student partial-failure reporting
(`AdaptiveGenerationFailure`); the teacher's override of the scanner is kept *beside* the
machine's reading rather than on top of it; and `Attempt.score` and `Attempt.correct` stay
two different quantities all the way out to two different response models. Frontend and
backend teams can build against most of this in parallel today.

Three things stop me saying yes.

1. **Two endpoints return or destroy the wrong data, and both are in the adaptive/scan
   path that is the product's whole point.** `POST /adaptive/propose` deduplicates
   in-flight jobs **per school** rather than per class (`api/v1/adaptive.py:111-122`), so
   a second teacher clicking "propose" while a colleague's run is in flight is handed the
   colleague's job id — and `GET /adaptive/proposal/{job_id}` will then serve them a plan
   for a class they may not teach, keyed by pupils they may not know, while their own
   request is silently discarded. `PATCH /scans/{scan_id}/pages/{page_id}` deletes every
   `Detection` on the page (`services/scan_processing.py:630-632`) and, alone among the
   four page/detection mutations, carries no confirmed-pile guard — so it erases the
   teacher's corrections without a warning and can do it to a pile whose grades are
   already live. These are C1 and C2 and they are cheap to fix now.

2. **The gate that is supposed to keep the client and the server in agreement does not
   exist.** `apps/web/src/lib/api/endpoints.ts:80-84` says "Every path below is checked
   against the served OpenAPI document by `apps/web/src/lib/api/__tests__/contract.test.ts`".
   There is no `__tests__` directory. `types.ts` is a 1 162-line hand mirror of
   `alppy/schemas`, `packages/shared/src/index.ts` exports only the layout constants, and
   CI checks `export-layout.py` for staleness and nothing about the API types. The repo
   has the fix half-written and uncommitted (`scripts/generate-api-types.py`,
   `packages/shared/src/api-types.generated.ts`, both `??` in `git status`). Until that
   lands, "build against the contract in parallel" means "build against a copy of it that
   nothing compares".

3. **Every read means "now", and Phase 1's two Critical findings are now contract
   shape, not just schema shape.** No endpoint takes an `as_of` — the capability exists
   one layer down (`services/mastery_service.py:161-195`) and no route passes it — and
   `année scolaire` appears nowhere in the surface at all (`grep -rn "school_year"
   apps/api/alppy/api/` returns nothing). Grading a pile photographed three weeks ago uses
   today's roster, and adding the parameter later changes the meaning of nine existing
   responses. This is where the versioning question bites (§7).

Fix C1, C2 and H1 (a missing `commit()` that silently discards a Branch rename), land the
generated types, and the answer becomes yes with the temporality work sequenced
deliberately rather than discovered in August.

---

## 2 · Findings

Ordered within each severity by **cost of fixing once clients exist**, descending — so
the changes that get expensive the moment a second consumer appears are at the top.

| ID | Sev | Area | Summary | Evidence |
|---|---|---|---|---|
| C1 | Critical | Authorisation / correctness | `/adaptive/propose` dedupes in-flight jobs per **school**; a second teacher gets a colleague's job and then a colleague's class's plan | `api/v1/adaptive.py:111-122`, `:168-170` |
| C2 | Critical | Data loss | `PATCH /scans/{id}/pages/{id}` deletes every detection on the page, teacher corrections included, with no confirmed-pile guard | `api/v1/scans.py:209-230`, `services/scan_processing.py:630-632`, `services/scan_service.py:885-937` |
| C3 | Critical | Temporality | Every roster, matrix, profile and report read means "now"; no `as_of` anywhere in the surface; `année scolaire` is not a parameter | `services/mastery_service.py:161-195`, `api/v1/*` (no `school_year`) |
| H1 | High | Correctness | `PATCH /subjects/{id}` never commits — the rename is rolled back, the 200 says otherwise, and no API test can see it | `api/v1/classes.py:273-278`, `services/nouns_service.py:112-124`, `tests/test_api_fixtures.py:168-176` |
| H2 | High | Contract integrity | The contract-drift gate `endpoints.ts` cites does not exist; client types are a hand mirror; the generated ones are untracked and unwired | `apps/web/src/lib/api/endpoints.ts:80-84`, `types.ts:1-11`, `packages/shared/src/index.ts` |
| H3 | High | Cost / async | `/adaptive/feedback/generate` queues one provider call per student with **no** AI rate limit and no in-flight dedup | `api/v1/adaptive.py:319-323` |
| H4 | High | Async | `POST /adaptive/regenerate` calls a model provider synchronously inside the request handler | `api/v1/adaptive.py:233-258`, `services/adaptive_service.py:1892-1935` |
| H5 | High | Idempotency | No idempotency key anywhere; render has no in-flight guard, and every render `DELETE`s and rewrites the sheet's `AnswerBoxPlacement` rows | `api/v1/sheets.py:133-176`, `sheets/render.py:668` |
| H6 | High | Authorisation | `POST /schools/{id}/teachers/{id}` grants any teacher id full read of every child in a school, unaudited, and **no route revokes it** | `api/v1/classes.py:379-410` |
| H7 | High | Authentication | Stateless signed cookie, 12 h, no revocation, no session list, no reset, no verification, no account creation | `core/security.py:63-84`, `api/v1/auth.py:124-126` |
| H8 | High | nLPD | No export endpoint and no anonymisation; the only erasure is a cascade that leaves every scan image in the bucket | `api/v1/classes.py:323-339`, Phase 1 §H5 |
| H9 | High | PER / product | No exercise-bank endpoint: the corpus is reachable only nested under one source, and cannot be filtered by competency, objective or year | `api/v1/sources.py:307-405` |
| M1 | Medium | i18n | At least 12 error codes the API emits have no catalogue entry and collapse to one generic sentence; nothing compares the two sets | `apps/web/messages/fr.json`, `api/errors.py` |
| M2 | Medium | Validation | `SheetUpdate.items` has no length bound where `SheetCreate.items` caps at 64; `AdaptiveBatchRequest.plans` is unbounded | `schemas/__init__.py:555`, `:1255` |
| M3 | Medium | Tenancy | `timeline._titles` runs five tenant-unfiltered queries, contradicting the rule and `adaptive.py:382-387`'s claim to be the only such place | `api/v1/timeline.py:49-74`, `:125-130` |
| M4 | Medium | Collections | Eight collection endpoints have no pagination, filtering or sorting at all | `api/v1/classes.py:54`, `:82`, `sheets.py:77`, `scans.py:43`, … |
| M5 | Medium | Authorisation | Jobs, proposals, approval and discard are tenant-grained, not owner-grained | `api/v1/jobs.py:29-44`, `adaptive.py:168-230` |
| M6 | Medium | Connectivity | Scan upload is one atomic multipart of up to 120 × 50 MB held in memory; no resume, no partial success | `api/v1/scans.py:58-97`, `api/deps.py:521-586` |
| M7 | Medium | Async | No job cancellation and no retry; a stuck job can only be waited out | `api/v1/jobs.py` |
| M8 | Medium | Validation | Domain rules are type-correct, not domain-correct: `canton` is free text, and no HarmoS year, school year or grade scale exists in the contract | `schemas/__init__.py:187`, `:193` |
| M9 | Medium | nLPD | The one student identifier that travels in a query string: `DELETE /students/{id}?confirm=7B_15` | `api/v1/classes.py:323-339` |
| M10 | Medium | Cost control | Per-teacher, per-process token buckets only; no per-establishment quota and no cost ceiling | `api/deps.py:407-445` |
| M11 | Medium | Spec | ~59 of 89 routes are absent from the published surface, and one documented route has the wrong shape | `docs/plan.md:112-142` |
| M12 | Medium | Authorisation | Any member may flip `approved` on any exercise, and `/adaptive/discard` destroys a colleague's proposals | `api/v1/sources.py:472-509`, `adaptive.py:221-230` |
| M13 | Medium | Modelling | `POST /sheets/{id}/printed` writes only an `Event`; no response field reports it, so a client cannot read the fact back | `api/v1/sheets.py:302-331` |
| L1 | Low | Efficiency | `GET /sources/{id}/status` fetches every ingest job in the school and filters in Python | `api/v1/sources.py:204-217` |
| L2 | Low | Disclosure | `DetectionOut.vision_model` and `AdaptiveGenerationFailure.detail` cross to the client | `schemas/__init__.py:694`, `:1200` |
| L3 | Low | nLPD | Presigned URLs for scan crops of children's handwriting are unauthenticated for 900 s | `storage.py:167-179` |
| L4 | Low | Operability | No readiness probe distinct from liveness; `/health` opens three connections per unauthenticated call | `api/v1/health.py:55-71` |
| L5 | Low | REST | Three-level paths, and one hierarchy encoding an assumption that will change | `api/v1/classes.py:173`, `mastery.py:87` |
| L6 | Low | REST | 201 for an idempotent no-op; DELETE returning 200 + a list | `api/v1/classes.py:103-146` |
| L7 | Low | Naming | The contract's nouns and the product's nouns differ (`Subject`=Branch, `Chapter`=Theme) and the contract does not say so | `schemas/__init__.py` passim |

---

## 3 · Detailed findings

### Critical

---

#### C1 · `/adaptive/propose` hands a teacher another teacher's class

**What is wrong.** The in-flight guard is scoped to the tenant, not to the class:

```python
running = db.scalars(
    select(Job).where(
        Job.school_id == scope.school_id,          # api/v1/adaptive.py:112
        Job.kind == JobKind.PROPOSE_ADAPTIVE,
        Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
    )
).first()
if running is not None:
    return job_out(running)                        # :122
```

The docstring says why it exists — *"a double-click used to cost one token and now costs a
second Job and a second set of unapproved Exercise rows"* — and that reasoning is right for
a double-click. It is wrong for two teachers, because the predicate does not mention
`payload.class_id`, `payload.subject_id` or `scope.teacher_id`, all three of which are in
hand two lines above.

The second half is `read_proposal`, which gates only on the tenant:

```python
job = db.get(Job, job_id)
if job is None or job.school_id != scope.school_id:   # api/v1/adaptive.py:169
    raise errors.not_found("job", ids=[str(job_id)])
```

**Why it matters here.** It is Tuesday afternoon in a Sion établissement. Mme Berger opens
the adaptive screen for her niveau-1 maths group, 10-MAT-N1, and clicks *Proposer*. The job
takes forty seconds. At second twelve M. Rossier, two doors down, clicks *Proposer* for
9B — a class Berger does not teach and whose roster she has no footing in. He gets a 202
carrying **Berger's** job id. His screen polls it, sees `succeeded`, and calls
`GET /adaptive/proposal/{that id}`, which passes the tenant check and returns Berger's
plans: one entry per 10-MAT-N1 pupil, each carrying `student_id`, `student_uid`
(`10VG3_07`), the competencies that pupil is weak in, and eight exercise statements aimed
at those weaknesses. Rossier is now looking at a per-child diagnosis for twenty-two
children in a colleague's streamed group.

He then does the natural thing and clicks *Créer la série*. `POST /adaptive/batch` checks
the plans' `student_id`s against **his** class (`sheet_service.py:421-424`) and 404s with a
list of unknown students — so nothing is printed, which is the one mercy. But his own
proposal was never queued, and nothing anywhere tells him that: the second click did not
fail, it succeeded with someone else's answer.

Two separate defects, and both matter:

* **The wrong answer.** The dedup returns a job whose `payload.class_id` is not the one
  asked for. Anything keyed to the request — the class, the subject, the student
  selection, `items_per_student`, `n_groups`, `source_sheet_id` — is silently substituted.
* **The disclosure.** `read_proposal` is the only adaptive read that reaches pupil-level
  data, and it is the one that drops to `TenantDep` grain. Every other pupil-facing read
  in the API funnels through `owned_class_ids` or `taught_here`
  (`services/enrollment.py:40-107`); this one does not, and the whole argument for that
  module is that *"a laxer rule invented in a new read path is how a roster leaks"*.

**The fix.** Two lines and one predicate.

* Narrow the guard to the request: add `Job.payload["class_id"].astext == str(payload.class_id)`
  (or, more honestly, add a `class_id` column to `Job` — three other handlers already
  reach into `payload` with string comparisons, and `GET /sources/{id}/status` does it by
  fetching every row and filtering in Python, L1). Include `subject_id`, and include the
  actor: two teachers co-teaching one class legitimately want their own runs.
* Gate `read_proposal` on the class the job names, through `get_class(db, scope, ...)` —
  the same call `propose` itself makes at line 93.

**Breaking for clients?** No. Both changes only ever *narrow* what a caller gets back. A
client that today receives a foreign job id receives its own instead; a client that today
can read a foreign proposal gets a 404. Nothing in `apps/web` depends on either behaviour.

---

#### C2 · Re-assigning a scanned page deletes the teacher's corrections, on a confirmed pile too

**What is wrong.** `PATCH /scans/{scan_id}/pages/{page_id}` re-reads the page once the
student is known, and re-reading starts by throwing away everything that was there:

```python
for stale in list(page.detections):       # services/scan_processing.py:630
    db.delete(stale)
db.flush()
```

`page.detections` is not the machine's readings — it is *the* readings, including every
row where a teacher has already set `detected_index`, `outcome = CORRECTED`,
`corrected_by_id`, `corrected_at`, a `transcription` or a `verdict_correct`.

And this is the one page/detection mutation with no confirmed-pile guard. The other three
have it:

| Route | Guard | Line |
|---|---|---|
| `PATCH /scans/{id}/detections/{d}` | `_refuse_when_confirmed(scan)` | `scan_service.py:298` |
| `POST /scans/{id}/detections/{d}/revert` | `_refuse_when_confirmed(scan)` | `scan_service.py:381` |
| `POST /scans/{id}/pages/{p}/discard` | explicit `scan_already_confirmed` 409 | `scan_service.py:977-980` |
| **`PATCH /scans/{id}/pages/{p}`** | **none** | `scan_service.py:885-937` |

`correct_detection`'s own docstring names this exact hazard and says it was closed:
*"Until now nothing on the server said so — only the review screen's `readOnly` prop did,
which meant a direct PATCH could edit a reading that a live `Attempt` had already been
graded from, leaving the grade and the reading it claims to come from disagreeing."* It was
closed on that route and left open one route over, on the more destructive of the two.

**Why it matters here.** Mme Berger photographs 7B's twenty-eight copies on her phone. Page
12's printed UID grid reads `7B_04` at 0.41 confidence, so the review screen shows it for
adjudication. She works through it: three ambiguous bubbles corrected by hand, one written
answer she re-transcribes because the model read *"1/2"* where the child wrote *"1/3"*.
Fourteen minutes of a Tuesday evening.

Then she notices the page is actually Nadia's, `7B_14` — the grid was smudged. She picks
Nadia from the dropdown. The response is a cheerful 200 with a fresh page of detections.
Her fourteen minutes are gone: deleted rows, no warning, no undo, and nothing recorded
anywhere that a human reading ever existed. The screen redraws with the machine's raw
output and she has no way to know what she has lost except by remembering it.

The confirmed-pile variant is worse and rarer. The pile is signed off; twenty-eight
children have grades. Someone re-assigns a page — a mis-click on a touch screen is enough,
because the route does not refuse a page that already has a `student_id`. The detections go;
`Attempt.detection_id` is `ON DELETE SET NULL` (`models/__init__.py:1235-1237`) so the
grades survive but lose their provenance, and `GET /students/{id}/competencies/{c}/attempts`
— the drill-down that exists so *"a teacher who disagrees with a band follows it to the
individual answers"* — now shows `corrected: false` and `scan_id: null` for rows that were
in fact corrected by hand. The band is unchanged and the evidence for it is gone. If the
pile is later reopened and re-confirmed, the machine's reading is what grades the child.

**The fix.** Three pieces, in order of importance:

1. `_refuse_when_confirmed(scan)` in `assign_page_student`, matching the other three
   routes. One line.
2. Do not re-detect a page that already carries corrected readings without the caller
   saying so. Either refuse with a named code (`page_has_corrections`) and require an
   explicit `force`, or — better, and matching how `Detection` already thinks — preserve
   the correction: re-detection rewrites `machine_*` and leaves a row with a
   `corrected_at` alone. The model already has the columns for the second option.
3. Make the route idempotent in the mundane sense: assigning the student who is already
   assigned should not re-detect at all.

**Breaking for clients?** (1) and (3), no — they turn a currently-silent corruption into a
409 or a no-op. (2) as a refusal is a new error code the client must render (M1); (2) as
preservation is not breaking at all and is the better change.

---

#### C3 · Every read means "now", and the school year is not in the contract

**What is wrong.** Three related absences, and the first is the one that is easy to miss
because the capability is *there*.

*The service layer can do it and the contract cannot ask for it.*
`mastery_service.load_attempt_inputs` takes `as_of: datetime | None` and applies it
(`services/mastery_service.py:161`, `:194-195`) — but every call site passes either `None`
or `now`, and no route accepts the parameter. `GET /classes/{id}/mastery`,
`GET /classes/{id}/tree`, `GET /students/{id}/mastery`,
`GET /students/{id}/competencies/{c}/attempts`, `GET /classes/{id}/points`,
`GET /sheets/{id}/mastery` and `GET /students/{id}/sheets/{s}` are all
implicitly-now, all seven of them.

*The roster is worse, because there is no `as_of` even at the service layer.*
`class_service.list_students` (`:351-370`) reads current enrolment
(`enrolled_student_ids`, `enrollment.py:139-148`), and Phase 1 C1 establishes there is no
`valid_to` to read instead — leaving a class is a `DELETE`.

*`année scolaire` is absent from the surface entirely.* `grep -rn "school_year"
apps/api/alppy/api/` returns nothing. `ClassCreate.school_year_id` is the single
appearance of the concept in `schemas/__init__.py` (`:227`), and it is optional and
resolved server-side by `class_service.current_school_year`, which — per Phase 1 H8 —
derives the year from a hardcoded 1 August boundary with no uniqueness constraint behind
it.

**Why it matters here.** Two scenarios, both ordinary.

*Grading late.* M. Rossier photographs a pile on 3 March and, as teachers do, gets to
reviewing it on 24 March. In the meantime Léa has moved from his niveau-2 group to
niveau 3 — a `DELETE FROM class_student`. `POST /scans/{id}/confirm` grades the pile; the
attempts are written correctly against `Attempt.student_id`. But
`GET /scans/{id}/students`, which the review screen uses to offer manual assignment, calls
`assignable_students` on today's roster: Léa is not in it. A page whose UID could not be
read cannot be assigned to the child who actually sat the sheet. And every class-grained
read afterwards — the matrix, the tree, `GET /classes/{id}/points` — omits her from the
columns covering March, which she sat.

*The first Monday of the new year.* On 3 August 2027 the first request creates a new
`SchoolYear`, and `GET /classes` returns an empty list to every teacher in the school. The
contract offers no way to ask for last year: no `school_year` parameter on `/classes`, no
`GET /school-years` to discover the ids, no rollover endpoint. The API's answer to "show me
my 10VG3 from last year" is that the question cannot be phrased.

**The fix.** This is where the contract has to move *before* clients exist, because the
change is in the meaning of existing responses rather than in new fields:

* `as_of: datetime | None` on the seven mastery/report reads, defaulting to now.
* `on: date | None` on `GET /classes/{id}/students` and `GET /scans/{id}/students`,
  defaulting to today, resolving against the `valid_from`/`valid_to` Phase 1 C1 adds.
* `school_year_id` as an explicit optional filter on `/classes`, `/home`, `/sheets` and
  `/scans`, plus a `GET /school-years` so a client can discover the ids and a
  `SchoolYearOut` carrying `label`, `starts_on`, `ends_on`, `is_current`.
* A `school_year_id` on `ClassOut` so a client can tell which cohort it is holding.

**Breaking for clients?** The parameters themselves are additive and not breaking. What
*is* breaking is the day the defaults stop being wrong: a client that today renders the
matrix and means "the whole term" is silently getting "the pupils enrolled right now", and
after the fix it gets the historically-correct set. That is a behaviour change with no
signature change — the worst kind to ship late. Doing it now, with one school's demo data,
is a re-read of seven handlers. Doing it after the first term is a data-correctness
conversation with teachers about numbers they have already shown to parents.

---

### High

---

#### H1 · `PATCH /subjects/{id}` returns 200 and changes nothing

**What is wrong.** The handler does not commit:

```python
@router.patch("/subjects/{subject_id}", response_model=SubjectOut)
def update_subject(subject_id, payload, scope, db):
    subject = scoped_get(db, Subject, subject_id, scope.school_id, label="subject")
    return subject_out(nouns.update_subject(db, scope, subject, labels=payload.labels))
    #      ^ no db.commit()                            api/v1/classes.py:273-278
```

and the service it calls only flushes:

```python
subject.labels = labels
db.flush()                                            # services/nouns_service.py:122-123
return subject
```

`get_db` closes the session in its `finally` (`api/deps.py:59-62`), and a `Session.close()`
on an uncommitted transaction rolls it back. The response is serialised from the in-memory
object, so it faithfully reports the new labels — of a write that is about to be discarded.

It is the only one. I checked all 44 write handlers mechanically; the other 43 either
commit in the router or call a service that commits (`adaptive_service.regenerate_exercise`
commits internally at `:1935`). `PATCH /subjects/{id}` is alone.

**Why it matters here.** A Sion établissement seeds `mathematics`, `french`, `german`.
The maths teacher renames the Branch to *"Mathématiques 10e"* for her group's nav. The
save button turns green, the label updates on screen, and on the next page load it is
`Mathématiques` again. She tries twice more, decides the feature is broken, and stops
trusting the rest of the nouns editor — which is a shame, because the other five routes in
that block work.

**Why no test catches it, and this is the part worth fixing beyond the one line.** The
suite's `app` fixture overrides `get_db` with a generator that yields *the test's own
session* and never closes it (`tests/test_api_fixtures.py:168-176`). Every request in a
test therefore sees every previous request's uncommitted flush. A missing `commit()` is
structurally invisible to the entire API test suite — the same shape of blind spot
CLAUDE.md already names for `create_all()` versus migrations, and Phase 1 H4 names for
`compare_server_default`.

The existing test walks right past it:

```python
response = client.patch(f"/api/v1/subjects/{tenant.subject.id}",
                        json={"labels": {"fr": "Maths", ...}})
assert response.status_code == 200
assert response.json()["labels"]["fr"] == "Maths"        # the response, not the row
assert response.json()["key"] == db.get(Subject, ...).key  # the row, but only for `key`
```
`tests/test_nouns_crud.py:75-86`

It asserts the row for the field that is *not supposed* to change and the response for the
field that is.

**The fix.** `db.commit()` in the handler, matching its five neighbours. Then the general
one: give the fixture a session-per-request that closes, or add one test per write route
that re-reads through a fresh session. The first is a fixture change and catches every
future instance; the second is 44 assertions and catches only what someone remembers.

**Breaking for clients?** No — it makes the endpoint do what its response already claims.

---

#### H2 · The contract-drift gate the code cites does not exist

**What is wrong.** Four things, which together mean nothing checks the client against the
server:

1. `apps/web/src/lib/api/endpoints.ts:80-84` says every path is checked against the served
   OpenAPI document by `apps/web/src/lib/api/__tests__/contract.test.ts`. There is no
   `__tests__` directory under `apps/web/src/lib/api/` (`find apps/web/src -name
   "contract*"` returns nothing). The comment even carries the incident that motivated it
   — `POST /scans/{id}/pages/{id}/assign` called for two milestones against an API that
   only ever exposed `PATCH …/pages/{id}` — which makes the missing file more pointed, not
   less.
2. `apps/web/src/lib/api/types.ts` opens with *"The API contract, hand-mirrored from
   `apps/api/alppy/schemas/__init__.py`"* and runs to 1 162 lines. Every field name, every
   enum member and every optionality is transcribed by hand.
3. `packages/shared/src/index.ts` exports `SCAN_THRESHOLDS`, `SHEET_LAYOUT` and
   `SheetLayout` — the print geometry, generated and CI-checked — and nothing else. Its
   own docstring makes the argument for doing this: *"a contract nothing imports is a
   contract nobody keeps."* The API types are not in it.
4. `.github/workflows/ci.yml:192-197` regenerates `layout.generated.ts` and fails if it is
   stale. There is no equivalent step for the API types, because there is nothing to run.

The repo knows. `scripts/generate-api-types.py` and `packages/shared/src/api-types.generated.ts`
both exist in the working tree and are **untracked** (`??` in `git status`). The script is
good — it builds the document from `create_app()` rather than from a running server,
explains which five types stay hand-written and why, and proposes `git diff --exit-code` in
CI exactly as `export-layout.py` does. Its docstring says *"`types.ts` … is now a short
file that says why it exists rather than a 1 162-line mirror."* `types.ts` is still 1 162
lines. The migration is half-done and uncommitted, which is the state where the new
mechanism exists and the old hazard is still live.

**Why it matters here.** A Pydantic field is renamed — say `SheetInstanceOut.points_earned`
becomes `points`. Nothing fails. `pnpm typecheck` passes, because `types.ts` still declares
`points_earned` and TypeScript has no way to know the server disagrees. CI passes.
The first thing to notice is a teacher's screen showing `—` where every mark should be,
because `undefined` is indistinguishable from "nothing graded yet" — a distinction the
schema goes out of its way to preserve (*"null when nothing has been graded — never
rendered as a zero"*).

The blast radius is not hypothetical. Nine `?? null` and `| null` fields in `types.ts`
carry that same null-means-something semantics.

**The fix.** Commit what is already written: `scripts/generate-api-types.py`,
`packages/shared/src/api-types.generated.ts`, a CI step mirroring lines 192-197, a re-export
from `packages/shared/src/index.ts`, and reduce `types.ts` to the five hand-written types
its own successor names. Then either write `contract.test.ts` or delete the sentence that
promises it — a comment asserting a check that does not exist is worse than no comment,
because a reviewer reads it and stops looking.

**Breaking for clients?** No, and this is the change that makes every *later* breaking
change visible.

---

#### H3 · Feedback generation is the one model-reaching endpoint with no rate limit

**What is wrong.** Every other endpoint that can reach a provider — directly or through the
job it queues — carries `AiRateLimit`:

| Endpoint | `AiRateLimit` | Line |
|---|---|---|
| `POST /sheets/propose` | yes | `sheets.py:52` |
| `POST /sources` | yes | `sources.py:114` |
| `POST /sources/{id}/sections/{sid}/extract` | yes | `sources.py:253` |
| `POST /scans` | yes | `scans.py:62` |
| `POST /adaptive/propose` | yes | `adaptive.py:72` |
| `POST /adaptive/regenerate` | yes | `adaptive.py:236` |
| `POST /adaptive/batch` | yes | `adaptive.py:265` |
| **`POST /adaptive/feedback/generate`** | **no** | `adaptive.py:319-323` |

`deps.enforce_ai_rate_limit`'s docstring states the rule this violates: *"Dependency for
every endpoint that can reach a model provider. Directly or through the job it queues: an
endpoint that queues nothing but a chain ending in a provider call is exactly as expensive
as one that calls out itself."* The handler's own docstring agrees about the cost —
*"one model call per student: a class of twenty inside a request handler is a timeout"* —
and then does not take the dependency.

There is no in-flight dedup either, unlike `/adaptive/propose` two hundred lines up.

**Why it matters here.** A teacher on a slow classroom connection clicks *Générer les
retours* for 7B, sees nothing happen, and clicks again. Twice more. Four
`GENERATE_FEEDBACK` jobs, twenty-eight students each: 112 provider calls where 28 were
wanted, four times the bill and four `MisconceptionNote` rows per child. The damage is
partly hidden, because `GET /adaptive/feedback` de-duplicates to the newest note per
student (`adaptive.py:397-401`) — so the screen looks right and the invoice does not.
Held down, or scripted, there is nothing between the click and the provider.

**The fix.** Add `dependencies=[AiRateLimit]` — one line, matching the other seven. Add the
in-flight guard `/adaptive/propose` has (narrowed per C1, so both are fixed the same way).

**Breaking for clients?** A new 429 the client must render. `rate_limited` is one of the
codes with no catalogue entry (M1), so today it would surface as the generic fallback
sentence — fix both together.

---

#### H4 · `POST /adaptive/regenerate` blocks a request handler on a model call

**What is wrong.** The handler calls `regenerate_exercise` synchronously
(`adaptive.py:252-255`), and that function builds an `AiClient()` (`adaptive_service.py:1892`),
runs a retrieval pass (`:1895`) and then a generation (`:1913-1929`) before returning. Every
other model-reaching operation in the product is a `Job`.

CLAUDE.md is unambiguous: *"Nothing blocks a request handler on a model call. Long work
goes to the arq worker and reports progress through `Job`."* `POST /adaptive/propose`'s own
docstring cites the rule as the reason it is a job.

There is a second, smaller problem in the same handler:

```python
raise errors.unprocessable(f"could not regenerate this exercise: {exc}") from exc
#                                                                ^ adaptive.py:255
```

`AdaptiveGenerationError`'s text can be a provider failure's message. `_not_renderable` in
`sheets.py:179-193` reasons about exactly this case and refuses to pass through anything
but our own authored text; this line passes through everything, into a `message` field that
`api/client.ts` says plainly is for the console. The `code` is the generic `unprocessable`,
so the client cannot render anything specific either way.

**Why it matters here.** A teacher rejects one generated exercise on the review screen and
clicks *Régénérer*. The request holds an HTTP connection for as long as a retrieval plus a
generation takes — typically several seconds, occasionally past whatever proxy timeout sits
in front of the API in the Cloudflare deployment (`docs/deploy-cloudflare.md`). On a
timeout the browser sees a network error while the server carries on: `regenerate_exercise`
discards the old exercise and commits the replacement (`:1911`, `:1935`), so the teacher's
screen still shows the item they rejected, the database no longer has it, and clicking
*Régénérer* again fails with "only a generated exercise can be regenerated" — the row is
already discarded.

**The fix.** Make it a job, like its seven siblings: `202` + `JobOut`, poll `GET /jobs/{id}`,
read the replacement from a result endpoint or from `Job.result`. If that is too heavy for
a single-item operation, at minimum bound it with an explicit timeout and return a named
error code the client can localise. And drop the `{exc}` interpolation — pass a code, let
the client own the sentence.

**Breaking for clients?** Yes, and this is the expensive one on the list. `202 + JobOut` is
a different response model, a different status code and a different client flow from
`200 + AdaptiveRegenerateResponse`. `apps/web` calls it today (`endpoints.ts`), and any
second consumer would have to change. **Change it before there is a second consumer.**

---

#### H5 · No idempotency anywhere, and two renders race on the geometry the scanner reads

**What is wrong.** `grep -rn "idempoten" apps/api` returns nothing. No endpoint accepts an
`Idempotency-Key`, and none of the three that matter guards itself another way:

* `POST /sheets/{id}/render` (`sheets.py:133-176`) — no in-flight check.
* `POST /adaptive/batch/{id}/render` (`adaptive.py:287-313`) — no in-flight check.
* `POST /scans` (`scans.py:58-97`) — no content-digest check, though `POST /sources` does
  exactly that with `sha256` (`sources.py:132-145`) and returns the existing row.

The only thing between a double-tapped button and two jobs is the per-teacher render
bucket at 12/min (`config.py:219`), which admits a double-click trivially.

That would be merely wasteful if rendering were pure. It is not:

```python
db.execute(delete(AnswerBoxPlacement).where(AnswerBoxPlacement.sheet_id == sheet.id))
#                                                    sheets/render.py:668
```

Every render **deletes every answer-box placement for the sheet** and rewrites them from
what Chromium just measured. CLAUDE.md's rule for those rows: *"An answer box is cut where
it printed, never where it was estimated. The render job measures every box in Chromium and
writes `AnswerBoxPlacement`; the scan job crops at those rows."* Phase 1 L1 adds that
placements are keyed `(sheet_id, student_uid, copy_page, item_index)` and *replaced* on
every re-render, so reprints deliberately collide and the newest render wins.

Two concurrent render jobs for one sheet therefore interleave a delete and an insert over
the same key set, while only one of the two PDFs ends up under `sheet.blank_pdf_key`. The
placements the scan job will crop at are whichever job finished writing last; the paper the
teacher printed came from whichever job wrote the bucket last. Nothing forces those to be
the same job.

**Why it matters here.** This is the brief's QR question in the shape Alppy actually has.
Mme Berger's laptop is slow; she clicks *Générer les PDF* and, seeing no spinner, clicks
again. Two `RENDER_SHEET` jobs run. She downloads the PDF, photocopies twenty-eight copies,
and the class writes in the boxes. Three days later she photographs the pile. The scan job
crops each written answer at the `AnswerBoxPlacement` rows — and if the losing job wrote
them last, every crop is offset by however much the two Chromium passes disagreed. In the
common case the two renders are identical and nothing happens, which is exactly what makes
this the kind of bug that surfaces once, on a sheet with a long statement that paginated
differently, and is never reproducible.

The `GRADE_OPEN_ANSWERS` chain then sends those crops to a vision model. A crop that starts
half a line high contains the bottom of the printed statement and the top of the child's
answer, and `alppy/scan/answer_box.py` removes Alppy's own ink, not the book's.

**The fix.**

* An in-flight guard on both render routes: a `QUEUED`/`RUNNING` job of the same kind for
  the same `sheet_id` returns that job, as `/adaptive/propose` does (narrowed per C1).
* An `Idempotency-Key` header on `POST /sheets/{id}/render`, `POST /adaptive/batch`,
  `POST /adaptive/batch/{id}/render`, `POST /scans` and `POST /scans/{id}/confirm`, stored
  against the created row and replayed rather than re-executed.
* Longer term, and worth deciding now: placements are keyed by `(sheet, uid, page, item)`
  with no print-run identity, so a re-render after an edit silently invalidates the
  geometry of paper already in circulation. A `print_run_id` on the placement and on the
  printed page would let a scan resolve against the run it came from.

`POST /scans/{id}/confirm` is the one that is already safe by accident and worth keeping
that way: a retried confirm gets a `scan_already_confirmed` 409 rather than a second set of
attempts, and re-confirming supersedes rather than accumulates (`scan_service.py:652-657`).
That is the right shape; the others should copy it.

**Breaking for clients?** No. An in-flight guard returning the existing job matches what
`/adaptive/propose` already does; `Idempotency-Key` is opt-in.

---

#### H6 · Anyone can add anyone to a staffroom, nothing removes them, and nothing records it

**What is wrong.** `POST /schools/{school_id}/teachers/{teacher_id}` (`classes.py:379-410`)
requires only that the **caller** is a member of the target school. The teacher being added
is looked up by primary key with no scoping at all:

```python
joining = db.get(Teacher, teacher_id)          # classes.py:402
if joining is None:
    raise errors.not_found("teacher", id=str(teacher_id))
svc.join_school(db, joining.id, school_id)
```

The handler's docstring is admirably honest about all of it: *"Membership is the whole
check — there is no admin tier, deliberately (D85). Note it is also add-only: no route
removes a membership, so a colleague added by a mistyped uuid comes out in SQL.
`teacher_school` was built for the removal … the endpoint is missing, not refused."*

What membership buys is not small. `get_membership` proves the pair against
`teacher_school` and binds `app.current_school_id` (`deps.py:136-153`), after which the new
member can read `GET /colleagues`, `GET /subjects`, `GET /chapters`, every uploaded
textbook and every extracted exercise, and — by creating a class or being assigned a branch
— reach `GET /classes/{id}/students`, which returns children's real first and last names.

No `EventKind` covers it either (Phase 1 H7 lists all eleven, all product verbs), so the
grant leaves no trace in the agenda and no trace in an audit log that does not exist.

**Why it matters here.** Two ways this goes wrong, and neither needs malice.

*The typo.* A teacher pastes a uuid from the wrong column and adds a colleague from another
établissement to their staffroom. There is no way to undo it in the product. The fix is a
`DELETE FROM teacher_school` run by whoever has database access, against a table whose row
grants access to minors' records.

*The leaver.* A teacher moves to another school in August. Nothing in Alppy removes their
membership, because nothing can. `get_membership`'s comment says *"Valid signature, but
this teacher no longer works at the school the cookie names — they left, or it was never
theirs"* — describing a `teacher_school` row that was deleted, by a mechanism the API does
not have.

**The fix.** `DELETE /schools/{school_id}/teachers/{teacher_id}`, refusing the last member
and refusing a teacher who is still `head_teacher_id` of a class (that column is `NOT NULL`
and `RESTRICT`, so the refusal is already enforceable). An `EventKind` for both directions.
And decide D85 deliberately rather than by omission: a flat staffroom is a legitimate
choice for a five-teacher établissement and a poor one for a forty-teacher collège, and
the API currently has no way to express the second.

**Breaking for clients?** No — purely additive. `apps/web` calls neither route today.

---

#### H7 · The session cannot be revoked, and four standard auth flows do not exist

**What is wrong.** The session is a stateless `itsdangerous` signature over
`{"t": teacher_id, "s": school_id}` (`core/security.py:63-67`), valid for
`session_max_age_s = 43200` — twelve hours (`config.py:62`). There is no server-side
session store, so:

* **Logout is client-side only.** `POST /auth/logout` calls `response.delete_cookie` and
  nothing else (`auth.py:124-126`). A cookie copied before logout stays valid for the
  remainder of its twelve hours.
* **There is no revocation path at all.** Rotating `secret_key` invalidates every session
  in every school simultaneously; there is nothing between that and waiting.
* **There is no session or device listing**, so a teacher cannot see where they are signed
  in, and support cannot answer "was this account used from somewhere else".
* **There is no password reset, no email verification and no account creation.** No route
  under `/auth` other than login, school-switch, logout and me; `Teacher` rows exist only
  because a seed made them (`seed/demo.py`, `seed/staging.py`).

What *is* there is good and worth saying: Argon2id with rehash-on-login, a dummy-hash
verify so an unknown address costs the same time as a known one (`auth.py:56-61`),
failure-only rate limiting per account and per address with the check before the hash
(`deps.py:371-394`), and a deliberate refusal to clear the IP bucket on success because
*"one success among many failures from the same source is what credential stuffing looks
like when it works"*. The account-enumeration question (#34) is answered correctly for the
one flow that exists.

**Why it matters here.** The brief's shared-device case is the live one. Alppy is used *on
a projector laptop in the classroom* — the CSP and `frame-ancestors 'self'` reasoning in
`main.py:36-42` is about a preview being projected onto a wall. A teacher signs in on the
staffroom machine at 08:15 to print, walks away, and the cookie is good until 20:15 with no
way to end it from anywhere else. The next person to touch that browser has a roster of
children's names, every scanned answer sheet, and `DELETE /students/{id}`.

**The fix.** Smallest change that closes the hole: a `session_version` integer on `Teacher`,
carried in the cookie payload and compared in `get_membership` — logout and "sign out
everywhere" both increment it, and a stolen cookie dies at the next request. That is one
column, one payload field and one comparison, and it keeps the no-store design.

Beyond that, and needed before a second school: password reset (with the same
enumeration-resistant shape login already has), email verification, and an invitation flow
so H6's raw `teacher_id` is not how colleagues are added.

**Federated identity (#31).** Nothing here anticipates Edulog, cantonal SSO or a school
Microsoft 365 / Google Workspace tenant, and it does not have to yet — but the contract's
shape is fortunate. `Teacher.email` is the identity, the cookie carries only ids, and
`get_membership` re-proves entitlement against `teacher_school` on every request rather
than trusting a claim. Adding OIDC or SAML is therefore a new `/auth/*` route that mints
the same cookie, plus an external-subject column on `Teacher` — no change to the 85 routes
below it. The thing that would make it hard, and does not exist, is a role or permission
claim baked into a token; the codebase's decision to answer authorisation from data
(H-adjacent, see §5) is exactly what keeps that door open.

**Students (#30, #35, #36).** Students do not authenticate. There is no student account, no
class code, no student-facing route, and `Student` has no password column. The identifier
on paper is a printed UID bubble grid (`sheets/layout.py:208`), read by
`scan/detector.py:571` into `scan_page.detected_uid`, and it is used for **attribution
only** — no code path treats it as an authentication or authorisation factor, which is the
right answer to #36 and worth keeping written down. The one place a UID gates anything is
`DELETE /students/{id}?confirm=<uid>`, and that is a typo guard, not a secret: the
docstring says so, and the UID is printed on the paper. Correct as designed, and see M9 for
the query-string half of it.

**Breaking for clients?** `session_version` is invisible to clients. Reset/verification/
invitation are additive.

---

#### H8 · No export, no anonymisation, and the only erasure leaves the photographs behind

**What is wrong.** The contract's entire answer to a data-subject request is
`DELETE /students/{id}?confirm=<uid>` (`classes.py:323-339`), which calls
`nouns_service.delete_student` — `db.delete(student)` and a cascade (Phase 1 H5,
`nouns_service.py:396`). Three consequences at the API level:

* **Nothing is exported.** There is no endpoint that assembles one pupil's record. The
  closest is `GET /students/{id}/mastery` plus one `GET /students/{id}/sheets/{sheet_id}`
  per sheet — a client-side loop over a list the profile happens to carry.
* **Nothing is anonymised.** There is no `PATCH` that nulls the names and keeps the
  evidence. The route destroys `attempt`, `mastery_snapshot`, `sheet_instance`,
  `misconception_note` and `exercise_variant`, so the class's own statistics change
  retroactively — `GET /classes/{id}/points` and `GET /classes/{id}/mastery` both return
  different numbers for terms already reported.
* **The images stay.** `Storage` has no `delete` (the `delete_source` docstring says so
  outright: *"this is not the route to introduce an untested destructive call on the object
  store"*), so `scan_page.image_key` and `detection.crop_key` — photographs of a child's
  handwriting — survive the deletion of every row that pointed at them. After the delete
  nothing can find them to remove later.

**Why it matters here.** A parent in Valais exercises a deletion request in March 2027. The
school runs the delete. The child's name leaves the database; twenty-eight PNGs of their
handwriting stay in MinIO under a key naming their school and their scan id, now unreferenced.
Meanwhile the class average for the autumn test moves, because the child's marks were
cascaded out of it, and the teacher who reported that average to a *conseil de classe*
cannot reproduce it.

**The fix.** Three routes, and the middle one should be the default:

* `GET /students/{id}/export` — the pupil's whole record as one document.
* `POST /students/{id}/anonymise` — names nulled, `uid` and evidence retained, an
  `anonymised_at` stamp. Class statistics survive; the person is no longer identifiable.
* Keep `DELETE` for genuine erasure, and make it enumerate and delete the pupil's storage
  objects first.

This depends on Phase 1's open question 4 (whether the cantonal DPO requires erasure of the
pedagogical record or only of the identifier), which is a legal question and is repeated in
§8.

**Breaking for clients?** No — additive.

---

#### H9 · There is no exercise bank

**What is wrong.** The only way to list exercises is `GET /sources/{source_id}/exercises`
(`sources.py:307-405`) — nested under one document. There is no `GET /exercises`. The
consequences for the brief's #20 (*"can a teacher filter the exercise bank by objective,
year, difficulty and source book in one query?"*):

| Filter | Available? |
|---|---|
| source book | only by *being* in one book's URL; no cross-book query |
| difficulty | yes (`difficulty`, 1–5) |
| type | yes, with facet counts |
| document section | yes (`section_id`) |
| Theme | yes (`chapter_id`, plus the `none` sentinel — good, and DC-content-06) |
| free text | yes (`q`, over statement/label/title) |
| **PER objective / competency** | **no** |
| **year (9H/10H/11H)** | **no** — the concept does not exist in the schema (Phase 1 H1) |
| origin (textbook / AI / teacher) | no |
| approved / unapproved | no |

So a teacher cannot ask the question their planning actually starts from — *"show me
everything I have on MSN 34, difficulty 2-3, across all my books"* — and the adaptive
engine's own `retrieval.gather_candidates` can filter by `competency_ids`
(`adaptive_service.py:1895-1904`), which means the capability exists in the service layer
and is not exposed. Same shape as C3's `as_of`.

**Why it matters here.** It is the difference between a textbook browser and a bank. Mme
Berger has three MER PDFs indexed for maths. She is teaching Pythagore next week and wants
the twelve exercises she has on it. Today she opens book one, guesses which section, scans
a page of results, opens book two, repeats. The Theme filter helps only if the ingest
tagged `Exercise.chapter_id`, which CLAUDE.md says is null *"on a large minority of a real
textbook"*.

**The fix.** `GET /exercises` with `competency_id` (repeatable), `subject_id`, `chapter_id`
(with the `none` sentinel), `source_id` (repeatable), `type`, `difficulty`, `origin`,
`approved`, `q`, `offset`, `limit`, and the same facet block. The query is the one already
written in `sources.py:334-405` with the source predicate lifted out and a join to
`exercise_competency` added — Phase 1 M1 notes that join direction is currently unindexed,
so the index goes in with it.

**Breaking for clients?** No — additive. `GET /sources/{id}/exercises` stays for the
document browser, which is a different question and a good screen.

---

### Medium

**M1 · Twelve error codes with no sentence.** The API emits nine named codes
(`branch_holds_sheets`, `detection_not_corrected`, `scan_already_confirmed`,
`scan_confirmed`, `scan_matches_no_sheet`, `scan_not_confirmed`,
`scan_open_grading_pending`, `scan_pages_unassigned`, `sheet_not_renderable`) plus the
constructor defaults (`unauthorized`, `forbidden`, `conflict`, `not_found`, `unprocessable`,
`payload_too_large`, `unsupported_media_type`, `rate_limited`, `service_unavailable`,
`validation_error`, `internal_error`) and the `_STATUS_CODES` map (`bad_request`,
`method_not_allowed`, `http_error`). `apps/web/messages/fr.json` `errors.code` holds
thirteen keys. Missing, and therefore rendered as the generic fallback: `branch_holds_sheets`,
`detection_not_corrected`, `scan_confirmed`, `scan_not_confirmed`, `unauthorized`,
`forbidden`, `rate_limited`, `service_unavailable`, `internal_error`, `bad_request`,
`method_not_allowed`, `http_error`. So a teacher who hits the AI limit, or who tries to
remove a Branch that still holds sheets — a refusal the API took the trouble to name and
carry details for — reads the same sentence as any other failure. The design is right (#25:
codes cross, the client owns the sentence, and `apiErrorMessage` never throws); the gate is
missing. `pnpm i18n:check` proves the three catalogues agree with *each other*, and
`catalogue.test.ts` asserts two keys exist. Nothing compares the API's code set to the
catalogue's key set — and the code set is mechanically extractable, so it can be.

**M2 · A PATCH may smuggle in what POST would refuse.** `SheetCreate.items` is bounded at
64 (`schemas/__init__.py:540`); `SheetUpdate.items` is `list[SheetItemIn] | None` with no
bound at all (`:555`), and `update_sheet` applies it without one (`sheet_service.py:312-317`).
`SheetDraftPreview.items` correctly carries the 64. `AdaptiveBatchRequest.plans` is
unbounded (`:1247`), and each plan carries unbounded `retrieved` and `generated` lists of
full `ExerciseOut` objects. `ExerciseUpdate`'s docstring makes the argument this violates:
*"An edit is not a lesser write than a creation: the row it lands in is the row the sheet
renderer paginates … so a statement PATCH may not smuggle in what POST would refuse."*
Same rule, three places it was not applied.

**M3 · Five tenant-unfiltered queries in the timeline.** `api/v1/timeline.py:49-74` resolves
event titles with `select(Sheet).where(Sheet.id.in_(ids))`, and the same shape for `Source`,
`SourceSection`, `Scan` and `Class`; `:125-130` adds a sixth for class codes. None carries
`school_id`. RLS covers them in Postgres because the session is bound — but the first layer
is the required `school_id` argument, and CLAUDE.md is explicit that it *"does not change"*.
Worth raising because `adaptive.py:382-387` claims to be *"the only place in the codebase
where the tenant filter is an inference rather than a line"* and writes the redundant
predicate anyway; that claim is now false by six.

**M4 · Eight collections with no paging, filtering or sorting.** `GET /classes`,
`GET /classes/{id}/students`, `GET /subjects`, `GET /chapters`, `GET /colleagues`,
`GET /sheets`, `GET /scans`, `GET /curricula/{kind}/competencies` and
`GET /scans/{id}/detections` all return everything. Three endpoints do it properly —
`/sources/{id}/exercises`, `/timeline` and `/jobs` — with `offset`/`limit`/`total` and, for
the first two, facet counts computed with every filter except the one each chip controls.
That is the right pattern and it should be the house style. At current scale only
`/scans/{id}/detections` (28 copies × 12 items = 336 rows, each with `fill_ratios` and
`bubble_boxes`) and `/curricula/{kind}/competencies` (which will be several hundred rows
once Phase 1 H1's five real PER levels are seeded) are near a problem, but the shape is
what a client builds against.

**M5 · Jobs and proposals are tenant-grained.** `GET /jobs`, `GET /jobs/{id}`
(`jobs.py:29`, `:41`) and `GET /adaptive/proposal/{job_id}` (`adaptive.py:169`) filter on
`school_id` only, as do `POST /adaptive/approve`, `/discard` and `/regenerate`. Everything
else that touches a class or a pupil is class- or pair-grained. `JobOut` carries `result`,
a free `dict`, and `Job.payload` holds `class_id`, `subject_id` and `student_ids` — so
`GET /jobs?kind=propose_adaptive` enumerates every adaptive run in the school. C1 is the
sharp end of this; the general fix is to give `Job` a nullable `class_id` column and filter
on `owned_class_ids`.

**M6 · Scan upload is atomic, in-memory, and not resumable.** `POST /scans` takes
`list[UploadFile]`, checks the count before the first read (`deps.py:521-535` — good, and
the reasoning is right), then reads every file fully into memory
(`scans.py:92`) before writing anything. Caps are 120 files × 50 MB
(`config.py:235-236`), and the config docstring acknowledges *"the worst case is still
`max_upload_files x max_upload_mb`"* — 6 GB. There is no partial success, no resume and no
chunking: a 30-photo batch that drops at photo 29 on classroom Wi-Fi is retried whole, and
the retry creates a second `Scan`. Answer to #52: the contract assumes a connection good
enough to hold one large multipart body. `POST /scans/{id}/confirm` is the counter-example
and is genuinely resilient — a retried confirm 409s rather than double-grading, and
re-confirmation supersedes rather than accumulates.

**M7 · No cancellation and no retry.** `Job` has `QUEUED`/`RUNNING`/`SUCCEEDED`/`FAILED`
and no route mutates it. A `PROPOSE_ADAPTIVE` run started against the wrong class must be
waited out — and because of C1 it also blocks every other proposal in the school while it
runs. `DELETE /jobs/{id}` (cancel) and `POST /jobs/{id}/retry` are both natural and absent.

**M8 · Domain validation is type-correct, not domain-correct.** Checked against the brief's
list:

| Rule | Status |
|---|---|
| class code | **enforced**, `is_valid_class_code` — "must look like 7B or 11AB" (`schemas:229-238`) |
| MCQ answer agrees with type | **enforced**, and refuses rather than coerces (`schemas:406-428`) |
| option count ≤ printed bubbles | **enforced**, `MAX_OPTIONS` from `sheets.layout` |
| answer-box lines ≤ page | **enforced**, `ANSWER_BOX_MAX_LINES` from `sheets.layout` |
| per-item points | **enforced**, `0..MAX_ITEM_POINTS`, penalty as a magnitude |
| detection index ≤ this item's options | **enforced in the service**, which is the only layer that knows (`scan_service:308-314`) |
| UID format | `validate_uid` exists (`schemas:1415`) and **is not used by any schema** |
| canton code | `Field(max_length=2)`, no set (`schemas:187`, `:193`) |
| school-year format | no such field in the contract |
| HarmoS year 9–11 | no such field anywhere |
| grade scale (Swiss 1–6) | not modelled — Alppy grades in points and bands, deliberately |

The print-geometry rules are the best-validated part of the contract and they are validated
against `sheets.layout` constants rather than against re-typed numbers, which is exactly
right. The Swiss-structure rules are the gap, and it is the same gap Phase 1 M8 names:
`canton` exists as data and nothing branches on it. `validate_uid` being defined and unused
is worth a line either way — wire it or delete it.

**M9 · A pupil's identifier in a query string.** `DELETE /students/{id}?confirm=7B_15`
(`classes.py:328`). The UID is pseudonymous rather than a name, and the access log records
`request.url.path` only (`main.py:76-77`) — so *our* log is clean. Browser history, any
reverse proxy's access log and any referrer are not. It is the only student identifier
anywhere in a URL or query string; every other route takes a UUID. Sweep result for #46:
no names, no emails, no birthdates in any path or query anywhere. Fix: move `confirm` into
a request body (`DELETE` with a body is legal and FastAPI supports it) or make it a
two-step `POST /students/{id}/deletion-intent` → `DELETE`.

**M10 · No quota, only a throttle.** `TokenBucketLimiter` is per teacher and per process,
and its docstring is honest that this is *"a guard against one teacher holding a click, not
a billing control"* and that the real ceiling is `rate × uvicorn workers`. There is no
per-establishment budget, no monthly cap, no spend counter and no endpoint reporting usage
— `ModelCall` exists in the database to answer an auditor but nothing surfaces it. For a
product sold to a school, "what did this cost us this month" is a question the contract
cannot answer.

**M11 · The published surface is a third of the real one.** `docs/plan.md` §4 lists 30
routes in prose. The code has **89**. There is no OpenAPI document in the repository, and
the served one is switched off in staging and production (`main.py:103-114`, with a good
argument for it). So the published contract is prose plus a hand-written client. Beyond the
59 undocumented routes, one documented route has the wrong shape: plan.md:140 says
`POST /adaptive/batch -> job -> one PDF`, and the code returns `201 + SheetOut` and requires
a second call to `POST /adaptive/batch/{sheet_id}/render` for the job. Four routes exist
that no client calls at all: `POST /chapters`, `POST /schools`,
`POST /schools/{id}/teachers/{id}` (H6) and `GET /jobs`. One of them, `POST /chapters`,
defines its request model *inside the router* with a comment saying so — `class ChapterCreate`
at `curriculum.py:28-35`, *"Not in `alppy.schemas` — see the report note on the contract
gap"* — so it is in the OpenAPI document but outside the file the client mirrors.

**M12 · Approval and discard are school-wide.** `PATCH /exercises/{id}` with
`{"approved": true}` (`sources.py:504-505`) and `POST /adaptive/discard`
(`adaptive.py:221-230`) both take `TenantDep`-grain school scoping and no ownership check.
The corpus being staffroom-shared is a deliberate and correct decision
(`enrollment.py:124-136`, I-platform-04) — but `approved_at` is not a corpus property, it
is a *sign-off*, and CLAUDE.md's rule is that *"AI-generated exercises are never printed
without teacher approval"*. As written, teacher A's approval satisfies the gate for teacher
B's print. Similarly `discard_exercises` sets `discarded_at`, after which the item *"is
never proposed or printed again"* — a colleague can destroy the proposals you are in the
middle of reviewing. Neither is a leak; both are a missing "whose" on an action that has
one.

**M13 · "Printed" is written and cannot be read back.** `POST /sheets/{id}/printed`
(`sheets.py:302-331`) records an `EventKind.SHEET_PRINTED` and returns `SheetOut`, which has
`rendered_at` and no `printed_at`. The docstring explains why the moment matters — *"a
teacher renders on Sunday and prints on Tuesday morning"* — and then leaves it retrievable
only by paging `/timeline` and filtering by kind and subject id. A client cannot show "not
yet printed" on a sheet card without a second, unreliable query.

### Low

**L1 · `GET /sources/{id}/status` filters in Python.** It selects every `INGEST_SOURCE` job
in the school ordered by date and loops looking for a payload match
(`sources.py:208-217`). One row wanted, N fetched, N growing monotonically with every
upload the school ever makes. The fix is the same `Job.source_id`/`Job.class_id` column M5
wants.

**L2 · Two internals cross to the client.** `DetectionOut.vision_model`
(`schemas:694`) puts a provider's model identifier on the review screen, and
`AdaptiveGenerationFailure.detail` (`schemas:1200`) carries a generation failure's prose.
Both are arguably deliberate — the teacher auditing a machine verdict has a real interest
in which machine — but they should be a deliberate decision rather than a field that got
serialised. `detail` in particular is the one field in the whole contract that can carry a
provider error's own text to a browser, which is the thing `Job.error` and `Source.error`
were both restructured to prevent (D86).

**L3 · Presigned URLs for children's handwriting.** `S3Storage.url_for` signs for 900 s
(`storage.py:167-179`). Those URLs appear in `ScanPageOut.image_url` and
`DetectionOut.crop_url` — a photograph of a page of a child's answer sheet and a crop of
one written answer. Within the window the URL is bearer authority with no session behind
it, so a pasted link, a screenshot of a URL bar or a browser sync carries it. 900 s is a
defensible number and 15 minutes is a long time in a staffroom chat; worth an explicit
decision, and worth shortening for `crop_url` specifically.

**L4 · One health endpoint doing three jobs.** `GET /health` (`health.py:55-71`) opens a
database connection, a Redis connection and an S3 `head_bucket` on every call, is
unauthenticated, and is the only probe. A liveness probe hitting it at 1 Hz triples that
load; there is no cheap readiness/liveness split. It never raises, which is right.
Request-id propagation is good: `X-Request-ID` is accepted, validated against a strict token
pattern with a written argument about log forging (`main.py:26-32`), echoed on every
response including non-JSON ones, and carried in every error envelope — so #51's "a
correlation id a teacher could report to support" is answered.

**L5 · Nesting and hierarchy.** Two paths are three levels deep:
`/classes/{c}/teachers/{t}/branches/{s}` and `/students/{s}/competencies/{c}/attempts`. Both
are defensible as they stand. The one to watch is `Sheet` — it is reached as `/sheets/{id}`
(flat, good) but `SheetCreate` requires `class_id`, and `SheetTarget` already has a `group`
member that Phase 1 notes has been unused since 0001. When a sheet can target an ad-hoc
group rather than a class, `class_id`-as-required becomes the assumption that has to move.

**L6 · Verb and status drift.** `POST /classes/{c}/students/{s}/enrollment` returns 201 for
an explicitly idempotent operation that may create nothing (`classes.py:103-125`), and its
`DELETE` counterpart returns 200 with a roster body (`:128-146`). Both are pragmatic and
both are documented in the docstrings; they are listed here so the de facto convention is
written down rather than inferred. Otherwise verb usage is clean: 44 writes, correct 201s
on creation, 202s on every job-queuing route, 204s on the two true deletes, and `PUT` used
exactly once for the one whole-list replacement (`/classes/{id}/subjects`) with a written
reason.

**L7 · The contract's nouns are not the product's nouns.** Paths and fields are English
throughout (`class`, `subject`, `chapter`, `student`, `sheet`), with French only ever as
*data* in `labels`/`description`. That is consistent, and matches Phase 1 L5's finding for
the schema. But `Subject` is "Branche" on screen, `Chapter` is "Thème", and `Class` covers
both an administrative *classe* and a maths *groupe*. A frontend developer reading
`ChapterOut` has no way to learn from the contract that it is the thing the UI calls a
Theme. One paragraph in the schemas module's header would fix it.

---

## 4 · Endpoint inventory

Reconstructed from the `@router.*` decorators across `apps/api/alppy/api/v1/*.py`, not from
`docs/plan.md`. **89 routes.** There is exactly one role in the system — an authenticated
teacher — so the "permitted" column reports the *ownership grain* rather than a role:

* **public** — no session required
* **tenant** — any member of the school (`TenantDep`, `get_membership`)
* **class** — a footing in the class: head teacher **or** any branch (`owned_class_ids`)
* **pair** — teaches *this branch* in *this class* (`taught_here`)
* **self** — the signed-in teacher's own row

"Spec" is `docs/plan.md` §4, the only published surface.

| Method | Path | Purpose | Auth | Permitted | Tenant scoping | Spec |
|---|---|---|---|---|---|---|
| GET | `/health` | liveness of db/redis/storage | no | public | — | ✓ |
| GET | `/files/{key:path}` | dev object proxy | yes | tenant | key segment == `school_id` | ✗ |
| POST | `/auth/login` | sign in, set cookie | no | public | — | ✓ |
| POST | `/auth/school/{school_id}` | switch tenant, re-issue cookie | yes | self | `schools_for_teacher` | ✗ |
| POST | `/auth/logout` | clear cookie (client-side only, H7) | yes | self | — | ✓ |
| GET | `/auth/me` | current teacher + staffrooms | yes | self | session | ✓ |
| PATCH | `/teachers/me/preferences` | locale + 4 display switches | yes | self | session | ✓ |
| GET | `/home` | teacher home summary, one round trip | yes | class | `owned_class_ids` | ✗ |
| GET | `/subjects` | Branches in this school | yes | tenant | `school_id` | ✓ |
| POST | `/subjects` | create a Branch | yes | tenant | `school_id` | ✗ |
| PATCH | `/subjects/{id}` | rename a Branch — **H1, never commits** | yes | tenant | `scoped_get` | ✗ |
| GET | `/colleagues` | staffroom, for the branch picker | yes | tenant | `teacher_school` | ✗ |
| GET | `/classes` | classes with a footing | yes | class | `owned_class_ids` | ✓ |
| POST | `/classes` | create a class | yes | tenant | `school_id` | ✓ |
| GET | `/classes/{id}` | one class, detail | yes | class | `owned_class_ids` | ✓ |
| PATCH | `/classes/{id}` | rename; code refused once pupils exist | yes | class | `owned_class_ids` | ✗ |
| GET | `/classes/{id}/students` | roster — **implicitly now (C3)** | yes | class | `enrolled_in_owned_classes` | ✓ |
| POST | `/classes/{id}/students` | roster paste, mints UIDs | yes | class | `owned_class_ids` | ✓ |
| POST | `/classes/{id}/students/{sid}/enrollment` | seat an existing pupil | yes | class | `owned_class_ids` | ✗ |
| DELETE | `/classes/{id}/students/{sid}/enrollment` | unseat — **a hard DELETE (Phase 1 C1)** | yes | class | `owned_class_ids` | ✗ |
| GET | `/classes/{id}/teachers` | who teaches what here | yes | class | `owned_class_ids` | ✗ |
| POST | `/classes/{id}/teachers/{tid}/branches/{sid}` | assign a branch | yes | class | `owned_class_ids` | ✗ |
| DELETE | `/classes/{id}/teachers/{tid}/branches/{sid}` | unassign — **hard DELETE** | yes | class | `owned_class_ids` | ✗ |
| POST | `/classes/{id}/subjects/{sid}` | declare a Branch studied here | yes | class | `owned_class_ids` | ✗ |
| DELETE | `/classes/{id}/subjects/{sid}` | undeclare; refused while sheets exist | yes | class | `owned_class_ids` | ✗ |
| PUT | `/classes/{id}/subjects` | reorder the Branch nav | yes | class | `owned_class_ids` | ✗ |
| PATCH | `/schools/me` | rename the school | yes | tenant | session | ✗ |
| POST | `/schools` | create a school and join it | yes | any teacher | — | ✗ |
| POST | `/schools/{id}/teachers/{tid}` | **H6** — add a colleague, no revoke | yes | tenant | caller's membership | ✗ |
| PATCH | `/students/{id}` | rename a pupil | yes | class | `get_student` | ✗ |
| DELETE | `/students/{id}?confirm=<uid>` | destroy a pupil — **H8, M9** | yes | class | `get_student` | ✗ |
| GET | `/curricula/{kind}/competencies` | PER/LP21 reference data | yes | tenant¹ | none (global table) | ✓ |
| GET | `/chapters` | Themes in this school | yes | tenant | `school_id` | ✓ |
| POST | `/chapters` | create a Theme — **request model outside `schemas`** | yes | tenant | `school_id` | ✓ |
| PATCH | `/chapters/{id}` | rename/move/re-credit | yes | tenant | `scoped_get` | ✗ |
| DELETE | `/chapters/{id}` | remove; refused on `unfiled` | yes | tenant | `scoped_get` | ✗ |
| GET | `/sources` | the shelf | yes | tenant | `school_id` | ✗ |
| POST | `/sources` | upload a PDF → job; sha256 dedup | yes | tenant | `school_id` | ✓ |
| GET | `/sources/{id}` | one book | yes | tenant | `school_id` | ✓ |
| PATCH | `/sources/{id}` | edit book metadata | yes | tenant | `scoped_get` | ✗ |
| DELETE | `/sources/{id}` | refused while exercises cite it; **leaves the PDF** | yes | tenant | `scoped_get` | ✗ |
| GET | `/sources/{id}/status` | the ingest job — **L1** | yes | tenant | `school_id` | ✓ |
| GET | `/sources/{id}/sections` | the book's table of contents | yes | tenant | `school_id` | ✓ |
| POST | `/sources/{id}/sections/{sid}/extract` | read one chapter → job | yes | tenant | `school_id` | ✓ |
| GET | `/sources/{id}/exercises` | paged + faceted — **the only bank (H9)** | yes | tenant | `school_id` | ✓ |
| POST | `/exercises` | teacher-written exercise | yes | tenant | `school_id` | ✓ |
| PATCH | `/exercises/{id}` | edit; **flips `approved` (M12)** | yes | tenant | `school_id` | ✓ |
| POST | `/sheets/propose` | ranked exercises + provenance | yes | class | `get_class` | ✓ |
| GET | `/sheets` | sheets in branches taught | yes | pair | `taught_here` | ✗ |
| POST | `/sheets` | create a sheet | yes | class+ | `get_class` | ✓ |
| GET | `/sheets/{id}` | one sheet with items + instances | yes | pair | `taught_here` | ✓ |
| PATCH | `/sheets/{id}` | edit; invalidates the render — **M2** | yes | pair | `taught_here` | ✓ |
| POST | `/sheets/{id}/render` | queue blank + key PDFs — **H5** | yes | pair | `taught_here` | ✓ |
| POST | `/sheets/preview` | render an unsaved draft (HTML) | yes | class | `get_class` | ✓ |
| GET | `/sheets/{id}/preview` | the print document as HTML | yes | pair | `taught_here` | ✓ |
| POST | `/sheets/{id}/printed` | record the photocopier — **M13** | yes | pair | `taught_here` | ✗ |
| GET | `/sheets/{id}/mastery` | class bands for one sheet | yes | pair | `taught_here` | ✗ |
| GET | `/sheets/{id}/confidence` | per-item scan confidence | yes | pair | `taught_here` | ✗ |
| GET | `/scans` | piles, optionally by sheet | yes | pair² | `taught_here` | ✗ |
| POST | `/scans` | upload a pile → job — **M6** | yes | tenant | `school_id` | ✓ |
| GET | `/scans/{id}` | pile with pages + detections | yes | pair² | `taught_here` | ✓ |
| GET | `/scans/{id}/detections` | readings for the pile | yes | pair² | `taught_here` | ✓ |
| PATCH | `/scans/{id}/detections/{d}` | teacher override; refused if confirmed | yes | pair² | `taught_here` | ✓ |
| POST | `/scans/{id}/detections/{d}/revert` | undo an override | yes | pair² | `taught_here` | ✗ |
| GET | `/scans/{id}/students` | assignable pupils — **implicitly now (C3)** | yes | pair² | `taught_here` | ✗ |
| PATCH | `/scans/{id}/pages/{p}` | assign a page — **C2** | yes | pair² | `taught_here` | ✗ |
| POST | `/scans/{id}/pages/{p}/discard` | take a page out / put it back | yes | pair² | `taught_here` | ✗ |
| POST | `/scans/{id}/confirm` | grade → attempts → mastery | yes | pair² | `taught_here` | ✓ |
| POST | `/scans/{id}/reopen` | withdraw the grades | yes | pair² | `taught_here` | ✗ |
| GET | `/classes/{id}/mastery` | the matrix — **implicitly now (C3)** | yes | class | `owned_class_ids` | ✓ |
| GET | `/classes/{id}/tree` | Branch→Competence→Theme, banded | yes | class | `owned_class_ids` | ✓ |
| GET | `/classes/{id}/points` | what the class scored | yes | class | `owned_class_ids` | ✗ |
| GET | `/students/{id}/mastery` | the profile | yes | class | `_owned_student` | ✓ |
| GET | `/students/{id}/competencies/{c}/attempts` | the drill-down | yes | class | `_owned_student` | ✗ |
| GET | `/students/{id}/sheets/{sid}` | one pupil's copy, item by item | yes | class+pair | both | ✗ |
| POST | `/adaptive/propose` | queue targeting + generation — **C1** | yes | class | `get_class` | ✓ |
| GET | `/adaptive/proposal/{job_id}` | read the plan — **C1** | yes | **tenant** | `school_id` only | ✗ |
| POST | `/adaptive/approve` | the printability gate | yes | tenant | `school_id` | ✗ |
| POST | `/adaptive/discard` | destroy generated items — **M12** | yes | tenant | `school_id` | ✗ |
| POST | `/adaptive/regenerate` | replace one item — **H4, sync model call** | yes | tenant | `school_id` | ✗ |
| POST | `/adaptive/batch` | approved plans → one sheet | yes | class | `get_class` + approval gate | ✓ |
| POST | `/adaptive/batch/{id}/render` | queue the batch PDF — **H5** | yes | pair | `taught_here` | ✗ |
| POST | `/adaptive/feedback/generate` | queue per-pupil notes — **H3, no limit** | yes | class | `get_class` | ✗ |
| GET | `/adaptive/feedback` | live notes for one sheet | yes | pair | `taught_here` | ✗ |
| POST | `/adaptive/feedback/approve` | the printability gate for notes | yes | tenant | `school_id` | ✗ |
| POST | `/adaptive/feedback/discard` | discard notes | yes | tenant | `school_id` | ✗ |
| GET | `/timeline` | the agenda, paged + faceted — **M3** | yes | mixed³ | `school_id` + visibility | ✗ |
| GET | `/jobs` | list jobs — **M5, no client** | yes | tenant | `school_id` | ✗ |
| GET | `/jobs/{id}` | poll one job — **M5** | yes | tenant | `school_id` | ✓ |

¹ Requires a session (`_school_id: TenantDep`) but the data is global reference data with no
`school_id` — the dependency is there to keep the route behind the cookie, which is right.
² `taught_here` reached through `sheet_service.get_sheet` when the scan has a `sheet_id`;
`scan_service.get_scan` is what resolves it.
³ Three visibility arms by design: staffroom events for everyone, class events for anyone
with a footing, branch events only for the teacher who takes that branch.

**Routes in code, absent from the published spec: 59 of 89.**
**Routes in the spec that do not exist: 0** — but `POST /adaptive/batch` is documented with
the wrong shape (`-> job`; it returns `201 + SheetOut`).
**Routes with no client at all: 4** — `POST /chapters`, `POST /schools`,
`POST /schools/{id}/teachers/{id}`, `GET /jobs`.

---

## 5 · Authorisation matrix

Alppy has **one role**: an authenticated teacher. There is no admin tier, no support tier
and no student account, and D85 records that flatness as a decision rather than an
omission. The matrix is therefore roles × resources × *relationship*, which is where the
real answers are.

Authorisation is decided **against data, not against a claim** (#38) — and this is the
strongest thing in the API. The cookie carries only `{teacher_id, school_id}`; every
request re-proves membership with a `SELECT` against `teacher_school`
(`deps.py:136-140`, with a written argument for why it is a `SELECT` and not a relationship
read), and every class-grained read re-evaluates `owned_class_ids` as a subquery. A
teacher's assignment ending mid-term takes effect on their next request. There is no stale
role claim anywhere, because there is no role claim.

**Where authorisation is decided (#37).** In three shared predicates
(`services/enrollment.py`) plus five shared getters (`class_service.get_class`,
`get_student`, `get_colleague`, `sheet_service.get_sheet`, `scan_service.get_scan`,
`mastery_service._owned_student`) and `deps.scoped_get`. Handlers call one of these; almost
none decide anything inline. The exceptions, and they are the whole inline list:

| Route | Inline, unshared check | Line |
|---|---|---|
| `POST /schools/{id}/teachers/{tid}` | `mine = {s.id for s in schools_for_teacher(...)}` | `classes.py:399-401` |
| `GET /adaptive/proposal/{job_id}` | `job.school_id != scope.school_id` | `adaptive.py:169` |
| `GET /jobs/{id}` | `Job.school_id == school_id` in the select | `jobs.py:41-42` |
| `GET /files/{key:path}` | `parts[1] != str(school_id)` | `health.py:84` |
| `POST /auth/school/{id}` | `next((s for s in schools if s.id == ...))` | `auth.py:107-110` |

Four of the five are correct-but-unshared; the second is C1.

### The matrix

| Resource | Operation | Teacher with a footing in the class | Teacher in the school, no footing | Teacher in another school | Intended |
|---|---|---|---|---|---|
| Class | read / rename | ✔ `owned_class_ids` | 404 | 404 | as-is |
| Roster (named children) | read | ✔ class-grained | 404 | 404 | as-is |
| Roster | paste / enrol / unenrol | ✔ | 404 | 404 | as-is |
| Branch assignment | assign / unassign | ✔ **any** owner | 404 | 404 | head teacher only? (open Q) |
| Pupil | rename | ✔ | 404 | 404 | as-is |
| Pupil | **delete** | ✔ **any** owner + UID typed back | 404 | 404 | head teacher of home class |
| Sheet | read / edit / render | ✔ **pair-grained** | 404 | 404 | as-is |
| Scan pile | read / correct / confirm | ✔ pair-grained | 404 | 404 | as-is |
| Scan page | **re-assign** | ✔ — **and on a confirmed pile (C2)** | 404 | 404 | refuse when confirmed |
| Mastery matrix / tree | read | ✔ class-grained | 404 | 404 | as-is |
| Pupil profile / attempts | read | ✔ class-grained (`_owned_student`) | 404 | 404 | as-is |
| Corpus (books, sections, exercises) | read | ✔ | ✔ **by design** | 404 | as-is (I-platform-04) |
| Exercise | edit | ✔ | ✔ tenant | 404 | as-is |
| Exercise | **approve for print** | ✔ | ✔ tenant — **M12** | 404 | the teacher who prints it |
| Exercise | **discard** | ✔ | ✔ tenant — **M12** | 404 | its proposer, or its class's teacher |
| Adaptive proposal | read | ✔ | ✔ tenant — **C1** | 404 | the class's teachers |
| Adaptive job | poll | ✔ | ✔ tenant — **M5** | 404 | the class's teachers |
| Misconception note | approve / discard | ✔ | ✔ tenant | 404 | the class's teachers |
| Themes / Branches | create / edit / delete | ✔ | ✔ tenant | 404 | as-is (school nouns) |
| School | rename | ✔ | ✔ tenant | 404 | as-is, argued (D85) |
| Staffroom | **add a member** | ✔ | ✔ tenant — **H6** | 404 | as-is + audit |
| Staffroom | **remove a member** | ✖ no route | ✖ | ✖ | needed (H6) |
| Timeline | read | ✔ three visibility arms | staffroom rows only | 404 | as-is |
| Job | cancel / retry | ✖ no route | ✖ | ✖ | needed (M7) |

### The brief's six hard cases, answered against the code

1. **A teacher requests a student in another establishment.** → **404.**
   `class_service.get_student` filters `Student.school_id == scope.school_id` *and*
   `enrolled_in_owned_classes` (`:399-407`), and underneath it RLS on
   `app.current_school_id` would refuse the row anyway. Never 403 — `errors.not_found`'s
   docstring makes the non-confirmation argument explicitly.
2. **A teacher requests a student in their establishment but in none of their groups.**
   → **404.** Same predicate; `enrolled_in_owned_classes` is the second half.
3. **A substitute whose validity period ended yesterday.** → **still has full access.**
   There is no validity period (Phase 1 C1), and no role distinguishing a *remplaçant*
   (Phase 1 L2). Ending a substitution means deleting the `class_teacher_subject` row,
   which takes effect immediately — so access is correct *if* someone remembers to delete
   it, and unbounded otherwise. This is the one hard case the API answers wrongly, and the
   fix is in the schema, not the contract.
4. **A teacher requests a worksheet they did not author but which was assigned to their
   group.** → **200, and correctly.** `sheet_service.get_sheet` is pair-grained on
   `(class, subject)` and never looks at `created_by_id`. A co-teacher taking the same
   branch sees it; a colleague taking French in the same class does not.
5. **A student requests another student's submission.** → **not possible.** Students have
   no accounts and no routes; there is no student-facing surface at all.
6. **A teacher requests last year's roster for a group they no longer teach.** → **cannot
   be phrased, and would be 404 if it could.** No `school_year` parameter, no `as_of`, and
   the footing that gates the class is current (C3).

### IDOR sweep (#40, #41)

Every route taking an id in a path, query or body was checked. **No route accepts an id as
sufficient.** Every one either goes through a shared getter, calls `scoped_get`, or adds
`school_id` to the select. The three that deserve naming:

* `POST /exercises` looks up `subject_id` and `chapter_id` **within the tenant** rather than
  by primary key, with a comment saying exactly why (`sources.py:420-439`): *"`db.get` by
  primary key alone would happily accept another school's subject id."*
* `POST /adaptive/batch` re-validates every `student_id` in the client's plans against the
  class roster and every `exercise_id` against the approval gate
  (`sheet_service.py:421-444`), with the right argument: *"the client sends exercise ids, so
  'the UI would not offer an unapproved item' is not a guarantee — it is a hope about one
  caller."*
* `POST /schools/{id}/teachers/{tid}` is the exception: `db.get(Teacher, teacher_id)` with
  no scoping (H6). It cannot be used to *read* anything — the response is the target
  school's staffroom, which the caller already belongs to — but a 404 versus a 201 does
  reveal whether a given teacher uuid exists globally.

**IDs are UUIDv4 everywhere** (`db/base.py:26`) — no sequential integers in any
user-facing route, so #41 is clean.

### Mass assignment (#42)

Checked every `*Create` and `*Update` model. **No request schema carries `school_id`,
`teacher_id`, `created_by_id`, `approved_at`, `discarded_at` or any tenant field.** The
tenant always comes from the session; `created_by_id` is passed by the handler
(`sheets.py:99`). Three deliberate near-misses, all argued in place:

* `SchoolCreate.default_curriculum` is settable — and only there, because it is resolved
  into every chapter's primary competency (D56).
* `SchoolUpdate` deliberately omits `default_curriculum` for the same reason.
* `ExerciseUpdate.approved` is a boolean the client sets — the approval gate is
  *supposed* to be client-driven, by a teacher. M12 is about *whose* teacher, not about
  mass assignment.
* `ExerciseUpdate` deliberately omits `type`, with a written reason.

The one field that is settable and should not be is the same one M12 names.

### Tenant scoping by default (#43)

**Both layers.** The declared layer: every service function takes `school_id` as a required
argument, so a handler that forgets it fails to type-check
(`docs/architecture.md` §4, `deps.py:12-15`). The enforced layer: RLS on
`app.current_school_id`, bound in `get_membership` after the `teacher_school` check and
nowhere else (D84, `db/tenancy.py`). An unbound session sees nothing rather than
everything.

**Handlers that must remember it: 6.** Five inline checks listed above, plus the six
tenant-unfiltered title lookups in `timeline._titles` (M3), which rely on RLS alone. Every
other handler inherits scoping from a shared getter. Six out of 89 is a very good number,
and five of the six are correct.

---

## 6 · Phase 1 propagation — what is now contract, not just schema

| Phase 1 | What it is | Endpoints that propagate it | Cost at the DB | Cost at the API | Cost at the client |
|---|---|---|---|---|---|
| **C1** no time-bounded membership | leaving a class is a `DELETE` | `GET /classes/{id}/students`, `GET /scans/{id}/students`, `GET /classes/{id}/mastery`, `/tree`, `/points`, `GET /students/{id}/mastery`, `GET /home`, `DELETE …/enrollment` | 3 columns + backfill | `on`/`as_of` params on 7 reads; `DELETE …/enrollment` becomes an `UPDATE` and should arguably become `PATCH` | responses change meaning under the same signature — the expensive half |
| **C2** year-bound pupil identity | no person above `student` | every `/students/*` route, `StudentOut`, `AdaptiveStudentPlan.student_id`, `SheetInstanceOut.student_id` | `person` table + repoint 3 FKs | `StudentOut` gains `person_id`; `student_id` in six response models keeps meaning "this year's enrolment" | every cached `student_id` is year-scoped; a longitudinal view needs the new id |
| **H1/H3** 2-level PER, no edition | invented codes in CIIP notation | `GET /curricula/{kind}/competencies`, `CompetencyOut`, every `competency_id` in matrix/tree/profile | 2 columns + re-seed | `CompetencyOut` gains `kind`, `year`, `edition`, `is_official`; `list_competencies` gains `year`/`kind` filters | re-parenting rewrites bands already shown to parents |
| **H2** no niveau, no streaming | `Class.code` is free text | `ClassOut.code`, `ClassCreate.code`, every band in every response | `stream` lookup + `niveau` columns | `ClassOut` gains `stream_id`/`niveau`; bands become niveau-relative | historic curve gets a visible discontinuity at the fix date |
| **H5** no scan retention or erasure | images outlive every row | `DELETE /students/{id}` (H8) | retention column + sweep | new export + anonymise routes | additive |
| **H7** no read audit | who looked at this child | *every* class- and pupil-grained read | new `access_log` table | write it from `get_membership`, which already knows actor + tenant | invisible |
| **H8** no school-year uniqueness/CRUD | one hardcoded August calendar | **no endpoint at all** (C3) | 2 constraints | a whole `/school-years` resource | a client cannot ask for last year today |
| **L1** no QR, UID grid, no print run | reprints collide by design | `POST /sheets/{id}/render` (H5), `ScanPageOut.detected_uid` | `print_run_id` on placement | render response names the run; scan resolves against it | additive |
| **M6** booleans that should be timestamps | `scan_page.discarded` | `ScanPageOut.discarded`, `POST …/discard` | 2 columns | `ScanPageOut.discarded_at`/`discarded_by` | `discarded: bool` → `discarded_at: datetime \| null` is breaking |

**The reading.** Phase 1 said its two Critical findings were additive at the schema layer
and got more expensive with elapsed time. At the API layer that is still true of the
*shape* — every change above is a new optional parameter or a new field — but one of them is
not additive in *meaning*: C1's fix changes what seven existing responses contain without
changing their signature. That is the class of change that is nearly free with one client
you control and genuinely expensive with two.

---

## 7 · Proposed contract changes

Diff-style, Critical and High only. `+` add, `~` change, `-` deprecate.

### Non-breaking — do these first

```
~ POST /adaptive/propose        dedup predicate gains class_id + subject_id + teacher_id   [C1]
~ GET  /adaptive/proposal/{id}  gate on get_class(job.payload.class_id) not school_id      [C1]
~ PATCH /scans/{id}/pages/{p}   + _refuse_when_confirmed; preserve corrected detections;
                                no-op when the student is already assigned                  [C2]
~ PATCH /subjects/{id}          + db.commit()                                               [H1]
~ POST /adaptive/feedback/generate  + dependencies=[AiRateLimit]; + in-flight guard         [H3]
~ POST /sheets/{id}/render      + in-flight guard on (sheet_id, RENDER_SHEET)               [H5]
~ POST /adaptive/batch/{id}/render  + in-flight guard                                       [H5]
~ POST /adaptive/regenerate     drop the f"{exc}" interpolation; return a named code        [H4]

+ Idempotency-Key header, honoured on:
    POST /sheets/{id}/render, /adaptive/batch, /adaptive/batch/{id}/render,
    POST /scans, POST /scans/{id}/confirm                                                   [H5]

+ GET    /school-years                    -> SchoolYearOut[]                                [C3]
+ GET    /exercises                       -> ExerciseListOut
         ?competency_id=&subject_id=&chapter_id=&source_id=&type=&difficulty=
         &origin=&approved=&q=&offset=&limit=                                               [H9]
+ DELETE /schools/{id}/teachers/{tid}     -> ColleagueOut[]   (refuse last member,
                                             refuse a sitting head teacher)                 [H6]
+ GET    /students/{id}/export            -> StudentExportOut                               [H8]
+ POST   /students/{id}/anonymise         -> StudentOut                                     [H8]
+ DELETE /jobs/{id}                       -> JobOut          (cancel)                       [M7]
+ POST   /jobs/{id}/retry                 -> JobOut                                         [M7]
+ GET    /teachers/me/sessions            -> SessionOut[]                                   [H7]
+ DELETE /teachers/me/sessions            -> 204   (sign out everywhere)                    [H7]
+ POST   /auth/password-reset             -> 204   (enumeration-resistant, as login is)     [H7]
+ POST   /auth/password-reset/confirm     -> 204                                            [H7]

+ query  as_of: datetime | None   on  GET /classes/{id}/mastery, /tree, /points,
                                      GET /students/{id}/mastery,
                                      GET /students/{id}/competencies/{c}/attempts,
                                      GET /sheets/{id}/mastery,
                                      GET /students/{id}/sheets/{sid}                       [C3]
+ query  on: date | None          on  GET /classes/{id}/students,
                                      GET /scans/{id}/students                              [C3]
+ query  school_year_id           on  GET /classes, /home, /sheets, /scans                  [C3]
+ field  ClassOut.school_year_id                                                            [C3]
+ field  SheetOut.printed_at                                                                [M13]
+ bound  SheetUpdate.items: max_length=64;  AdaptiveBatchRequest.plans: max_length=40       [M2]
```

### Breaking — decide before a second client exists

```
~ POST /adaptive/regenerate
    - 200 AdaptiveRegenerateResponse
    + 202 JobOut, poll GET /jobs/{id}, read from GET /adaptive/regeneration/{job_id}        [H4]

~ ScanPageOut.discarded: bool
    + discarded_at: datetime | null, discarded_by_id: uuid | null                    [Phase 1 M6]

~ POST /adaptive/approve, /adaptive/discard, PATCH /exercises/{id} {"approved": …}
    + require a class_id (or a proposal id) so approval has an owner                        [M12]

~ DELETE /students/{id}?confirm=<uid>
    + move `confirm` into a request body                                                    [M9]

~ semantics, no signature change — the expensive one:
    GET /classes/{id}/students and the six mastery reads stop meaning "as enrolled now"
    and start meaning "as enrolled on the date asked for"                              [C3 / Phase 1 C1]
```

**On versioning (#29).** The scheme exists and is applied — `/api/v1` lives on the
aggregate router precisely so *"an eventual `/api/v2` is a new package rather than an edit
of every file"* (`api/v1/__init__.py:3-5`). That is the right shape and it is unused. But a
`v2` package is a poor fit for what Phase 1's Criticals actually need: they are field
additions and one change in the *meaning* of an unchanged field, spread across nine
endpoints. Standing up a whole `v2` for that means maintaining two of everything for one
semantic change. **The versioning scheme can absorb the additive half and cannot usefully
absorb the semantic half** — for which the honest answer is to make the change now, while
`apps/web` is the only consumer and a coordinated deploy is possible.

---

## 8 · Open questions for you

1. **Should approval have an owner?** (M12) Today any teacher in the school can stamp
   `approved_at` on any AI-generated exercise, and any teacher can discard one. The corpus
   is shared on purpose; approval is a sign-off with a name behind it. *Options:* keep it
   flat and log it; scope it to the teacher who will print; scope it to the class the item
   was generated for. *Consequence:* the third makes `Exercise.approved_at` insufficient
   (approval becomes per-class) and is a schema change, not a contract one.

2. **Is the staffroom flat forever?** (H6, D85) Any member may rename the school, add a
   colleague, create a class, delete a pupil. That is defensible for a five-teacher
   établissement. *Consequence:* a forty-teacher collège wants a head-of-department tier,
   and adding roles later means every one of the 89 routes gets re-argued. The cheapest
   hedge that costs nothing today is the audit log (Phase 1 H7) plus the missing
   `DELETE /schools/{id}/teachers/{tid}`.

3. **How much history does the contract have to answer?** (C3) There are three levels:
   (a) "who was in this group on the day this sheet was sat" — needed for correct grading
   of a late-reviewed pile; (b) "what did the matrix look like at the end of the autumn
   term" — needed for reporting; (c) "show me last year". *Consequence:* (a) is a
   parameter on two routes and Phase 1 C1; (b) is the `as_of` set; (c) needs Phase 1 C2 and
   a `/school-years` resource. They are separable and (a) is the one with a deadline.

4. **Who is the second consumer, and when?** The whole cost profile of §7 turns on this. If
   `apps/web` is the only client for another two terms, the breaking list is nearly free.
   If a cantonal integration, a mobile client or a partner is in view, H4's job conversion
   and C3's semantic change should land in the next fortnight.

5. **Is Edulog / cantonal SSO in the roadmap at all?** (H7, #31) The contract is well
   positioned for it — no role claims, entitlement re-proved per request — but the answer
   changes whether password reset and invitation are worth building at all, or whether
   they are throwaway work in front of a federation that will replace them.

6. **What is the per-school cost ceiling, and who sees it?** (M10) There is a throttle and
   no budget. A school signing a contract will ask what caps their exposure, and today the
   answer is `ai_max_output_tokens` and the provider account. *Consequence:* if the answer
   has to be per-establishment, `ModelCall` needs a read endpoint and the buckets need to
   move out of process memory into Redis.

7. **Inherited unanswered from Phase 1, because they bind the contract too:** cantonal
   scope (§the brief's placeholder); what happens on 1 August (Phase 1 Q3 — this determines
   whether `/school-years` needs a rollover verb); deletion versus anonymisation as the
   default answer to a parent (Phase 1 Q4 — this determines whether H8 ships two routes or
   three).

---

## 9 · What I could not verify

* **That the `PATCH /subjects/{id}` rollback happens against Postgres** (H1). I traced it —
  the service flushes, the handler does not commit, `get_db` closes, and
  `Session.close()` rolls back an open transaction — and I confirmed the test fixture
  shares one un-closed session so the suite cannot see it. I did **not** run the request
  against a live database, because that means writing and running code and the audit rules
  are read-only. **To close this:** `PATCH /api/v1/subjects/{id}` against the docker-compose
  stack, then `GET /api/v1/subjects` in a fresh request.
* **The C1 exposure end-to-end.** I established the predicate is school-wide, that
  `read_proposal` gates on the tenant only, and that both handlers have `class_id` in hand.
  I did not run two concurrent proposals with two teachers to watch a foreign job id come
  back. The code path is short enough to read with confidence; the observation would still
  be worth having before the fix.
* **Whether the C2 detection deletion is reachable on a confirmed pile in practice.** The
  guard is absent from `assign_page_student` and present in its three siblings, and the
  router adds none — but I did not confirm that the review UI can be made to issue the PATCH
  after confirmation, only that the API accepts it. The API accepting it is the finding;
  the UI is not the boundary, as `correct_detection`'s own docstring argues.
* **Actual request latency for `POST /adaptive/regenerate`** (H4). The claim that it can
  exceed a proxy timeout is reasoned from what it does — a retrieval pass plus a generation
  — not measured. The rule it breaks is categorical either way.
* **The two concurrent renders racing on `AnswerBoxPlacement`** (H5). I confirmed the
  `DELETE`-then-insert (`render.py:668`) and the absence of any in-flight guard on either
  render route. I did not run two jobs concurrently to observe an interleaving, and I did
  not measure how much two Chromium passes over the same document actually differ — which
  is the difference between "rare and invisible" and "never happens". **To close this:**
  render the same sheet twice and diff the placement rows.
* **Whether RLS actually refuses the six tenant-unfiltered timeline queries** (M3). Phase 1
  could not exercise `check-rls.py` either, for the same reason — it drops the `public`
  schema. So the second layer is *present and correctly shaped* in both audits and
  *unexercised* in both.
* **The OpenAPI document itself.** `create_app()` is switched off for `openapi_url` in
  staging and production, and I did not build the app to render the document from a
  checkout — the inventory in §4 is reconstructed from the decorators, which is what the
  brief asked for, but it means I have not seen the schemas FastAPI actually emits for the
  three request models defined outside `alppy.schemas`.
* **i18n coverage of `de` and `en`.** I compared the API's error-code set against
  `fr.json` only. `pnpm i18n:check` is stated to keep the three in sync, so the gap in M1
  should be identical in all three, but I did not confirm it.
* **Load and N+1 in practice.** The round-trip counts in §3 are from reading the client's
  call sites and the response models, not from a network trace. `GET /home` genuinely does
  the teacher dashboard in one request; `GET /sheets/{id}` carries items, instances, scans
  and derived competency ids in one; `GET /scans/{id}` carries pages and detections in one.
  All three are good and none was timed.
