# Phase 4 audit — Frontend architecture

**Scope:** `apps/web` (18 495 lines across 90 files: 24 routes, 14 layouts, 23 app components,
the API layer, i18n, middleware and CSP), `packages/ui` (7 480 lines: 36 primitives,
18 domain components, 5 design stylesheets, 49 icons, 7 illustrations), `packages/shared`
(the generated layout constants), the three message catalogues, the Playwright and Vitest
suites, and the print path where it crosses into `apps/api/alppy/sheets/`.

**Method:** read-only. Every route module and every component over 100 lines read in full;
the route tree reconstructed from the filesystem, not from `docs/plan.md` §5; the print
chain traced from the button in the browser to `AnswerBoxPlacement` in Postgres. No file was
written except this one. No server was started, no build was run and no test was executed —
where I say a test does not cover something, that is from reading the spec, not from
watching it fail (§13).

**Prior phases** were read first, in full:
[`01-database-audit.md`](01-database-audit.md), [`02-api-audit.md`](02-api-audit.md),
[`03-backend-audit.md`](03-backend-audit.md). §10 says, finding by finding, what this layer
is compensating for and what it is propagating.

**Brief placeholders**, answered by the repo rather than assumed. **Stack** is Next.js 15
App Router (React 19, TypeScript strict, Tailwind v4, next-intl 4, TanStack Query 5) — not
Vite. **Primary user** is the teacher and there is no other: the contract has no role field
at all (`schemas/__init__.py:70-80`), so there is no school admin and no student login, and
every authenticated session is equivalent. **Cantonal scope** remains unanswered, inherited
from Phase 1 — and it now has a concrete cost, because `School.canton` is a two-character
free-text box on the settings screen with no list behind it (§F21).

**Snapshot:** `main` at `0c15b6e` plus the working tree in `git status` at 2026-09-11.
The API-side files under modification (`services/enrollment.py`, `api/v1/adaptive.py`,
`api/v1/sheets.py`) are Phase 3's B1/B2 landing; nothing in this report depends on how
that refactor finishes.

---

## 1 · Verdict

**Yes for the architecture. No for the paper.**

This is the strongest layer of the three I have read after the database. The state
architecture is correct and, unusually, correct on purpose: server state lives in a query
cache and nowhere else, there is exactly one global client store and it holds two ids and a
tenant, every cache key is spelled in one object so invalidation is never guessed, and the
comments on those invalidations name the bug each one fixed. The component hierarchy is
real — 36 unstyled primitives, 18 domain components that own the product's own vocabulary,
23 app components, then pages — and the domain components enforce the rules that matter:
`MasteryBandTag` takes `label` as a *required* prop precisely so a caller cannot produce a
bare coloured pill, `ConfidenceBar` carries a shorter bar and a different colour and a
warning glyph and its own words. There is one raw `fetch` outside the API layer and it is
justified in a comment. Tokens are complete, CI fails on a colour literal, i18n is set up
from the first commit with three catalogues kept in sync by a gate, the locale is `fr-CH`
with the apostrophe group separator, the register is consistent vouvoiement, and the French
reads like French rather than like translated English. The session is an HttpOnly cookie
and there is no token in `localStorage` anywhere. The scan review screen — the densest
surface in the product — puts the registered page beside the machine's reading, sorts the
least-confident item to the top, keeps the machine's verdict beside the teacher's override
rather than under it, and gives the whole queue a single keystroke. A teacher can review
thirty sheets on this screen.

Two things stop me saying yes without qualification, and both are on the one surface where
this product cannot be wrong.

1. **There are two print paths and only one of them is the one the grading pipeline
   measured.** The `Imprimer` button calls `print()` on the preview iframe
   (`sheets/[sheetId]/page.tsx:77-93`) and then records the sheet as printed. The preview
   endpoint writes nothing; `AnswerBoxPlacement` — the rectangles the scan job crops a
   written answer from — is written only by the render job
   (`alppy/sheets/render.py:746`). So a sheet with open items can be printed, sat, and
   photographed with no placements at all, and every written answer comes back
   `NOT_GRADEABLE` and is counted as skipped. And when placements *do* exist they were
   measured in the API's headless Chromium, while the paper came off the teacher's browser
   at the teacher's margins and the teacher's scale. **Underneath both**, the printed
   document declares no `@font-face` at all: `--font-sans: 'Nunito Variable', system-ui, …`
   is inlined into the sheet from `tokens.css`, but the `@fontsource-variable` packages are
   imported by the Next app's layout and by nothing else, so the PDF, the preview and the
   browser print each typeset the statements in whatever their own environment falls back
   to. Text that wraps differently is text that pushes an answer box to a different row.
   This is F1 and F2 and neither is expensive to fix — an inlined `@font-face`, and a gate
   that refuses to print a sheet whose placements are stale — but both get much more
   expensive once teachers have paper in circulation.

2. **The frontend has no concept of a teaching group, and it cannot acquire one.** The
   class code the UI validates is `^\d{1,2}[A-Za-z]{1,2}$` (`classes/new/page.tsx:43`),
   copied deliberately and exactly from `alppy/core/uid.py:17`, because that string is half
   of the UID printed on every sheet. Phase 1's own worked example of a Cycle 3 maths
   group — `10-MAT-N2` — is rejected by both. So a teacher who takes the niveau-2 group
   drawn from three homerooms has no object to put it in. The data model half-supports the
   case (a pupil carries `class_codes[]` and a `home_class_code`, and the roster labels the
   second one *origine*), and the naming layer forbids it. Worse for the vocabulary: the
   word **groupe** is already spent — in this UI it means one of the adaptive
   differentiation cohorts, which is a different thing that changes every sheet. This is
   not the "one label doing both jobs" defect the brief expects; it is the concept being
   absent and its name being occupied.

Behind those sit two structural absences that are cheap now and awkward later: there is no
`error.tsx` and no `not-found.tsx` anywhere in the tree, so one render exception drops the
whole app to Next's untranslated default page; and there is no 401 handling at all —
`ApiError.isUnauthorized` and `ApiError.isOffline` are both defined and both dead — so a
session that expires halfway through a pile tells the teacher *"L'envoi a échoué.
Réessayez."* forever.

**Will a real teacher complete the two under-pressure flows?** Reviewing a scanned batch
between lessons: **yes**, in about seven minutes for a clean pile, and every correction is
persisted the moment it is made, so an interruption costs nothing. Generating differentiated
sheets in a free period: **no, not reliably** — not because of the click count, which is
fine, but because the entire run lives in one component's `useState`. Closing the laptop
between the propose click and the export loses the job id, the plan, the teacher's group
moves and the approval state, and there is no screen anywhere in the app that can find that
proposal again. The wait it happens across has no progress bar, no estimate and no cancel.

---

## 2 · Findings

Ordered within each severity by **cost of fixing once the UI is built out**, descending.

| ID | Sev | Area | Summary | Evidence |
|---|---|---|---|---|
| F1 | Critical | Print fidelity | The `Imprimer` button prints the preview iframe and marks the sheet printed; the preview writes no `AnswerBoxPlacement`, so written answers on that paper are ungradeable | `sheets/[sheetId]/page.tsx:77-93`, `api/v1/sheets.py:269-304`, `sheets/render.py:746` |
| F2 | Critical | Print fidelity | The printed document declares no `@font-face`; the design system's fonts are imported only by the Next app, so PDF, preview and browser print each use a different fallback | `tokens.css:180-184`, `sheets/templates/sheet.html.j2:18-29`, `app/[locale]/layout.tsx:1-4`, `apps/api/Dockerfile:45` |
| F8 | High | Temporality | `année scolaire` appears nowhere in the UI: no year switcher, no as-of, no way to open last year's cohort | `lib/scope.tsx` (whole), `messages/fr.json` (no `année scolaire`) |
| F3 | High | Student dignity | No projector or discretion mode anywhere; names, weakest band and group placement are on every screen a teacher displays | `settings/page.tsx` (whole), `classes/[classId]/students/page.tsx:99-104` |
| F9 | High | Domain / IA | There is no *groupe*: the class code regex forbids one, and the word is already spent on adaptive cohorts | `classes/new/page.tsx:43`, `alppy/core/uid.py:17`, `messages/fr.json` `adaptive.group*` |
| F7 | High | Contract | The drift gate `endpoints.ts` cites still does not exist; the generated types are untracked and imported by nothing; the hand mirror has already drifted | `lib/api/endpoints.ts:80-84`, `packages/shared/src/index.ts:9`, `git status` |
| F4 | High | State / async | The whole adaptive run — job id, plan, group moves, approvals, export job — lives in component `useState`; navigating away loses it irrecoverably | `adaptive/page.tsx:104-124` |
| F11 | High | Scan flow | An unregistered page has no route back into its pile: the UI says re-shoot it and offers only Discard | `scans/[scanId]/page.tsx:552-591` |
| F10 | High | Connectivity | Scan upload is one atomic multipart, no per-file progress, no resume, no retry; the help text says "keep this page open" | `scans/new/page.tsx:44-65`, `messages/fr.json` `scans.uploadingHelp` |
| F12 | High | Disclosure / i18n | Raw server prose reaches the teacher in English on five screens, including a developer sentence about registration quality and a worker log line | `scans/[scanId]/page.tsx:247,557`, `sources/page.tsx:190`, `sheets/new/page.tsx:321-323`, `SectionPicker.tsx:220`, `alppy/scan/detector.py:764`, `alppy/worker/tasks.py:160-373` |
| F5 | High | Auth | No 401 handling anywhere; `isUnauthorized` and `isOffline` are dead code. A mid-review expiry reports a generic send failure | `lib/api/client.ts:29-36`, `Providers.tsx:19-25` |
| F6 | High | Robustness | No `error.tsx`, no `global-error.tsx`, no `not-found.tsx`. One render exception takes the app down to Next's untranslated default | `find apps/web/src/app -name 'error.tsx'` → none |
| F13 | Medium | Async UX | The propose run polls `Job.progress` and shows a skeleton; "24 variants" has no progress, no estimate, no cancel | `adaptive/page.tsx:133-138`, `:641-642` |
| F14 | Medium | Errors | The catalogue answers 13 codes; 401, 403, 429, 500 and 503 all collapse to "L'envoi a échoué. Réessayez." and nothing compares the sets | `messages/fr.json` `errors.code`, `alppy/api/errors.py:60-92`, `scripts/check-i18n.mjs` |
| F15 | Medium | Errors | Login reports every failure as invalid credentials, including a rate limit and a network drop | `login/page.tsx:73` |
| F16 | Medium | PER | `ConceptTag code={id.slice(0,8)}` renders eight hex characters of a UUID in the slot reserved for `MSN 32` | `adaptive/page.tsx:985` |
| F17 | Medium | Vocabulary | Three French words for one object — Branche, Discipline, Matière — and *École* where a Sek I product says *établissement* | `messages/fr.json` `settings.branches`, `nav.currentSubject`, `sources.subject`, `settings.school` |
| F18 | Medium | Destructive actions | Regenerating or discarding a generated exercise is irreversible and unconfirmed; `Rouvrir` withdraws a whole pile's grades on one click | `adaptive/page.tsx:391-419`, `scans/[scanId]/page.tsx:309-317` |
| F19 | Medium | Unsaved work | The sheet builder's draft is `useState` with no persistence and no navigation guard | `components/sheet-builder/useDraftSheet.ts:176-181` |
| F20 | Medium | A11y | No focus management on route change; `<main tabIndex={-1}>` exists and nothing ever focuses it | `components/AppShell.tsx:149` |
| F21 | Medium | Domain validation | Canton is a two-character free-text input with no list; the class-code regex is hand-duplicated from Python | `SchoolSettings.tsx:69-75`, `classes/new/page.tsx:43` |
| F22 | Medium | States | `/classes/[classId]/roster` has no loading, empty or error state; a 404 renders an empty add-students form | `classes/[classId]/roster/page.tsx:62-67` |
| F23 | Medium | Performance | The review screen loads every registered page image and every answer-box crop eagerly; no lazy loading, no virtualisation | `ScanReviewOverlay.tsx:132`, `OpenAnswerCard.tsx:98-103` |
| F24 | Medium | Connectivity | No connection-state signalling at all; the offline branch exists in the client and is never read | `lib/api/client.ts:33-36` |
| F25 | Medium | Polling | The `/sources` poll is a hand-rolled `setInterval` that fires on a blurred tab and never gives up on a stuck job | `sources/page.tsx:40-44` |
| F26 | Medium | Tooling | No Storybook or component workbench; the primitives' only visual coverage is 36 screenshots of two screens | `apps/web/e2e/*-snapshots/` |
| F27 | Medium | Onboarding | The only roster import is pasted text; no CSV upload, no cantonal export, no establishment creation in the UI | `classes/new/page.tsx`, `RosterInput.tsx:36-60` |
| F28 | Medium | PER | The curriculum tree is Branch → Competence → Theme; no *attentes fondamentales*, no per-year progression, no Niv. 1/2/3 | `components/CurriculumTree.tsx`, Phase 1 §H1–H2 |
| F29 | Low | Disclosure | The feedback page's printed header carries the group label; two pupils comparing pages can read their placement | `alppy/sheets/html.py:665-676` |
| F30 | Low | Hygiene | `errors.notFound` is dead catalogue text in three languages; `school_year_id` is a client type for a field no endpoint carries | `messages/fr.json`, `lib/api/types.ts:150` |
| F31 | Low | Artefacts | `docs/plan.md` §5 lists 11 screens; 24 exist. The plan is stale in the safe direction, but it is the only screen inventory | `docs/plan.md:148-164` |
| F32 | Low | Hygiene | Stray empty `<div>` left in the roster list markup | `classes/[classId]/roster/page.tsx:75` |

---

## 3 · Detailed findings

### Critical

---

#### F1 · The `Imprimer` button prints paper the grading pipeline has no coordinates for

**What is wrong.** There are two ways to get paper out of Alppy and they do different things.

```tsx
const printPreview = () => {                       // sheets/[sheetId]/page.tsx:77
  const frame = frames.current[kind];
  const target = frame?.contentWindow;
  if (target) {
    try {
      target.focus();
      target.print();
      if (kind === 'blank') markPrinted.mutate(sheetId);
      return;
    } catch { /* … */ }
  }
  window.open(previewUrl(sheetId, kind), '_blank', 'noopener');
};
```

The iframe's `src` is `GET /sheets/{id}/preview`, and that handler says so itself:

```python
# REPORT: the preview renders the sheet's own stored rows and writes
# nothing. Printing it is `render_sheet`, which stays a gate.
```

But the client does not treat it as a preview. It prints it, and then calls
`POST /sheets/{id}/printed`, which writes a `SHEET_PRINTED` event. The one thing that
`render_sheet` produces and `preview_sheet` does not is the rows the scan job reads:

```python
_persist_answer_box_placements(db, sheet, data, measure_answer_boxes(blank_html))
#   sheets/render.py:746 (and :858)
```

and on the way back in:

```python
if result.canonical is None or not placements:      # scan_processing.py:231
    return {}
```

No placements, no crops. An open item with no crop stays `NOT_GRADEABLE`, which the
confirmation screen honestly reports as *"# réponse n'a pas pu être corrigée
automatiquement : à reprendre à la main."* — the right behaviour, and it is the second half
of a bug rather than a bug of its own.

**Why it matters here.** Mme Berthod builds a fiche for 9VG2 with four written-answer items,
opens it, checks the preview, and presses **Imprimer**. Nothing warns her; the sheet is
recorded as printed and appears on the agenda as such. Twenty-four pupils sit it. She
photographs the pile on Friday. Every bubble grades — registration works off the fiducials,
which are on the page whatever else happened. Every written answer comes back "à reprendre à
la main", all ninety-six of them, and there is nothing on the review screen that says why or
that the fix was a button she did not press two days earlier.

The second half is subtler and worse. Suppose she *had* pressed **Générer le PDF** first.
The placements exist, measured in the API's Chromium at A4 with `@page { margin: 14mm }`.
She then prints from the browser anyway, because the preview is right there. Chrome's print
dialog defaults to the printer's margins, offers a **Scale** control that many school
printers pre-set to "Fit to page", and — see F2 — resolves the font stack differently from
the container. The bubbles survive all of that, because registration is fiducial-relative
and a uniform scale cancels. The answer boxes do not: they are stored as page millimetres
measured against one text flow, and cropped from a page whose text flowed differently.
`crop_answer_box` cuts a rectangle that is a line or two off, the vision grader is handed a
crop containing half of one answer and half of the next, and it returns a verdict with a
confidence high enough to auto-apply.

**The fix.** Three things, in order of value:

1. Make **Imprimer** call `render_sheet` when the sheet has open items and its placements
   are stale (no `rendered_at`, or `rendered_at < updated_at`), and print the resulting PDF
   rather than the frame. The gate already exists server-side; the client is routing around
   it.
2. Failing that, disable **Imprimer** on a sheet with open items and no render, and say why
   in one sentence. A refusal a teacher can read beats paper they cannot grade.
3. Regardless: `markPrinted` should not fire on the browser-print path for a sheet the
   render gate has not passed. Recording a print that produced ungradeable paper puts a lie
   in the agenda.

**Cost of fixing after the UI is built out.** The code change is small and stays small. The
cost that grows is the paper: every batch printed through this path is a class-set of
written answers that cannot be graded and cannot be recovered, because the placement rows
for that printing never existed. There is no migration for paper.

---

#### F2 · The printed document declares no `@font-face`, so nothing that prints uses the design system's type

**What is wrong.** `render_sheet_html` inlines three stylesheets verbatim from
`packages/ui/src/design/` — and it is right to, that is the mechanism that keeps preview and
PDF from drifting:

```jinja
<style>/* packages/ui/src/design/tokens.css */
{{ css.tokens }}
</style>
```

Those tokens name the families:

```css
--font-display: 'Fredoka Variable', 'Nunito Variable', system-ui, sans-serif;
--font-sans:    'Nunito Variable', system-ui, -apple-system, 'Segoe UI', sans-serif;
--font-mono:    'JetBrains Mono Variable', ui-monospace, 'SFMono-Regular', monospace;
```

and nothing anywhere loads them. `grep -rn "font-face" packages/ui/src/design/
apps/api/alppy/sheets/templates/` returns nothing. The faces arrive through
`@fontsource-variable`, and the only place they are imported is the Next app's own layout:

```tsx
import '@fontsource-variable/fredoka';     // app/[locale]/layout.tsx:1-4
import '@fontsource-variable/nunito';
```

which is a JavaScript import that ends up in the web bundle's CSS. The print document is
served by the API and never sees it. So:

| Renderer | Resolves `--font-sans` to |
|---|---|
| The PDF (`playwright install --with-deps chromium`, `apps/api/Dockerfile:45`) | whatever base fonts the Playwright dependency set installs — Liberation/DejaVu on Debian |
| The preview iframe (same document, teacher's browser) | the browser's `system-ui` — SF Pro on macOS, Segoe UI on Windows |
| The teacher's browser print of that iframe | the same, plus the print dialog's own settings |

**Why it matters here.** Two consequences, and the second is the one that costs grades.

The visible one: the sheet a pupil holds is not in the shipped identity. Alppy's whole
design argument — the brand library is shipped, not described; the assets win — is undone on
the one artefact that leaves the building. Every A4 page, blank and answer key, is set in a
system fallback.

The measurable one: `measure_answer_boxes` asks Chromium where each box landed *in that
Chromium, with those metrics*. `_check_box_inside_statement_region` then verifies the box
sits inside `ITEMS_TOP_MM..ITEMS_BOTTOM_MM` and raises if not — a real guard, and it is why
this has not shown up as a crash. But it only catches a box that has left the statement
region entirely. A statement that wraps to four lines in DejaVu and three in SF Pro moves
its box by one `linePitchMm` (8 mm) and stays comfortably inside the region. Eight
millimetres is most of a written line. Along the server-PDF path the measure and the print
happen in the same process, so this cancels — that path is internally consistent and I want
to say so plainly. It stops cancelling the moment F1's browser-print path is used, and it
stops cancelling if the API image's font set ever changes underneath a sheet already
printed.

**The fix.** Add `@font-face` rules with the woff2 payloads as `data:` URIs into a fourth
inlined stylesheet, generated the way `geometry.css.j2` already is, from the
`@fontsource-variable` files in the workspace. It is one build step and it makes all three
renderers agree. The CSP already permits it (`font-src 'self' data:`). If the size is
objectionable, subset to Latin — these are worksheets in French, German and English.

Second, and independently: pin the font situation with a test. `theme-script.test.ts`
already exists to stop a hash and a script drifting; the same trick applies here — assert
that the rendered sheet HTML contains an `@font-face` for each of the four families.

**Cost of fixing after the UI is built out.** The change itself never gets more expensive.
What gets expensive is the audit trail: once sheets have been printed and scanned under one
font stack and the stack later changes, every re-crop of an archived page reads the wrong
rectangle, and there is no field on `AnswerBoxPlacement` recording which stack measured it.
Adding the fonts now means the question never arises.

---

### High

---

#### F8 · `année scolaire` does not exist in the interface

**What is wrong.** There is no year anywhere. `grep -rn "school_year" apps/web/src` finds a
single hit — `types.ts:150`, an optional field on a client type that no endpoint sends or
accepts (F30). The scope provider resolves a class and a subject and a school and nothing
else (`lib/scope.tsx:35-79`). The scope switcher offers school, class, subject
(`ScopeSwitcher.tsx:58-138`). No screen takes an `as_of`, because no endpoint offers one
(Phase 2 C3).

Every read means *now*, and "now" is defined by the current enrolment.

**Why it matters here.** Two moments in the Swiss calendar, both of which arrive on a fixed
date rather than as an edge case.

**Mid-August.** A teacher opens Alppy to prepare. Last year's classes are either still there
under their old codes — in which case `/classes` shows twelve classes and no way to tell
which six are current — or they are gone, along with every matrix that justified an
orientation decision. There is no year selector to choose between those states, and no
screen that would use one if there were.

**Any Monday in June.** M. Rossier is asked by a parent why Léa was oriented as she was. The
mastery matrix he needs is October's. `/classes/{id}` renders today's, computed from today's
roster, with today's decay applied — the mastery model's whole point is that a band fades,
so the October band is not recoverable by looking harder. Phase 2 notes the capability
exists one layer down (`services/mastery_service.py:161-195`) and no route passes it. No
screen asks.

I am ranking this High rather than Critical only because the frontend is the wrong place to
fix it: the parameter does not exist to pass. But it is Critical at the level of the stack,
and Phase 1 C1/C2 and Phase 2 C3 say so.

**The fix.** Frontend-side, once the API carries it: a year row in `ScopeSwitcher` above the
class row, read from and written to `?year=`, defaulting to the current one and *visibly*
non-current when it is not — a banner, not a subtle chip, because a teacher reading last
year's numbers as this year's is the failure mode. `lib/scope.tsx` is already the right
shape for this: it resolves ids from the URL with a validated fallback and it already
distinguishes "sticky across sessions" (class) from "not sticky" (chapter). A year is
sticky.

**Cost of fixing after the UI is built out.** High and rising, which is why it sits at the
top of its severity band. Adding a year to the scope changes the cache key of every
class-grained query — `classMastery`, `classPoints`, `classTree`, `students`, `sheets`,
`scans` — and the `queryKeys` object is the one place that is cheap to change *today*,
while every key still hangs off a small number of prefixes. It gets more expensive with
every screen that reads one of those caches.

---

#### F3 · No projector or discretion mode

Covered in full in §4, which the brief asks for separately. In summary: the settings screen
offers theme, contrast, motion and a *mode lecture* that hides decorative illustrations
(`settings/page.tsx:73-112`). There is nothing that hides names, bands or group placement.
`DESIGN.md:135` mentions "projector mode" once, as a type-scale floor, and nothing
implements it. Every screen a teacher would put on the wall — the class matrix, the roster,
the results grid, the adaptive groups — carries either full names or per-pupil placement.

**Cost of fixing after the UI is built out.** Second only to F8, and for the same reason:
it is a cross-cutting mode, not a screen. Every component that renders a name, a band, a
score or a group label has to learn to render a reduced form of itself. Today that is five
screens and about eight components; it is cheap because `lib/display.ts` already ships the
mechanism — a preference applied as a root `data-*` attribute before paint, persisted through
`TeacherPreferences`, with `calm` as the working precedent. Retrofitting it once the full UI
exists means auditing every screen for identity disclosure rather than designing three or
four components to have a discreet variant.

---

#### F9 · There is no *groupe*, and the word is already spent

**What is wrong.** The brief expects the recurring Phase 1 defect — one label doing two
jobs. What is here is sharper. The class code the UI validates:

```ts
// Exactly `_CLASS_RE` in `alppy/core/uid.py` — one or two digits then one or
// two letters. It has to be exact: looser here (this accepted `11ABC`) and
// the form green-lights a code the server then rejects with a 422 …
const codeValid = /^\d{1,2}[A-Za-z]{1,2}$/.test(code.trim());   // classes/new/page.tsx:43
```

and the Python it mirrors:

```python
_CLASS_RE = re.compile(r"^\d{1,2}[A-Za-z]{1,2}$")               # core/uid.py:17
```

with the reason: the class code is half of the UID printed on every sheet and read from the
bubble grid (`7B_15`). Phase 1's own worked example of a Cycle 3 maths group — `10-MAT-N2`,
the niveau-2 group Léa is streamed into — is rejected by both. There is no second object.
`Class` is the only container, and its name must be homeroom-shaped.

Meanwhile the French catalogue uses **groupe** seven times, all of them for something else:

```
adaptive.groupCount      = Nombre de groupes
adaptive.groupedByRule   = Groupes formés par lacune principale.
adaptive.groupsTitle     = Groupes personnalisés
adaptive.moveHint        = Sélectionnez un élève pour le déplacer vers un autre groupe.
```

These are the adaptive differentiation cohorts — recomputed on every propose, labelled
*Groupe 2 · Fractions équivalentes*, and gone as soon as the sheet is printed.

**Why it matters here.** The vocabulary collision is the part a teacher will feel first. In a
Vaudois or Valaisan staffroom, *"mon groupe de niveau 2"* is a stable, timetabled thing with
a room and a register. In Alppy, *groupe* is an ephemeral bucket the software invented five
minutes ago. A teacher who reads *"4 groupes formés"* on the adaptive screen and *"Classe
9VG2"* in the rail has been given the wrong two words for the two things they actually have.

The structural part is worse and is not the frontend's to fix alone. The model half-supports
the case already: a pupil carries `class_codes[]` and a `home_class_code`, and the roster
labels the second membership *origine* (`students.homeClass = "{code} · origine"`), which is
precisely the "visitor in another class" shape a streamed group needs. What blocks it is
that the second container must also be named like a homeroom, and its code goes on the
printed UID — so `10MB` would work and would be indistinguishable, on paper and in the
roster, from a homeroom called 10MB.

**The fix.** Not a rename. The frontend should not paper over this with a label; the concept
needs somewhere to live. What the frontend can and should do now, before the UI is built out
further:

- Stop spending *groupe* on the adaptive cohorts. *Série*, *lot* or *niveau de fiche* all
  read correctly for "the four variants of this worksheet" and leave *groupe* free.
- Give `Class` a visible `kind` in the UI as soon as the model has one — *classe* vs
  *groupe* — and render it in the rail, the roster header and the sheet header, so the
  teacher is never guessing which kind of container they are in.
- Until then, at minimum, surface `label` in more places than the switcher: a class code of
  `10MB` with the label *"Maths — niveau 2"* is the only signal a teacher has, and today it
  appears in one truncated line of the rail.

**Cost of fixing after the UI is built out.** The rename is cheap and gets slightly cheaper
the sooner it happens (seven catalogue keys × three languages, plus a handful of comments).
The concept is expensive whenever it lands, because it touches the UID and therefore
touches paper.

---

#### F7 · The contract gate still does not exist, and the hand mirror has already drifted

**What is wrong.** `endpoints.ts` makes a claim about itself:

```
 * Every path below is checked against the served OpenAPI document by
 * `apps/web/src/lib/api/__tests__/contract.test.ts`.
```

There is no `__tests__` directory. Phase 2 raised this as H2; four days later the state is
unchanged in every particular. `lib/api/types.ts` is still a 1 162-line hand mirror of
`alppy/schemas`. `packages/shared/src/index.ts` still exports only the layout constants.
`scripts/generate-api-types.py` and `packages/shared/src/api-types.generated.ts` are both
still `??` in `git status`, and the generated file is imported by nothing —
`grep -rn "api-types" apps packages` matches only the file's own header comment.

What is new is that I can now show the drift rather than predict it. Diffing the 92
hand-written interfaces against the 103 generated ones:

```
in generated but not hand: BranchOrder, ChapterCreate, ChapterUpdate, ClassUpdate,
  MasteryCell, MasteryPoint, SchoolCreate, SchoolUpdate, SheetStudentMastery,
  SheetTaken, SourceUpdate, StudentUpdate, SubjectCreate, SubjectUpdate, …
field drift: AdaptiveBatchRequest — missing in hand: ['source_sheet_ids']
```

**Why it matters here.** `AdaptiveBatchRequest.source_sheet_ids` is not cosmetic. The server
comment explains what it is for:

```python
#: Every sheet whose corrected results justified this batch, principal
#: first. A reprise may answer a test *and* the worksheets whose gaps it
#: revisits; `source_sheet_id` alone could only name one of them.
```

The sheet detail screen already renders that lineage, plural, with a **Principal** chip on
entry 0 (`sheets/[sheetId]/page.tsx:201-213`). The adaptive builder can only ever set the
singular, because the type it is written against does not know the plural field exists
(`adaptive/page.tsx:431`). So the app *displays* a capability it *cannot produce*, and the
only reason nothing breaks is that `resolved_source_ids()` keeps back-compatibility for "an
older client". The older client is the current one.

This is the cheapest High in the report to close and the one with the widest blast radius
if left: every new endpoint added from here is another chance for the two copies to
disagree, and each disagreement is discovered by a teacher rather than by CI.

**The fix.** Commit the two untracked files, re-export the generated types from
`packages/shared/src/index.ts`, point `lib/api/types.ts` at them (keeping the app-only types
— `ExerciseQuery`, `TimelineQuery`, `ApiErrorBody` — as the local additions they are), and
add a CI job in the shape of the one that already guards `layout.generated.ts`: regenerate,
`git diff --exit-code`, fail if stale. That gate exists and works; it needs a second
consumer.

**Cost of fixing after the UI is built out.** Linear in the number of screens: switching
`types.ts` to a re-export is a compile-time exercise today, with 92 interfaces and one known
drift. Every additional month of hand-mirrored types adds more silent divergences, each of
which surfaces as a screen that renders `undefined`.

---

#### F4 · An adaptive run lives in one component's state and cannot be recovered

**What is wrong.** Everything about a differentiation run is local:

```tsx
const [proposeJobId, setProposeJobId] = useState<Uuid | null>(null);   // :113
const [plan, setPlan] = useState<AdaptiveProposeResponse | null>(null); // :114
const [moves, setMoves] = useState<Record<string, number>>({});         // :108
const [approvedIds, setApprovedIds] = useState<ReadonlySet<Uuid>>(new Set()); // :124
const [sheetId, setSheetId] = useState<Uuid | null>(null);              // :120
const [jobId, setJobId] = useState<Uuid | null>(null);                  // :121
```

None of it is in the URL, in `localStorage`, or in a query cache with a stable key. The
proposal *is* durable server-side — `GET /adaptive/proposal/{job_id}` retrieves it and the
query pins `staleTime: Infinity` for exactly that reason — but the job id that addresses it
exists only in this component. There is no `/adaptive/[jobId]` route, no list of recent
proposals, and nothing on the home screen or the agenda that links to one.

Contrast the scan flow, which got this right: `scans/new` redirects to
`/scans/{id}?job={jobId}`, so the job handle is in the URL and survives a reload
(`scans/new/page.tsx:55-58`).

**Why it matters here.** M. Rossier has a free period at 10:15. He opens `/adaptive`, sets
four groups, presses **Proposer**. Twenty-four students means twenty-four sequential
provider calls behind one 600-second job timeout (Phase 3 B10) with, per F13, no progress
displayed. At 10:40 the bell goes. He closes the laptop and walks to his lesson.

The job finishes at 10:47. The plan is in the database. He cannot reach it. Reopening
`/adaptive` gives him the empty state and a **Proposer** button. Pressing it *may* hand him
the still-running job of a colleague in the same school, because the in-flight guard is
scoped to the tenant rather than the class (Phase 2 C1 / Phase 3 B12, still unfixed at the
snapshot) — in which case he will be shown a plan for a class he may not teach, keyed by
pupils he may not know. Otherwise he pays for twenty-four more provider calls to rebuild
what already exists.

The same shape, one step later, loses the export: `sheetId` and `jobId` vanish, though there
the sheet *is* recoverable from `/sheets` once the render finishes, so the cost is confusion
rather than loss.

**The fix.** Put the job id in the URL, as the scan flow does: `/adaptive?job={id}`, written
with `router.replace` on `onSuccess`. Read it back on mount and re-enter the poll. That
alone fixes the recoverability. Then two smaller things: persist `moves` and `approvedIds`
alongside it (they are small and keyed by uid, so `sessionStorage` keyed on the job id is
enough), and add a route — or a row on the agenda — listing recent `PROPOSE_ADAPTIVE` jobs
so a teacher who lost the tab has somewhere to look.

**Cost of fixing after the UI is built out.** Moderate and rising. The URL change is small
today because `/adaptive` is one screen with one job; once the screen grows a second async
chain (feedback already is one, with its own orphaned `feedbackJobId`) the state has to be
lifted properly rather than parameterised, and the parameterisation has to be designed
rather than added.

---

#### F11 · A page that would not register has no route back into its pile

**What is wrong.** The manual-assignment control is gated on registration having succeeded:

```tsx
{page.registered && !page.student_id && !page.discarded && !confirmed ? (
  <Panel className="mb-3">
    <Field label={t('assignManually')} help={t('assignHelp')}>  {/* :565-591 */}
```

An unregistered page gets two sentences and a Discard button:

```
registrationWhy  = Les repères d'angle n'ont pas été trouvés sur cette page.
registrationHelp = Reprenez la photo en cadrant les quatre coins de la feuille.
```

The advice is correct and there is nowhere to act on it. `/scans/new` creates a *new* scan
against the same sheet, which becomes a second pile with its own review screen and its own
confirmation.

**Why it matters here.** Thirty copies photographed on a desk in a hurry. Three are shot at
an angle that loses a corner. The teacher reads "retake the photo", retakes three photos,
and now has to decide what to do with them. Uploading them creates pile #2. She must review
pile #2 separately, confirm pile #2 separately, and remember that 9VG2's fiche has two
confirmations against it. On the sheet detail screen both appear under **Corrections** as
two links (`sheets/[sheetId]/page.tsx:217-232`), with no indication that one is the
remainder of the other. Nothing is *wrong* in the data — attempts land correctly either
way — but the teacher's mental model of "the pile" has been split by a tooling limitation
and nothing told her it would be.

The realistic alternative behaviour is worse: she discards the three pages, confirms
twenty-seven, and three pupils are silently unassessed on that sheet.

**The fix.** Add files to an existing scan. `POST /scans/{id}/pages` on the API; on the
review screen, a `FileDrop` on the unregistered page's card labelled *"Reprendre cette
page"*, which uploads into this pile and replaces (or supersedes) the failed page. The
review screen already knows how to poll a scan while the worker reads it, so the second half
is free.

**Cost of fixing after the UI is built out.** Moderate. The screen is already the densest in
the product; adding a per-page upload affordance later means fitting it into a layout that
has since acquired more states. The API half is a new route either way.

---

#### F10 · Scan upload is one atomic multipart and the UI tells the teacher to stand still

**What is wrong.**

```tsx
function onFiles(files: File[]) {
  // …
  setPending(files.length);
  upload.mutate({ files, sheetId }, {                 // scans/new/page.tsx:52
    onSuccess: (scan) => router.push(/* … */),
    onError: (e) => { setPending(0); setError(apiErrorMessage(e, tErr)); },
  });
}
```

One mutation, all files, one request. No per-file progress (the panel shows a spinner and a
count, and the comment says why: nobody is measuring). No resume. No retry. No partial
success — the API takes up to 120 × 50 MB in one atomic multipart held in memory (Phase 2
M6). And the honest help text:

> Gardez cette page ouverte jusqu'à la fin de l'envoi.

**Why it matters here.** Thirty photographs of A4 at a modern phone's resolution is
comfortably 90–150 MB. School Wi-Fi is what it is. At 80 % of the way through, the AP hands
the phone to another radio, `fetch` rejects, and the client turns it into
`ApiError(0, 'network_error')` → *"L'application n'a pas pu joindre le serveur."* Everything
uploaded is discarded server-side; the teacher starts again from the first photograph, with
no indication that a second attempt is any more likely to survive than the first.

The brief asks what a teacher sees when 3 of 30 pages fail. The answer is: that case cannot
arise on upload, because upload is all-or-nothing. It arises later — 3 of 30 pages fail
*registration* — and that is F11.

**The fix.** This is properly an API change (chunked or per-file upload with a scan id
allocated first), and Phase 2 M6 is the place it belongs. What the client can do without
one, and should: upload the files in batches against a scan created up front, so a drop
costs the current batch rather than the pile; and report per-file state, because
`FileDrop` already has the list.

**Cost of fixing after the UI is built out.** The client side is contained — one mutation
and one screen. The reason it is High is that the failure is silent-ish and total, and it
happens in the exact conditions the product is used in.

---

#### F12 · English developer prose reaches the teacher on five screens

**What is wrong.** CLAUDE.md states the rule plainly: *a failure crosses to the client as a
code; the client owns the sentence*. The client honours it almost everywhere —
`apiErrorMessage(err, t)` is used on 23 call sites and `error.message` is rendered nowhere.
Five places bypass it, and they do it by rendering a server *field* rather than a server
*error*:

| Site | Field | What is actually in it |
|---|---|---|
| `scans/[scanId]/page.tsx:557` | `page.registration_error` | `"registration quality 0.42 is below 0.55: the four marks found do not form a page"` (`scan/detector.py:764`), or `str(RegistrationError)`, or `"sheet was printed with layout v1, this detector reads v2"` |
| `scans/[scanId]/page.tsx:247` | `scan.error` | `str(ScanDecodeError)` — e.g. `"IMG_4471.HEIC is not a readable image"` (`scan_processing.py:121`) |
| `sources/page.tsx:190` | `source.error` | `UNREADABLE_PDF_ERROR` / `UNEXPECTED_INGEST_ERROR` — genuinely teacher-facing prose, written for a teacher, **in English** |
| `sources/page.tsx:196`, `sheets/new/page.tsx:321-323` | `source.notice` | same shape |
| `SectionPicker.tsx:220` | `job.message` | a worker log line: `"targeting"`, `"reading the chapter"`, `"proposal built"`, `"batch rendered"` (`alppy/worker/tasks.py:160-373`) |

The last row is the one that shows this is a *drift*, not a policy. The scan review screen
faced exactly this field and refused it, in a comment that reads like it was written after
the bug: *"Driven by the job, not by its prose: `message` is a log line, in English. … The
stage drives the words now; the server string never reaches the screen."* The builder's
section picker, written against the same `JobOut`, renders it.

The `Source.error` pair is the interesting case, because the backend did the hard part
right: `_teacher_facing_error` refuses to pass an exception's own text through and maps to
two curated sentences. Those sentences are just not in the catalogues, so a French teacher
reads *"Alppy could not read this PDF. It may be damaged, password-protected, or not really
a PDF."*

`registration_error` is the one that is straightforwardly wrong. It is a developer's
sentence about a quality metric, on the screen the product is most likely to be projected
from.

**Why it matters here.** Two costs. The obvious one: a trilingual product that speaks
English when something goes wrong is a product a teacher stops trusting at exactly the
moment trust matters. The second is the one D86 was written about — these screens are
projected onto a classroom wall, and `str(exc)` on this path is a threshold, a filename, or
a layout version, none of which belongs on a wall.

**The fix.** Same shape as the error envelope, one layer out. `ScanPageOut` should carry a
`registration_error_code` (`fiducials_not_found`, `quality_too_low`, `layout_mismatch`) and
the client should switch on it — the catalogue already has the *right* sentence for the
common case, `registrationHelp`, sitting one line above the raw one. `Source.error` and
`Source.notice` should become codes for the same reason; there are two and three of them
respectively, so the mapping is small.

**Cost of fixing after the UI is built out.** Low now, moderate later — each of these is a
schema field change plus a catalogue entry, and the number of such fields grows as the
product acquires more asynchronous work that can fail.

---

#### F5 · There is no 401 handling anywhere, and the code for it is written and dead

**This is a half-taken fix, not a new find.** `docs/reviews/F7-review.md:178-196` reported
it on 2026-09-06 — same file, same line, same observation that `ApiError.isUnauthorized`
*"has zero callers"* — and offered two directions: *"Guard in middleware on the session
cookie, **or** a client boundary that redirects on `isUnauthorized`."* `F7-fixes.md:105-115`
implemented the first. The first covers a visitor who is not signed in. Only the second
covers a session that expires while a teacher is working, which is the case below.

**What is wrong.** `ApiError` exposes exactly the two predicates a client needs:

```ts
get isUnauthorized(): boolean { return this.status === 401; }
get isOffline(): boolean { return this.code === 'network_error'; }
```

`grep -rn "isUnauthorized\|isOffline" apps/web/src` finds them only in their own
definitions. Nothing calls either. The only 401-aware code in the app is a retry predicate
that declines to retry (`Providers.tsx:19-25`) — correct as far as it goes, and it goes no
further.

The session is a stateless signed cookie with `max_age = 12 h` (`core/config.py:62`). The
middleware gate checks *presence* of the cookie, and only on a navigation
(`middleware.ts:76`).

**Why it matters here.** Mme Berthod signs in at 07:50 on Monday. On Tuesday at 08:10 she
opens the laptop on the pile she was reviewing — the tab is still there, react-query serves
the cached scan, the screen looks normal. She presses a verdict. The cookie expired twenty
minutes ago; the browser has already dropped it, so the request goes out without one and the
API answers 401. `apiErrorMessage` finds no `unauthorized` entry in the catalogue (F14),
falls through to `errors.code.fallback`, and she reads:

> L'envoi a échoué. Réessayez.

She retries. It fails again, identically. Nothing suggests signing in; nothing distinguishes
this from the API being down. Every correction she makes from this point is lost, and she has
no way to know which ones landed. The middleware would redirect her — but only if she
navigates, and there is no reason to navigate away from a screen that looks like it is
working.

The one genuine mercy here is that the review screen persists each correction as its own
mutation, so what landed before the expiry is safe. That is the design that saves this from
being a data-loss finding.

**The fix.** One place, in `apiRequest`: on a 401 that is not the `/auth/me` probe, dispatch
to a single handler that clears the query cache and redirects to
`/login?from={pathname}{search}` — the login screen already honours `from`
(`login/page.tsx:39-41`). Then use the predicate that is already written. Add
`errors.code.unauthorized` in three languages as the belt to that braces.

**Cost of fixing after the UI is built out.** Low and flat — it is one interception point in
one file, and it stays one file however many screens exist. I rank it high in *severity*
rather than in cost because every day it is absent is a day a teacher can silently lose
corrections.

---

#### F6 · No error boundary and no not-found page

**What is wrong.**

```
$ find apps/web/src/app -name 'error.tsx' -o -name 'global-error.tsx' -o -name 'not-found.tsx'
(nothing)
```

The App Router's contract is that an uncaught render error propagates to the nearest
`error.tsx`, and `notFound()` to the nearest `not-found.tsx`. There are neither, at any
level. And `notFound()` *is* called — `app/[locale]/layout.tsx:53` calls it for an unknown
locale.

The catalogues even carry the strings for it:

```
errors.notFound.title  = Page introuvable
errors.notFound.body   = Cette page n'existe pas ou vous n'y avez pas accès.
errors.notFound.action = Retour à l'accueil
```

translated three times, referenced nowhere (F30).

**Why it matters here.** Every screen handles a *failed request* well — `ErrorState` with a
retry, an `apiErrorMessage`, a designed empty state. What none of them handles is a
component that throws. And there is a live candidate: `toScanMarks` reads
`bubble_boxes` defensively, but `PageCard` maps `page.detections` and `DetectionRow` indexes
`letters[i]` and `detection.options.map` — a malformed payload from a partially-migrated API
(the exact situation Phase 3 B2 describes) throws inside the render, and the teacher's
reaction to a white page with Next's English "Application error: a client-side exception has
occurred" is to assume Alppy is broken and stop using it. In production Next does not even
say which component; the message is deliberately opaque.

The `notFound()` path is more mundane and more likely: any typo'd URL, any stale bookmark
with an old locale, gets Next's default 404 in English, outside the app shell, on a product
that is otherwise carefully trilingual.

**The fix.** Two files. `app/[locale]/error.tsx` rendering the existing `ErrorState` with
`errors.generic` and a `reset()` button; `app/[locale]/not-found.tsx` rendering the
`errors.notFound` strings that are already translated. Optionally a third,
`app/global-error.tsx`, for a throw in the layout itself — that one must ship its own
`<html>` and cannot use the intl provider, so it gets a fixed French sentence.

**Cost of fixing after the UI is built out.** Very low, and it does not grow — but the cost
of *not* having it grows with every screen, because every screen is another place a throw
can originate and take the whole app with it.

---

### Medium

---

#### F13 · The propose run has no progress, in an app that knows how to show progress

`useJob` polls `GET /jobs/{id}` every 900 ms and stops on a terminal status
(`queries.ts:1065-1075`). `JobOut` carries `progress`. The scan review screen uses it
properly — a `ProgressRing` with a percentage when progress is non-zero, a `Spinner` when it
is still zero, and a deliberate comment about why a ring drawn at 0 is a lie
(`scans/[scanId]/page.tsx:332-359`). Two files away, the adaptive screen collapses the whole
chain into one boolean:

```tsx
const proposing =
  propose.isPending ||
  (proposeJobId != null && proposeJob.data?.status !== 'succeeded' && … ) ||
  (proposeSucceeded && proposal.isPending);              // :133-138
…
{proposing ? <LoadingState shape="list" label={t('preparing')} rows={5} /> : …}
```

A skeleton and the word *Préparation…*, for a run that is one provider call per student.
There is no cancel — the API offers none (Phase 2 M7) — and no estimate.

Partial failure, to the screen's credit, is handled well *after* the fact: the `failures`
panel lists each affected pupil by UID with a reason-specific sentence, including a separate
line for `truncated` because "the cause is a configured limit". What it does not offer is a
retry of only the failed subset — the only retry resets `proposeJobId` and re-proposes the
whole class (`:627-637`).

**Fix:** show `proposeJob.data.progress` with the same treatment the scan screen uses, and
add a per-student regenerate to the failures panel (the machinery exists —
`useRegenerateAdaptive` already regenerates one exercise in place).

---

#### F14 · The error catalogue answers 13 of the API's codes

The API emits, from `errors.py` alone: `not_found`, `unauthorized`, `forbidden`, `conflict`,
`unprocessable`, `payload_too_large`, `rate_limited`, `service_unavailable`,
`internal_error`, `bad_request`, `method_not_allowed`, `validation_error`, `http_error`,
`unsupported_media_type`, plus the named ones (`sheet_not_renderable`, `scan_*`). The
catalogue has thirteen entries and is missing `unauthorized`, `forbidden`, `rate_limited`,
`service_unavailable`, `internal_error`, `bad_request` and `http_error`. All of them land on:

```
errors.code.fallback = L'envoi a échoué. Réessayez.
```

Three of those are routinely reachable. A 429 from the AI bucket (`api/deps.py:407-445`) is
what a teacher gets for pressing **Proposer** twice; the sentence tells them to press it
again. A 500 is indistinguishable from a validation slip. A 401 is F5.

`scripts/check-i18n.mjs` compares the three catalogues to each other and cannot see this;
`catalogue.test.ts` asserts that `fallback` and `sheet_not_renderable` exist and stops
there. Phase 2 raised this as M1 with the same conclusion: nothing compares the two sets.

**Fix:** export the code list from the API (it can be derived from `errors.py` plus a grep
for `code=`) and add it to the i18n gate. Then write the seven missing sentences — the
`rate_limited` one should say how long, since the envelope already carries `retry_after_s`.

---

#### F15 · Login reports a rate limit as a wrong password

```tsx
error={login.isError ? t('invalidCredentials') : undefined}   // login/page.tsx:73
```

Every failure mode of the login mutation is rendered as *"identifiants invalides"* — a 429
from the login rate limiter that shipped in `f147850`, a 503, and a network drop included.
The comment above it explains, correctly, that the error should never say *which half* was
wrong; that argument does not extend to saying the password was wrong when the server never
looked at it.

**Fix:** switch on `error.status` — 401 keeps the deliberately vague sentence, 429 says how
long to wait, everything else uses `apiErrorMessage`.

---

#### F16 · A UUID prefix rendered where a PER code belongs

```tsx
{p.targeted_competency_ids.slice(0, 6).map((id) => (
  <li key={id}><ConceptTag code={id.slice(0, 8)} /></li>       // adaptive/page.tsx:985
))}
```

`ConceptTag`'s own contract says what the slot is for: *"The curriculum code, e.g. `MA.2.A.1`
(LP21) or `MSN 32` (PER)."* The adaptive screen puts eight hex characters in it. Everywhere
else in the app gets this right — `sheets/[sheetId]:195`, `students/[studentId]:181,319`,
`themes/[chapterId]:148`, `competences/[competencyId]:138`, `CellDrillDown:87` all pass a
real `code` — and `themes/[chapterId]:155` even shows the intended pattern, falling back to
`id.slice(0,8)` only when the lookup misses.

Six mono pills reading `a3f19c2b` on the screen where a teacher decides what a child will
practise is worse than showing nothing: it looks like a reference and refers to nothing.

**Fix:** the plan response carries only ids, so the screen needs the tree it does not
currently fetch. `useCurriculumTree(classId, { subjectId })` is one hook and the sheet page
already does exactly this for exactly this reason (*"The tree names the Theme and the
competency codes; the sheet carries only ids."*).

---

#### F17 · Three French words for one object

| Screen | String | Object |
|---|---|---|
| `settings.branches` | **Branches** | `Subject` |
| `nav.currentSubject` | **Discipline** courante | `Subject` |
| `sources.subject` | **Matière** | `Subject` |
| `sheets.subjectLabel` | **Matière** | `Subject` |

One entity, three names, three screens. The PER's own word is **discipline**; **branche** is
what a Swiss staffroom says; **matière** is the France-French term and is the one that will
read as foreign to a Vaudois or Genevois teacher. Repo-internally the product noun is
*Branch* and the contract noun is `Subject` (Phase 2 L7 flags that too), so the confusion
starts upstream — but the interface is where a teacher meets it.

Separately, `settings.school = École`. In Suisse romande the administrative unit for Sek I is
the **établissement scolaire**; *école* reads as *école primaire*. The word *établissement*
appears nowhere in any catalogue.

Terms that read correctly and should be kept: *fiche* (98 uses, exactly right), *élève*,
*barème*, *plan d'études*, *thème*, *compétence*, *copie*, *lot*. Terms conspicuously
absent: *établissement*, *degré*, *année scolaire*, *cycle*, *attentes fondamentales*,
*niveau* in its streaming sense (the single `niveau` in the catalogue means exercise
difficulty).

**Fix:** pick **discipline** and use it everywhere, or pick **branche** and use it
everywhere. I would pick *discipline* in labels, since it matches the PER a teacher is
mapping to, and keep *branche* in the settings screen only where the object is being
administered. Then rename *École* to *Établissement*.

---

#### F18 · Irreversible actions with no confirmation, and reversible ones with a good one

`ConfirmDestructive` is a genuinely well-designed component — it names what will be
destroyed rather than asking "are you sure", takes a typed identifier for the ones that
destroy evidence, and offers the alternative the teacher probably wanted (*"Vous vouliez
peut-être le désinscrire ?"*). It is used for deleting a student, a theme, a textbook, and
for taking a branch away from a colleague.

It is not used for:

- **Regenerating a generated exercise** (`adaptive/page.tsx:391-405`). One click. The
  comment states the consequence: *"The old id is gone server-side (discarded)"*. It also
  spends a provider call.
- **Discarding a generated exercise** (`:407-419`). One click, irreversible, no undo.
- **Rouvrir** on a confirmed pile (`scans/[scanId]/page.tsx:309-317`). One click, and the
  mutation's own comment says what it does: *"Reopening withdraws grades, so it invalidates
  exactly what confirming does — the same numbers move, in the other direction."* A whole
  class's marks come off the record on a single unguarded press of a secondary button in the
  header.

Conversely **Valider les résultats** — the action that writes a class's grades — has no
confirmation and I think that is right, because `Rouvrir` is its undo and the screen already
blocks it while written answers are pending (`disabled={processing || reading > 0}`, counted
over *unfiltered* pages on purpose). The asymmetry is backwards: the reversible action is
unguarded, and so is the one that undoes it.

**Fix:** a lightweight confirm (not `ConfirmDestructive`, which is for evidence destruction)
on `Rouvrir`, naming how many pupils' results will be withdrawn — `ScanConfirmResponse`
already reports `students_affected`. An undo toast on discard, which the `ToastProvider`
already supports.

---

#### F19 · The sheet builder's draft has no persistence and no navigation guard

`useDraftSheet` holds the whole sheet — items, per-item overrides, per-item barème, answer
box heights, expected answers — in two `useState` hooks (`useDraftSheet.ts:177-181`). A
teacher who has ticked eighteen exercises, reordered them, overridden four statements and
set a barème, then follows a link or closes the tab, loses all of it. There is no
`beforeunload` handler and nothing in `sessionStorage`.

The component's own docstring explains why the selection is deliberately independent of the
picker — *"A teacher who ticks three exercises, searches for a fourth, and finds the first
three gone has lost work"* — which is exactly the right instinct applied one scope too
narrowly.

Note the contrast, and it is to the app's credit: **the scan review screen does not have
this problem.** Every correction is its own mutation, fired on change, invalidating the scan
query (`queries.ts:824-843`). A teacher halfway through thirty sheets who closes the tab
loses nothing. The brief's §37 case is already handled where it matters most.

**Fix:** serialise the draft to `sessionStorage` keyed on `class:subject`, restore on mount,
clear on successful create. A `beforeunload` guard while `draft.count > 0`.

---

#### F20 · No focus management on route change

The shell does the static half well: a skip link, `<main id="main" tabIndex={-1}>`, per-route
`<title>` via `generateMetadata` on all fourteen layouts, `aria-current="page"` on the active
destination. What it does not do is move focus when the route changes. In an App Router SPA
nothing resets focus, so after a client-side navigation a keyboard user is still focused on
the link they activated in the rail, and a screen-reader user gets no announcement that the
page changed beyond whatever their SR does with the document title.

`tabIndex={-1}` on `<main>` is exactly the affordance needed and nothing uses it.

**Fix:** a small `useEffect` on `pathname` in `AppShell` that focuses `#main`, guarded so it
does not fire on the initial mount. Modal focus, by contrast, is handled properly and
carefully — `useReturnFocus` exists specifically because Radix only restores focus to a
`Dialog.Trigger` and the app drives `open` itself.

---

#### F21 · Domain validation the client duplicates or does not do

Two shapes.

**Duplicated.** `classes/new/page.tsx:43` hand-copies `_CLASS_RE` from Python, with an
honest comment about why it has to be exact.

It has already drifted once, and the repo records it. `docs/reviews/F7-fixes.md:219-223`:

> **The class-code field was looser than the server.** I wrote `/^\d{1,2}[A-Za-z]{1,3}$/`
> and commented that it "mirrors `alppy/core/uid.py`". It does not: `_CLASS_RE` is
> `\d{1,2}[A-Za-z]{1,2}`. So `11ABC` passed the form and 422'd at the API, leaving the
> teacher to decode a validation error for a field the form had just accepted.

That is the whole argument for generating it. The drift was caught by a human reading two
files side by side; nothing in CI could have. Similarly `sources/page.tsx:48-57`
re-implements the file size and MIME checks with its own `MAX_MB`.

**Absent.** `SchoolSettings.tsx:69-75` renders canton as:

```tsx
<Input className="max-w-[8rem]" maxLength={2} value={canton || (school?.canton ?? '')} … />
```

Two characters of free text. `ZZ` is accepted here and by the API (Phase 2 M8 / Phase 3
B24: `canton` is free text with no rules table). There is no HarmoS year field, no grade
scale, no school-year format anywhere.

There is also no form library — every form in the app is hand-rolled `useState` — which is a
defensible choice at this size and one I would have made too (§11), but it means there is no
place for shared validation to live even once it exists.

**Fix:** the class regex should come from `@alppy/shared`, generated alongside the layout
constants by the same script that already exists. Canton should be a `<Select>` over the 26
cantons, which is a static list.

---

#### F22 · `/classes/[classId]/roster` has no loading, empty or error state

Every other route in the app handles all three. This one handles none:

```tsx
const klass = useClass(classId);
const existing = useStudents(classId);
…
<h1 className="mb-1">{tstud('heading', { code: klass.data?.code ?? '' })}</h1>
<p className="mb-6 text-ink-500">{tstud('count', { count: existing.data?.length ?? 0 })}</p>
```

While loading, the heading reads *"Élèves de "* and the count reads *"aucun élève"*. On a
404 — a deleted class, a class the teacher no longer teaches, a stale bookmark; all reachable
states, and the API answers 404 rather than 403 for all of them by design — it renders
permanently as an empty roster with a working paste form pointing at a class that does not
exist. Submitting it produces a 409 or a 404 in the error line and nothing explains the
situation.

`classes/new` and `settings` also have no states, but those are pure forms with nothing to
load; this one has two queries.

**Fix:** the same three branches every sibling screen has. `LoadingState shape="list"`,
`ErrorState` with a retry, and the `students.empty` object that is already translated.

---

#### F23 · The review screen loads every image eagerly

Two image sources on the densest screen, neither lazy and neither virtualised:

```tsx
<img src={imageSrc} alt={imageAlt} className="block h-auto w-full select-none" … />
//  ScanReviewOverlay.tsx:132 — the full registered page, one per PageCard
<img src={detection.crop_url} alt={…} className="mt-1 block w-full …" />
//  OpenAnswerCard.tsx:98 — one per written answer
```

`visiblePages.map` renders every page in the pile at once (`scans/[scanId]/page.tsx:472`).
A thirty-page pile with four open items each is thirty full-page PNGs plus 120 crops, all
requested on mount, all from presigned object-store URLs. The only `loading="lazy"` in the
whole app is on the exercise picker's figure thumbnails (`ExerciseRow.tsx:82`), so the
pattern is known.

There is a second-order effect worth naming: those presigned URLs are valid for 900 s
(Phase 3 L3). Loading all of them at mount means 150 URLs for children's handwriting are
minted at once, and a teacher who leaves the tab open past fifteen minutes gets broken
images rather than a re-signed fetch.

The `md`+ layout does mitigate the perceived cost — the overlay is `lg:sticky` beside a
scrolling item list — but the bytes are requested regardless.

**Fix:** `loading="lazy"` on both, which is one attribute each and covers the realistic
worst case. Virtualisation of the page list is not worth it at thirty; it would be at 120,
which the API's upload cap allows.

---

#### F24 · No connection-state signalling

`ApiError.isOffline` exists and is never read (F5's twin). There is no online/offline
listener, no service worker, no queueing, no "vous êtes hors ligne" banner. A network drop
surfaces as `errors.code.network_error` — *"L'application n'a pas pu joindre le serveur."* —
inside whichever screen happened to be fetching, and disappears again on the next successful
poll with nothing recording that it happened.

The brief asks whether the app is honest about connection state. It is honest per-request
and silent overall. On school Wi-Fi, per-request honesty means a teacher sees a failure
sentence flash on one card while the rest of the screen looks fine.

**Fix:** a single connection-state hook on `navigator.onLine` plus a "last request failed
with `network_error`" flag, rendered as one persistent bar in `AppShell`. Cheap, and it
turns a confusing screen into a legible one.

---

#### F25 · The one hand-rolled poll is the one that misbehaves

Every other poll in the app goes through react-query's `refetchInterval`, which by default
does not fire while the tab is hidden, and all of them stop on a terminal state — the scan
poll stops on a terminal status *and* keeps looking while any detection is `pending`
(`queries.ts:795-803`); `useJob` stops on `isTerminal` (`:1070-1073`); `useFeedback` polls
only while its job is in flight. That is careful work.

`/sources` does it by hand:

```tsx
const pending = (data ?? []).some((s) => s.status === 'queued' || s.status === 'running');
useEffect(() => {
  if (!pending) return;
  const id = setInterval(() => void refetch(), 2000);   // sources/page.tsx:40-44
  return () => clearInterval(id);
}, [pending, refetch]);
```

It cleans up on unmount, which is the important half. It does not pause on blur, and it has
no give-up condition — and Phase 3 B9 says there is no stale-job reaper, so a hung ingest
leaves a source `RUNNING` forever. A staffroom laptop left open on `/sources` over a weekend
polls the API every two seconds for sixty hours.

**Fix:** move it into the query, where every other poll already lives:
`refetchInterval: pending ? 2000 : false`.

---

#### F26 · No component workbench

There is no Storybook, Ladle, or equivalent. `packages/ui` ships 36 primitives and 18 domain
components with no isolated render surface. Their only visual coverage is 36 Playwright
screenshots (`e2e/locales.spec.ts-snapshots`, `e2e/themes.spec.ts-snapshots`) of two
screens — `/` and `/classes` — across three locales, two viewports and four display modes.

That is a real regression net for the shell and it covers none of the primitives directly.
`Stepper`, `Slider`, `CodeInput`, `Popover`, `Toast`, `Avatar`, `Breadcrumb`,
`MasteryCurve`, `BandHistogram`, `CelebrationOverlay` and `ProvenancePanel` have no visual
coverage in any state. There are two unit tests in the package
(`MasteryBandTag.test.tsx`, `mastery.test.ts`, `recipes.test.ts`) and they test the
band-rendering rules — the right things to test, and not a substitute for seeing the
components.

**Fix:** the cheapest version that pays for itself is a single `/_gallery` route in the web
app, gated on `NEXT_PUBLIC_ALPPY_MOCK`, rendering every primitive in every state, with one
Playwright screenshot per theme. That reuses the fixture layer and the screenshot harness
that already exist.

---

#### F27 · The only import path is pasting a roster, and there is no establishment creation

`RosterInput.parseRoster` is thoughtful — it accepts `Nom, Prénom`, tab- and
semicolon-separated columns, and bare `Prénom Nom`, and it explicitly refuses to normalise
beyond trimming because *"a name is the teacher's data, not ours to clean up"*. That is the
right paste target.

It is the only one. No CSV file upload, no cantonal export format (no LAGAPES, CLOEE or
equivalent), no LDAP/AAI. And `POST /schools` exists in the API with nothing in the client
calling it: a teacher gets an establishment from the seed or from someone with database
access. `SchoolSettings` can rename one and cannot create one.

**Cold start, measured.** From an account that already has a school: create class (type
code, optional label, paste roster, submit) → 1 screen, ~4 interactions. Add a discipline if
the seed did not (settings → add branch) → 2 screens. Upload a textbook and wait for
ingestion → 1 screen plus an unbounded wait. Build a sheet → 1 screen, ~10 interactions.
Render and print → 2 clicks. So roughly **four screens and ten minutes of interaction plus
one ingestion wait** to first useful output, assuming the establishment exists. That is
good. The gap is the assumption.

---

#### F28 · The PER hierarchy is two levels because the data is two levels

`CurriculumTree` renders Branch → Competence → Theme, with the official code in mono
(never coloured — *"Official curriculum data is NEVER coloured"*), the full PER wording on
its own line because it is a whole sentence, a band on every node, and coverage shown only
when incomplete. The component is right, and the codes are real: the seed carries
`MSN 31`–`MSN 35` with `MSN 31.1`-style children and the CIIP wording.

What it cannot show, because the model does not carry it (Phase 1 H1–H3): *attentes
fondamentales*, the per-year progression (9e/10e/11e), the PER's own `Niv. 1/2/3`
differentiation, and any marker separating official CIIP codes from invented ones. A teacher
looking for "what a 10e pupil must be able to do by the end of the year" — which is the
thing the PER is consulted for — will not find it here.

This is a propagation, not a frontend defect, and I record it so the frontend work that will
be needed is visible when Phase 1 H1 is scheduled: two more levels in the tree, an
*attentes* view, and a year dimension that interacts with F8's.

---

### Low

---

#### F29 · The printed feedback page carries the group label

`FeedbackCopy` carries `group_label` and it goes into the page's header meta line:

```python
if copy.group_label:
    meta_parts.append(copy.group_label)      # alppy/sheets/html.py:670
```

producing a header like `9VG2 · Mathématiques · 12.03.2027 · Groupe 2 · Fractions
équivalentes`. See §4 for the analysis; the short version is that the *blank worksheet* does
**not** carry it (`Copy` is constructed without a note at `render.py:599` and `:613`) and
the feedback page does.

---

#### F30 · Dead catalogue text and a type for a field that does not exist

`errors.notFound.{title,body,action}` is translated in all three catalogues and referenced
nowhere — it is the copy for the `not-found.tsx` that F6 says is missing, written and never
wired. `lib/api/types.ts:150` declares `school_year_id?: Uuid | null` on a client type; no
endpoint in the surface sends or accepts it (`grep -rn "school_year" apps/api/alppy/api/`
is empty). Both are small, and both are the residue of work that was designed and not
finished — worth clearing so the next reader does not assume the feature exists.

---

#### F31 · `docs/plan.md` §5 is the only screen inventory and it lists half the screens

§5 lists eleven screens; twenty-four `page.tsx` files exist. The extras — `/results`,
`/timeline`, `/classes/[classId]/teaching`, `/classes/[classId]/themes/[chapterId]`,
`/classes/[classId]/competences/[competencyId]`, `/classes/[classId]/roster`,
`/classes/new`, `/settings/branches/[subjectId]`,
`/classes/[classId]/students/[studentId]/sheets/[sheetId]` — are all real, all reachable and
several are load-bearing. The plan is stale in the safe direction (it under-promises) but it
is the only document that enumerates screens at all, so a reader looking for the surface
will find half of it. `docs/features/*/architecture.md` documents the subsystems well and
does not enumerate routes.

---

#### F32 · Stray markup

`classes/[classId]/roster/page.tsx:75` — an empty `<div>` with trailing whitespace between
the `<section>` and its `<ul>`, presumably where a heading used to be.

---

## 4 · Student-dignity and disclosure risks

The brief asks for these separately, and this section is where the product is most
interesting: the *data* discipline is excellent and the *display* discipline has one large
hole.

### What is already right, and deliberately so

**No name ever reaches a model provider, and the frontend enforces it at the fetch layer,
not just the prompt layer.** The clearest evidence is a comment on a hook that is *not*
called:

```tsx
// `ClassOut.student_count`, not the roster. This slider needs one integer,
// and `useStudents` answers with every child's first name, last name, uid
// and class codes — on the one screen whose entire design keeps names away
// from a model … Fetching the names here to read `.length` put them in the
// page's cache for no reason at all.
const klass = useClass(classId || null);          // adaptive/page.tsx:185
```

The adaptive screen — the only screen that talks to a provider — never loads a roster. Every
pupil on it is a UID: the group chips (`:888`), the per-student plans (`:953`), the move
hint (`:855`), the failure lines (`:1045`). A teacher can work that entire screen, project
it, and screenshot it without a single child being named.

**No student personal data in any URL.** Every route parameter is a UUID
(`/classes/{uuid}/students/{uuid}/sheets/{uuid}`); every query parameter is a UUID or a
filter enum (`?class=`, `?subject=`, `?competency=`, `?chapter=`, `?job=`, `?from=`). No
name, no email, no UID. `Referrer-Policy: strict-origin-when-cross-origin` is set explicitly
with a comment naming the reason — the student UUID in the path would otherwise travel to
the object store in `Referer` on every scan crop (`lib/csp.ts:108-111`). The one identifier
that does travel in a query string is `DELETE /students/{id}?confirm=7B_15`, which is
Phase 2 M9 and is a pseudonymous class position rather than a name.

**Tokens are in an HttpOnly cookie.** `localStorage` holds two things and both are ids:
`alppy.scope` (`{classId, subjectId}`) and `alppy.mock`. Nothing authenticating, nothing
identifying a child. On a shared staffroom or projector machine, the exposure from
`localStorage` is which class the last teacher was looking at.

**The printed worksheet does not carry a placement.** I checked this specifically because it
is the one that would be worst. `build_sheet_data` constructs each `Copy` without a note
(`render.py:599`, `:613`), so a differentiated blank sheet's header is
`9VG2 · Mathématiques · 12.03.2027` and its footer is `page 1/2 · 9VG2_15 · layout v1`.
Two pupils comparing worksheets see different exercises and no label telling them why. That
is the correct design and it was clearly deliberate.

### The hole: no projector mode — **High**

Teachers project. The product knows it — `DESIGN.md:135` says `display-l` is the "floor in
projector mode" — and nothing implements one. The settings screen offers theme, contrast,
reduced motion, and *mode lecture* (which hides decorative illustrations). Nothing hides
identity.

What is on screen on each surface a teacher plausibly displays:

| Screen | What a pupil in the third row can read |
|---|---|
| `/classes/{id}` | The full roster crossed with competencies, five colour bands per cell |
| `/classes/{id}/students` | `NOM Prénom` per row, plus *the weakest band the pupil has been assessed on*, sorted worst-first (`students/page.tsx:99-104`) |
| `/results` | Points per pupil per sheet, and a total column |
| `/adaptive` | Four groups by UID — and a class knows its own UIDs, because they are printed on their sheets |
| `/scans/{id}` | Each page's UID, its crops of a pupil's handwriting, and its low-confidence items |

The roster screen is the sharpest of these, because it is not a matrix a pupil has to
decode — it is a list, sorted worst-first, with a named colour-and-word band beside each
name. It carries an honest caption (*"La bande indiquée est la compétence la plus faible
déjà évaluée — un ordre de priorité, pas une note globale"*), which helps the teacher and
does nothing for the pupil reading their own name at the top of the list.

The adaptive screen is the one the brief names — a pupil seeing they were placed in the
lowest of eight groups. The mitigation there is real but partial: the partition is by
*principal gap*, not by ability rank, and the label names a competency
(`Groupe 2 · Fractions équivalentes`), so a pupil in group 4 and a pupil in group 1 cannot
rank each other. Where it does leak is a *split*: `cluster_students` splits an over-large
bucket "by how badly" (`adaptive_service.py:1015-1019`), so `Groupe 2 · Fractions` and
`Groupe 3 · Fractions` are the same gap ordered by severity. Two pupils with the same
competency in their label can read their relative placement off the number.

**The fix**, and it is not expensive if it is designed before the rest of the UI is built:
a `discreet` display preference alongside `contrast`, `motion` and `calm` — the plumbing is
already there (`lib/display.ts`, `ThemeScript`, a `data-*` attribute applied before paint,
persisted server-side through `TeacherPreferences`). In that mode: names collapse to UIDs
across the roster, matrix and results; group labels drop the competency and keep the number;
per-pupil bands and points hide behind an explicit reveal. A keyboard toggle, because a
teacher realises they need it while the projector is already on.

### The smaller one: the feedback page carries the group label — **Low/Medium**

`FeedbackCopy` carries `group_label` into the header meta (`html.py:670`), so the *third*
PDF — the one handed to pupils alongside the worksheet — reads
`… · Groupe 2 · Fractions équivalentes`. Everything said above about splits applies, and
here it is on paper that stays in a bag.

The competency half is arguably a feature — a pupil should know what their feedback is
about. The group *number* is what carries no information for the pupil and all the
information for their neighbour. Dropping the number and keeping the competency name costs
nothing.

### Two smaller notes

- **Scan crops are children's handwriting on 900-second presigned URLs**, loaded eagerly and
  in bulk (F23, Phase 3 L3). Nothing here is the frontend's fault; the frontend's
  contribution is requesting 150 of them at once.
- **`DetectionOut.vision_model` crosses to the client** (Phase 2 L2) and, to the frontend's
  credit, is rendered nowhere. The screen shows an `AiBadge` reading *"Lu par l'IA"* instead,
  which is the right amount of provenance for a teacher.

---

## 5 · Print fidelity assessment

**Verdict: the server-PDF path can be trusted. The browser-print path cannot, and the UI
does not distinguish them.**

The good news first, because most of this chain is built correctly and I want the
distinction to be legible.

### The chain that holds

```
alppy/sheets/layout.py  ──scripts/export-layout.py──▶  packages/shared/layout.generated.ts
        │                        (CI: regenerate + git diff --exit-code)          │
        │                                                                          │
        ├──▶ templates/geometry.css.j2 ──┐                                        │
        │                                 ├──▶ the print document ──▶ Chromium ──▶ PDF
   packages/ui/src/design/print.css ──────┘                              │
        │                                                                 ├──▶ measure_answer_boxes
        └──▶ (also loaded by the web app for the on-screen print styles)   │
                                                                           ▼
                                                              AnswerBoxPlacement (mm)
                                                                           │
  photo ──▶ register on 4 fiducials ──▶ canonical frame ──▶ crop at those mm ──▶ VLM
                                              │
                    apps/web  ScanReviewOverlay draws boxes in the SAME frame,
                    from SHEET_LAYOUT.frame — not from the page
```

Every link in that diagram is deliberate and several carry a comment explaining the failure
they prevent:

- **§20 — coordinates share a source of truth.** `layout.py` is the origin; the TypeScript
  is generated from it and CI regenerates and diffs it on every push
  (`.github/workflows/ci.yml`, the *Regenerate and diff* step). The review overlay converts
  the detector's frame-relative coordinates using `SHEET_LAYOUT.frame`, with a comment
  spelling out the trap: *"the frame is not the page: on A4 it runs 18–192 mm across a
  210 mm sheet. Taking one for the other puts every box one to two bubble pitches out."*
  Nothing is re-derived by hand.
- **§21 — fiducials exist and are drawn as borders.** Four 8 mm squares at
  (18,18)/(192,18)/(18,279)/(192,279), drawn with `border: calc(var(--print-fiducial)/2)
  solid currentcolor` explicitly *"so they survive the browser's default 'do not print
  background graphics' setting"*, and forced visible again in the `@media print` block.
  Registration corrects skew and uniform photocopier scale.
- **§19 — A4, explicitly.** `@page { size: A4; margin: 14mm }`, and the page box is
  `width: var(--print-page-w)` with `min-height: var(--print-page-h)` from the generated
  geometry. Not Letter.
- **§25 — no MathJax, no KaTeX, no SVG math.** There is no math renderer anywhere in the
  repo. Statements are text. So the height-variance failure mode the brief asks about does
  not exist today — and this is exactly why F2 matters, because *font* metrics are then the
  only thing that can move a line, and they are unpinned.
- **§22 — no QR, by design, with a human-readable fallback.** Identity is a 32-bit
  checksummed pre-filled bubble grid at (120,30) plus the UID printed as text beside it
  (`print.print-uid-text`), plus the UID in the footer of every physical page. Phase 1 L1
  and Phase 3 B4 cover what the code does *not* encode (no sheet, no print run, no page
  number, no school year), which is a real misattribution risk and is not the frontend's.
  The layout's own answer to "what if the code fails to decode" is the printed text and the
  manual-assignment control on the review screen — which works, except for F11's case.
- **§24 — the preview is the print document.** Not an approximation:
  `GET /sheets/{id}/preview` returns the same markup `render_sheet_html` gives Chromium, and
  the client renders it in an iframe rather than re-implementing it. The comment records
  what it replaced: *"a hand-rolled React approximation: it put the answer bubbles inline
  beside each option instead of on the fixed grid the detector reads, printed no UID grid at
  all, and hardcoded A/B/C/D where the sheet prints V/F."* This is the single best decision
  on the print path.

### The chain that does not hold

**Assumption 1 — that the paper came from the render job.** *Broken.* F1: **Imprimer** prints
the preview frame and records the sheet as printed. `AnswerBoxPlacement` rows are written
only by `render_sheet`. A sheet with open items can go to a class with no placements at all,
and every written answer on it returns `NOT_GRADEABLE`.

**Assumption 2 — that the engine that measured the boxes is the engine that printed them.**
*Broken on the same path.* Placements are measured by the API's Chromium under `@page`;
browser-printed paper is laid out by the teacher's browser under the teacher's print dialog,
whose Margins and Scale controls the app cannot see and whose "Fit to page" default some
printers apply regardless. Bubbles survive this (fiducial-relative, uniform scale cancels);
answer boxes, stored as absolute page millimetres against a text flow, do not.

**Assumption 3 — that text wraps the same way everywhere.** *Broken on every path.* F2:
there is no `@font-face` in the printed document. `'Nunito Variable'` is not available to
the API container, to the preview iframe, or to the print. Each falls back independently. A
statement that wraps to four lines in one and three in another moves its box by one 8 mm
line pitch — inside the `ITEMS_TOP_MM..ITEMS_BOTTOM_MM` guard, so nothing raises. Along the
server-PDF path measure and print happen in one process, so this cancels *today*; it stops
cancelling the moment the container's font set changes or the browser-print path is used.

**Assumption 4 — that the teacher checked the preview before printing.** *Broken in the
shipped default stack.* The CSP sets `frame-src 'self'` (`lib/csp.ts:81`), and
`docker-compose.yml:199` defaults `NEXT_PUBLIC_API_BASE_URL` to
`http://localhost:8000/api/v1` — a different origin from the web app on :3000. The iframe is
blocked. `SheetPreview`'s error path only inspects a `fetch` to the same URL, and
`connect-src` *does* include the API origin, so the fetch succeeds, no error renders, and the
teacher sees a blank white A4 rectangle. `contentWindow.print()` on a cross-origin frame then
throws, and `printPreview` falls through to `window.open`, which does work. So in the default
stack the preview is blank and printing still happens — the worst combination.

This is folded into F1 rather than given its own ID because the fix is in the same place, but
it deserves naming: **the one pre-print check the product offers is blank in the stack
CLAUDE.md advertises as "whole stack + demo seed, one command".**

**Assumption 5 — that a sheet is not edited after printing.** *Broken upstream.* Phase 3 B7:
every render deletes and rewrites the sheet's `AnswerBoxPlacement` rows
(`render.py:668`). A re-render after printing moves the rectangles a later crop cuts from an
already-photographed page. The frontend contributes to the exposure — **Générer le PDF** is
an always-enabled primary button on the sheet detail screen with no warning that the sheet
has been printed, even though `SheetOut` carries the fact and `docs` describe
`SHEET_PRINTED` as the moment that matters.

### What must hold, stated as a list

For a written answer's grade to be trustworthy, all of these must be true, and today the UI
guarantees none of them:

1. The paper came from `render_sheet`, not from the browser.
2. No re-render happened between that render and the photograph.
3. The rendering environment's font metrics at measure time equal its metrics at print time.
4. The printer applied no scale-to-fit and no margin override — or, if it did, it applied
   the same one to the fiducials and the content (true for a uniform scale, false for a
   margin shift that crops).
5. The photograph shows all four fiducials.

(5) is checked and reported to the teacher. (4) is largely absorbed by registration. (1),
(2) and (3) are unchecked, and (1) is actively undermined by a button.

**The smallest set of changes that closes it:** inline the fonts (F2); make **Imprimer**
render when placements are stale and print the PDF (F1); refuse to re-render a printed sheet
without an explicit confirmation that names the consequence (Phase 3 B7's client half); and
stamp the layout version *and a placement generation id* on the page footer, so a scanned
page can be checked against the placements it was actually printed with rather than the ones
that exist now. The footer already carries `layout v1`; it has room.

---

## 6 · Route tree and component inventory

### Routes as actually registered

All routes live under `app/[locale]/`, `localePrefix: 'always'`, locales `fr | de | en`.
The single guard is `middleware.ts`: it checks for the *presence* of the `alppy_session`
cookie and redirects to `/{locale}/login?from=…` otherwise. There are **no role guards**,
because the contract has no roles. Two escape hatches bypass the guard entirely:
`NEXT_PUBLIC_ALPPY_MOCK=1` (fixture mode) and `NEXT_PUBLIC_ALPPY_DEMO_MODE=1`, both
documented in the middleware with their reasons.

| Route | Guard | What it is |
|---|---|---|
| `/[locale]` | session | Home: classes, per-class band shape, pupils needing attention |
| `/[locale]/login` | **public** | The only public route. Chromeless (`AppShell` returns bare `<main>`) |
| `/[locale]/classes` | session | All classes |
| `/[locale]/classes/new` | session | Create a class and paste a roster, one screen |
| `/[locale]/classes/[classId]` | session | Class dashboard: roster + mastery matrix + tree |
| `/[locale]/classes/[classId]/roster` | session | Paste more pupils; edit/delete one (**no states — F22**) |
| `/[locale]/classes/[classId]/students` | session | Roster list, worst band first |
| `/[locale]/classes/[classId]/students/[studentId]` | session | Pupil profile: rings, curve, history |
| `/[locale]/classes/[classId]/students/[studentId]/sheets/[sheetId]` | session | One pupil's copy of one sheet |
| `/[locale]/classes/[classId]/teaching` | session | Who teaches which Branch here (D75) |
| `/[locale]/classes/[classId]/themes/[chapterId]` | session | One Theme: its sheets and its band |
| `/[locale]/classes/[classId]/competences/[competencyId]` | session | One Competence, drilled |
| `/[locale]/sheets` | session | Sheets, grouped draft / ready to print |
| `/[locale]/sheets/new` | session | The builder: two tabs, three columns |
| `/[locale]/sheets/[sheetId]` | session | Print preview (blank + key), render, download |
| `/[locale]/scans` | session | Piles |
| `/[locale]/scans/new` | session | Choose sheet, photograph or upload |
| `/[locale]/scans/[scanId]` | session | **The review screen** |
| `/[locale]/adaptive` | session | Differentiation: propose, group, approve, export |
| `/[locale]/sources` | session | Textbooks: upload, ingestion status |
| `/[locale]/results` | session | Points per pupil per sheet |
| `/[locale]/timeline` | session | The agenda, by day, filterable |
| `/[locale]/settings` | session | School nouns, language, appearance |
| `/[locale]/settings/branches/[subjectId]` | session | One Branch: its Themes and its textbooks |

**Missing route files:** no `error.tsx`, no `global-error.tsx`, no `not-found.tsx`, no
`loading.tsx` anywhere (F6). The fourteen `layout.tsx` files are all `generateMetadata`
wrappers except `[locale]/layout.tsx`, which owns `<html>`, the theme script, the providers
and the shell.

### Components

**Pages (24)** — listed above. Largest and their responsibilities:

| File | Lines | Responsibilities |
|---|---|---|
| `adaptive/page.tsx` | 1 065 | Parameters · propose job · plan mutation (regenerate/discard/edit/append) · group partition + teacher moves · feedback sub-flow · approval gate · export chain · downloads. **Seven, at least** |
| `scans/[scanId]/page.tsx` | 815 | Poll · queue ranking · filters · keyboard queue · confirm/reopen · `PageCard` · `DetectionRow` · overlay mapping. Three components in one file, cohesive |
| `classes/[classId]/teaching/page.tsx` | 486 | Declared vs taught branches · assign/unassign · reorder · confirm |
| `sheets/new/page.tsx` | 445 | Theme root · two source tabs · draft · preview columns · create |
| `classes/[classId]/students/[studentId]/page.tsx` | 425 | Profile: rings, curve, tree, attempt history |
| `sheets/[sheetId]/page.tsx` | 401 | Metadata panel · render job · two preview frames · print · downloads |
| `classes/[classId]/page.tsx` | 395 | Roster + matrix + tree + drill-down |

**App components (23)**

| Kind | Components |
|---|---|
| Shell | `AppShell` (173), `Providers` (45), `ThemeScript` (33), `ScopeSwitcher` (141) |
| Feature | `CurriculumTree` (206), `OpenAnswerCard` (223), `AdaptiveItem` (166), `CellDrillDown` (146), `CompetenceThemeFilter` (149), `SchoolSettings` (201), `StudentEditor` (125), `FeedbackNoteCard` (69), `ConfirmDestructive` (114), `LockedValue` (21) |
| Builder | `SheetComposer` (666), `ExercisePicker` (406), `AddExerciseModal` (364), `SectionPicker` (245), `ProposeTab` (194), `DraftPreview` (173), `ThemePicker` (143), `ExerciseRow` (109), `useDraftSheet` (336, a hook) |

**Library primitives (36)** — `Avatar Badge Breadcrumb Button Card Checkbox Chip CodeInput
Divider EmptyState ErrorState Field FileDrop IconButton Input KeyboardHint LoadingState
Modal Panel Pill Popover Radio RosterInput SegmentedControl Select SelectSurface Sheet
Skeleton Slider Spinner Stepper Tabs Textarea Toast Toggle Tooltip`. Largest: `Toast` (188),
`LoadingState` (174), `Field` (159), `FileDrop` (144).

**Library domain components (18)** — `AiBadge AttemptList BandHistogram CelebrationOverlay
ConceptTag ConfidenceBar MasteryBandTag MasteryCell MasteryCurve MasteryLegend MasteryMatrix
MasteryMeter Matrix PointsCell PointsMatrix ProgressRing ProvenancePanel ScanReviewOverlay`.
Largest: `Matrix` (231), `ScanReviewOverlay` (185), `MasteryCell` (184).

**Brand (3)**, **icons (49)**, **illustrations (7)**, **design CSS (5 files, 1 556 lines)**.

### Design artefacts found

| Artefact | Date | Does the code match it? |
|---|---|---|
| `docs/design/Alppy-identite-visuelle.pdf` (8 A3 plates) | 2026-09-05 | Yes for the identity: `AlppyMark` is the two slopes and the smile, no mandarin accent; pictogram stroke is 2.2 |
| `docs/design/alppy-brand-assets/brand/alppy-mastery-tokens.css` | 2026-09-05 | Yes, verbatim — `--c-mastery-ok: #86cf5b`, glyph colours and computed background opacities all present in `tokens.css:84-108` |
| `docs/design/Craie-Alpine-philosophie.md` | 2026-09-05 | Not directly testable; the constraint file is the operative document |
| `DESIGN.md` | 2026-09-09 | Yes, except `display-l` "floor in projector mode" (F3) |
| `docs/design/constraints.md` (numbered `DC-*`) | 2026-09-09 | Yes — components cite the ids they exist because of (`DC-colour-06/08`, `DC-shape-01`, `DC-content-07`) and CI enforces the mechanical half |
| `docs/plan.md` §5 (screen list) | earlier | **Stale** — 11 screens listed, 24 exist (F31) |
| `docs/plan.md` §9 (responsive spec) | earlier | Yes, and the e2e suite asserts against it (`data-matrix-scroll`) |
| `docs/features/*/` (13 × README + architecture + decisions) | 2026-09-09 | Current; text architecture docs, not visual artefacts |
| `docs/reviews/F{1,2,3,4,7}-review.md` + `-fixes.md` (11 documents, 256 KB) | reviewed 2026-09-06, filed 2026-09-10 | **The most substantial visual record in the repo.** Independent per-feature reviews, each with a verdict, P0–P3 findings, repro steps and file:line, paired with a fixes document. All five are marked fixed or superseded |
| `docs/reviews/screenshots/` (338 PNGs across 11 directories, before/after per feature) | 2026-09-06 → 2026-09-10 | The evidence behind those reviews. Not assertions; `builder-shots.spec.ts` regenerates the builder set on `ALPPY_SHOTS=1` |
| `apps/web/e2e/*-snapshots/` (36 PNGs) | live | The only *asserting* visual spec: `/` and `/classes` × 6 display modes + 3 locales × 2 viewports |

**There are no wireframes, mockups, Figma exports or flow diagrams.** The design record is
prose, a shipped brand library, a per-feature adversarial review record with 338 screenshots,
and a 36-shot regression net. That is a defensible choice for a solo-built product (§11), it
means there is no stale-wireframe problem — which the brief notes is worse than none — and it
largely explains the quality of what is here: most of this code has already survived a review
pass that recorded what it found and what it changed.

**Caveat, and it matters for reading §2:** those reviews are dated 2026-09-06 and all five
are marked resolved. I cross-checked my Critical and High findings against them
(§13.9). F5 turns out to be a *half-taken* fix from that record rather than a new find —
`F7-review.md:178-196` reports exactly this defect, names `ApiError.isUnauthorized` as having
zero callers, and recommends *"Guard in middleware on the session cookie, **or** a client
boundary that redirects on `isUnauthorized`"*. `F7-fixes.md:105-115` took the first half. The
second half is still open, and it is the half that covers a session expiring mid-task. F1,
F2, F3, F4, F6, F8 and F9 appear nowhere in the review record.

---

## 7 · Flow walkthroughs — the two under pressure

### Flow A · Differentiated sheets in a free period (target: 10 min)

Teacher: one class of 24 already in the system, one corrected common sheet.

| # | Action | Interactions | Elapsed | Can it fail? |
|---|---|---|---|---|
| 1 | Reach `/adaptive` | 1 desktop (rail) / 2 phone (`adaptive` is **not** a primary tab — `AppShell.tsx:54`) | 0:05 | — |
| 2 | Items per student (slider, default 8) | 0–1 | 0:10 | — |
| 3 | Mode → *Par groupe* | 1 | 0:15 | — |
| 4 | Group count (slider) | 1 | 0:25 | — |
| 5 | Source sheet (select) | 2 | 0:35 | List is scoped to the class — good |
| 6 | **Proposer** | 1 | 0:40 | Per-school in-flight dedup can hand back a colleague's job (Ph2 C1) |
| 7 | **Wait** | 0 | **?** | 24 sequential provider calls, no timeout (Ph3 B10), 600 s job cap. **No progress, no estimate, no cancel** (F13). Leaving the page loses the run (F4) |
| 8 | Read the plan; move 2–3 pupils between groups | 4–6 | +0:40 | Moves are local; a re-propose drops them (correctly, and it says so) |
| 9 | **Approuver les N exercices** | 1 | +0:05 | Server-enforced too |
| 10 | *(optional)* Generate feedback | 1 | **?** | Another job, another unbounded wait, another orphanable id |
| 11 | *(optional)* Approve all notes | 1 | +0:05 | Blocks export until done — correct |
| 12 | **Exporter le lot** | 1 | 0:00 | Chains `batch` → `render`; ~170 pages through Chromium |
| 13 | **Wait** | 0 | **?** | Job polled; no progress shown on this screen either |
| 14 | Download blank + key (+ feedback) | 2–3 | +0:10 | — |

**Interactions: 16–21. Elapsed: 2 minutes of work plus two unbounded waits.**

**Verdict: does not fit, and the reason is not the click count.** Two waits of unknown
length, neither with a progress indicator, and the teacher cannot leave the page during
either. The screen's own instruction for the analogous scan case — *"Gardez cette page
ouverte"* — is the honest description of this flow too, except here nothing says it.

**Failure points, in order of likelihood:** the teacher closes the laptop and loses the run
(F4); the propose returns a colleague's plan (Ph2 C1); a subset of pupils fails generation
and can only be retried by re-proposing the whole class (F13); the 600 s job cap fires on a
class of 28.

**What would make it fit:** the job id in the URL, a progress ring reading
`proposeJob.data.progress`, and a way to come back to a finished proposal. None of the three
is architecturally hard — the scan flow already does all three.

### Flow B · Reviewing a scanned batch between lessons (target: 10 min)

Teacher: 30 copies of a printed sheet, photographed on a phone.

| # | Action | Interactions | Elapsed | Can it fail? |
|---|---|---|---|---|
| 1 | `/scans/new` (a primary bottom tab on phone) | 1 | 0:05 | — |
| 2 | Choose the sheet | 2 | 0:15 | Only `rendered_at != null` sheets offered — good, and it is also the check F1 routes around |
| 3 | Photograph 30 copies, or pick a scanner PDF | 30 shutter / 1 pick | 3:00 / 0:10 | — |
| 4 | Upload | 0 (auto) | 0:30–3:00 | **One atomic multipart. A drop loses everything** (F10) |
| 5 | Auto-redirect to `/scans/{id}?job={jobId}` | 0 | — | Job id in the URL — the pattern F4 wants |
| 6 | Watch processing | 0 | 1:00–3:00 | `ProgressRing` with a real percentage, honest queued/reading wording. **This is the model** |
| 7 | Press **N**, correct, repeat | ~1 keystroke + 1 click per uncertain item | 2:00–4:00 | Queue is `multiple` → least-confident → settled. Each correction is its own mutation and is saved immediately |
| 8 | Assign each unidentified page | 3 per page | +0:30 each | Only works if the page *registered* (F11) |
| 9 | Re-shoot unregistered pages | — | — | **No path.** Discard, or start a second pile (F11) |
| 10 | **Valider les résultats** | 1 | 0:05 | Blocked while written answers are pending, counted over unfiltered pages — exactly right |
| 11 | Read the confirmation | 0 | 0:10 | Reports attempts, pupils, and skipped items in warn colour |

**Interactions: ~40–60 (mostly one-key/one-click). Elapsed: 6–11 minutes.**

**Verdict: fits, for a clean pile.** This screen is the best-designed surface in the product
and the reason the answer to the brief's overall question is not simply no. Low confidence
first, one keystroke to walk the queue, the registered page beside the reading, the machine's
verdict kept beside the teacher's, one click to overrule, and everything persisted as it
happens.

**Failure points:** the upload drop (F10) — the single most likely thing to cost ten minutes;
3 of 30 pages failing registration, which forks the pile (F11); a session expiring mid-review
and reporting *"L'envoi a échoué"* on every subsequent correction (F5); and a pile whose
written answers were printed from the preview, in which case step 11 reports 120 skipped
items with no explanation (F1).

---

## 8 · State management map

### What lives where

| Layer | Holds | Where |
|---|---|---|
| **URL (path)** | class, student, sheet, scan, chapter, competency, subject-in-settings, locale | route params |
| **URL (query)** | `?class`, `?subject`, `?competency`, `?chapter`, `?job` (scans only), `?from` (login) | `lib/scope.tsx`, `useSearchParams` |
| **`localStorage`** | `alppy.scope` = `{classId, subjectId}`; `alppy.mock`; display prefs (`lib/display.ts`) | fallback only — the URL wins |
| **Server (cookie)** | the session; `TeacherPreferences.locale` and display prefs mirrored server-side | HttpOnly, 12 h |
| **Query cache** | **all** server state, no exceptions found | `@tanstack/react-query`, `staleTime: 30 s`, `refetchOnWindowFocus: false`, no retry on 401/404 |
| **Context** | exactly one: `ScopeProvider` — class, subject, school, competency, chapter, and the setters | `lib/scope.tsx` |
| **Component state** | view concerns (filters, selection, expansion, tab), form drafts, **and two things that should not be there** | `useState` |

**The de facto rule, and it is coherent:** server state lives in the query cache and is read
through a hook in `lib/api/queries.ts`; client state that a link must carry lives in the URL;
client state that is a *way of looking* lives in the component. `ScopeProvider` is the one
exception and it earns it with a stated reason — *"a teacher sends a colleague a link to a
matrix, and a context that lived only in memory or in localStorage would open somebody else's
default instead"* — and it holds ids, never entities.

**Violations of that rule:**

1. `adaptive/page.tsx:114` — `plan` is server state copied into `useState`. The comment
   defends the copy (*"an edit, a regeneration or a discard rewrites the plan in place, and
   the query holds a megabyte it would be pointless to re-fetch"*), which is a fair argument
   for a local working copy. What is *not* defensible is that the address of the server
   original — `proposeJobId` — is local too (F4).
2. `adaptive/page.tsx:124` — `approvedIds`. The comment is emphatic that this must reflect
   the database (*"Not a local flag: the export gate has to reflect a fact about the
   database"*) and then stores the server's answer in `useState` anyway, where a reload
   loses it and the export gate re-arms.
3. `sources/page.tsx:40-44` — a poll outside the query layer (F25).

### Invalidation rules, as written

`queryKeys` (`queries.ts:83-160`) is one object, and every filter variant is spelled into the
key so a prefix invalidation is exact. That is the single best structural decision in this
layer.

| Mutation | Invalidates | Correct? |
|---|---|---|
| `useLogin` | **everything** (`invalidateQueries()` with no key) | Yes, and the comment says why: queries that ran while logged out failed 401 and are never retried |
| `useLogout` | `client.clear()` | Yes |
| `useSwitchSchool` | `client.clear()` + drops `alppy.scope` | Yes — *"every cached id in the client belongs to the school we just left"* |
| `useConfirmScan` | `scan`, `home`, `['sheets']`, `['classes']`, `['students']` | Yes. The two broad prefixes are deliberate: *"a pile of copies can carry more than one class's worth of paper"* |
| `useReopenScan` | identical set | Yes — same numbers, other direction |
| `useCorrectDetection` / `useAssignScanPage` / `useDiscardScanPage` / `useRevertDetection` | `scan(scanId)` | Yes — nothing else moves before confirmation |
| `useDeleteStudent` | `students`, `klass`, `classes`, `home`, `classMastery(classId, {})` | Yes. The last line looks too narrow — `classMastery(classId, {})` is a fully-qualified six-element key, so on its own it would match only the unfiltered roster-sorted matrix — but `queryKeys.klass(classId)` = `['classes', classId]` is invalidated on the line above and prefix-matches every variant. Redundant, not broken |
| `useUpdateChapter` / `useDeleteChapter` | `chapters(subjectId)`, **`['classTree']`** | **Wrong key.** The tree is keyed `['classes', id, 'tree', …]` (`queryKeys.classTree`). `['classTree']` matches nothing, so renaming or deleting a Theme leaves its old name on every tree until the 30 s `staleTime` lapses. `invalidateTeaching` gets this right with `['classes', classId, 'tree']` — two spellings of one intent, one of them dead |
| `useEnrollStudent` / `useUnenrollStudent` | `students`, `['classes']`, `home` | Yes — `['classes']` is broad enough to cover matrix and tree |
| `useAssignBranch` / `useDeclareBranch` / `useReorderBranches` | via `invalidateTeaching`: teachers, klass, classes, tree | Yes, with a good comment on why the tree is the one that would be missed |
| `useMarkPrinted` | `['timeline']` | Yes, and deliberately not awaited |
| `useCreateSheet` / `useRenderSheet` / `useProposeAdaptive` / `useBatchAdaptive` | **nothing** | Defensible — each is followed by a navigation or a job poll. `useCreateSheet` pushing to `/sheets/{id}` means the list is refetched on its next visit, 30 s later at worst |

**One concrete invalidation bug** — `['classTree']`, which matches no query that exists. It
is the shape the brief's §35 warns about (stale data displayed after a mutation), it is
small, and it is worth fixing alongside a rule that every invalidation goes through
`queryKeys` rather than through a literal. Every other invalidation in the file I checked
is correct, including several where correctness depends on prefix matching that the comments
show the author was reasoning about deliberately.

### Optimistic updates

**There are none.** No `onMutate`, no `setQueryData` before a response, anywhere in the app.
Every mutation waits for the server. On a product where a mistaken "saved" on a grade would
be a correctness failure, this is the right call and it appears to be a deliberate one:
`useApproveAdaptive` explicitly takes the *server's* returned id list rather than assuming
(`adaptive/page.tsx:672-673`), and `useUpdatePreferences` uses `setQueryData` only in
`onSuccess`.

The one place something resembling optimism appears is benign: `useSourceExercises` and
`useTimeline` use `placeholderData: keepPreviousData` so a filter change does not blank the
list under the teacher's cursor. That is a read concern, not a write, and both carry a
comment explaining the loss of work they prevent.

### Polling

| Query | Interval | Stops when |
|---|---|---|
| `useJob` | 900 ms | `isTerminal(status)` |
| `useScan` | 1 s while uploading/processing, 2 s while any detection is `pending` | terminal + nothing pending |
| `useFeedback` | 1.5 s | only while `writing` is true |
| `/sources` | 2 s, **hand-rolled** | nothing pending, or unmount (F25) |

The three react-query polls stop on unmount and do not fire while the tab is hidden
(`refetchIntervalInBackground` defaults to false). The hand-rolled one stops on unmount and
does not pause on blur.

### Auth and tokens

Single place, and the answer to the brief's §41 is the right one: **HttpOnly cookie,
`SameSite=Lax`, `Secure` in staging and production, 12 hours, nothing in `localStorage`**
(`alppy/api/v1/auth.py:71-76`). `credentials: 'include'` on every request. The middleware
checks cookie presence for routing only and says so: *"This is a routing convenience, not the
security boundary."* Behaviour on expiry mid-task: **undefined** — see F5.

### Form state

No form library. Every form is `useState` plus a hand-written submit. Validation is
per-field, hand-written, and duplicated from the server in two places (F21). At this size
that is a defensible choice (§11); the missing piece is not a library but a shared
validation source.

---

## 9 · Built / designed / neither

Against the flows in Step 3 of the brief.

| Flow | Status | Notes |
|---|---|---|
| **8 · Create establishment** | **Neither** | `POST /schools` exists in the API; nothing in the client calls it. A teacher gets a school from the seed |
| 8 · Create class | **Built** | `/classes/new`, one screen, code + label + roster |
| 8 · Enter students | **Built** | Paste, with a forgiving parser and a live count |
| 8 · Import students (CSV / cantonal) | **Neither** | No file import path; no format named anywhere |
| **8 · Form teaching groups** | **Neither** | The concept does not exist and the code format forbids it (F9) |
| 9 · Author an assignment (document path) | **Built** | `/sheets/new` document tab: source → section → exercises, filtered and paged server-side |
| 9 · Author an assignment (retrieval path) | **Built** | `ProposeTab`, intent + ranked proposals + provenance |
| 9 · Choose objectives | **Built** | `ThemePicker` is the builder's root, with the counted *Sans thème* row (DC-content-06) |
| 9 · Difficulty spread | **Partial** | A difficulty *filter* on the picker; no spread control. `items_per_student` and `n_groups` exist on the adaptive path |
| **10 · Adaptive generation as a job** | **Built, with gaps** | Job resource, polled, terminal-aware. **No progress display (F13), no cancel (API), no recovery (F4)** |
| 10 · Partial failure display | **Built** | Per-pupil, reason-specific, with a separate line for `truncated` |
| 10 · Retry the failed subset only | **Neither** | Only a whole re-propose |
| 10 · Cancellation | **Neither** | No API route (Ph2 M7) |
| 10 · Navigate away mid-run | **Neither** | The run is lost (F4) |
| **11 · Print** | **Built, unsound** | Two paths, one of them bypasses the coordinate-producing render (F1, F2) |
| 11 · Print preview | **Built** | Server-rendered, byte-identical to the PDF source — and **blank in the default compose stack** (F1, assumption 4) |
| 12 · Capture — phone camera | **Built** | `capture` on the file input; explicitly a first-class workflow |
| 12 · Capture — scanner/PDF upload | **Built** | Same control, `application/pdf,image/*` |
| 12 · Batch upload UX | **Partial** | Multi-file, one request, a spinner and a count |
| 12 · Per-page progress | **Neither** | Upload: none. Processing: yes, a real percentage |
| 12 · Resumability | **Neither** | Atomic multipart (F10) |
| 12 · 3 of 30 pages fail | **Partial** | Failure is per-page after upload and clearly reported; **there is no way to re-shoot into the pile** (F11) |
| **13 · Scan review side-by-side** | **Built** | Registered page + marks overlay beside the item list, sticky at `lg`+ |
| 13 · Keyboard through 30 sheets | **Built** | `N` walks the uncertainty queue, scrolls and focuses; matrix is one tab stop with arrow keys |
| 13 · Low confidence surfaced first | **Built** | `queueRank`: `multiple` → least confident → settled, with a comment on why confidence alone is not monotonic |
| **14 · Override in one action** | **Built** | One `SegmentedControl` press for a bubble, one for a written verdict |
| 14 · Machine vs teacher visibly distinct | **Built** | `corrected` badge, *"Lu par l'IA"* badge, and the machine's reading printed beside the override |
| **15 · Progression view** | **Built** | Class matrix → cell drill-down → pupil profile → competency attempts; tree with bands at three levels |
| 15 · Point-in-time vs current state | **Neither** | Everything is now (F8). `MasteryCurve` draws the model's *projection* dashed, which is the one honest nod to time |
| **17 · Destructive actions confirmed** | **Partial** | Excellent dialog, used on four actions, absent on three that need it (F18) |
| — Projector / discretion mode | **Neither** | One mention in `DESIGN.md`; nothing built (F3) |
| — Offline capability | **Neither** | Not planned in any document I found |
| — Error boundary / 404 page | **Neither** | Strings translated, routes absent (F6, F30) |

---

## 10 · Phase 1–3 propagation

### Compensated for (the frontend absorbs the cost)

| Prior finding | How this layer copes |
|---|---|
| **Ph2 L2** — `DetectionOut.vision_model` crosses to the client | Rendered nowhere; an `AiBadge` reading *"Lu par l'IA"* is shown instead |
| **Ph3 B18** — `points_possible` read live against stored `points_earned` | `/results` shows a dash rather than a zero for an ungraded copy and says so in its docstring; it cannot fix the desynchronisation, but it does not compound it |
| **Ph1 C1 / D87** — memberships now temporal | The roster already renders `class_codes[]` with `home_class_code` labelled *origine*, so the multi-class pupil has a UI before the model finished acquiring one |
| **Ph2 M4** — eight collections with no pagination | The two that would hurt (`sourceExercises`, `timeline`) *do* paginate, and both use `keepPreviousData` so the list does not blank under the cursor |
| **Ph3 B8** — vision grader has no injection hardening | The UI never auto-applies a verdict to a grade without the teacher confirming the pile, and shows the model's `reference` answer when it invented one, so a teacher can disagree with the reference and not only the verdict |

### Propagated (visible to the teacher, unfixed)

| Prior finding | How it reaches the screen |
|---|---|
| **Ph1 C2 / Ph2 C3** — no school year, every read means now | F8: no year switcher, no as-of, no historical roster or matrix |
| **Ph1 C1** — memberships are intervals | F8's twin: the UI has no way to ask "as they were in October" |
| **Ph2 C1 / Ph3 B12** — `/adaptive/propose` dedupes per school | F4's worst case: a teacher who re-proposes after losing their tab may be handed a colleague's class's plan, and the screen has no way to know |
| **Ph2 H2** — no contract gate, hand-mirrored types | F7, now with demonstrated drift and a visible consequence (multi-source lineage displayed, not producible) |
| **Ph2 M1** — error codes with no catalogue entry | F14: 401/403/429/500/503 all read *"L'envoi a échoué. Réessayez."* |
| **Ph2 M6** — atomic multipart upload, no resume | F10, on school Wi-Fi |
| **Ph2 M7 / Ph3 B9** — no job cancellation, no reaper | F13 (no cancel) and F25 (a poll that never gives up on a stuck job) |
| **Ph2 M8 / Ph3 B24** — no Swiss domain validation | F21: canton is a two-character text box |
| **Ph2 M9** — the one identifier in a query string | `DELETE /students/{id}?confirm=7B_15` is called from `StudentEditor`; pseudonymous, and it is the frontend that puts it there |
| **Ph1 H1–H3** — curriculum tree two levels deep | F28: no *attentes fondamentales*, no per-year progression, no Niv. 1/2/3 |
| **Ph3 B7** — every render rewrites the placements | The sheet screen offers **Générer le PDF** as an always-enabled primary action with no warning that the sheet has been printed |
| **Ph3 B14 / Ph2 L3** — images accumulate, presigned 900 s | F23: 150 of those URLs minted at once on a 30-page review |
| **Ph2 L7** — the contract's nouns differ from the product's | F17: three French words for `Subject`, because the repo has two names for it already |

### Amplified (the frontend makes it worse)

| Prior finding | How |
|---|---|
| **Ph3 B7** — placements rewritten on every render | F1 adds a *second* way to get paper that never had placements at all, and records it as printed |
| **Ph2 H5** — render has no in-flight guard and no idempotency | **Générer le PDF** is a plain button; a double-click is two renders, each of which deletes and rewrites the placements |

---

## 11 · Defensible-but-different

Choices I would have made differently and am not calling findings.

1. **No form library.** Every form is `useState`. At 24 routes and mostly-simple forms this
   is less code than react-hook-form plus resolvers, and the bundle budget is real (D25
   names a 3 MiB Worker ceiling). I would have reached for one at about twice this size. The
   thing I *do* want is a shared validation source (F21), and that is orthogonal.

2. **HTML5 drag-and-drop instead of a sortable library** in `SheetComposer`, with arrow
   buttons as the accessible and mobile path. The comment argues it from the bundle ceiling.
   I would have used the same reasoning.

3. **`staleTime: 30_000` globally with `refetchOnWindowFocus: false`.** I would have inverted
   the second — refetch on focus is exactly what a teacher returning to a tab wants, and the
   30-second window means a confirmed pile can show stale numbers for half a minute after a
   colleague confirms one. The invalidations are thorough enough that this rarely bites, and
   the choice keeps a laptop on classroom Wi-Fi quiet. Defensible either way.

4. **Library components take many string props** — `MasteryMatrix` has 15, `PointsMatrix` 13.
   This is a direct consequence of an excellent rule (*"the library ships no strings"*) and I
   would not trade the rule for the ergonomics. A `labels` object prop would collapse most of
   them; that is a refactor, not a fix.

5. **A local working copy of the adaptive plan.** Copying a megabyte of server state into
   `useState` to mutate it locally is unusual, and the argument for it — regenerate, discard
   and edit each rewrite one item, and re-fetching to learn that is pointless — is sound. My
   objection is only to the *address* being local too (F4).

6. **`force-dynamic` on the locale layout.** Measured, documented, and correct: a prerendered
   shell serves un-nonced `__next_f.push` blocks and never hydrates. I would have reached the
   same conclusion; I record it because it looks like a performance regression to anyone who
   has not read the comment.

7. **Two `<select>` elements for the scope switcher rather than a custom listbox.** The
   argument — keyboard operability with nothing to learn, and the platform picker beating
   anything hand-written on a phone — is the right one for the control a teacher touches most.

8. **No wireframes.** The design record is prose, a shipped brand library, numbered
   constraints, and screenshots. For a solo-built product this is better than stale mockups
   and I would not ask for Figma. I *would* ask for the component gallery (F26), which is the
   same information in a form that catches regressions.

9. **The i18n catalogue as the only string store, with no ICU extraction tooling.** 810 keys
   in three files, kept in sync by a 60-line script. It works, it is auditable, and it will
   become unwieldy somewhere around 2 000 keys. Not yet.

---

## 12 · Open questions

1. **Cantonal scope.** Still unanswered from Phase 1, and it now has a concrete frontend
   cost: F21's canton control, whether German is a real locale or a placeholder (§F17's
   sibling — `de.json` is complete and in sync, which is either foresight or scope), and
   whether the PER is the only curriculum or LP21 is a real target. The seed carries 18 LP21
   and 16 PER competencies, which reads like both.

2. **Is there ever a second role?** The contract has none. If a school administrator or a
   *doyen* ever needs a read-only view of an establishment, that is a routing and guard
   design decision that is much cheaper before 24 routes exist than after. Ph3 B16 —
   `POST /schools/{id}/teachers/{id}` grants any teacher full school read with no revoke —
   is the shape of the problem arriving without the design.

3. **Do students ever see a screen?** The brief lists them as possible secondary users.
   Today they see paper only. If they ever see a screen, the register question (§51) becomes
   real — the catalogue is uniformly vouvoiement, which is right for teachers and wrong for
   a fourteen-year-old — and it is a second catalogue namespace, not a rewrite.

4. **What is the intended relationship between "Imprimer" and "Générer le PDF"?** I have
   read F1 as a bug, but it is possible the browser-print path is intended as the fast path
   for a bubble-only sheet, where it is harmless. If so, it needs to know that and refuse
   when the sheet has open items — which is the same fix from the other direction.

5. **How many groups does a real class get?** The slider runs from 1 to the roster size. If
   the answer is "two or three", the dignity analysis in §4 changes shape; if it is "eight",
   as the brief's example suggests, the group-label disclosure gets sharper.

6. **Is `docs/plan.md` still the screen inventory of record?** If yes it needs updating
   (F31); if `docs/features/*/` has superseded it, it should say so, because it is the
   document a new reader will find first.

---

## 13 · What I could not verify, and why

1. **Anything requiring a running system.** I started no server, ran no build and executed no
   test, per the read-only brief. So: bundle size is unmeasured (I can say the dependency
   list is lean — react, react-dom, next, next-intl, @tanstack/react-query, four fontsource
   packages, four Radix primitives, clsx, and nothing else — but not what it weighs); the
   e2e suite's 36 screenshots are unverified against current code; and I did not confirm that
   the CSP actually blocks the preview iframe in the compose stack, only that the directives
   and the default env say it must.

2. **The actual font fallback in each environment.** I established that no `@font-face`
   exists in the printed document and that the API's Dockerfile installs no font packages
   beyond whatever `playwright install --with-deps chromium` brings. I did not run the
   container to see which family Chromium actually picks, nor measure the wrap difference
   against a browser. The *mechanism* of F2 is established from the code; the *magnitude*
   (I claim "one 8 mm line pitch") is reasoned from `linePitchMm` and not measured.

3. **Whether any sheet has actually been printed via the browser path.** F1's severity
   assumes the button is used. I found no telemetry distinguishing the two print paths —
   `SHEET_PRINTED` records both identically, which is itself part of the finding.

4. **The German and English catalogues' quality.** `pnpm i18n:check` guarantees the three
   have the same keys and I confirmed the mechanism. I read the French closely and can vouch
   for its register and its Swiss vocabulary; I did not assess whether the German is good
   German or whether the layout tolerates its longer strings (§52) beyond noting that the
   screenshot suite renders `/` and `/classes` in `de` at both viewports, which covers two
   screens out of twenty-four.

5. **Colour contrast ratios.** I verified the *structure* of the non-colour channels — every
   band carries a glyph and a word, every confidence bar carries a threshold marker and a
   warning sentence, `MasteryBandTag` takes `label` as required — which is the load-bearing
   half. I did not compute contrast ratios for the five band inks against their tints in
   light, dark and high-contrast, which is nine palettes × five bands and wants a tool.

6. **Whether the brand assets match the components pixel-for-pixel.** I checked the
   testable claims from CLAUDE.md — the mastery tokens are present verbatim including the
   computed background opacities and the constant-luminance glyph colours; the mark carries
   no mandarin accent; `--c-mastery-ok` is `#86CF5B` — and did not open the 8-plate PDF to
   compare drawings.

7. **Runtime behaviour of the scan review at scale.** The eager-loading claim (F23) is from
   reading the render, not from watching a 30-page pile load. The sticky-overlay layout may
   well mask the cost in practice.

8. **The API side of anything.** Where I traced into `apps/api` — the preview handler, the
   placement writes, the detector's error strings, the group labels, the UID regex — I read
   the code and quote it. I did not re-audit those modules; Phase 3 did.

9. **The full prior review record.** I found `docs/reviews/` late — 11 documents totalling
   256 KB and 338 screenshots, from an independent per-feature pass on 2026-09-06 — and read
   the verdicts, the F7 navigation review in full, and grepped all eleven for each of my
   Critical and High findings. That grep is the basis for the claim above that F1, F2, F3,
   F4, F6, F8 and F9 are absent from that record and that F5 is a half-taken fix from it. I
   did **not** read all 256 KB, so it is possible that one of my Medium findings is recorded
   there as a considered trade-off rather than an oversight. If any of §2's Mediums has a
   reason I have not credited, that record is where it will be.

---

*Read-only audit. No file in this repository was modified except this one.*
