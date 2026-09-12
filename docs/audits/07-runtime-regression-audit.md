# Phase 7 audit — Runtime regression sweep (the running product)

**Scope:** the whole product as it actually runs. `docker compose up` — Postgres, Redis,
MinIO, the API, the arq worker and the built web image — driven in a real Chromium against
the real API, at three viewports, across every route in the tree. The print → render →
download → scan → review → confirm → mastery loop end to end, with the PDF the product
itself produced. Auth, tenancy, CRUD persistence, console and network hygiene. The test
estate was run, not read.

**Method:** the opposite of phases 1–6. Nothing here was concluded by reading a component
and judging it correct — that is the method those phases used, and the premise of this pass
is that things which look correct in isolation have broken in combination. **Every finding
below was reproduced in the running stack before a line was changed**, and re-verified in
the running stack after. Where a claim rests on something I could not run, §7 says so.

**Prior phases** were read first: [`01-database-audit.md`](01-database-audit.md),
[`02-api-audit.md`](02-api-audit.md), [`03-backend-audit.md`](03-backend-audit.md),
[`04-frontend-architecture-audit.md`](04-frontend-architecture-audit.md),
[`05-frontend-development-audit.md`](05-frontend-development-audit.md),
[`06-integration-testing-audit.md`](06-integration-testing-audit.md). Phase 6 named the
seams the suite cannot reach; this phase went and stood in them. Several findings below are
that report's predictions coming true.

**Snapshot:** branch `main` at `536490f`, clean working tree. 2026-09-12.

**The headline before the detail:** nine defects, and **most of them live in a seam between
two layers that are each individually tested and individually green.** The most serious —
`docker compose up` served a logged-out visitor the full authenticated shell wrapped around
invented children, and never called the API at all — was caused by a git-ignored file that
no reviewer has ever been able to see. A second pass then cleared everything §6 had first
listed as deferred, including one that made the **Anthropic provider raise `TypeError`
before reaching the network on every call**, and one that left `docker compose up` unable to
build a sheet at all.

All nine are fixed. The suites now run **1 470 pytest / 260 Playwright / 352 Vitest with
zero failures**, and `mypy --strict` is clean for the first time.

---

## 1 · Verdict

**The product works. It did not look like it, and none of the suites could have told you.**

Every one of these was green throughout: 34 `@alppy/ui` tests, 318 `@alppy/web` tests, 1 410
pytest tests, 260 Playwright behavioural tests, ESLint, tsc, stylelint, the screens
inventory, the i18n gate, the layout contract and the API contract. (Two gates were **not**
green and had not been for some time — `mypy --strict` and one font-metric test — and §3
covers both; neither was catching any of the defects below either.) The product was
nevertheless shipping an image that served a demo to everyone, could not upload a pile of
copies at all, showed a blank preview on every screen that frames one, panned sideways on a
phone, and printed two raw message keys at the teacher.

The gap is not effort and it is not coverage in the usual sense. It is that **the suites
test layers and these bugs are between layers**:

* The unit suite builds its schema with `create_all()` on SQLite. SQLite does not enforce
  foreign keys without `PRAGMA foreign_keys=ON`, and nothing sets it — so the scan upload
  that 500s on every real database returns 202 there (F-3). Phase 6 called this blind spot
  in the abstract (T3, T4, T6); this is a fourth instance, and the first that was reaching
  users.
* The E2E suite replaces `apiRequest` *before* `fetch`. So no CI job has ever sent an HTTP
  request to this API — which is why a CSP header that makes the preview unframeable (F-2)
  and a CORS-adjacent origin split could not be seen. Phase 6 said exactly this (T2) and
  the one spec that would have caught it is still skipped in CI.
* Fixture mode reaches neither the teaching screen nor a wide matrix nor a populated
  agenda, so three of these were simply unreachable by the screenshot and behaviour suites
  regardless of how well written they were.
* One gate was reading generated input that had gone stale, so it was enforcing a rule
  against a list that no longer matched the API (F-6).
* One test double was **more permissive than the thing it stands for**: the fake Anthropic
  client takes `**kwargs` and accepts anything, while the real SDK takes named parameters
  and no `**kwargs` — so a parameter the SDK had removed sailed through every test and
  raised `TypeError` in production (F-7).
* And one defect was invisible because **nothing exercises the seed the way a new user
  does**: every test builds its own fixtures, so no test ever tried to build a sheet on the
  data `docker compose up` actually ships (F-8).

The reassuring half: **once these are fixed, the product is sound.** The full loop closes
— a sheet built from the seeded corpus, rendered to two PDFs, downloaded through the
presigned-URL rewrite, uploaded back as a pile, registered and read by the worker (36 pages,
18 UIDs, zero wrong-class), reviewed, confirmed into 54 attempts, and rolled up into bands
on the class screen. Tenancy holds under direct probing. Session expiry behaves. Every
mutation I made survived a reload.

---

## 2 · Findings

| id | severity | what | where the suites were |
|---|---|---|---|
| F-1 | **Critical** | The production image served fixtures to everyone, with no login gate | all green |
| F-2 | **High** | Sheet preview blank wherever it is framed | all green |
| F-3 | **High** | Uploading a pile of copies → 500 on any real database | all green; 202 on SQLite |
| F-4 | Medium | Class screen pans 241px sideways on a phone | the spec asserting this passed |
| F-5 | Medium | "Qui enseigne quoi" shows the teacher `teaching.summary` | all green |
| F-6 | Medium | Three catalogue gaps + two blind gates | i18n gate green on a stale list |
| F-7 | **High** | Anthropic provider raised `TypeError` before the network, on every call | the test double takes `**kwargs` |
| F-8 | Medium | `docker compose up` could not build a sheet at all | no test builds a sheet on the seed |
| F-9 | Low | `mypy --strict` had never passed; 4 errors masked real ones | CI runs it and has been red |

All nine are fixed. §3 gives each one the reproduction, the root cause, the fix and the
re-verification. §5 covers what was exercised; §6 what was found and deliberately not fixed,
and §6 is now short — everything it originally deferred was resolved in a second pass.

---

## 3 · Detailed findings

### Critical

#### F-1 · A developer's `.env.local` shipped inside the image, and the product became a demo

**Reproduced.** `docker compose up`, then `GET /fr` with no cookie: **HTTP 200**, the full
authenticated shell, and a roster of children — *"Bonjour Claire"*, *"Classe de Mme
Fontaine"*, *"18 élèves"*, five mastery bands. Driving the same page in Chromium and
recording the network: **zero requests to the API**. Not one.

None of those children exist. They are `apps/web/src/lib/api/mock/fixtures.ts`.

**Root cause, and it is two mistakes meeting.** `.dockerignore` listed `.env` and
`.env.local`. A `.dockerignore` pattern is matched against the path from the **context
root**, so those two lines excluded the repository's own two files and nothing else.
`apps/web/.env.local` is a different path, and it is `.gitignore`d — line 20 — which is
precisely why it has never appeared in a diff, a review or a CI run. It contains:

```
NEXT_PUBLIC_ALPPY_MOCK=1
```

`next build` reads `.env.local` from the **app directory** and inlines `NEXT_PUBLIC_*` into
the bundle. So the build inside the image was a fixture build. Confirmed by grepping the
built output in the container: `Mme Fontaine` is present in both
`.next/static/chunks/*.js` and `.next/server/chunks/*.js`.

The second half is what turns a wrong-data bug into a **security** bug. `src/middleware.ts`
gates every non-public route on the session cookie — but the gate sits behind:

```ts
if (process.env.NEXT_PUBLIC_ALPPY_MOCK === '1') return response;
```

With the constant inlined as `'1'`, the whole remainder of the function is dead code and
the minifier removes it. Verified in the shipped artefact: `middleware.js` contained **zero**
occurrences of `login`, `alppy_session` or `SESSION_COOKIE`, and returned immediately after
setting the CSP.

The comment on that early return is correct about its own case and silent about this one:
fixture mode has no backend, so gating it *would* redirect the screenshot suite to a login
it cannot pass. The flag was never meant to be able to reach an image.

**Why nothing caught it.** Every gate that could have was looking elsewhere. CI builds the
web app but never builds or boots the *image*. The E2E suite deliberately runs with
`NEXT_PUBLIC_ALPPY_MOCK=1`, so a fixture build is its correct state and indistinguishable
from this one. And the file that caused it cannot appear in review, by construction.

**Fix.** `.dockerignore` now excludes every dotenv file at every depth:

```
.env
**/.env
**/.env.*
```

Nothing in either image legitimately wants a machine's local environment: the web image
takes configuration as **build args** (`apps/web/Dockerfile`), the API as the compose
environment.

**Re-verified.** Rebuilt; `GET /fr` → **307 → `/fr/login`**. `login` and `alppy_session` are
back in the built middleware. Logged in as the seeded teacher and the browser now issues
real API calls (`/auth/me`, `/classes`, `/home`, …), all 200, showing the real roster.

---

### High

#### F-2 · `frame-ancestors 'self'` cannot be satisfied by a front end on another origin

**Reproduced.** The sheet screen's *Fiche élève* / *Corrigé* tabs and the builder's preview
panel were blank. Console:

```
Framing 'http://localhost:8000/' violates the following Content Security Policy
directive: "frame-ancestors 'self'". The request has been blocked.
```

Network: `GET /api/v1/sheets/{id}/preview` → `net::ERR_BLOCKED_BY_RESPONSE`. The endpoint
itself is healthy — fetched directly it returns 200 and the correct HTML.

**Root cause.** `apps/api/alppy/main.py:49` set `Content-Security-Policy: frame-ancestors
'self'` on every response. The comment above it explains the intent exactly, and the intent
is right — *"deliberately not 'none': the preview is supposed to be framed, by us"*. But
`'self'` means **the origin that served the document**, which is the API. The builder is
never served from the API's origin. Under a single reverse proxy they are the same origin
and the policy is correct; under the arrangement this repository actually ships — compose
puts web on `:3000` and API on `:8000`, and `next.config.ts` documents the same split for
local development — they are different origins and the browser refuses every frame.

So the header was written for a deployment topology that is not the one in the repo.

**Why nothing caught it.** `test_request_id_hardening.py:47` asserted
`headers["Content-Security-Policy"] == "frame-ancestors 'self'"` — the bug, written down as
an expectation, passing forever. And no CI job has ever framed anything, because the E2E
suite intercepts above `fetch` and never reaches HTTP (Phase 6, T2).

**Fix.** A `frame_ancestors(settings)` function that names the front ends:

```
frame-ancestors 'self' http://localhost:3000
```

It reuses `cors_origins` rather than introducing a second variable. That list is already the
set of front ends trusted with a **credentialed** cross-origin request — a strictly stronger
trust than being allowed to frame one HTML page — so reusing it means the two cannot drift,
and naming the origins twice is how they would. A wildcard is **dropped, not translated**:
`_refuse_unsafe_deployment` already refuses `"*"` in staging and production, and
`frame-ancestors *` is the clickjacking hole this header exists to close, so on a local
instance permitting `"*"` for CORS, framing still falls back to `'self'` alone.

**Re-verified.** Header is now `frame-ancestors 'self' http://localhost:3000
http://localhost:3200`. The preview iframe renders its real content — *"Fiche de
vérification · 7B · Mathématiques · Code élève 7B_01 …"* — with the fiducials, the UID block
and the answer grid. Screenshot captured. The old test was **corrected, not deleted** (it was
asserting the defect); two tests added for the split-origin case and the wildcard case.

#### F-3 · Uploading a pile of copies returned 500 on every real database

**Reproduced, and not only in the browser.** Plain `curl`:

```
POST /api/v1/scans  (sheet_id + blank.pdf)  →  500
{"error":{"code":"internal_error","message":"unexpected server error"}}
```

Server log:

```
psycopg.errors.ForeignKeyViolation: insert or update on table "job"
violates foreign key constraint "fk_job_scan_id_scan"
DETAIL:  Key is not present in table "scan".
```

This is the entire correction half of the product. Nothing can be graded if no pile can be
uploaded.

**Root cause.** `scan_service.create_scan` added the `Scan` and then its `Job` and flushed
once. `Job.scan_id` carries a real foreign key (`models/__init__.py:2184`), but **`Job`
declares no `relationship()`** — deliberately; it is a content-free audit row — and
SQLAlchemy's unit of work orders a flush from **relationships**, not from foreign-key
columns. With no dependency to sort on it falls back to the mapper sort key, which is the
qualified class name, and `alppy.models.Job` sorts before `alppy.models.Scan`.

Confirmed directly rather than inferred. Postgres statement logging for the failing request
shows **no `INSERT INTO scan` at all** before the job insert; and reproduced in isolation
against the same database:

```
session.new before flush: ['Job', 'Scan']
FLUSH FAILED: IntegrityError ... fk_job_scan_id_scan
```

`inspect(Job).relationships` → `[]`.

**Why nothing caught it — and this is the important half.** The unit suite builds its schema
with `create_all()` on **SQLite**, which does **not enforce foreign keys** unless `PRAGMA
foreign_keys=ON` is set, and nothing sets it. The wrong order is simply accepted. I verified
this precisely: with the fix reverted, `POST /api/v1/scans` in the test suite still returns
**202**. The suite cannot express this failure.

This is the same structural blind spot Phase 6 raised for the three partial unique indexes
(T4) and `confirm_scan`'s race (T6) — a fourth instance, and the first one that had reached
users.

**Fix.** `db.flush()` after `db.add(scan)`, with the mechanism written down at the call site
so the next person does not remove it as redundant.

**Re-verified end to end.** `POST /api/v1/scans` → **202**. The worker then:

```
scan.processed  pages=36  registered=36  identified=36  wrong_class=0
```

36 pages (18 pupils × 2), every UID read. The review screen loads with the pile, the copy
filter, the per-item detections and *"Identifié comme 7B_01 · Léa Progin"*. Confirming wrote
**54 attempts** and bands appeared on the class screen.

**Regression test.** `test_the_pile_is_inserted_before_the_job_that_points_at_it` asserts the
**order of the statements** rather than an integrity error — because the order is the actual
invariant and is engine-independent, whereas the error is one SQLite will never raise.
Confirmed the test fails with the fix reverted and passes with it.

---

### Medium

#### F-4 · An invisible 1px span pushed the whole page sideways on a phone

**Reproduced.** `/fr/classes/{id}` at 390 × 844: `window.scrollTo(5000, 0)` leaves
`window.scrollX === 241`. The screenshot shows the app shell slid off-screen, the sidebar
gone, the matrix half-cut. At 768px: 119px.

**Root cause, isolated by DOM bisection rather than guessed.** Hiding one child at a time
until the page stops panning walks down to a single `<tr>` inside the matrix `<thead>`.
Every column header carries the competency's full label in a `.visually-hidden` span, and
that utility is `position: absolute` (`base.css:150`). **An absolutely-positioned box is
clipped by an ancestor's overflow only when that ancestor is in its containing-block
chain** — and `Matrix.tsx`'s scroller was `static`. So the six spans escaped the
`overflow-x-auto` that was supposed to hold them, sat at their static position deep inside
the 622px-wide table, and extended the **document's** scrollable width.

Proven in the live page, two independent ways:

```
baseline pan                        = 241
visually-hidden spans display:none  = 0
scroller position:relative          = 0
```

**Why nothing caught it.** `e2e/responsive.spec.ts` asserts exactly this — `expect(panned)
.toBe(0)` — and has been passing. It is a well-written test with a correct predicate (it
even explains why it pans rather than reading `scrollWidth`). It passes because the
**fixture** matrix has few enough competencies that the spans never clear the viewport. The
component's own docstring claims `max-w-full` plus `min-w-0` keep the intrinsic width from
propagating out; that is true of the table's in-flow width and says nothing about an
abs-positioned descendant.

**Fix.** `relative` on the scroller, so it becomes the containing block and the clip that was
always intended actually applies.

**Re-verified.** `scrollX` after panning: **241 → 0**, at 390px and 768px, on the class
screen and every other route.

#### F-5 · The teaching screen printed the literal string `teaching.summary`

**Reproduced.** `/fr/classes/{id}/teaching` renders `teaching.summary` as text under the
heading. Console:

```
FORMATTING_ERROR: The intl string context variable "disciplines" was not
provided to the string "{disciplines, plural, =0 {aucune discipline} ...}"
```

**Root cause.** The caller passes `{ branches, teachers }`
(`teaching/page.tsx:167`). `de` and `en` both declare `{branches, plural, …}`. **Only `fr`**
had been renamed to `{disciplines, plural, …}` — a user-facing vocabulary change ("branche"
→ "discipline") that reached the placeholder name as well as the prose. ICU then cannot
resolve the argument, throws, and next-intl falls back to printing the key.

**Why nothing caught it.** The i18n gate checks that the same **keys** exist in all three
catalogues. They do. Nothing compared the **placeholder names inside a message** across
locales, or against the call site.

**Fix.** `fr` uses `{branches}` again; the visible French wording ("aucune discipline",
"# discipline") is untouched, because that was the legitimate half of the rename.

**Swept for the same class of drift** across all 888 keys × 3 locales, and separately from
every `t('key', {...})` call site against the `fr` catalogue: **no other instance**. Two
keys differ across locales in placeholder *set* but only by plural-branch text
(`home.pendingCorrectionsValue`, `mastery.reviewDue`) — correct, not drift.

**Re-verified.** Renders *"aucune discipline · 1 enseignant"*, and after declaring a subject,
*"1 discipline · 1 enseignant"*. No console error.

#### F-6 · Three catalogue gaps, and two gates that could not see them

Three separate instances of one shape: **a screen renders a key the API can produce and no
catalogue has.**

**(a) A refusal told the teacher to retry something retrying cannot fix.** The API refuses a
confirmation with `code="scan_low_confidence_unreviewed"` when unsure readings have not been
looked at — the T24 gate, which exists precisely so an unsure reading never silently becomes
a mark. **No locale had a sentence for it.** So `apiErrorMessage` fell through to
`errors.code.fallback`: *"L'envoi a échoué. Réessayez."* The teacher retries. It fails
identically. This is the exact failure mode `docs/reviews/F7-review.md` documented and fixed
for the session-expiry case, reappearing on the correction path.

**(b) Five `EventKind` members had no `timeline.kind.*` label in any locale** —
`scan_reopened`, `teacher_joined`, `teacher_left`, `exercise_edited`, `exercise_approved`.
All five are emitted by ordinary teacher actions, and `scan_reopened` comes from the
*Rouvrir* button on the review screen. Reproduced: after reopening a pile, the agenda showed
the raw key `timeline.kind.scan_reopened` with `MISSING_MESSAGE` in the console.

**(c) The same five were missing from the timeline's hand-written `KINDS` filter list.** A
chip is only offered when its facet count exceeds zero, so a kind absent from that list can
**never** be filtered however many events exist. Reproduced: the agenda showed *"6 entrées"*
above five chips summing to five.

**Why nothing caught it — two blind gates, both real, both looking slightly past the
problem.**

* `scripts/check-i18n.mjs` **does** assert that every API error code has a sentence in all
  three catalogues. It reads the code list from `packages/shared/src/api-constants.
  generated.ts`. CI's `api-contract` job regenerates **three** files and diffed **two** —
  `api-types` and `api-routes`, not `api-constants`. The constants file had therefore
  drifted and was missing `scan_low_confidence_unreviewed` entirely. **The gate was
  enforcing a real rule against a list that no longer matched the API.** Regenerating it
  locally is what made the gate fire.
* Nothing anywhere asserted a label for an event kind.
* Cross-locale sync could not catch any of this: (a) and (b) were missing from all three
  catalogues **consistently**, and (c) is not a catalogue at all.

**Fixes, at the source rather than the symptom.**

1. Sentences and labels added in `fr`, `de`, `en`.
2. CI's contract job now diffs **all three** generated files.
3. `scripts/generate-api-types.py` emits `EVENT_KINDS` from the `EventKind` enum, and
   `check-i18n.mjs` holds the same rule for it that it already held for the error codes.
   **Switching that on immediately found two more gaps** — `exercise_edited` and
   `exercise_approved` — which is the gate doing its job on its first run.
4. The timeline's `KINDS` list is completed and commented. It stays **hand-written and not
   generated**: a checker can hold "every kind has a label", but the **order** of that list
   is editorial — it is the order a teaching cycle runs in, not alphabetical — so what is
   documented there is that *completeness* is load-bearing.

**Re-verified live.** Forcing two `LOW_CONFIDENCE` detections and pressing *Valider les
résultats* now yields a 409 rendered as *"Certaines lectures sont trop incertaines pour être
notées. Ouvrez chacune d'elles et confirmez-la ou corrigez-la, puis validez la pile."* The
agenda shows *"Correction rouverte"* and six chips for six entries. `i18n:check` green at 888
keys with both rules enforced; the generator is idempotent.

---

## 4 · The loop, end to end

Run against the live stack after the fixes, with the product's own artefacts at every step —
no synthetic input at any point.

| step | result |
|---|---|
| Log in (`demo@alppy.ch`) | 200, session cookie, real roster |
| Declare a discipline on *Qui enseigne quoi* | 201; curriculum tree goes from 0 to 4 competences / 7 themes |
| Build a sheet — title, Theme, 3 exercises, barème | draft state correct, page count live |
| Generate | 201, redirect to the sheet screen |
| Render | 202 + job polled to completion in ~4s |
| Preview | both tabs render the real document (F-2) |
| Download both PDFs | 291 KB, 8 pages, valid PDF — presigned MinIO URL rewritten to the host |
| Upload that PDF back as a pile | **202** (F-3) |
| Worker | 36 pages, 36 registered, 36 UIDs identified, 0 wrong-class |
| Review screen | pile, filters, per-copy list, per-item detections, *"Identifié comme 7B_01 · Léa Progin"* |
| Confirm | *"54 réponses enregistrées pour 18 élèves"* |
| Mastery | bands on the class screen; `attempt` 613, `mastery_snapshot` 822 |
| Results | per-pupil × per-sheet table populated; *"0 / 54"* — correct, the uploaded sheet was **blank** |
| Agenda | 6 events, all labelled and filterable (F-6) |

---

## 5 · What was actually exercised

**Suites — baseline first, then re-run after every fix.**

| suite | baseline | after |
|---|---|---|
| `@alppy/ui` vitest | 34 passed | 34 passed |
| `@alppy/web` vitest | 318 passed | 318 passed |
| pytest | 1 410 passed / 1 failed / 69 skipped | **1 467** passed / 1 failed / 15 skipped |
| Playwright (behaviour) | 260 passed / 0 failed | 260 passed / 0 failed |
| Playwright (screenshots) | 42 failed — no `-linux` baselines | unchanged (§6) |
| lint · typecheck · stylelint · screens · i18n · layout · contract | green | green |

The pytest count rises because Postgres was up, so the 34 Postgres-gated tests that skip on a
bare checkout actually ran — plus the one added here. The single failure is pre-existing and
unrelated (§6). The app's own database was verified intact after every Postgres-touching run.

**Routes.** All 29 — every file in the route tree, plus the id-addressed screens that only
became reachable once real data existed (theme detail, competency detail, sheet detail,
student-sheet, an empty newly-created class) — at **390 / 768 / 1440**, twice: once on the
seeded state and once with a sheet, a scan and an agenda present. 87 page loads per sweep,
with the console and the network recorded on every one. Final sweep: **zero flags**.

**Interaction and persistence** — each confirmed by reloading and re-reading, not by
trusting the optimistic UI:

* class create (with roster paste) → appears in the list and the switcher; pupils persist
* pupil rename → `PATCH /students/{id}` 200, survives reload
* pupil delete → typed-UID confirmation, `DELETE` 204, gone after reload
* declare a discipline → 201, tree populates
* sheet builder → source, chapter, type filters, difficulty, search, barème, points, penalty
* settings → theme (persists across reload), discreet mode (names → UIDs on the roster),
  locale FR/DE/EN (URL and UI both follow), all via `PATCH /teachers/me/preferences`
* scan upload → worker → review → confirm → attempts → bands

**Auth and tenancy.** Login; logout; **session expiry mid-task** (cookie cleared under a live
app → next navigation redirects to `/fr/login?from=%2Ffr%2Ftimeline`, preserving the
destination); the colleague account sees `7A` and **not** `7B`; requesting the demo
teacher's class by id as the colleague → **404 on all four calls**, no pupil name anywhere in
the response or the DOM.

**Hygiene.** Console clean on every route at every breakpoint after the fixes. No failed or
unresolved requests, no 4xx/5xx except the ones being deliberately provoked, no missing
assets, no broken images. The generated contract and the layout contract both regenerate to
no diff.

---

## 6 · Second pass — everything the first pass deferred

The first pass left five items in "found, not fixed". Working through them turned up two
further defects, one of them serious, and both invisible for reasons worth stating.

#### F-7 · The Anthropic provider raised `TypeError` before reaching the network

**Reproduced, without an API key or a network call:**

```
TypeError: Messages.create() got an unexpected keyword argument 'temperature'
```

Every Anthropic call failed, always, at the call site. A school that configured
`ALPPY_AI_CHAT_PROVIDER=anthropic` got nothing working: no differentiation batch, no vision
grading of a written answer.

**Root cause.** `pyproject.toml` asks for `anthropic>=0.40.0` and **does not pin**. The
parameter was removed from `messages.create` along the way, and the method takes **no
`**kwargs`** to absorb an unknown one. Confirmed by introspection of the installed SDK
(1.5.0): `temperature` and `top_p` are both gone, and no `VAR_KEYWORD` parameter exists.

**Why nothing caught it.** Three things had to line up, and they did:

* The **test double is more permissive than the real thing.** `_FakeMessages.create` in
  `test_ai_vision.py` takes `**kwargs: Any` and accepts anything at all. Every provider test
  talks to that double, so every provider test passed.
* `mypy` *did* report it — as `[call-overload]`, one of the four errors that had been
  failing CI's mypy step (F-9), where it read as a stubs-version complaint rather than as a
  hard runtime break. The real message was there and unreadable.
* The **default provider is `echo`**, because `docker compose up` must work on a clean
  machine with no account anywhere. So the broken path is precisely the one that only runs
  at a school that has paid for a key.

**Fix.** The provider asks the installed SDK whether it takes the parameter, rather than
gating on a version string — the dependency is a range, both SDK generations are legal, and
"does this accept the argument" is the question that actually matters. When it does not, the
argument is dropped and the call still happens, and `ai.temperature.dropped` is logged every
time. That is not a new invention: it is exactly the answer this file already gives for a
reasoning model that refuses the parameter, and the reason is the same one written in
`grade_open_answer.v2.md` — *"temperature 0.0 — a grade must be reproducible, never
creative"*. A provider that will not carry the parameter cannot honour that, and the log is
the only thing that can tell a school the grading contract is not being kept. The two
providers now share one `_warn_temperature_dropped`.

**Re-verified.** Two tests, both confirmed failing before the fix:

* `test_every_argument_the_anthropic_provider_sends_exists_on_the_installed_sdk` checks every
  argument the provider actually sends against the **installed** signature, and first asserts
  the SDK still has no `**kwargs` — so the test cannot quietly stop being able to catch
  anything. It costs no network call and no key, and it covers the *next* parameter to be
  removed as well as this one.
* `test_a_dropped_temperature_is_never_silent` pins the logging half.

#### F-8 · `docker compose up` shipped a corpus nothing could reach

**Reproduced.** On a **freshly seeded** database (`docker compose down -v` first), a teacher
who logs in and goes to build a sheet finds the Theme picker offering only *"Sans thème
(0)"*, and *Générer la feuille* permanently disabled. `GET /classes/{id}/tree` →
`{"branches": []}`.

**Root cause.** `Class → Branch → Competence → Theme` is read from `class_subject`, which
`declare_subject` writes — and the only place the product writes it by itself is
`create_sheet`, the very thing being blocked. The demo seed never declared anything, so the
63 exercises, 7 chapters and 34 competencies it carefully loads were unreachable from the
builder. `canFile` refusing "Sans thème" is correct and is not the bug: that row exists to
*find* untagged exercises, never to store a sheet nobody classified (D60).

**Why nothing caught it.** Every test builds its own fixtures. Nothing anywhere starts from
the seed and tries to do what a new user does first.

**Fix.** The seed calls `assign_branch` for 7B and mathematics — one line, using the
product's own service rather than writing the table directly. **7B only, deliberately:** 9A
keeps its roster and no teaching, because the "class with students but nothing taught yet"
empty state is meant to be reachable from `docker compose up` without anyone fabricating it,
and declaring for both would have destroyed exactly that.

**Re-verified from empty volumes.** `seed.done … declared=7B:mathematics`, then in the
browser with **no manual setup at all**: the Theme picker offers the real curriculum (MSN 32
Fractions, MSN 33 Proportionnalité, …), *Générer la feuille* is enabled, and a sheet is
created. `9A branches: 0` — the empty state survives.

#### F-9 · `mypy --strict` had never passed, and the noise hid F-7

**Reproduced.** `mypy --config-file apps/api/pyproject.toml apps/api/alppy` → 4 errors, in
`storage.py` (×2) and `ai/providers.py` (×2). CI runs this exact command as a required step.

**Root cause — the same mistake twice.** Both sites unpack a `**dict` into a function with
overloads. In `storage.py` a `creds` dict mixing strings with a `Config` infers as
`dict[str, object]`, which matches no `boto3.client` overload. In `providers.py` three
inline `**({...} if ... else {})` unpackings did the same to `messages.create`. In both
cases mypy can only say *"no overload variant matches"* — so **a real signature error was
reported as a generic complaint**, which is how F-7 sat in plain sight.

**Fix.** `storage.py` gets one small `_s3(endpoint_url)` factory that passes the arguments
explicitly; the two clients still differ in exactly one argument, which is the property
worth seeing at a glance. `providers.py` builds a single `kwargs: dict[str, Any]`.

**Re-verified.** `Success: no issues found in 95 source files` — **the first time this
project's strict mypy has passed** — and the diagnostics are now precise enough that the
next removed parameter will be named rather than hidden.

#### The font-metric test, which asked for this fix in its own failure message

`test_the_box_moves_when_the_font_stack_does` asserts that the answer box **moves** when the
document is re-typeset — the whole argument for embedding the faces, since a box cropped a
line off means part of a child's answer missing and part of the next thing included, at a
confidence high enough to auto-apply. It failed with `0.0 > 2.0` and said why: *"the fallback
happened to wrap identically here — pick a statement whose wrapping differs"*.

It did. The short statement wrapped to three lines in Nunito **and** in every fallback on a
Linux host, where fontconfig answers `serif`, `monospace` and `'Times New Roman'` all with
DejaVu. Measured across three statements × three stacks to find that out rather than
guessing.

**Fixed with the test's own suggestion, plus a guarantee it did not have.** The statement is
now long enough that the wrapping genuinely differs (7.6 mm — a line pitch), and the test
makes **two** measurements: first between two faces the repository *itself embeds*
(`fonts.css` ships Nunito, JetBrains Mono, Caveat), which cannot depend on what is installed
on the machine running the suite; then against the fallback, which is the real-world
scenario. The deterministic assertion is the one that will still be meaningful on a machine
nobody has thought about yet.

#### The 404 status code — diagnosed, and deliberately left alone

`/fr/nope` renders the correct localised not-found inside the app shell, with **HTTP 200**.
Two hypotheses, both tested and both **wrong**:

* *The `force-dynamic` locale layout streams, so the status is already committed.* Measured:
  a build with `force-dynamic` removed still returns **200** — and serves an inline script
  with no nonce, which is the hydration break `CLAUDE.md` warns about. Removing it costs the
  nonce and fixes nothing.
* *The middleware is rewriting.* Measured: a path with a dot skips the middleware matcher
  entirely and still returns 200.

**The actual cause,** by elimination: a path matching **no route at all** (`/nope.x`)
correctly returns **404**. Only paths caught by `[locale]/[...rest]/page.tsx` return 200.
That catch-all exists on purpose — without it a typo'd URL gets Next's default 404, in
English, unstyled, outside the shell, on a trilingual product. So the status code is the
price already paid for the localised page, knowingly, by the commit that added it.

**Not fixed**, and this is a recommendation rather than a change: the only way to have both
is for the middleware to answer unknown paths itself, which means a route table in the
middleware — a second source of truth that rots. That is a routing decision with real
downside risk (a mistake means a valid page 404s) for a benefit that is invisible to every
teacher and matters only to crawlers. It is unchanged from before this pass.

---

---

## 7 · Still open

Everything the first pass deferred has been resolved except the two below, and neither is a
defect in the product.

**The 42 screenshot tests still cannot run on Linux.** Every committed baseline is
`-darwin`; there are no `-linux` ones, which is documented in `ci.yml` as a deliberate,
honest gap rather than an omission — and the E2E job does not run them
(`--grep-invert "renders in"`), so nothing is currently reporting a false green.

**Not fixed, on purpose.** Generating baselines is one command, and I ran it — but this
machine is WSL2, not the `ubuntu-latest` container CI uses, and font rasterisation differs
between them. Committing baselines from an unvalidated machine would convert a *known* gap
into a gate that is either red on arrival or quietly wrong, which is the precise failure
mode the existing comment exists to avoid. I deleted the `-linux` files I produced. The fix
is to generate them **in the CI container** — `playwright test --grep "renders in"
--update-snapshots` on `ubuntu-latest`, commit the result, then drop the `--grep-invert`.

**The not-found status code is 200.** Cause fully diagnosed in §6; unchanged from before
this pass; the UI is correct in all three languages. Fixing it means putting a route table in
the middleware, which is a routing decision with real downside risk for a benefit no teacher
can see. Recommended, not taken.

**Not verified at all, and not claimed:** live model providers (the stack ran the offline
`echo`/`hash` providers throughout — F-7 is proven at the call boundary, by signature, not
against Anthropic's servers), real photographed or HEIC scans, the Cloudflare build path,
and the staging/production startup refusals. All need infrastructure or credentials not
present here.

---

## 8 · What would have caught these, ranked

1. **Run `live-loop.spec.ts` in CI.** It exists, it talks to a real API and a real database,
   and it is skipped in every CI run (Phase 6, T2). F-2 and F-3 are precisely what it is
   for, and F-1 would have shown as "the app never called the API". This is the single
   highest-value change on the list, and the work is already written.
2. **Decide what SQLite-on-`create_all` is allowed to hide.** It missed F-3 completely and
   returns 202 for a request that 500s in production. Either set `PRAGMA foreign_keys=ON`
   on the test engine — the broader fix, which may surface pre-existing failures that need
   triage — or accept the limit and write invariants engine-independently, which is what the
   new test does.
3. **A gate is only as good as the freshness of what it reads.** The i18n gate was green
   while enforcing a real rule against a stale generated list. Fixed here, but worth
   auditing anywhere else a check consumes a generated artefact: if regeneration is not
   diffed, the check is advisory.
4. **Build-context hygiene is a security boundary, not tidiness.** A `.gitignore`d file no
   reviewer can see decided what shipped. A one-line CI assertion that the built image
   contains no fixture strings (`grep -r 'Mme Fontaine' .next`) would have caught F-1 at the
   commit that introduced it.
5. **Fixtures that are tidier than reality hide real bugs.** F-4 passed its own correct
   assertion for months because the fixture matrix is narrow; F-5 and F-6 were unreachable
   in fixture mode. Where a fixture stands in for real data, make it at least as awkward as
   the real thing — a wide matrix, a populated agenda, a teacher with no subject declared.
6. **Two of these were comments describing a deployment the repo does not have.** F-2's
   `frame-ancestors 'self'` and its test were both written for a single-origin proxy. Where
   a header or a policy depends on topology, the topology belongs in the assertion — which
   is why the fix reads `cors_origins` instead of restating a hostname.
7. **A test double must not be more permissive than what it stands for.** `_FakeMessages`
   takes `**kwargs` and accepts anything; the real SDK takes named parameters and rejects an
   unknown one at the call. That gap *is* F-7. Where a double stands in for a third-party
   API, check the real signature somewhere — it costs no network call and no key, and it is
   the only thing that survives an unpinned dependency moving underneath you.
8. **Pin, or check, the SDKs that are load-bearing.** `anthropic>=0.40.0` with no upper
   bound is how a parameter removal became a production `TypeError`. The same open range
   applies to `openai`. Either pin them and upgrade deliberately, or keep a signature test
   per provider — the second is cheaper and is now in place for one of the two.
9. **Exercise the seed the way a new user does.** F-8 survived because every test builds its
   own fixtures and nothing starts from `docker compose up` and tries the first thing a
   teacher tries. One smoke test that seeds, logs in and builds a sheet would have caught
   it, and would also have caught F-1.

---

## 9 · Changes made

| file | why |
|---|---|
| `.dockerignore` | F-1 — exclude every dotenv at every depth |
| `apps/api/alppy/main.py` | F-2 — `frame_ancestors()` names the configured front ends |
| `apps/api/tests/test_request_id_hardening.py` | F-2 — corrected the test that asserted the defect; +2 tests |
| `apps/api/alppy/services/scan_service.py` | F-3 — flush the pile before the job that references it |
| `apps/api/tests/test_api_scans.py` | F-3 — statement-order regression test (engine-independent) |
| `packages/ui/src/components/domain/Matrix.tsx` | F-4 — `relative` scroller becomes the containing block |
| `apps/web/messages/{fr,de,en}.json` | F-5, F-6 — placeholder name; 1 sentence + 5 labels × 3 locales |
| `apps/web/src/app/[locale]/timeline/page.tsx` | F-6 — complete the filter list |
| `scripts/generate-api-types.py` | F-6 — emit `EVENT_KINDS` |
| `scripts/check-i18n.mjs` | F-6 — assert a label for every event kind |
| `.github/workflows/ci.yml` | F-6 — diff all three generated files |
| `packages/shared/src/api-constants.generated.ts` | regenerated (was stale) |
| `apps/api/alppy/ai/providers.py` | F-7 — ask the SDK whether it takes `temperature`; shared warning; F-9 — one kwargs dict |
| `apps/api/tests/test_ai_vision.py` | F-7 — +2 tests: arguments vs the installed signature, and the warning |
| `apps/api/alppy/seed/__init__.py` | F-8 — the demo declares 7B × mathematics (9A stays empty on purpose) |
| `apps/api/alppy/storage.py` | F-9 — one `_s3()` factory instead of a `**dict` that matched no overload |
| `apps/api/tests/test_answer_box_placement.py` | the font test gets a statement that wraps differently, plus a host-independent assertion |
| `docs/decisions-log.md` | the decisions, per CONTRIBUTING |

No behaviour was changed to make a test pass, and no test was weakened to make it green. Two
tests were edited and both were asserting a defect verbatim:
`test_request_id_hardening.py:47` pinned the CSP that made the preview unframeable, and
`test_the_box_moves_when_the_font_stack_does` carried a statement that could not demonstrate
the property it tests. Both say so in the test itself rather than leaving it in the diff.
Every new regression test was confirmed to **fail without its fix** before being kept.

---

## 10 · Final state

| gate | before | after |
|---|---|---|
| pytest | 1 410 passed, **1 failed**, 69 skipped | **1 470 passed, 0 failed**, 15 skipped |
| `@alppy/ui` + `@alppy/web` vitest | 352 passed | 352 passed |
| Playwright (behaviour) | 260 passed | 260 passed |
| `mypy --strict` | **4 errors** (CI step red) | **clean, 95 files** |
| ruff · ESLint · tsc · stylelint | green | green |
| i18n | green on a stale list, 882 keys | green on a checked list, **888 keys**, +event-kind rule |
| screens · layout · API contract | green | green, contract now diffs all three files |
| live sweep, 29 routes × 3 viewports | 6 defects | **87/87 clean, from empty volumes** |
| `docker compose up` → build a sheet | impossible | works with no manual step |
