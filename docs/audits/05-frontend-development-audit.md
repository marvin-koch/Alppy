# Phase 5 audit — Frontend development (the build)

**Scope:** the built frontend. `apps/web/src` (20 117 lines: 26 routes, 14 layouts, 23 app
components, the API layer, i18n, middleware, CSP), `packages/ui/src` (36 primitives, 18
domain components, 6 design stylesheets, 49 icons), `packages/shared` (now four generated
files, not one), the three catalogues, the Vitest and Playwright suites, and the print path
where it crosses into `apps/api/alppy/sheets/`. Where a claim depends on the API I read the
API and quote it; I did not re-audit `apps/api` — Phase 3 did.

**Method:** read-only. No file was written except this one. No server was started, no build
was run, no test was executed. Every finding below is grounded in `file:line`. Where I could
not settle runtime behaviour by reading, §12 names the test that would.

**Prior phases** were read first, in full:
[`01-database-audit.md`](01-database-audit.md), [`02-api-audit.md`](02-api-audit.md),
[`03-backend-audit.md`](03-backend-audit.md),
[`04-frontend-architecture-audit.md`](04-frontend-architecture-audit.md). Phase 4 audited the
plan; this audits the build against it. §8 answers F1–F32 one by one.

**Snapshot:** branch `feat/phase1-time-and-identity` at `ec444ef`, with
`apps/api/alppy/sheets/{html,render}.py` modified in the working tree. 2026-09-11.

**The headline before the detail:** twenty-five of Phase 4's thirty-two findings are closed,
including both Criticals. The print path is now sound. What this phase found instead is a
different and quieter failure mode: **capability that reached `endpoints.ts` and stopped
there.** The API grew a school-year dimension, an `as_of` parameter on every mastery read,
and an `Idempotency-Key` on the four operations that cost real money — the client layer types
all three and no hook, no key and no screen uses any of them.

---

## 1 · Verdict

**Yes, a teacher can complete a full generate → print → scan → review → finalise cycle today
without losing work or misgrading a student — with three qualifications, none of which is the
paper.**

The two Criticals Phase 4 raised are genuinely fixed, and fixed at the root rather than
papered over. There is now exactly one door to paper: `printReadiness`
(`lib/print.ts:57-76`) returns `ready` only when the server says `rendered_at !== null`, the
button is a link to the PDF the render job measured, and `markPrinted` can only fire on that
path (`sheets/[sheetId]/page.tsx:152-179`). The iframe is an *aperçu* and there is no code
anywhere that prints it — the comment at `:67-83` records what it replaced and why. The four
faces are embedded as `data:` URIs in a generated `fonts.css` (248 KB, four `@font-face`
rules) which the print template inlines first (`sheets/templates/sheet.html.j2:23-24`), so the
PDF, the preview and the answer key typeset identically, and `scripts/embed-fonts.mjs` is
re-run and diffed in CI the way the geometry already was. On top of that the sheet is no
longer editable from the UI at all (`updateSheet` is exported and has no caller), which closes
the re-render-after-print hole from the client side by construction. **The coordinate
assumptions the grading pipeline depends on hold.**

The three qualifications:

1. **A correction that fails to save says nothing.** `useCorrectDetection`'s error is rendered
   nowhere on the review screen — `correct.mutate` is called at
   `scans/[scanId]/page.tsx:513` and `correct.isError` appears at no line in the file. The
   only feedback a teacher gets is the `SegmentedControl` snapping back to the machine's
   value, because it renders `verdictOf(detection)` from query data that never changed
   (`OpenAnswerCard.tsx:206-207`). On a network drop the shell's offline bar does appear
   (`AppShell.tsx:180-188`), which is the good half; on a 409 or a 500 there is no signal at
   all, and `N` has already scrolled the teacher somewhere else. Press *Juste*, look away,
   confirm the pile, and the machine's wrong reading becomes the grade. This is the one path
   in the product that can misgrade a child silently, and it is cheap to close.
2. **A decimal barème cannot be typed.** The custom points field is a controlled
   `type="number"` whose handler is `clampPoints(Number(event.currentTarget.value))`
   (`SheetComposer.tsx:393-401`). A browser sanitises the intermediate `1.` to the empty
   string, `Number('')` is `0`, `clampPoints(0)` is `0`, React writes `0` back into the field,
   and the next keystroke makes it `05` → **5**. A teacher aiming for 1.5 points an item gets
   5. A comma is rejected outright. The sibling control two hundred lines down uses
   `valueAsNumber` and therefore behaves (`:596`), which is what shows this is an oversight
   rather than a decision.
3. **Thirty photographs are still one atomic request with no retry and no idempotency key.**
   `scans/new/page.tsx:51-74` posts every file in one `FormData`, with no client-side size or
   count check (`sources/page.tsx:44-57` has one; this screen does not) and no resize of a
   phone's 4 MB photographs. A drop at 80 % discards everything and the teacher re-picks
   thirty files. Meanwhile the API added `Idempotency-Key` to exactly this route for exactly
   this reason (`api/v1/scans.py:95-115`) and the client cannot send a header at all —
   `RequestOptions` has no `headers` field (`lib/api/client.ts:52-64`).

Neither flow loses in-progress *corrections*: every verdict is its own mutation and lands as
it is made, the sheet builder now persists its draft to `sessionStorage` with a
`beforeunload` guard (`useDraftSheet.ts:227-258`), and an adaptive run is recoverable from the
URL and from a five-entry local history (`adaptive/page.tsx:144-156`, `:231-242`, `:1274`).
Projector mode exists, is a display preference applied before paint, has a keyboard shortcut
for the moment the projector is already on, and is honoured on seven screens — with one hole
(§5). The French reads like Suisse romande, *matière* is gone, *École* is now
*Établissement*, and *groupe* has been given back to the teachers: the adaptive cohorts are
*séries* now.

---

## 2 · Findings

Ordered within each severity by risk to student data or teacher work, descending.

| ID | Sev | Area | Summary | Evidence |
|---|---|---|---|---|
| G1 | High | Misgrading | A failed correction on the review screen is silent; the control reverts to the machine's reading and nothing says the save did not happen | `scans/[scanId]/page.tsx:513`, `queries.ts:900-908`, `OpenAnswerCard.tsx:206` |
| G2 | High | Validation | A decimal barème cannot be typed: `Number('')→0` resets the controlled field, so `1.5` becomes `5`; a comma is rejected | `SheetComposer.tsx:393-401`, `useDraftSheet.ts:42-45` |
| G3 | High | Drift / temporality | `as_of` and `school_year_id` are plumbed through `endpoints.ts` and used by nothing above it; `listSchoolYears` has no caller | `endpoints.ts:156,166,169,525,537,556,559`, `queries.ts:576-661` |
| G4 | High | Double submission | No `Idempotency-Key` is ever sent, on any of the four routes the API added one for; `RequestOptions` cannot carry a header | `client.ts:52-64`, `endpoints.ts:315,325,477,480`, `api/v1/scans.py:108`, `api/v1/sheets.py:152` |
| G5 | High | Connectivity | Scan upload is one atomic multipart: no per-file progress, no resume, no retry, no client size or count check, no image downscale | `scans/new/page.tsx:51-74`, `FileDrop.tsx:62-65` |
| G6 | High | Disclosure / i18n | English developer prose still reaches the teacher on five sites, including a quality-metric sentence on the screen most likely to be projected | `scans/[scanId]/page.tsx:253,596`, `sources/page.tsx:185,194`, `sheets/new/page.tsx:324` |
| G7 | High | Student dignity | `CellDrillDown` renders the pupil's full name as its title, opened by clicking a cell on the matrix that is showing UIDs | `CellDrillDown.tsx:65` |
| G8 | Medium | Cache invalidation | Confirming or reopening a pile does not invalidate `['sheet-mastery']` or `['timeline']`; the sheet screen's class band is stale for 30 s after a write | `queries.ts:962-982,932-948`, `sheets/[sheetId]/page.tsx:61` |
| G9 | Medium | Requests | No request anywhere has a timeout. `apiRequest` accepts a signal and one caller passes one | `client.ts:177-218`, `DraftPreview.tsx:87` |
| G10 | Medium | Polling | No backoff and no maximum duration: `useJob` polls every 900 ms forever on a job that never terminates, `useScan` every 2 s while any verdict stays pending | `queries.ts:1141-1151,849-864` |
| G11 | Medium | Performance | No `React.memo` anywhere; one `setSelected` re-renders all 30 `PageCard`s and ~1 000 overlay buttons, and the inline `registerRow` ref detaches every row each render | `scans/[scanId]/page.tsx:500-516`, `Matrix.tsx:213` |
| G12 | Medium | Review queue | The default view is unfiltered page order; least-confident-first applies only *within* a page | `scans/[scanId]/page.tsx:120-127,130-134,193-196` |
| G13 | Medium | Layout stability | 30 page images and their crops are lazy but reserve no dimensions, so rows move under the teacher's finger as images arrive | `ScanReviewOverlay.tsx:137-143`, `OpenAnswerCard.tsx:98-106` |
| G14 | Medium | Semantic colour | `success` means both "the machine read this bubble" and "this is the correct option" on the same card; `AttemptList` uses the mastery *fading* ink (staleness) for "incorrect" | `ScanReviewOverlay.tsx:74-79`, `scans/[scanId]/page.tsx:766`, `AttemptList.tsx:69-72` |
| G15 | Medium | Contract | `AdaptiveBatchRequest.source_sheet_ids` exists now and the client still sends only the singular, while the sheet screen renders the plural lineage with a **Principal** chip | `adaptive/page.tsx:575`, `api-types.generated.ts:44-45`, `sheets/[sheetId]/page.tsx:210-222` |
| G16 | Medium | Partial success | Creating a class is two sequential awaits; a failure of the second keeps the class and loses the pasted roster, and resubmitting conflicts | `classes/new/page.tsx:50-77` |
| G17 | Medium | Generation | No retry of only the failed subset: the failures panel lists each pupil and offers nothing; the only remedy is a whole re-propose | `adaptive/page.tsx:874-889,767-787` |
| G18 | Medium | Incident reporting | `ApiError.requestId` is parsed and surfaced nowhere; only `error.digest` reaches a screen, and only in `global-error` | `client.ts:85-97`, `global-error.tsx:54-58` |
| G19 | Medium | A11y | Row selection is `onClick` on a `Panel`, i.e. a `div` with no role and no key handler; keyboard selection exists only through `N` and the overlay buttons | `Panel.tsx:17-25`, `scans/[scanId]/page.tsx:737-741`, `OpenAnswerCard.tsx:71-75` |
| G20 | Medium | Validation UX | Validation fires on every keystroke, and `Field`'s error is associated but never announced | `classes/new/page.tsx:43,88-90`, `Field.tsx:104-107` |
| G21 | Medium | Number inputs | The scroll wheel changes a focused number field; there is no `onWheel` guard anywhere | `SheetComposer.tsx:393,589` |
| G22 | Medium | Error boundaries | One boundary, at the locale segment: a throw in one detection row blanks the whole 30-page review | `app/[locale]/error.tsx`, no boundary inside `scans/[scanId]` |
| G23 | Medium | Dead capability | `printed_at` and `updateSheet` are in the contract and used by nothing: a teacher cannot see that a sheet already went to the photocopier, nor fix its title | `api-types.generated.ts:952`, `endpoints.ts:302`, `sheets/page.tsx:87-88` |
| G24 | Low | Misattribution | An attributed page shows the UID and never the pupil's name, even with projector mode off | `scans/[scanId]/page.tsx:563-569` |
| G25 | Low | A11y | `n` and `Shift+D` are screen-reader quick-navigation keys in browse mode, so both shortcuts are unreachable for a screen-reader user | `scans/[scanId]/page.tsx:223-235`, `AppShell.tsx:112-132` |
| G26 | Low | Errors | A deep link to a class the teacher no longer owns renders `errors.generic` ("réessayez") rather than the translated `not_found` sentence that exists | `classes/[classId]/page.tsx`, `messages/fr.json` `errors.code.not_found` |
| G27 | Low | Projector mode | `RevealNames` is on three screens of the seven that hide names; roster, profile, competence and review offer no in-page reveal | `RevealNames.tsx`, grep of `useDiscretion` |
| G28 | Low | Render-phase side effect | `ScopeProvider` reads and `JSON.parse`s `localStorage` during render, on every render | `scope.tsx:144` |
| G29 | Low | Keys | `key={group.label \|\| groupIndex}` on the series list; `key={name}` on the in-flight upload list | `adaptive/page.tsx:1054`, `scans/new/page.tsx:157` |
| G30 | Low | Projector mode | The roster replaces a name with `—` where every other screen substitutes the UID | `classes/[classId]/roster/page.tsx:146` |
| G31 | Low | Fixture mode | `isMockEnabled()` reads `localStorage`, so any visitor can flip the whole app — and the `_gallery` route — into fixture mode in a production build | `client.ts:42-50`, `%5Fgallery/page.tsx:74-76` |
| G32 | Low | Tests | No unit test for `lib/format.ts`, the single point through which every number, date and percentage in the product passes | `find apps/web/src -name 'format.test.ts'` → none |

---

## 3 · Detailed findings

### High

---

#### G1 · A correction that does not save says nothing, and the control lies about it

**What is wrong.** The review screen's whole safety argument is that every correction is its
own mutation and lands the moment it is made. It is — and nothing reads the result:

```tsx
onCorrect={(detectionId, body) => correct.mutate({ detectionId, body })}
//  scans/[scanId]/page.tsx:513
```

`grep -n "correct\." scans/[scanId]/page.tsx` returns that one line. There is no
`correct.isError` branch, no toast, no `onError`. Compare the three mutations beside it, all
of which *are* reported: `confirm.isError` gets a `role="alert"` panel (`:418-422`),
`retake.isError` gets one on the page card (`:622-626`), and `assign`'s failure is at least
visible because the select does not clear.

The second half is what makes it dangerous. The verdict control is driven by server data:

```tsx
<SegmentedControl<Verdict> value={verdictOf(detection)}    // OpenAnswerCard.tsx:206
```

and `verdictOf` reads `detection.verdict_correct`. A failed mutation leaves the cached
detection untouched, so the control renders the machine's original verdict again. The teacher
pressed *Juste*; the control shows *Incertain*. Nothing distinguishes that from a press that
did not register.

**Why it matters here.** Mme Berthod is on copy 19 of 28. The API answers 500 once — a
connection reset behind the proxy, a transient database error, any of the codes the catalogue
now has a sentence for. She presses *Juste* on a written answer, presses `N`, and the screen
scrolls her to the next uncertain item on another page card. Item 7 of copy 19 stays as the
model read it: wrong. She reaches the end, presses **Valider les résultats**, and the
confirmation reports 224 attempts written. One of them is a child marked wrong on an answer
their teacher judged correct, and there is no record anywhere that she said otherwise.

The network case is better and worth crediting: `apiRequest` reports every failure to
`lib/connection.ts`, so a dropped wifi raises the shell bar — *"Hors ligne — Alppy ne répond
pas. Vos corrections déjà envoyées sont enregistrées."* (`AppShell.tsx:180-188`). That is
honest and it is the right sentence. It does not fire for a 409, a 422 or a 5xx, which are
precisely the failures that are not the teacher's fault and not the network's.

**The fix.** Two lines and a component that already exists. `useCorrectDetection` should take
an `onError` that raises a toast through `useToast` — the provider is mounted
(`Providers.tsx:63`), the adaptive screen already uses it for the discard undo
(`adaptive/page.tsx:557-562`), and the toast is where a transient failure belongs because it
does not need dismissing. Then, so the control cannot lie: keep the pressed value in local
state while `correct.isPending`, and on failure fall back with the toast rather than
silently. The stronger version is a per-detection retry in the toast's action slot, which
`ToastProvider` supports.

**Effort.** Half a day including the interaction test that is currently missing (§12).

---

#### G2 · A decimal barème cannot be typed, and the number that lands is wrong

**What is wrong.** The custom points control is fully controlled, typed `number`, and parsed
with `Number()`:

```tsx
<Input
  type="number"
  inputMode="decimal"
  numeric
  min={0}
  max={MAX_ITEM_POINTS}
  step={0.25}
  value={value ?? 0}
  onChange={(event) => onChange(clampPoints(Number(event.currentTarget.value)))}
/>
//  SheetComposer.tsx:392-402
```

with

```ts
export function clampPoints(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_POINTS_CORRECT;
  return Math.min(MAX_ITEM_POINTS, Math.max(0, Math.round(value * 100) / 100));
}
//  useDraftSheet.ts:42-45
```

Trace `1.5`, keystroke by keystroke, in any browser:

| typed | `input.value` | `Number(...)` | `clampPoints` | React writes back | field shows |
|---|---|---|---|---|---|
| `1` | `"1"` | 1 | 1 | — | `1` |
| `.` | `""` — `1.` is not a valid floating-point number, so the value sanitisation algorithm empties it | 0 | **0** | `"0"` | `0` |
| `5` | `"05"` | 5 | **5** | — | `5` |

The teacher wanted 1.5 and has 5. A comma is worse and shorter: `1,` empties the value the
same way, `clampPoints(0)` is `0`, and the field reads `0`.

The guard that would have caught this is `Number.isFinite`, and it never fires, because
`Number('')` is `0` and zero is finite. The sibling control in the same file gets it right:

```tsx
lines: clampAnswerBoxLines(event.currentTarget.valueAsNumber),   // :596
```

`valueAsNumber` is `NaN` for an empty value, `clampAnswerBoxLines` tests `Number.isFinite`
and returns the default. Same file, same shape, two different readings of the same DOM
property.

**Why it matters here.** The presets cover 0.5, 1, 2, 3 and 5 (`useDraftSheet.ts:38`), so
the custom field is reached exactly when the teacher wants a value the presets do not have —
1.5 for a two-part question, 0.25 for a quick check. On the sheet barème it multiplies across
every item: a sheet of twelve items meant to be worth 18 points is printed worth 60, the
barème is printed on the paper beside each statement, and `Attempt.score` carries it into
`/results` forever. On an item override it is one statement.

The mitigations are real and I want them stated: the field visibly shows `5`, the panel shows
`draft.totalPoints` beside the title (`SheetComposer.tsx:311-313`), and `DraftPreview` posts
the draft to the server and shows the actual paper. A teacher who looks will see it. This is
High rather than Critical because of those three, not because the parse is acceptable.

**The fix.** Use `valueAsNumber`, like the control below it. `clampPoints` already does the
right thing with `NaN`. If a comma is to be accepted — see §10 on whether it should be —
that is a separate `inputMode="decimal"` text input with a parse, not a `type="number"`.

**Effort.** One line, plus the test in §12 that would have caught it.

---

#### G3 · The temporal dimension reached `endpoints.ts` and stopped there

**What is wrong.** Phase 4's F8 said *"`année scolaire` does not exist in the interface"* and
ranked it High while noting the frontend was the wrong place to fix it, because *"the
parameter does not exist to pass"*. The parameter exists now. The API grew:

- `GET /school-years` — a discovery route whose docstring says why it was added: *"Every
  `school_year_id` filter in this API needs an id, and until now there [was no way to get
  one]"* (`api/v1/classes.py:68-72`);
- `school_year_id` on `/home` and `/classes` (`api/v1/classes.py:54,96`);
- `as_of` on `/classes/{id}/mastery`, `/classes/{id}/tree`, `/students/{id}/mastery`,
  `/students/{id}/competencies/{id}/attempts` and `/classes/{id}/points`
  (`api/v1/mastery.py:38,75,98,120`, `api/v1/reports.py:38`) — with the docstring *"`as_of`
  computes the answer as it would have stood at that moment"*.

The client layer types every one of them, with comments explaining the point:

```ts
export const listSchoolYears = () => apiRequest<SchoolYearOut[]>('/school-years');
//  endpoints.ts:166

      // An ISO instant. The matrix computed as it stood then — the roster
      // moves with it, so this is October's group and not today's.
      as_of: options.asOf,
//  endpoints.ts:547-549
```

And then nothing. `grep -n "schoolYear\|asOf\|as_of" queries.ts scope.tsx ScopeSwitcher.tsx`
returns nothing. `useClassMastery` takes `{ subjectId, chapterId, sort }` and no more
(`queries.ts:607-616`); `queryKeys.classMastery` spells those three into the key and not a
fourth (`:117-125`). `listSchoolYears` has exactly two references outside its own definition:
the fixture file and the mock handler. No hook, no screen, no control. The catalogue has no
`année scolaire`, no `degré`, no HarmoS year — 857 keys and none of them names a year.

**Why it matters here.** The scenario is unchanged from Phase 4 and now it is the frontend's:
M. Rossier is asked in June why Léa was oriented as she was. The matrix that justified it is
October's, the decay model means it is not recoverable by looking harder, and
`GET /classes/{id}/mastery?as_of=2026-10-14T00:00:00Z` would answer him today. Nothing in the
product will send that request. Mid-August is the other half: `/classes` shows whichever
classes the default filter returns, with no control to ask for last year's and no banner if
it ever gave them.

This is the most important *drift* in the report, and the cost of leaving it is exactly the
one Phase 4 predicted: every class-grained cache key would have to grow a dimension, and
`queryKeys` is still the one place that is cheap to change — eight builders, one file.

**The fix.** The shape is already designed, in the file that would hold it. `lib/scope.tsx`
resolves ids from the URL with a validated fallback and already distinguishes sticky (class,
subject) from not-sticky (competency, chapter); a year is sticky. A `useSchoolYears` hook, a
year row at the top of `ScopeSwitcher` written to `?year=`, the id threaded into
`queryKeys.classMastery / classTree / classPoints / sheets / scans / home`, and — the part
that is not plumbing — a banner, not a chip, whenever the selected year is not the current
one. A teacher reading last year's numbers as this year's is the failure mode, and it is
worse than not offering the feature.

**Effort.** Two days for the plumbing and the banner; the API half is done.

---

#### G4 · The client cannot send an idempotency key, on the four routes that were given one for it

**What is wrong.** Phase 3's B17 was taken seriously. There is an `IdempotencyKey` table whose
docstring names the case — *"A phone on a flaky [connection]"* (`models/__init__.py:1725-1756`)
— a `services/idempotency.py`, an `IdempotencyKeyDep` header dependency
(`api/deps.py:611-624`), two error codes in the generated contract
(`api-constants.generated.ts:23-24`) with French sentences for both
(`messages/fr.json` `errors.code.idempotency_*`), and `idempotency.run(...)` wrapped around
exactly the four operations that are expensive to repeat:

| route | the comment's own reason |
|---|---|
| `POST /scans` | *"without it the pile is uploaded twice — twenty-eight copies reviewed and confirmed in duplicate"* (`api/v1/scans.py:95-115`) |
| `POST /sheets/{id}/render` | *"tapping 'print' twice because the screen has not moved yet used to queue two renders of the same sheet, each rewriting the other's answer-box placements"* (`api/v1/sheets.py:148-160`) |
| `POST /adaptive/batch` | *"a retry used to build a second sheet binding the same pupils to the same plans"* (`api/v1/adaptive.py:324-342`) |
| `POST /adaptive/batch/{id}/render` | same shape (`api/v1/adaptive.py:346-364`) |

The client sends none of them, and cannot:

```ts
export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
  query?: Record<…>;
}
//  client.ts:52-64 — no `headers`
```

and the four call sites pass nothing extra (`endpoints.ts:315-316, 325-330, 477-478,
480-481`).

**Why it matters here.** The UI-level guard is real but it is only one of the two the brief
asks for. Every one of these buttons disables itself while pending — `Button` sets
`disabled={disabled === true || loading}` (`Button.tsx:54`) and the screens pass
`loading={print.state === 'rendering'}` and `loading={exporting}`. That covers a second
deliberate click. It does not cover the two cases the key was added for: a double-tap inside
the render that sets `isPending` (a real hazard on a touchscreen), and a *retry* after an
answer that never arrived — which on a phone in a classroom is the normal case, and which the
teacher performs by pressing the button again after the spinner has cleared.

The consequence is worst on the upload, and the API's own comment states it: a second pile of
the same twenty-eight copies, reviewed separately and confirmed separately. The client has no
way to distinguish "the request failed" from "the answer was lost", so it reports failure and
invites the retry that causes the duplicate.

**The fix.** Add `headers?: Record<string, string>` to `RequestOptions` and merge it in both
`apiRequest` and `apiRequestText`. Then generate a key *per user intent*, not per request —
that is the whole point, and it is where this is easy to get wrong. `crypto.randomUUID()`
held in a `useRef`, minted when the screen arms the operation (a file selection, a first press
of **Générer le PDF**), reused by every retry of that same intent, and cleared on success.
The two error codes already have their sentences: `idempotency_in_flight` reads *"Cette
demande est déjà en cours. Attendez sa fin plutôt que de la relancer."*, which is exactly
what a teacher needs to be told and is currently unreachable.

**Effort.** One day for all four, including the ref-held key and a test that a retry sends the
same value.

---

#### G5 · Thirty photographs are still one request, and nothing measures it

**What is wrong.** Phase 4's F10, essentially unchanged in the client:

```tsx
setPending(files.length);
setSending(files.map((file) => file.name));
upload.mutate({ files, sheetId }, {
  onSuccess: (scan) => router.push(…),
  onError: (e) => { setPending(0); setSending([]); setError(apiErrorMessage(e, tErr)); },
});
//  scans/new/page.tsx:58-73
```

What *has* improved is honesty: the panel now names the files being sent, with a comment
saying why that is the half the client owns (`:150-154`), and it correctly uses a `Spinner`
rather than a ring drawn at zero. What has not improved:

- **No client-side limits.** `sources/page.tsx:44-57` checks `MAX_MB` and the MIME type before
  posting, with a comment calling a client check *"a courtesy and never a control"*. The scan
  screen checks neither, and the API caps at 120 files × 50 MB (Phase 2 M6). Thirty photos
  from a modern phone is 90–150 MB, and the failure mode is a `payload_too_large` after the
  whole body has been uploaded.
- **No downscale.** `FileDrop` hands `Array.from(list)` straight through (`FileDrop.tsx:62-65`).
  The detector registers off four fiducials and works from a deskewed page; it does not need
  12 megapixels. A `canvas`-based downscale to ~2 000 px on the long edge would cut the
  payload by an order of magnitude and is the single largest win available on this screen.
- **No resume, no per-file retry, no partial success.** A drop at 80 % is total.
- **No timeout** (G9), so a stalled connection shows the spinner and the words *"Gardez cette
  page ouverte"* indefinitely.

**Why it matters here.** This is the longest wait in the product, performed on the worst
network in the building, on the device with the least patience. The brief asks what happens
when connectivity drops mid-upload: the `fetch` rejects, `apiRequest` turns it into
`ApiError(0, 'network_error')`, the shell raises the offline bar, the screen shows *"L'application
n'a pas pu joindre le serveur."*, `sending` is cleared, and the file input's selection is
gone. The teacher re-photographs or re-picks thirty files. Nothing was uploaded; nothing was
queued.

**The fix.** Three steps, in value order: downscale client-side before posting (pure client,
no API change, largest effect); check size and count with the same courtesy message
`sources/page.tsx` already uses; and send an idempotency key (G4) so the retry that follows a
lost answer cannot make a second pile. Batched upload against a scan created up front is the
proper answer and belongs with Phase 2 M6.

**Effort.** Two days for the client half.

---

#### G6 · English developer prose still reaches five screens

**What is wrong.** Phase 4's F12 named six sites. One is fixed, and fixed exemplarily:
`SectionPicker` no longer renders `job.message`, and the comment records the rule —
*"The job's own `message` is a log line, in English … off the stage rather than off the
string"* (`SectionPicker.tsx:222-232`). The other five render a server *field* rather than a
server *error*, which is the shape that slips past `apiErrorMessage`:

| site | field | what is in it |
|---|---|---|
| `scans/[scanId]/page.tsx:596` | `page.registration_error` | `"registration quality 0.42 is below 0.55: …"` (`scan/detector.py:797`), or `str(RegistrationError)`, or a layout-version sentence |
| `scans/[scanId]/page.tsx:253` | `scan.data.error` | `str(ScanDecodeError)` — e.g. a filename off the teacher's phone |
| `sources/page.tsx:185` | `source.error` | `UNREADABLE_PDF_ERROR` — *"Alppy could not read this PDF. It may be damaged, password-protected, or not really a PDF."* (`ingest/pipeline.py:71-74`) |
| `sources/page.tsx:194`, `sheets/new/page.tsx:324` | `source.notice` | same shape |

The `Source` pair is the frustrating one, because the backend did the hard part: Phase 3's
`_teacher_facing_error` refuses to pass an exception's text through and maps to two curated
sentences (`ingest/pipeline.py:259-267`). They are written *for a teacher*. They are in
English, and a French teacher reads them in English.

`registration_error` is the one that is simply wrong. It is a developer's sentence about a
quality threshold, rendered at `text-ink-500` under two perfectly good translated sentences —
`registrationWhy` and `registrationHelp`, which say the same thing correctly, one and two
lines above it.

**Why it matters here.** D86 exists because these screens are projected onto a classroom wall.
A threshold, a filename or a layout version does not belong on a wall, and a trilingual
product that switches to English at the moment something fails is a product a teacher stops
trusting at the moment trust matters.

**The fix.** Same shape as the error envelope, one layer out: `ScanPageOut` carries a
`registration_error_code` (`fiducials_not_found`, `quality_too_low`, `layout_mismatch`),
`SourceOut` carries `error_code` and `notice_code` — there are two and three of them
respectively — and the client switches on the code through the catalogue. Until the schema
moves, the cheapest correct step is to **stop rendering `registration_error`**: the two
sentences above it already say everything a teacher can act on.

**Effort.** Deleting the raw line: minutes. The three codes and their nine catalogue entries:
one day across both halves.

---

#### G7 · Projector mode has one hole, and it is one click from the screen it protects

**What is wrong.** Projector mode is otherwise good work. `discreet` is a display preference
applied as `data-discreet` before paint alongside `contrast`, `motion` and `calm`
(`lib/display.ts:16-27,52-59`); `useDiscretion` watches the attribute with a `MutationObserver`
so a mid-lesson toggle reaches every mounted screen (`lib/discreet.tsx:85-93`); the reveal is
React state in a provider reset on every navigation, so it cannot outlive the screen
(`:56-65`); `Shift+D` toggles it from anywhere with a live-region announcement, chosen
deliberately over a bare letter and over a combination the browser owns
(`AppShell.tsx:112-132`); and eight Playwright tests cover it, including *"names come back
only when the teacher asks, and not for long"* (`e2e/discreet.spec.ts`).

Seven screens honour `hideNames`. The eighth does not exist as a screen — it is a side sheet:

```tsx
title={
  data ? `${data.student.first_name} ${data.student.last_name}` : t('title')
}
//  CellDrillDown.tsx:65
```

`CellDrillDown` has no `useDiscretion` import. It is opened by clicking a cell on
`/classes/[classId]`, which *is* discreet-aware and *does* carry `RevealNames`
(`classes/[classId]/page.tsx:45,185,329`). So the projected matrix shows `7B_04`, the teacher
clicks a red cell to explain it to the class, and a panel slides in from the right titled
**Léa Berthod**, above her band, her review date, and every attempt she has made on that
competency with the statements printed out.

**Why it matters here.** This is the exact action the drill-down was built for — *"A band is
an argument the teacher is entitled to check"* — and it is the action a teacher takes while
the matrix is on the wall. The mode is defeated by the one click that the screen invites.

**The fix.** Four lines: `useDiscretion()` in `CellDrillDown`, and the title becomes
`pupilLabel` — the pure helper that already exists for this and is already unit-tested
(`lib/pupil-label.ts`, `lib/discreet.test.ts:15-33`). While there, `AttemptList`'s statements
are the child's own work and arguably belong behind the reveal too; the name is the part that
identifies.

**Effort.** An hour, including an assertion in `e2e/discreet.spec.ts` next to the seven that
are already there.

---

### Medium

---

#### G8 · Confirming a pile leaves the sheet's class band stale

`useConfirmScan` invalidates five things and the comments show the reasoning was careful —
the two broad prefixes are deliberate, *"a pile of copies can carry more than one class's
worth of paper"* (`queries.ts:968-981`). Two namespaces are missed, because neither hangs off
a prefix in the set:

| key | builder | matched by `['sheets']`? |
|---|---|---|
| `sheetMastery(id)` | `['sheet-mastery', id]` | **no** — the first element differs |
| `timeline(q)` | `['timeline', …]` | **no** |

`sheetMastery` is what the sheet detail screen reads for its **Bande de la classe** panel
(`sheets/[sheetId]/page.tsx:61,245-262`). The teacher's path after confirming is the
breadcrumb at the top of the review screen, straight to that sheet. Inside the global
`staleTime: 30_000` they see the band as it was before they confirmed — over the sentence
that says how many attempts were just written. `useReopenScan` has the identical set and
therefore the identical gap, in the other direction.

`['timeline']` matters less but is the same class of miss: confirming writes an event, and the
agenda does not know.

**Fix:** add `queryKeys.sheetMastery`'s namespace and `['timeline']` to both mutations. Better,
add a line to `query-keys.test.ts` — which already asserts that no invalidation names a
namespace nothing is stored under (`:58-66`) — checking the converse: that every top-level
namespace in `queryKeys` is reachable from at least one invalidation. That test is what would
have caught this, and it is a natural extension of one that exists.

---

#### G9 · No request has a timeout

`apiRequest` accepts `signal` and every endpoint helper omits it (`client.ts:59,196`). The
only `AbortController` in the app is `DraftPreview`'s, and it is a debounce guard rather than
a timeout (`DraftPreview.tsx:87-119`). So the brief's third requirement — loading, error,
**timeout** — is met twice out of three, everywhere.

What that costs, concretely: a request that is accepted and never answered (a proxy holding a
connection, a school captive portal, a worker that hangs) shows a spinner for as long as the
tab is open. The offline bar does not fire, because `noteReachability(false)` is only reached
from the `fetch` rejection (`client.ts:198-203`) and a stalled connection does not reject.
The scan upload is the worst case, because its help text tells the teacher to stand still.

**Fix:** a default `AbortSignal.timeout(ms)` in `apiRequest`, combined with any caller signal
through `AbortSignal.any`, and a longer budget for the multipart upload. A timeout should
surface as its own code so the catalogue can say *"Alppy ne répond pas"* rather than
*"L'envoi a échoué"*.

---

#### G10 · Polling has no backoff and no ceiling

Every poll now lives in the query layer — F25 is fixed and `useSources` carries the comment
explaining what a `refetchInterval` inherits for free, including pausing on a hidden tab
(`queries.ts:690-708`). Two of them have no exit other than the terminal state they are
waiting for:

```ts
refetchInterval: (query) => {
  const status = query.state.data?.status;
  return status && isTerminal(status) ? false : 900;
}
//  queries.ts:1146-1149 — useJob
```

Phase 3's B9 says there is no stale-job reaper. A job that dies without reaching `failed` is
polled every 900 ms for as long as the tab is visible. `useScan` is the same shape: `2000` ms
for as long as any detection's outcome stays `pending` (`:854-862`), and a written answer
whose grader job died stays pending forever. A laptop left open on a review screen over a
weekend is 200 000 requests.

Everything else about these polls is right: they stop on terminal, they stop on unmount, they
pause on blur. What is missing is a maximum duration and a widening interval.

**Fix:** count attempts in the interval callback and widen — 900 ms for the first thirty
seconds, then 3 s, then 10 s — with a hard stop and a "this is taking longer than expected"
state after, say, ten minutes. The teacher needs the ceiling more than the laptop does: a
poll that never gives up is a screen that never admits something is wrong.

---

#### G11 · Nothing is memoised, and the review screen re-renders whole

`grep -rn "memo("` across `apps/web/src` and `packages/ui/src` returns nothing. On most
screens that is the right call — a matrix of 24 × 8 static cells does not need it. On the
review screen it is load-bearing:

```tsx
{visiblePages.map((page) => (
  <PageCard
    key={page.id}
    …
    selected={selected}
    registerRow={(id, el) => { … }}
    onCorrect={(detectionId, body) => correct.mutate({ detectionId, body })}
//  scans/[scanId]/page.tsx:500-514
```

`selected` is passed to every card, so one `setSelected` — one press of `N`, one click on a
bubble — re-renders all thirty `PageCard`s, each of which rebuilds its `ScanReviewOverlay`
with roughly thirty-two absolutely-positioned `<button>` elements. That is ~1 000 buttons plus
~240 detection rows per keystroke. `visiblePages` is memoised so the array is stable, but the
cards are not, and `registerRow` and `onCorrect` are fresh closures on every render, so
memoising the card without also stabilising those two would achieve nothing.

The ref callback has its own cost: a new function identity means React detaches and reattaches
every `<li ref>` on every render, calling `registerRow(id, null)` then `registerRow(id, el)`
— ~480 Map operations per keystroke, which is harmless in itself and is a clear signal that
nobody has looked at this path with a profiler.

`Matrix` has a milder version: `onFocus: () => setCursor(…)` re-renders the whole grid on
every arrow press (`Matrix.tsx:213`).

I am not claiming this is perceptible — see §12, this wants a measurement, not an assertion.
I am claiming that walking a thirty-sheet queue with `N` is the product's densest interaction
and no one has checked what a keystroke costs.

**Fix:** `selected` should not be a prop on all thirty cards. Either lift the comparison into
each card via context, or pass `selectedOnThisPage` computed per page so a card whose page
holds neither the old nor the new selection re-renders to the same output. Then `memo` the
card, with `registerRow` and `onCorrect` wrapped in `useCallback`.

---

#### G12 · The default review view is page order, including everything settled

Phase 4 read this as "sorts the least-confident item to the top". Read precisely, it sorts
*within* a page:

```tsx
const pages = useMemo(() =>
  (scan.data?.pages ?? []).map((page) => ({
    ...page,
    detections: [...page.detections].sort((a, b) => queueRank(a) - queueRank(b)),
  })), [scan.data]);
//  scans/[scanId]/page.tsx:120-127
```

Pages themselves keep their order, and `queue` is `visiblePages.flatMap(…)` (`:193-196`), so
`N` walks page 1's uncertain items, then page 2's, and so on. The outcome filter starts empty
— `useState(() => new Set<FilterOutcome>())` (`:130-132`) — so the first thing a teacher sees
on a clean pile is copy 1's eight settled items, correctly read, at the top of a thirty-card
column.

This is defensible and it is not what the brief asks for. The sorting *is* right where it
matters (`queueRank`'s comment on why confidence alone is not monotonic across outcomes is
exactly correct, `:835-845`), the filter with live counts is the tool
(`:436-453`), and `itemsToCheck` states the number up front. What is missing is that the
filter is off by default, so a teacher who does not discover the checkboxes reviews thirty
pages of mostly-settled work by scrolling.

**Fix:** default `outcomeFilter` to `{low_confidence, multiple}` when the pile has any, with
the clear-filter button already beside it and a count of what is hidden. The queue follows the
filter by design (`:191-192`), so `N` keeps working unchanged.

---

#### G13 · The images are lazy now and still reserve no space

F23 is fixed: `loading="lazy"` is on the registered page (`ScanReviewOverlay.tsx:140`, with a
comment about the twenty-ninth page and a school connection) and on every answer-box crop
(`OpenAnswerCard.tsx:103`). Neither carries intrinsic dimensions:

```tsx
<img src={imageSrc} alt={imageAlt} loading="lazy"
     className="block h-auto w-full select-none" draggable={false} />
```

`h-auto w-full` with no `width`/`height` and no `aspect-ratio` box means the element has zero
height until the image decodes, then jumps to ~1.41 × its width. In a single scrolling column
of thirty cards, every image that resolves pushes everything below it down. The interaction
that suffers is the one this screen exists for: the teacher is reading item 4 of copy 12 with
a finger on *Juste* when copy 11's page finishes decoding above it.

The A4 aspect ratio is a constant the app already knows — `SHEET_LAYOUT.pageWMm` and
`pageHMm` are imported in the same file (`scans/[scanId]/page.tsx:27,67-72`).

**Fix:** wrap the `img` in a box with `aspect-ratio: 210 / 297` from the generated layout, or
pass `width`/`height` through as props. The crop's ratio is not constant, but a reserved
minimum height from `answer_box_lines` would do the same job.

---

#### G14 · One green means two things on the same card

The colour discipline is otherwise strong and mechanically enforced: `stylelint` on CSS plus a
grep over TS/TSX, and the only hits outside the exemptions are in `mock/fixtures.ts`, which is
named in the CI exclusion with its reason (`ci.yml:152-172`). No colour literal carries
meaning anywhere in the app. The five mastery bands are the shipped tokens verbatim including
the calibrated opacities and the constant-luminance glyph colours (`tokens.css:84-108`), and
`-ink` has its own derivation with the contrast reasoning written out (`:112-125`). Two
conflicts survive that, and both are semantic rather than mechanical:

**Green, on the review screen, in two senses at once.** `ScanReviewOverlay` paints a mark
`detected: 'border-success-500 bg-success-100/50 text-success-600'` with a check glyph
(`:75,82`) — meaning *the pipeline is confident it read this bubble*. Nine inches to the right,
in the same card, the item list paints the correct option
`text-success-600` with the words *"C'est la réponse"* (`scans/[scanId]/page.tsx:766-768`) —
meaning *this is the right answer*. A teacher glancing at a page covered in green checks reads
"all correct". What it says is "all read". The glyph is a check in one and the word is present
in the other, so neither is colour-alone; they simply mean different things in the same green.

**The mastery `fading` ink for "incorrect".** `AttemptList` colours a wrong attempt
`border-[var(--c-mastery-fading)] bg-[var(--c-mastery-fading-tint)]
text-[var(--c-mastery-fading-ink)]` (`:71`). `fading` is the band that means *decayed* — the
whole point of the model is that a band fades with time, not with error. In `CellDrillDown`
both appear together: a `MasteryMeter` showing the band above a list whose incorrect rows are
the same red. A teacher reading that panel cannot tell from colour whether the red is "she got
these wrong" or "this has gone stale".

**Fix:** give the overlay's confident-read state a neutral or informational treatment and
reserve green for correctness, or accept the overload and label the overlay's legend
explicitly ("lu", not "juste"). For `AttemptList`, use the state families (`success`/`danger`)
for correctness and leave the mastery ramp to mastery — it is a calibrated encoding of one
specific quantity and borrowing it for another is what makes the two unreadable side by side.

---

#### G15 · The plural lineage is displayed and still cannot be produced

Phase 4's F7 is fixed at the root: `lib/api/types.ts` is 124 lines that re-export
`@alppy/shared/api-types`, generated from `alppy/schemas` and diffed in CI, with the four
name drifts it found recorded in the header comment. `contract.test.ts` exists now and checks
every path in `endpoints.ts` against the generated route list, with an honest note on why it
checks the address and not the method.

The *consequence* Phase 4 found is still live. `AdaptiveBatchRequest` now carries both fields:

```ts
  source_sheet_id?: Uuid | null;
  source_sheet_ids?: Uuid[] | null;
//  api-types.generated.ts:44-45
```

and the builder still sends only the singular (`adaptive/page.tsx:575`), while the sheet detail
screen renders the plural with a **Principal** chip on entry 0 (`sheets/[sheetId]/page.tsx:210-222`).
So the app displays a capability it cannot produce, and the only reason nothing looks broken
is the server's back-compatibility for "an older client".

**Fix:** the adaptive screen already knows one source sheet; the honest version is a
multi-select on **Fiche de référence** feeding `source_sheet_ids` with the principal first.
The cheap version is to send `source_sheet_ids: [sourceSheetId]` and stop pretending there is
a second field.

---

#### G16 · Creating a class is two writes and one of them can be orphaned

```tsx
const created = await createClass.mutateAsync({ code, label });
if (parsed.length > 0) {
  await addStudents.mutateAsync({ classId: created.id, body: { students: parsed } });
}
router.push(`/classes/${created.id}`);
//  classes/new/page.tsx:56-73
```

If the roster post fails — a 422 on a name, a network drop, a 429 — the class exists, the
pasted roster is in a textarea, and the teacher is on the form with an error line. Pressing
**Créer** again re-posts the class and gets a conflict: *"Cette action n'est plus possible
dans l'état actuel."* The roster is never saved, and nothing on the screen explains that half
of the work landed.

The same two-step exists in the `/roster` screen, but there the class already exists so a
failure is recoverable by pressing again (`roster/page.tsx:58-73`).

**Fix:** on a successful class creation, navigate to `/classes/{id}/roster` with the pasted
text carried over, so the second write is retried on a screen where retrying is correct.
Failing that, hold `created.id` in state and make the second press skip the class creation.

---

#### G17 · A failed subset can only be retried by re-proposing everyone

The failures panel is genuinely good: per-pupil by UID, reason-specific, with `truncated`
given its own sentence because *"the cause is a configured limit"*, and a closing line saying
the rest exported normally (`adaptive/page.tsx:874-889`, `messages/fr.json`
`adaptive.failureHint`). It answers the brief's "18 of 24 succeeded" question clearly.

It offers no action. The only retry resets the job and re-proposes the whole class
(`:776-786`), which is twenty-four more provider calls to rebuild twenty-three plans that
already exist. `useRegenerateAdaptive` regenerates *one exercise* in place and is wired to
every item card (`:501-515`), so the machinery for a narrow retry exists one level down; what
is missing is a per-pupil regenerate on the failure line.

**Fix:** a **Réessayer pour cet élève** button per failure row. The API needs a
propose-for-one-student path, or `student_ids` on `/adaptive/propose` — which the request type
already has (`AdaptiveProposeRequest.student_ids`, sent as `[]` at `:715`).

---

#### G18 · The correlation id is parsed and never shown

`parseError` reads `body.error.request_id` and hands it to `ApiError`
(`client.ts:85-97`); `ApiError.requestId` has no reader anywhere in the app. So when a
teacher writes "it failed at about 10:20", there is nothing to correlate it with. The one id
that does reach a screen is Next's own `error.digest`, and only in `global-error.tsx:54-58` —
the boundary for a failure to mount the app at all, which is the least likely of the two to
be hit.

**Fix:** render `requestId` under the `ErrorState` description, in mono, with a line saying it
identifies the incident. `errors.generic` would grow one key. The teacher does not need to
understand it; they need to be able to read it out.

---

#### G19 · Row selection is a click handler on a `div`

`Panel` spreads its props onto a `div` (`Panel.tsx:17-25`), and both detection cards pass
`onClick`:

```tsx
<Panel sunken={needsAHuman(detection)} onClick={onSelect} …>   // scans/[scanId]/page.tsx:737-741
<Panel sunken={…} onClick={onSelect} … data-open-answer="">    // OpenAnswerCard.tsx:71-75
```

No `role`, no `tabIndex`, no key handler. The sweep for `<div onClick>` comes back empty
precisely because the pattern is hidden behind a component.

The mitigation is real: the overlay's boxes are proper `<button>`s that select the same item
(`ScanReviewOverlay.tsx:151-158`), `N` selects and focuses (`scans/[scanId]/page.tsx:209-218`),
and the actual *action* — the `SegmentedControl` — is keyboard-operable and takes the 44 px
floor. So nothing is unreachable. But a keyboard user cannot select a row by focusing it, and
the click target that a mouse user has is invisible to assistive tech.

**Fix:** either drop the `onClick` (selection already has two better paths) or make the card a
real control. Dropping it is the better change: selection is a *view* concern and the card is
already full of controls, so a click anywhere on it selecting something is as likely to
surprise as to help.

---

#### G20 · Validation fires per keystroke and is never announced

```tsx
const codeValid = classCodeRe().test(code.trim());        // classes/new/page.tsx:43
…
error={code !== '' && !codeValid ? t('codeInvalid') : undefined}   // :88-90
```

`classCodeRe` comes from the generated contract now, which is F21's fix and the right one. The
timing is not: typing `7B` shows *"Code invalide"* after the `7` and clears it after the `B`.
Every hand-rolled form in the app has this shape — the error is a derived boolean evaluated on
render.

Second half: `Field` wires `aria-describedby` and `aria-invalid` correctly and renders the
message with a warning glyph, never colour alone (`Field.tsx:62-66,104-107`) — but the `<p>`
has no `role="alert"` and no live region. A message that appears while focus is in the field
is not announced; a message that appears on submit is announced only if focus happens to move
there, and no form moves focus to its first invalid field.

**Fix:** validate on blur and on submit, keep validating on change only *after* the field has
been blurred once (the conventional pattern, and the one that stops the flicker). Add
`role="alert"` to `Field`'s error paragraph — one attribute, in one place, for every form in
the product.

---

#### G21 · The scroll wheel changes a focused number field

`grep -rn "onWheel"` returns nothing. Both `type="number"` inputs — the custom barème
(`SheetComposer.tsx:393`) and the custom answer-box height (`:589`) — sit inside a long
scrolling item list. A teacher who has just set the barème and scrolls the list with the
trackpad, with focus still in the field, changes the value by `step` per notch: 0.25 points
per tick on the barème.

The barème is printed on the paper and carried into every score, so the value is not cosmetic;
and the interaction is one a teacher performs constantly on this screen.

**Fix:** `onWheel={(e) => e.currentTarget.blur()}` on the shared `Input` when
`type === 'number'`, which fixes every present and future number field at once.

---

#### G22 · One boundary, for thirty pages

`app/[locale]/error.tsx` is a real improvement over Phase 4 and is written for exactly the
right reason — the comment even names the live candidate: *"`DetectionRow` indexes
`letters[i]` and `detection.options.map` — a payload from a partially migrated API throws
inside the render, on the densest screen in the product"* (`:14-17`). It renders inside the
locale layout so the shell and the navigation survive, and there is a unit test asserting it
never puts the exception's own text on screen (`error.test.tsx:39`).

It is the *only* boundary. The brief asks for one scoped around scan review specifically, and
the consequence of having it at the segment level is that the throw the comment predicts takes
the whole pile: thirty pages, the filters, the confirm button, replaced by one generic error
with a `reset()` that will throw again on the same payload. A teacher twenty sheets into a
batch has nothing to go back to except the corrections already saved — which is the good news
— but no way to finish the pile.

**Fix:** a small boundary around each `PageCard`, rendering that card as "cette page n'a pas
pu s'afficher" with its page index and a discard control, so one malformed detection costs one
copy instead of the batch. React has no per-component boundary primitive without a class
component or a dependency; a fifteen-line `ErrorBoundary` in `packages/ui` would serve both
this and the generation screen.

---

#### G23 · `printed_at` and `updateSheet` are in the contract and used by nothing

`SheetOut.printed_at` is generated into the client types (`api-types.generated.ts:952`) and
appears on no screen. `/sheets` groups by `rendered_at` into *drafts* and *ready*
(`sheets/page.tsx:87-88`); "already printed" is not a third group and not a badge. So a
teacher with two sheets on the same theme cannot tell which one went to the photocopier last
Tuesday — which is the question `SHEET_PRINTED` was recorded to answer.

`endpoints.ts:302` exports `updateSheet` and nothing calls it, which is the other half: a
sheet's title cannot be corrected, and a sheet cannot be edited at all from the UI. That
absence is what closes Phase 3's B7 from the client side (no edit means no re-render means no
placement rewrite under printed paper), so I am not asking for the edit path — I am recording
that the product has no way to fix a typo on a document it prints, and that a dead export is
how you find that out.

**Fix:** a **Imprimée le …** line in the sheet header and a chip on the list row, from a field
the client already receives. The edit path is a product decision, not a defect.

---

### Low

**G24 · The review screen never names the pupil.** `PageCard`'s heading is
`t('identifiedAs', { uid: page.detected_uid })` or a red *"Non identifiée"*
(`scans/[scanId]/page.tsx:563-569`). The name appears only in the manual-assignment select,
and only when names are not hidden (`:647`). The brief asks whether the UI shows *which*
student prominently enough to catch a misattribution before finalising. It shows the UID,
which is what is printed on the page — so the cross-check against the photograph in the
overlay is possible, and that is the check that matters for a mis-decoded bubble grid. What it
forecloses is the human check: a teacher who would recognise "that's Léa's handwriting, not
7B_15's" is never given the name to be surprised by. Outside projector mode, showing
`7B_15 · Léa Berthod` in that heading costs nothing and adds the one check a machine cannot
make. I am ranking it Low because the UID comparison is the load-bearing one and it works.

**G25 · Both keyboard shortcuts are screen-reader quick-nav keys.** `n`
(`scans/[scanId]/page.tsx:225`) and `Shift+D` (`AppShell.tsx:115`) are both intercepted by
NVDA and JAWS in browse mode — `n` skips past a block of links, `d` moves between landmarks.
A screen-reader user cannot reach either. Neither shortcut is the *only* path to its function
(the **Suivant à vérifier** button carries a `KeyboardHint`, and the settings screen carries
the discreet toggle), so nothing is unreachable; the shortcuts are simply unavailable to the
users who would benefit most. The `Shift+D` choice is well reasoned in its comment for the
browser-conflict question, and this is the axis it did not consider.

**G26 · A 404 reads as an outage.** Every detail screen's error branch renders
`errors.generic` — *"Réessayez"* — including for a 404, which is what the API answers for a
class the teacher no longer teaches (by design, so existence is not revealed). `ApiError` has
the status and the catalogue has the sentence: `errors.code.not_found` reads *"Cet élément
n'existe pas ou n'est plus accessible."* Switching on `error.status === 404` to render the
`not-found` treatment instead of a retry button is a small, consistent improvement, and the
deep-link privacy property is already correct.

**G27 · `RevealNames` is on three screens of seven.** It appears on `/classes/[classId]`,
`/classes/[classId]/students` and `/results`. The pupil profile, the roster editor, the
per-competence drill and the scan review all hide names with no in-page way to show them —
the teacher must use `Shift+D`, which turns the mode *off* globally and persists that
(`AppShell.tsx:121-128`), which is the opposite of what the temporary reveal was designed for.

**G28 · `ScopeProvider` reads storage during render.** `const stored = readStored();`
(`scope.tsx:144`) is a `localStorage.getItem` plus `JSON.parse` on every render of the
provider that wraps the entire app. It is not a hydration bug in practice — on both server and
first client render the class list is empty, so both resolve to `null` — but it is a
render-phase side effect in the one component that re-renders on every navigation.

**G29 · Two keys that are not identities.** `key={group.label || groupIndex}`
(`adaptive/page.tsx:1054`) keys a series by a label the server composes; two series on the
same competency differ only by a number today, so it holds, and it holds by accident.
`key={name}` on the in-flight upload list (`scans/new/page.tsx:157`) collides if two selected
files share a filename. Neither list reorders, so neither is currently a bug.

**G30 · The roster's em dash.** `hideNames ? '—' : …` (`roster/page.tsx:146`), reasoned in the
comment as avoiding a second copy of the UID that is already in the row. Every other screen
substitutes the UID. The inconsistency is small; the cost is that the roster editor in
projector mode is a column of dashes, and it is the screen where the teacher needs to find a
specific pupil to fix their name.

**G31 · Fixture mode is self-serve.** `isMockEnabled()` returns true for
`localStorage['alppy.mock'] === '1'` (`client.ts:42-50`), so anyone can flip the whole app —
and the `_gallery` route whose comment says it *"has no business existing in a build a teacher
can reach"* (`%5Fgallery/page.tsx:19,74-76`) — into fixture mode in production. No real data
is exposed (the fixtures are invented pupils), so this is a footgun rather than a disclosure:
a teacher who trips it sees a plausible app full of children who do not exist.

**G32 · `lib/format.ts` has no test.** Every date, percentage, number and file size in the
product passes through it, it hardcodes `Europe/Zurich`, and it is the file where the Swiss
separator decision lives (§10). `points.test.ts` tests the arithmetic above it and nothing
tests the formatting.

---

## 4 · Work-loss and misgrading risks

The paths that can lose a teacher's in-progress corrections, submit a wrong grade, or attach
work to the wrong student. These outrank everything above.

### Can a wrong grade be submitted?

**Yes, by one path: G1.** A correction whose mutation fails is not reported, and the control
reverts to the machine's reading. The teacher believes they overruled the model; the model's
verdict is what gets confirmed. The window is any non-network failure — a 409 if a colleague
confirmed the pile in between, a 500, a 422 — and the teacher's next keystroke moves them
away from the row. This is the one Critical-shaped risk in the build, held below Critical only
because the offline case (the commonest) does raise a visible bar.

**No, by every other path.** The reasons are worth stating because they are all deliberate:

- **There are no optimistic updates anywhere.** `grep` for `onMutate` and for `setQueryData`
  outside `onSuccess` returns nothing. Every mutation waits for the server, and
  `useApproveAdaptive` explicitly takes the server's returned id list rather than assuming
  (`adaptive/page.tsx:856-857`). So the brief's §19 — "any optimistic update on a grade, an
  override or a finalisation is a High finding" — has nothing to bite on. This is the single
  best decision in the layer.
- **The mark and the mastery signal stay apart.** `/results` reads points, `/classes/{id}`
  reads bands, and the screens' own docstrings say why they are different screens
  (`results/page.tsx:31-42`).
- **An ungraded copy is a dash, never a zero.** `lib/points.ts` exists solely to hold that
  rule, `pointsRatio` returns `null` rather than `0` or `NaN`, `aggregatePoints` refuses to
  let an unmarked sheet enlarge the denominator, and eleven unit tests pin all of it
  (`points.test.ts`).
- **Confirmation is gated on pending verdicts, counted over unfiltered pages.**
  `disabled={processing || reading > 0}` with `reading` computed from `pages`, not
  `visiblePages`, and a comment saying why: *"a filter is a way of looking, never a way of
  signing off"* (`scans/[scanId]/page.tsx:197-206,352`).
- **The barème cannot reach the mastery model.** That is enforced server-side (CLAUDE.md,
  `mastery_service`), and the client does not have a path to try.

### Can in-progress work be lost?

| path | what happens | verdict |
|---|---|---|
| **30 corrections, tab closed / laptop shut** | Each correction was its own mutation and landed as it was made. Nothing is held in memory. | **Safe** |
| **30 corrections, session expires mid-batch** | The 401 reaches `noteUnauthorized`, which calls the handler `Providers` registered: clear the cache, `router.replace('/login?from=…')` (`client.ts:143-146`, `Providers.tsx:46-58`). The login screen honours `from` and strips the locale (`login/page.tsx:41-46`). The corrections made before the expiry are on the server; the one in flight is lost, and G1 means it is lost silently. Six unit tests cover the 401 path including the two probes that must not trigger it (`client.test.ts`). | **Safe, except the in-flight one** |
| **30 corrections, connection drops** | The offline bar appears and stays until a request succeeds. Corrections already sent are safe and the bar's own sentence says so. New presses fail silently (G1). | **Partly signalled** |
| **Sheet builder, 18 exercises ticked, tab closed** | `sessionStorage` keyed on `class:subject`, restored after mount, cleared on successful creation, plus a `beforeunload` guard while the draft is non-empty (`useDraftSheet.ts:188-258`). A stored shape from an older build is *dropped* rather than half-rendered, with the reason given: *"a half-understood draft is worse than an empty one, because the teacher would print it."* | **Safe** |
| **Adaptive run, laptop closed between Proposer and the result** | The job id is in the URL, written with `router.replace` (`adaptive/page.tsx:144-156`); moves, sheet id and export job id are in `sessionStorage` keyed by job id (`:231-242`); the empty state lists the last five runs for this class (`:1274-1305`), and the wait's own help text promises it: *"Vous pouvez fermer l'onglet : la proposition reste accessible."* Four e2e tests cover the reload, a fresh page at the same address, and finding the run from the empty state. `approvedIds` is deliberately *not* restored, with a written argument for why restoring a server fact from a tab's storage would open the export gate on nobody's authority. | **Safe; the approval gate re-arms** |
| **30 photographs, connection drops at 80 %** | Everything is discarded; the file selection is gone; the teacher starts again. No queue, no resume, no retry (G5). | **Lost** |
| **Class creation, roster post fails** | The class exists; the pasted roster is lost; resubmitting conflicts (G16). | **Lost** |
| **Any screen, a component throws** | One boundary at the locale segment: the whole screen is replaced, corrections already saved survive, the rest of the pile is unreachable until the payload changes (G22). | **Degraded** |

### Can work be attached to the wrong student?

The pipeline's own guards are upstream (Phase 1 L1, Phase 3 B4: the identity code carries no
sheet, no print run, no page number, no year). The UI is the last line of defence and it does
three things right and one thing incompletely:

- A page whose code did not decode is loud: a red *"Non identifiée"* heading plus a
  `danger` badge, and it is excluded from confirmation server-side
  (`scan_pages_unassigned` has a French sentence).
- A page whose UID belongs to another class gets a `warn` badge and an explanatory line
  (`:571,586-588`).
- Manual assignment offers only the sheet's own class — `useScanStudents` is scoped to the
  scan, *"the sheet's class, nobody else"* (`queries.ts:866-873`).
- **But an attributed page is labelled by UID alone (G24),** so the check available to the
  teacher is "does the UID on the screen match the UID printed on the photograph beside it",
  which the overlay makes possible. The check that is *not* available is the one only a
  teacher can make: recognising that the handwriting is not that child's.

---

## 5 · Student-dignity and disclosure risks

**What is right, and it is most of it.**

- **Projector mode is built, and built as a mode rather than a screen option.** §3 G7 covers
  the one hole. Everything else about it is correct: applied before paint so there is no flash
  of names, observed via `MutationObserver` so a toggle reaches mounted screens, reveal held
  in React state that a reload cannot restore, `Shift+D` from anywhere with a live-region
  announcement, and a warning line while names are showing — *"Les noms sont visibles. Ils
  seront masqués à nouveau en quittant cette page."*
- **No student name ever reaches a model provider, and the adaptive screen never loads a
  roster.** The comment at `adaptive/page.tsx:276-282` explains that even reading
  `students.length` would put names in the page's cache for no reason, so it reads
  `ClassOut.student_count` instead. Every pupil on that screen is a UID: the series chips
  (`:1072`), the per-student plans (`:1137-1139`), the failure lines (`:1233-1257`).
- **No student data in any URL.** Every route parameter and query parameter is a UUID or a
  filter enum. `Referrer-Policy: strict-origin-when-cross-origin` is set with the reason named
  — the student UUID in the path would otherwise travel to the object store in `Referer` on
  every crop fetch (`lib/csp.ts`, `csp.test.ts:80-88`).
- **No analytics, no error tracker, no session replay.** `grep -rni "sentry\|posthog\|gtag\|
  datadog\|logrocket\|analytics"` over `apps/web/src` and the package manifest returns
  nothing. The brief's §85 — no student data in client logs, analytics or error-reporting
  payloads, no handwriting in a breadcrumb — is satisfied by absence, which is the strongest
  form. The one deliberate `console.error` is in `error.tsx:42` and logs `digest` and the
  error, not application state.
- **`localStorage` holds four keys and none identifies a child:** `alppy.scope`
  (`{classId, subjectId}`), `alppy.display`, `alppy.mock`, `alppy.adaptive.*` (job ids and uid
  → series-index moves). `sessionStorage` holds the sheet draft, which contains exercise text
  and no pupil. Nothing authenticating: the session is an HttpOnly cookie and
  `credentials: 'include'` is the only mechanism (`client.ts:190-191`).
- **Logout clears everything.** `useLogout` calls `client.clear()` (`queries.ts:213-216`);
  `useSwitchSchool` clears the cache *and* drops `alppy.scope`, with the reason: *"every
  cached id in the client belongs to the school we just left"* (`:523-544`). The 401 handler
  clears the cache before redirecting, and says why — *"it holds another teacher's session's
  worth of rosters and results"* (`Providers.tsx:42-48`). What survives a logout is
  `alppy.display` (a preference) and the sheet draft in `sessionStorage` (exercise text, no
  pupil). That is the right residue.
- **`DetectionOut.vision_model` crosses the wire (Phase 2 L2) and is rendered nowhere.** An
  `AiBadge` reading *"Lu par l'IA"* stands in its place, which is the right amount of
  provenance for a teacher.

**What remains.**

| risk | where | severity |
|---|---|---|
| The matrix drill-down names the pupil while the matrix behind it shows UIDs | `CellDrillDown.tsx:65` | **High** (G7) |
| Four of seven identity-hiding screens have no in-page reveal, so the only way back is the global toggle | G27 | Low |
| Children's handwriting is fetched from 900-second presigned URLs; lazy loading now limits it to what is on screen, which is the frontend's whole contribution | `OpenAnswerCard.tsx:103`, Phase 3 L3 | Low |
| Series placement: `groupCountMany` says *"les élèves ayant la même lacune principale sont réunis"*, and a split of an over-large bucket orders by severity, so two pupils whose series name the same competency can read their relative placement off the number | `messages/fr.json`, Phase 4 §4 | Low, unchanged |
| The printed feedback page still carries the series label | `alppy/sheets/html.py:670` (Phase 4 F29) | Low, unchanged |

---

## 6 · Print fidelity verdict

**The built print path satisfies the coordinate assumptions the grading pipeline depends on.**
This is a reversal of Phase 4 and it is earned, not narrowed.

Phase 4 listed five conditions that must hold for a written answer's grade to be trustworthy,
and said the UI guaranteed none of them. Today:

1. **The paper came from `render_sheet`, not from the browser.** Guaranteed by construction.
   `printReadiness` returns `ready` only when `sheet.rendered_at !== null` *and*
   `sheet.blank_pdf_url` — "both, not either", with the reasoning that if the two ever stop
   moving together, refusing is the safe half (`lib/print.ts:68-73`). In `needs_render` the
   primary button becomes **Générer le PDF**; there is no second button that prints anything
   else, the iframe is `sandbox="allow-same-origin"` with `allow-modals` deliberately removed,
   and the comment records that *"nothing prints the frame any more"*
   (`sheets/[sheetId]/page.tsx:440-444`). `markPrinted` fires only from the two links that
   hand the teacher the rendered PDF (`:163,288`). Eight unit tests pin the gate
   (`print.test.ts`) and four e2e tests pin the screen, including *"the preview is an aperçu:
   it is never what gets printed"* (`e2e/sheet-print.spec.ts`).
2. **No re-render between that render and the photograph.** There is no edit path in the UI
   (`updateSheet` has no caller), so `rendered_at` cannot be invalidated from the client, and
   a sheet that is `ready` stays ready. This is closure by absence rather than by a guard —
   see G23 — but it is closure.
3. **The measuring environment's font metrics equal the printing environment's.** Fixed
   properly. `scripts/embed-fonts.mjs` writes `packages/ui/src/design/fonts.css`: four
   `@font-face` rules, Latin subset, normal weight only, woff2 as `data:` URIs, 248 KB
   committed because *"The API's container image has no `node_modules`"*. The print template
   inlines it **first**, with the reason given in the template itself
   (`sheet.html.j2:9,23-24`), and `html.py:59-63` orders the four sheets `fonts, tokens, base,
   print` because *"the faces have to be declared before anything asks for them"*. So the
   PDF, the preview iframe and the answer key all resolve `--font-sans` to the same file. CI
   re-runs the generator and fails if the committed file changes, the way
   `export-layout.py` already guarded the geometry. And the script's own docstring states the
   measurement argument verbatim: a statement that wraps to four lines in DejaVu and three in
   SF Pro *"moves its box by one line pitch (8 mm) — far enough to crop the wrong pixels, not
   far enough for `_check_box_inside_statement_region` to raise."*
4. **No printer scale or margin override.** Now a PDF rather than a browser print, so the
   teacher's print dialog acts on a fixed-geometry document. A uniform scale still cancels
   through fiducial-relative registration.
5. **All four fiducials visible in the photograph.** Checked by the pipeline and reported to
   the teacher, now with a route back into the pile: the unregistered page carries a
   `FileDrop` whose retake supersedes the failed photograph in the same request, disabled while
   a run is in flight with a sentence saying why (`scans/[scanId]/page.tsx:597-628`,
   `endpoints.ts:332-350`). Phase 4's F11 — "no route back into its pile" — is closed, and two
   e2e tests assert the retake goes to this scan rather than creating a second one.

**The coordinate source of truth is still shared, not recomputed.** `layout.py` →
`export-layout.py` → `layout.generated.ts`, regenerated and diffed in CI. The review overlay
converts the detector's frame-relative coordinates through `SHEET_LAYOUT.frame`, with the trap
spelled out in both places — *"the frame is not the page: on A4 it runs 18–192 mm across a
210 mm sheet"* (`scans/[scanId]/page.tsx:60-72`, `ScanReviewOverlay.tsx:8-22`, which states
"There is no default. The one thing this component must never do is guess"). Nothing in the
client re-derives a millimetre.

**The preview is the print document**, not an approximation: `GET /sheets/{id}/preview`
returns the same markup the renderer consumes, and the client puts it in an iframe rather than
re-implementing it. Phase 4's "assumption 4" — a preview blanked by `frame-src` in the default
compose stack — is fixed twice over: the API origin is in `frame-src` (`csp.test.ts:60-70`),
and a violation event, an 8-second load timeout and an empty-body check each produce a
sentence instead of blank paper (`sheets/[sheetId]/page.tsx:377-459`).

**Math rendering:** there is still no renderer of any kind in the repo, so the
height-variance failure mode the brief asks about does not exist. With the fonts pinned, the
`Nunito` metrics are now the only thing that can move a line, and they are byte-identical
across the three renderers.

**Identity code:** unchanged and by design — a checksummed pre-filled bubble grid plus the UID
printed as text beside it and in every page footer, rather than a QR. The human-readable
fallback the brief asks for is the printed UID, and it is what the review screen labels a page
with.

**The one residual, and it is upstream:** the footer carries `layout v1` and no placement
generation id, so a scanned page cannot be checked against the placements it was *actually*
printed with — only against the ones that exist now. With no client edit path that gap cannot
be opened from here, but it is the thing that would make the chain provable rather than
merely consistent.

---

## 7 · Built / partial / stub / missing

Against the flows Phase 4 enumerated in its §9. "Renders but does nothing useful" is `stub`.

| Flow | Phase 4 | Now | Notes |
|---|---|---|---|
| Create establishment | Neither | **Built** | `POST /schools` is called from `SchoolSettings`, with a canton `Select`; it deliberately does not switch the session |
| Create class | Built | **Built** | Code validated from the generated contract; partial-failure gap (G16) |
| Enter students (paste) | Built | **Built** | Forgiving parser, live count, single-pupil path added |
| Import students (CSV / cantonal) | Neither | **Missing** | No file import, no format named anywhere |
| Form teaching groups | Neither | **Missing** | The concept still has no object. The *vocabulary* half of F9 is fixed: *groupe* is free now (the adaptive cohorts are *séries*) |
| **School year / as-of** | Neither | **Stub** | The API serves it, `endpoints.ts` types it, nothing above passes it (G3) |
| Author an assignment (document path) | Built | **Built** | Theme root, server-side filtering and paging, counted *Sans thème* row |
| Author an assignment (retrieval path) | Built | **Built** | `ProposeTab`, intent + ranked proposals + provenance |
| Choose objectives | Built | **Built** | — |
| Difficulty spread | Partial | **Partial** | A filter on the picker; `items_per_student` and `n_groups` on the adaptive path; no spread control |
| Barème | Built | **Partial** | Presets work; the custom decimal field is broken (G2) |
| Adaptive generation as a job | Built, gaps | **Built** | F13 closed: `ProgressRing` with a percentage, `Spinner` at zero, queued vs running wording. No cancel (no API route) |
| Partial failure display | Built | **Built** | Per-pupil, reason-specific, `truncated` on its own line |
| Retry the failed subset only | Neither | **Missing** | G17 |
| Navigate away mid-run | Neither | **Built** | URL job id + `sessionStorage` + recent-runs list + 4 e2e tests |
| Print | Built, unsound | **Built** | One door, gated on `rendered_at`; fonts embedded (§6) |
| Print preview | Built (blank in compose) | **Built** | `frame-src` fixed, plus three independent failure detections |
| Capture — phone camera | Built | **Built** | `capture="environment"`, hidden from `md` up |
| Capture — scanner PDF | Built | **Built** | Same control |
| Batch upload UX | Partial | **Partial** | Files now named while sending; still one atomic request, no size check, no downscale (G5) |
| Per-page upload progress | Neither | **Missing** | Processing progress is real; upload progress is not measured |
| Upload resumability | Neither | **Missing** | G5 |
| 3 of 30 pages fail registration | Partial | **Built** | Per-page retake into the same pile, superseding the failed photograph |
| Scan review side-by-side | Built | **Built** | Sticky overlay at `lg`+, lazy images |
| Keyboard through 30 sheets | Built | **Partial** | `N` walks the queue; no previous, no accept, no flag; row selection not keyboard-reachable (G19, G25) |
| Low confidence surfaced first | Built | **Partial** | Within a page, yes; across the pile it is page order and the filter is off by default (G12) |
| Override in one action | Built | **Built** | One `SegmentedControl` press, 44 px, block |
| Machine vs teacher visibly distinct | Built | **Built** | `corrected` badge + edit glyph + info tint + the machine's reading printed beside the override, before and after |
| Correction is saved and reported | — | **Partial** | Saved; a failure is not reported (G1) |
| Progression view | Built | **Built** | Matrix → drill-down → profile → competency attempts |
| Point-in-time vs current state | Neither | **Stub** | G3 |
| Destructive actions confirmed | Partial | **Built** | `ConfirmDestructive` on evidence-destroying actions; two-click armed `Rouvrir` naming the pupil count; discard-with-undo on a generated exercise, flushed on unmount |
| Projector / discretion mode | Neither | **Built** | One hole (G7) |
| Connection state | Neither | **Built** | One bar, from the last request's outcome rather than `navigator.onLine` alone |
| 401 / session expiry | Neither | **Built** | One interception point, cache cleared, `?from=` honoured, 6 unit tests |
| Error boundary / 404 | Neither | **Built** | `error.tsx`, `not-found.tsx`, `global-error.tsx`, a locale catch-all, 4 e2e tests. Scoped coarsely (G22) |
| Component workbench | Neither | **Built** | `/_gallery`, gated on fixture mode (F26) |
| Offline capability | Neither | **Missing** | Not planned in any document |
| Request timeouts | — | **Missing** | G9 |
| Idempotency keys | — | **Missing** | Server-side only (G4) |
| PER *attentes fondamentales* / per-year progression | Neither | **Missing** | Propagation of Phase 1 H1–H3 |

---

## 8 · Architecture drift from Phase 4

### Phase 4's findings, one by one

**Fixed (25):** F1 (one print door), F2 (embedded fonts + CI gate), F3 (projector mode),
F4 (adaptive run recoverable), F5 (401 handling), F6 (error/not-found boundaries),
F7 (generated types + contract test), F11 (retake into the pile), F13 (propose progress),
F14 (error catalogue, now gated by `check-i18n.mjs` against the generated code list),
F15 (login switches on status), F16 (`ConceptTag` gets a real code or nothing),
F17 (one word per object; *Établissement*), F18 (armed `Rouvrir`, discard undo),
F19 (draft persistence + `beforeunload`), F20 (focus follows the route),
F21 (canton `Select`, class regex from the contract), F22 (roster's three states),
F23 (lazy images), F24 (connection bar), F25 (poll moved into the query layer),
F26 (`/_gallery`), F27 (school creation; the CSV half remains), F30/F32 (dead text and
stray markup), F31 (superseded — the inventory question stands).

**Half-fixed (2):** F12 — `job.message` is gone, five server-prose fields remain (G6).
F9 — the vocabulary collision is resolved, the missing *groupe* concept is not.

**Unchanged (5):** F8 → now G3 and materially worse, because the parameter exists.
F10 → G5. F28 (PER depth, upstream). F29 (feedback page's series label, upstream).
F31 (`docs/plan.md` §5 still the only screen inventory; 26 pages now, and it lists 11).

### Departures from the Phase 4 architecture, and whether each is an improvement

| departure | judgement |
|---|---|
| `lib/api/types.ts` went from a 1 162-line hand mirror to a 124-line re-export of generated types, keeping only what OpenAPI genuinely cannot carry (the raised error envelope, `Literal` aliases, query-string shapes, Python `@property` members) each with its reason | **Improvement**, and the header records the four drifts it found on the way |
| `packages/shared` grew from one generated file to four (`layout`, `api-types`, `api-routes`, `api-constants`), with `api-constants` feeding the i18n gate | **Improvement.** The error catalogue is now mechanically complete instead of thirteen of thirty-one |
| `everyClassTree` replaced the literal `['classTree']` invalidation with a predicate, and `query-keys.test.ts` asserts no invalidation names a namespace nothing is stored under | **Improvement**, and the right shape: the bug is now untypeable |
| The adaptive job id moved from `useState` to the URL; `moves`/`sheetId`/`jobId` to `sessionStorage` keyed by job; `approvedIds` deliberately left in memory with a written argument | **Improvement.** The refusal to restore the approval gate from a tab's storage is the better half of it |
| Polls consolidated into `refetchInterval`; the last hand-rolled `setInterval` removed | **Improvement**, with the ceiling still missing (G10) |
| Projector mode implemented as a fourth display preference on the existing `data-*` mechanism rather than a screen option | **Improvement**, and the cheapest place it could have gone |
| The sheet preview iframe kept but demoted to an aperçu, with three independent failure detections | **Improvement** |
| `endpoints.ts` grew `as_of` and `school_year_id` on eight calls and a `listSchoolYears` route, and no layer above consumes any of them | **Erosion.** A typed, commented, tested-nowhere capability is worse than an absence: it reads as done |
| `printed_at` and `updateSheet` crossed the contract with no consumer | **Erosion**, mild — the same shape as above, one field and one verb |
| `AdaptiveBatchRequest.source_sheet_ids` arrived in the types and the request still sends the singular | **Erosion**, and now visible rather than latent (G15) |
| `apiRequest` still cannot carry a header, while the API added one that four routes read | **Erosion.** The client's request layer is now narrower than the contract it serves |
| Still no form library, still no optimistic updates, still `staleTime: 30_000` with `refetchOnWindowFocus: false` | **Held**, and I would hold all three (§10) |

---

## 9 · Contract mismatches

The generated types close the structural half of this, so what remains is *behavioural*: places
where the client's handling and the API's behaviour disagree even though the shapes agree.

| # | Mismatch | Evidence |
|---|---|---|
| 1 | `Idempotency-Key` is read by four routes and cannot be sent | `api/deps.py:611-624`, `client.ts:52-64` |
| 2 | `school_year_id` (2 routes) and `as_of` (5 routes) are served, typed, and never sent | `api/v1/classes.py:54,96`, `api/v1/mastery.py:38,75,98,120`, `api/v1/reports.py:38`, `queries.ts` |
| 3 | `GET /school-years` is served and has no client caller | `api/v1/classes.py:68`, `endpoints.ts:166` |
| 4 | `AdaptiveBatchRequest.source_sheet_ids` exists; the client sends `source_sheet_id` while the UI renders the plural | `api-types.generated.ts:44-45`, `adaptive/page.tsx:575` |
| 5 | `SheetOut.printed_at` is sent and rendered nowhere | `api-types.generated.ts:952` |
| 6 | `updateSheet` (`PATCH /sheets/{id}`) is typed and never called | `endpoints.ts:302` |
| 7 | `ScanPageOut.registration_error` and `SourceOut.error`/`notice` are English prose fields the client renders verbatim, against the rule that a failure crosses as a code | `scans/[scanId]/page.tsx:596`, `sources/page.tsx:185,194` |
| 8 | `AdaptiveGenerationFailure.reason` is `string` in the contract and a four-member union in the client's local types; `failureLine` switches on a fifth value (`truncated`) that the union does not list | `api-types.generated.ts:68`, `types.ts:58-62`, `adaptive/page.tsx:1248` |

**Status codes.** Every code the API can emit now has a French sentence, and `check-i18n.mjs`
parses `API_ERROR_CODES` out of the generated constants and fails CI if one is missing — so
this can no longer drift. Checked against the brief's list:

| code | handled? |
|---|---|
| 202 Accepted | Yes — `apiRequest` reads any `ok` status; the four 202 routes return a `JobOut` or a `ScanOut` and the caller polls. `scans/new` reads `scan.job_id` and puts it in the URL |
| 409 Conflict | Yes — `conflict`, `scan_already_confirmed`, `scan_confirmed`, `scan_not_confirmed`, `branch_holds_sheets`, `teacher_still_head`, `school_last_teacher`, each with its own sentence |
| 422 Validation | Yes — `unprocessable`, `validation_error`, `sheet_not_renderable` (with the longest and most useful sentence in the catalogue) |
| 429 Rate limit | Yes, and it says how long: `valuesFor` reads `details.retry_after_s`, rounds up, and refuses to say "wait 0 seconds" (`error-message.ts:33-46`) |
| 5xx | Yes — `internal_error` ("Rien n'a été enregistré ; réessayez"), `service_unavailable`, `http_error` |
| 401 | Yes — a sentence *and* an interception point that clears the cache and redirects |
| 413 / 415 | Yes — `payload_too_large` ("Scannez en plusieurs fois"), `unsupported_media_type` |
| network failure | Yes — its own code, plus the shell bar |
| **timeout** | **No such concept** (G9) |

**Cancellation and races.** In-flight requests are not aborted on unmount — no endpoint passes
a signal — but nothing observes them either: TanStack Query discards results for unmounted
observers, so there are no state-updates-after-unmount. Fast switching between classes cannot
produce a last-write-wins race, because every read is keyed by its parameters
(`queryKeys.classMastery(classId, {…})`) rather than written into shared state, and
`placeholderData: keepPreviousData` on the two paginated lists is a read concern with a comment
explaining the loss of work it prevents. The one manual fetch, `DraftPreview`, aborts its own
debounced request and checks `signal.aborted` in all three callbacks.

---

## 10 · Defensible-but-different

Choices I would have made differently, or that contradict the brief, and am not calling
findings.

1. **`fr-CH` uses a decimal point, not a comma.** The brief's §54 asserts that Swiss users type
   `4,5` and that display must use a comma, and calls a silent parse to `4` Critical. The repo
   disagrees deliberately and says so: *"`fr` alone would print `1 234,5`; Suisse romande
   writes `1'234.5`, and so does Deutschschweiz — hence `fr-CH` / `de-CH`"*
   (`lib/format.ts:7-11`). ICU agrees — `fr-CH` is `.` for decimals and `’` for groups. So
   `fmt.number(4.5)` renders `4.5` and that is correct for the locale. G2 is a real bug about
   a *controlled number input*, not about the separator. Whether inputs should nonetheless
   *accept* a typed comma is a question for the teachers (§11) — I would accept it and
   normalise, because the cost of accepting is zero and the cost of rejecting is a field that
   appears broken.
2. **No Swiss grade scale, and no grade entry at all.** There is no 1–6 field, no cantonal
   rounding, no HarmoS year input, and no school-year format — because there is no screen on
   which a teacher types a grade. Marks are computed from the barème and the scan. The brief's
   §53 asks for those rules to be enforced client-side; the honest answer is that the product
   does not have the inputs they would apply to. If a report-mark screen is ever built, that
   is where they arrive, and `lib/points.ts` is the right place for them.
3. **No form library, every form hand-rolled `useState`.** At 26 routes and mostly simple
   forms this is less code than react-hook-form plus resolvers, and the Worker bundle ceiling
   (D25) is real. I would reach for one at twice this size. What I do want is shared validation
   *timing* (G20), which is orthogonal.
4. **No optimistic updates, anywhere.** Unusual for a 2026 React app and exactly right here.
   §4 explains why.
5. **`staleTime: 30_000` with `refetchOnWindowFocus: false`.** I would invert the second — a
   teacher returning to a tab is precisely when a refetch is wanted — and the choice keeps a
   classroom laptop quiet. It is also what makes G8 visible for thirty seconds rather than
   invisible.
6. **A local working copy of the adaptive plan in `useState`.** Copying a megabyte of server
   state to mutate it locally is unusual; the argument (regenerate, discard and edit each
   rewrite one item, and re-fetching to learn that is pointless) is sound, and now that the
   *address* is in the URL my Phase 4 objection is answered.
7. **Recent adaptive runs kept in `localStorage` rather than read from `GET /jobs`.** The
   comment argues it: the job list is school-scoped and `JobOut` carries no `class_id`, so a
   server-side list would show a colleague's run and could offer a row that 404s. It names the
   gap it leaves — a run started on the classroom desktop is not listed on the laptop at home
   — and names the one field that would close it. This is the right trade, documented.
8. **No virtualisation anywhere.** At 24 pupils × 8 competencies (192 cells) and 30 review
   cards, a full render is correct and virtualising a `<table>` would cost the sticky column
   and the arrow-key navigation. It would matter at the API's 120-page upload cap.
9. **The `Matrix` shell is headless and shared; the *cells* deliberately are not.** The comment
   is the best design argument in the package: *"The five-band colour ramp is a calibrated
   encoding of decayed competency evidence; a raw score is a different measurement, and a
   shared cell would quietly claim they were the same thing. A shared shell claims nothing."*
10. **Library components take many string props** because the library ships no strings. A
    `labels` object would collapse most of them; that is ergonomics, not a fix, and I would not
    trade the rule for it.
11. **`/_gallery` instead of Storybook.** One route, the app's own tokens, the app's own theme
    switch, reusing the fixtures and the screenshot harness that already exist. I would have
    made the same call. G31 is about its gate, not its existence.
12. **`force-dynamic` on the locale layout for the CSP nonce.** Measured, documented, and
    correct; `theme-script.test.ts` keeps the hash and the script from drifting.

---

## 11 · Open questions

1. **Should a number field accept a typed comma?** G2's fix is `valueAsNumber` either way. The
   separate question is whether `0,5` should be read as 0.5 on a Romand keyboard. I would say
   yes; §10.1 explains why the *display* side is already settled and should not change.
2. **Is the school-year dimension meant to be reachable this milestone?** The API half looks
   finished. If the UI half is scheduled, `queryKeys` is the cheap moment (G3). If it is
   deliberately parked, the dead `listSchoolYears` export and the unused `asOf` parameters
   should carry a comment saying so, the way every other deliberate absence in this codebase
   does.
3. **What is the intended remedy for a *groupe de niveau*?** The vocabulary is free now. The
   concept still needs a container whose code does not have to be homeroom-shaped, and that
   touches the UID and therefore paper. Is it in scope before teachers have paper in
   circulation?
4. **How should a teacher find out that a correction failed?** A toast is my recommendation
   (G1), but if the intended answer is stronger — a per-item "non enregistré" marker that
   persists until it succeeds, or a blocking banner on **Valider** — that is a design decision
   and it changes the shape of the fix.
5. **Should the review screen name the pupil when projector mode is off?** G24. It adds the one
   misattribution check a machine cannot make, and it puts a name on a screen that currently
   has none. I lean yes; it is a dignity call, not a technical one.
6. **Is there ever a second role?** Unchanged from Phase 4 and still cheaper before the route
   tree grows again. Twenty-six routes now, one guard, no role field in the contract.
7. **Is `docs/plan.md` §5 still the screen inventory of record?** It lists 11; there are 26.
   Phase 4 asked this and it is still open.

---

## 12 · What I could not verify by reading, and the test that would settle each

1. **That the decimal barème actually breaks the way I traced it (G2).** The HTML value
   sanitisation algorithm says `1.` is not a valid floating-point number and must be replaced
   by the empty string, and React writes a prop of `0` back over an empty DOM value — so the
   mechanism is established from the specification and the code, not from watching it.
   **Test:** a Vitest + `@testing-library/user-event` test on `PointsSelect` that types `1.5`
   into the custom field and asserts `onChange` was last called with `1.5`; and a second that
   types `1,5`. Both would fail today.
2. **Whether the review screen's re-render cost is perceptible (G11).** I established that
   thirty `PageCard`s and ~1 000 overlay buttons re-render per `setSelected`; I did not measure
   a frame. **Test:** a Playwright trace over a fixture-mode scan of 30 pages × 8 items,
   measuring the time from `keydown n` to the next paint, with a budget. Or a React Profiler
   run asserting committed-component count per keystroke.
3. **Whether the image layout shift is felt (G13).** The absence of reserved dimensions is
   certain; the magnitude depends on decode timing. **Test:** a Playwright measurement of
   cumulative layout shift on `/scans/{id}` with throttled images.
4. **That a 500 on a correction is silent end to end (G1).** I verified `correct.isError` has
   no reader. **Test:** a Playwright route interception that fails
   `PATCH /scans/*/detections/*` with a 500, then asserts that something in the accessibility
   tree says the save failed. It would fail today.
5. **Bundle size and the split (§ item 73).** The dependency list is tiny — react, react-dom,
   next, next-intl, `@tanstack/react-query`, four `@fontsource-variable` packages, four Radix
   primitives, clsx — there is no client-side PDF, math or image library, and the only
   `await import` calls are the mock handlers and the message catalogues. `fonts.css` is *not*
   imported by `packages/ui/src/index.css`, so its 248 KB ships only inside the print document.
   I did not run a build and cannot state a number against the 3 MiB Worker ceiling.
   **Test:** a `next build` size budget in CI, per route.
6. **Contrast ratios on the band, confidence and difficulty indicators (§ item 69).** I
   verified the *structure* of the non-colour channels — every band carries a glyph and a word,
   `MasteryBandTag` takes `label` as a required prop with a unit test asserting it *"never
   renders a bare coloured pill"*, `ConfidenceBar` carries a threshold marker and its own
   warning sentence — and I read the derivation comment for `--c-mastery-*-ink` claiming 4.5:1
   on each tint. I did not compute a ratio, and nine palettes × five bands wants a tool.
   **Test:** a contrast assertion in `recipes.test.ts` over the token pairs, or axe-core in the
   existing display-state e2e matrix.
7. **What a clean run emits to the console (§ item 84).** Requires running the app. By reading,
   the only deliberate `console.error` is `error.tsx:42`. The hydration risk I can name is
   `scope.tsx:144`'s render-phase `localStorage` read (G28), which I argue does not mismatch in
   practice because both server and first client render see an empty class list.
   **Test:** a Playwright fixture that fails any spec emitting a console error or warning.
8. **Real-network behaviour of the upload (G5).** The atomicity is certain from the code; the
   failure timing is not. **Test:** a Playwright run with `context.setOffline(true)` fired
   mid-request, asserting what the screen says and what the teacher can do next.
9. **Whether the German catalogue's longer strings fit the densest screens (§ item 63).**
   `check-i18n.mjs` guarantees the three have the same keys, and the screenshot suite renders
   `/` and `/classes` in `de` at two viewports — two screens of twenty-six. The review screen,
   the builder and the adaptive screen have no German coverage. **Test:** extend the existing
   screenshot matrix to `/scans/{id}` and `/sheets/new` in `de`.
10. **That the embedded font subset covers every glyph a worksheet prints.** The script argues
    it (Latin covers `U+0152-0153` and the umlauts; autoescape means no italic face can be
    requested). I did not decode the four `data:` URIs to check their `unicode-range`.
    **Test:** assert the rendered sheet HTML contains an `@font-face` for each of the four
    families — the trick `theme-script.test.ts` already uses for the CSP hash — plus a
    `unicode-range` assertion.
11. **The API side of anything.** Where I traced into `apps/api` — the idempotency dependency,
    the `as_of` and `school_year_id` parameters, `_teacher_facing_error`, the detector's error
    string, the print template's stylesheet order — I read the code and quote it. I did not
    re-audit those modules.
12. **Whether the coordinate agreement is *asserted* anywhere (§ item 87).** It is, mechanically:
    the `layout-contract` CI job regenerates `layout.generated.ts` from `layout.py` and fails on
    a diff, and the review overlay derives its frame from that constant so it cannot drift by
    hand. `sheet-print.spec.ts` asserts the print *gate*. What no test asserts is the end-to-end
    property: that a box measured by `measure_answer_boxes` is the box `ScanReviewOverlay`
    draws. **Test:** a fixture round trip — render a known sheet, read its `AnswerBoxPlacement`
    rows, convert them through `SHEET_LAYOUT.frame` the way the client does, and assert the
    result matches the overlay's computed percentages within a tolerance.
