# F7 — Navigation and overview · independent review

Reviewed 2026-09-06 against `main` @ `1ea7ee6` with the working tree as found
(120 modified files from the F2–F4 fix passes, uncommitted).
`docs/handover.md:12` records this milestone as **"M0 — foundation, design system,
i18n, nav — Done"**. That claim is what is under test.

---

## 1. Verdict

> **Superseded — all twenty findings were subsequently addressed.** See
> [`F7-fixes.md`](F7-fixes.md) for what changed and the evidence for each. This
> section records the state of the phase *as reviewed*, and is left unedited so
> the fixes can be checked against what was actually claimed.


**FAIL** — the phase's central mechanism, a class/subject context that navigation
scopes every screen to, does not exist in any form; and a teacher can read another
teacher's roster of named children.
**1 × P0 · 5 × P1 · 7 × P2 · 7 × P3.**

Two requirements (R6 loading states, R8 mobile reachability) pass cleanly and are
better than the brief asked for. The design-token and i18n gates are genuinely
green and genuinely enforced in CI. The failure is not workmanship — it is that
R3 and R4, which are the reason F7 exists, were never built, while the i18n keys
and the API query parameters that would feed them were.

---

## 2. What I ran

Stack already up via `docker compose up` (postgres, redis, minio, api, worker, web).
Web `http://localhost:3000` (production Next build, **real API**, not fixture mode).
API `http://localhost:8000/api/v1`. Login `demo@alppy.ch` / `alppy-demo-2026`.

| # | Command / action | Purpose |
|---|---|---|
| 1 | `PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q` | backend suite → **391 passed**, 0 failed, 0 skipped |
| 2 | `.venv/bin/ruff check apps/api` | → `All checks passed!` |
| 3 | `.venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/alppy` | → `Success: no issues found in 68 source files` |
| 4 | `node scripts/check-i18n.mjs` | → `ok — 361 keys in sync across fr, de, en` |
| 5 | `pnpm exec stylelint`, the CI colour-literal grep, `node packages/ui/scripts/check-tokens.mjs` | all three exit 0 |
| 6 | `cd apps/web && npx playwright test --reporter=list` | e2e suite → **101 passed, 7 skipped**, exit 0 (see §5 for what that does *not* cover) |
| 7 | `curl` session probes against `/home`, `/classes`, `/classes/{id}/students`, `/classes/{id}/mastery`, `/subjects` as three different teachers | R1 tenancy |
| 8 | `docker exec alppy-postgres-1 psql …` — independent SQL for every home stat | R2 |
| 9 | Playwright scripts (real API, no mocks) at 1440×900 and 390×844 | R3–R8 |
| 10 | axe-core 4.13.0 injected on home, class detail, phone home | a11y |
| 11 | `data-theme` / `-contrast` / `-motion` / `-calm` toggled on `:root`, 7 states × 2 viewports | cross-cutting design |

Seeds used: the shipped demo seed (school `0072aa17…`, teacher Camille Rochat,
class 7B / 18 students, subject `mathematics`, 559 attempts, 822 mastery
snapshots), plus temporary tenancy fixtures created and then removed (§6).

Screenshots — `docs/reviews/screenshots/F7/` (≈60 files). Key ones:
`01-home-desktop-1440x900.png`, `02-home-phone-390x844.png`,
`f7-home-theme-dark-1440x900.png`, `f7-home-theme-dark-contrast-high-1440x900.png`,
`06-deeplink-subject-mastery.png` (404), `07-adaptive-desktop.png` (no class control),
`15-classes-EMPTY-dead-end.png`, `25-class-detail-add-students-after-click.png`,
`36-phone-ghost-menu-button-focused-NO-RING.png`,
`reviewer-390-nontouch-panned-right.png`, `f7-unauth-_fr.png`.

---

## 3. Requirement trace

| Req | How verified | Result | Evidence |
|---|---|---|---|
| **R1** classes + subjects, nothing from other teachers | Created Teacher B (same school) and Teacher C (other school); probed `/home`, `/classes`, `/classes/{id}`, `/students`, `/mastery`, `/subjects` as each. Grepped the rendered home HTML for the subject. | **FAIL** | Demo teacher's `/home` listed `7C`, owned by `teacherb@alppy.ch`. Teacher B `GET /classes/baa2daea…/students` → **200, 18 real names** (`Léa Progin`, `Noah Bettschen`, …). Cross-*school* correctly 404s. Subject id `5fa9e928…` appears **0×** in the home HTML. → F-1, F-6 |
| **R2** quick stats correct vs the database | Independent SQL per stat for the demo class; `_last_sheets` ordering probed with a 2020 and a 2030 sheet. | **FAIL** (4 of 5 stats correct; the visible mastery caption is wrong) | `student_count` 18 = SQL 18 · `pending_scans` 0 = 0 · `band_counts` {6,38,23,23,0} = SQL · `students_needing_attention` 16 = SQL 16 · last-sheet ordering correct. But the card renders **"S'efface · 23 réponses"** where 23 is a competency-cell count; the class has **559** attempts. → F-4 |
| **R3** switching is fast and persistent (switch, reload, deep-link) | Grepped for any switcher; dumped every interactive element in the shell; deep-linked in a fresh context and reloaded; dumped `localStorage`/`sessionStorage`/cookies. | **FAIL** | No switcher exists. `nav.currentClass` / `currentSubject` / `switchClass` / `switchSubject` ship in all three catalogues with **zero** source references. Client storage after a deep link + reload: `localStorage {}`, `sessionStorage {}`, cookies `["NEXT_LOCALE","alppy_session"]`. → F-2 |
| **R4** every screen scoped to current class + subject | Visited 7Z then `/sheets/new`, `/adaptive`, `/scans/new`, `/sheets`; inspected each screen's selectors. | **FAIL** | `/sheets/new` defaults to `classes.data[0]`, ignoring what you just viewed. `/adaptive` has **zero** class or subject controls (`adaptive/page.tsx:85-86`). `/sheets` lists every class's sheets with no class column and no filter. `useClassMastery`'s `subjectId` is plumbed end-to-end and passed by **no caller**. → F-2 |
| **R5** empty states with a next action | Forced `[]` responses per screen; clicked each action. | **FAIL** | All 8 screens render an `EmptyState` — none is blank, none crashes. But `/classes` empty has **no action at all**, and it is where home's "Créer une classe" sends you; `classes/[classId]/page.tsx:119` renders a bare `<button>` with no handler. `createClass` has one reference in the repo: its own definition. → F-5 |
| **R6** `LoadingState` with a matching `shape` | Delayed the API 8–9 s with `page.route`; inspected the DOM. | **OK** | `shape="cards"` (4 card skeletons), `"list"` (5 rows), `"matrix"` (8×7 grid). All `role="status" aria-live="polite" aria-busy="true"`, bars `aria-hidden`. No bare spinner anywhere. `21/22/23-loading-*.png` |
| **R7** keyboard-complete, visible focus ring, switcher operable | 20 sequential Tabs with `activeElement` + computed `box-shadow` logged; drawer opened and closed by keyboard only. | **FAIL** | Desktop tab order is correct and every rail link shows `--focus-ring`. But `variant="ghost"` buttons render **no ring at all** (CSS specificity, 13 call sites incl. the mobile drawer trigger); Escape returns focus to `<body>`, not the trigger; `#main` is not focusable so the skip link doesn't move `activeElement`. The switcher requirement is vacuous — there is no switcher. → F-8, F-9 |
| **R8** mobile shell usable, scan upload ≤ 2 taps | Tap-counted at 390×844; measured every shell target. | **OK** | **1 tap**: bottom tab "Corrections" → `/fr/scans/new` with the drop zone and a "Prendre une photo" capture affordance on screen. All shell targets ≥ 44 px (tabs 98×56, drawer trigger 48×48). `32/33-mobile-step*.png` |

Cross-cutting: **design tokens PASS** (zero colour literals outside `tokens.css`/`print.css`; stroke 2.2 everywhere; no accent and no Caveat on any F7 surface; `MasteryMeter` carries four channels; 7 theme states × 2 viewports with zero light-on-dark anomalies and contrast 15.9:1 → 21:1). **i18n PASS** (361 keys in sync; every string changes across fr/de/en; no raw keys). **a11y: axe-core reports 0 violations** on home, class detail and phone home. **Privacy: not applicable and not exercised** — F7 makes no model calls.

---

## 4. Findings

### F-1 · P0 — There is no class/subject context, so R3 and R4 fail entirely and `/adaptive` can only ever target one class

**Repro.** Log in. Look at the app shell at 1440×900 and at 390×844. Dump every
interactive element. Then visit `/fr/classes/<any class>`, then `/fr/adaptive`.

**Expected.** A class and a subject switcher in the shell; the choice persists
across reload and deep-link; every screen scopes to it.

**Observed.** The shell is a hard-coded seven-item `DESTINATIONS` array
(`apps/web/src/components/AppShell.tsx:29-37`) and nothing else — no combobox, no
select, no class or subject control at either viewport. Nothing is persisted:
`localStorage {}` and `sessionStorage {}` after a deep link and a reload. Each
screen invents its own default independently — three separate `useState`s in
`sources/page.tsx:33`, `sheets/new/page.tsx:57`, and nothing at all in
`adaptive/page.tsx:85-86`, which reads:

```
const classId  = classes.data?.[0]?.id  ?? '';
const subjectId = subjects.data?.[0]?.id ?? '';
```

and sends those straight into `class_id`/`subject_id` on propose (`:200-201`) and
approve (`:270-271`). With five classes in the database the screen silently planned
for 7B and offered **no way** to plan for any other — `adaptive selects/comboboxes: []`
(`07-adaptive-desktop.png`). Adaptive sheets are the product's focal deliverable
(`docs/plan.md` §1); for every class but the alphabetically first they are unreachable.

The scaffolding for the missing feature is already in the repo, unused:
- `nav.currentClass`, `nav.currentSubject`, `nav.switchClass`, `nav.switchSubject`
  ship in `fr.json`, `de.json` and `en.json` — `grep -rn` across `apps/web/src` and
  `packages/ui/src` returns **zero** hits for all four.
- `subjectId` is threaded through `endpoints.ts:190`, `queries.ts:170` and
  `queryKeys.classMastery` to the API's `subject_id` query parameter
  (`apps/api/alppy/api/v1/mastery.py:28`) and is passed by **no caller**.
- `/fr/classes/<id>/subjects/<id>/mastery` → **HTTP 404** (`06-deeplink-subject-mastery.png`).
- Class detail picks the subject silently: `const subjectId = klass.data?.subject_ids?.[0]`
  (`classes/[classId]/page.tsx:49`) with no control and no indication which one it chose.

**file:line** `apps/web/src/components/AppShell.tsx:29`; `apps/web/src/app/[locale]/adaptive/page.tsx:85`; `apps/web/src/app/[locale]/classes/[classId]/page.tsx:49`; `apps/web/src/lib/api/queries.ts:170`.

**Direction.** Put the class+subject pair in the URL (a route segment or a search
param) so it is deep-linkable, mirror it into a context provider read by the shell's
switcher, and make every screen consume that instead of `data[0]`.

---

### F-2 · P1 — A teacher can list and read another teacher's classes, roster and mastery within the same school

**Repro.**
```
# Teacher B owns only class 7C. Ask for the demo teacher's class:
curl -s -c /tmp/tb.txt -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"teacherb@alppy.ch","password":"teacherB-pass-2026"}'
curl -s -b /tmp/tb.txt localhost:8000/api/v1/classes/baa2daea-…/students
```

**Expected** (checklist R1, verbatim): "expect 404/403, never 200 with data".

**Observed.** `HTTP 200`, 18 students, real first and last names:
`[('7B_01','Léa','Progin'), ('7B_02','Noah','Bettschen'), ('7B_03','Elif','Yilmaz'), …]`.
The same holds for `/classes/{id}` and `/classes/{id}/mastery`, in both directions,
and the demo teacher's `/home` and `/classes` **list** Teacher B's class `7C`
(`label: "Classe de Beatrice"`) with its student count and band histogram.
Cross-*school* isolation is correct — Teacher C's class 404s from both other teachers.

`Class.teacher_id` is `NOT NULL` and indexed (`0001_initial.py:204,229`) and is never
used as a filter anywhere in `class_service.py`: `list_classes`, `get_class`,
`student_counts`, `_pending_scan_counts`, `_last_sheets`, `list_subjects` and `home()`
all filter on `school_id` alone. `plan.md` §3 says every row carries `school_id`
"and `teacher_id` where ownership is personal" — `Class` carries it — but no
decisions-log entry records a choice to make class visibility school-wide.

The reason this survived: `apps/api/tests/test_api_fixtures.py`'s `make_tenant()`
creates a **new School per tenant**, so `tenant` and `other_tenant` are always in
different schools. `test_api_tenancy.py` therefore only ever exercises the school
boundary; there is no fixture anywhere for a second teacher inside one school.

**file:line** `apps/api/alppy/services/class_service.py:88-100`; `apps/api/alppy/api/v1/classes.py:39,62`; `apps/api/tests/test_api_fixtures.py` `make_tenant`.

**Not graded P0** because the exposure is colleague-to-colleague inside one school
tenant and no name reaches a model provider. **It becomes P0 if roster
confidentiality between teachers is a product requirement** — the checklist's own
wording says it is, so decide this explicitly rather than by default.

**Direction.** Decide the boundary, write it into `decisions-log.md`, then either
filter every class read path on `teacher_id` or delete the column; add a same-school
two-teacher fixture either way.

---

### F-3 · P1 — No authentication guard: a logged-out visitor gets the full app chrome and a generic error instead of the login screen

**Repro.** Fresh browser context, no cookie. Visit `/fr`, `/fr/classes`, `/fr/sheets`.

**Expected.** Redirect to `/fr/login`.

**Observed.** No redirect on any of the three. The rail, all seven destinations and
the bottom tabs render; only the data region shows
*"Quelque chose n'a pas fonctionné / Réessayez dans un instant…"* with the raw English
server string **`no session cookie`** printed in the details `<pre>` of a French UI.
`GET /api/v1/home → 401` in every case. `ApiError.isUnauthorized`
(`apps/web/src/lib/api/client.ts:29`) has **zero callers**; `Providers.tsx:19` carries the
comment *"retrying just delays the redirect to login"* for a redirect that does not exist.

This also makes R5's "new teacher" scenario untestable: a genuinely empty account and
an expired session are indistinguishable on screen.

**file:line** `apps/web/src/lib/api/client.ts:29`; `apps/web/src/components/Providers.tsx:19`; `apps/web/src/middleware.ts` (locale only). Screenshots `f7-unauth-_fr*.png`.

**Direction.** Guard in middleware on the session cookie, or a client boundary that
redirects on `isUnauthorized`; stop printing server `message` strings to teachers.

---

### F-4 · P1 — The home screen reports a competency-cell count as an answer count

**Repro.** Log in, read the demo class card. Compare with
`select count(*) from attempt;`.

**Expected.** Either the number of answers, or a caption that says what it counts.

**Observed.** The card renders **"S'efface · 23 réponses"** ("Fading · 23 answers").
The class has **559** attempts. 23 is `band_counts.fading` — the number of
*(student, competency) cells* in the fading band, which I confirmed with an
independent window-function query over `mastery_snapshot`. `band_counts` itself is
correct; the caption that displays it is not:

```
caption={tm('attempts', { count: c.band_counts?.[worst] ?? 0 })}
```
with `mastery.attempts` = `"{count, plural, … other {# réponses}}"`.

R2 requires each stat to be correct against the seed data. Four of five are; this one
is off by a factor of 24 and, worse, names the wrong quantity.

**file:line** `apps/web/src/app/[locale]/page.tsx:126`; `apps/web/messages/fr.json` `mastery.attempts`.

**Direction.** Add a `home.bandCells`-style key that names competencies, not answers.

---

### F-5 · P1 — The onboarding path a first-time teacher is pointed at ends in a screen with no controls

**Repro.** Force `GET /api/v1/classes` → `[]`. Load `/fr`. Click "Créer une classe".
Separately, force a class's `/students` → `[]` and click "Ajouter des élèves".

**Expected.** A way to create a class, and a way to add students.

**Observed.**
- Home's empty state links to `/fr/classes`, which renders an `EmptyState` with
  **no `action` prop at all** (`classes/page.tsx:32-36`); `main` actions = `[]`.
  Dead end (`15-classes-EMPTY-dead-end.png`).
- The zero-roster empty state renders
  `<button type="button" data-variant="primary" class="ard-btn">Ajouter des élèves</button>` —
  **no `onClick`, no `href`**. Clicking changes neither the URL nor the DOM
  (`19-…-EMPTY.png` and `25-…-after-click.png` are identical).
- `grep -rn "createClass" apps/web/src packages/` returns exactly one line: the
  definition at `endpoints.ts:80`. There is no class-creation UI in the app, and no
  roster-add UI, although `RosterInput` is built in `packages/ui` and
  `classes.create` / `code` / `codeHelp` / `codeInvalid` / `addStudents` / `rosterHelp` /
  `rosterPreview` are translated in all three catalogues.

**file:line** `apps/web/src/app/[locale]/classes/page.tsx:32`; `apps/web/src/app/[locale]/classes/[classId]/page.tsx:119`; `apps/web/src/lib/api/endpoints.ts:80`.

**Direction.** Build the create-class and paste-roster screens the endpoints, the
component and the strings are already waiting for; until then, do not offer a button
that does nothing.

---

### F-6 · P1 — The home screen drops the `subjects` half of R1

**Repro.** `curl /api/v1/home` → `subjects: [{id:"5fa9e928…", key:"mathematics", …}]`.
Search the rendered home HTML for it.

**Expected.** R1: "Teacher home shows all the teacher's classes **and subjects**".

**Observed.** `"5fa9e928"` → 0 occurrences; `"mathematics"` → 0; `"Mathematik"` → 0.
The single `"Mathématiques"` hit is `class.label`, not the subject.
`page.tsx` destructures `data.teacher` and `data.classes`; `data.subjects` is never read.

**file:line** `apps/web/src/app/[locale]/page.tsx:52-71`.

**Direction.** Render subjects, or drop them from `HomeOut` — shipping a field no
screen reads invites the next reader to assume it is used.

---

### F-7 · P2 — The pending-corrections label *is* the pending-corrections value

**Repro.** Read the second `<div>` of the home card's `<dl>`.

**Observed.**
```html
<dt class="text-ink-500">Aucune correction en attente</dt>
<dd class="font-bold" data-numeric="true">Aucune correction en attente</dd>
```
Both come from `t('pendingCorrections', …)` — the `<dt>` hard-codes `{count: 0}`
purely to obtain a string. There is no label key. With a non-zero count the row reads
*"Aucune correction en attente" / "3 corrections en attente"* — a term that contradicts
its own definition.

**file:line** `apps/web/src/app/[locale]/page.tsx:110-115`.

**Direction.** Add `home.pendingCorrectionsLabel` to all three catalogues.

---

### F-8 · P2 — `variant="ghost"` buttons have no focus ring, including the mobile drawer trigger

**Repro.** At 390×844, Tab three times to "Ouvrir le menu" and read the computed style.

**Observed.** `{outlineStyle:"none", boxShadow:"none"}` — nothing is drawn
(`36-phone-ghost-menu-button-focused-NO-RING.png`). Cause, confirmed by reading
`recipes.css`: `.ard-btn:focus-visible` (line 49) and `.ard-btn[data-variant='ghost']`
(line 88) have **identical specificity** (0,2,0), and the ghost rule comes later, so its
`box-shadow: none` wins even while focused. 13 call sites, including `AppShell.tsx:103`,
`Sheet.tsx:87` and `Modal.tsx:78`.

**file:line** `packages/ui/src/design/recipes.css:49,88`.

**Direction.** Give ghost its `--edge: transparent` shadow rather than `none`, or move
`:focus-visible` after the variant block.

---

### F-9 · P2 — Drawer focus is not restored, and the skip link does not move focus

**Observed.** Keyboard-only on the phone: Enter on the trigger correctly moves focus
into the drawer and focus **is** trapped there (a correct modal loop); Escape closes it
(correct) but returns focus to `<body>`, so the user restarts at the top of the page.
The skip link navigates to `#main` but `activeElement` stays `<body>` — `#main` has no
`tabindex="-1"`, so a screen reader's cursor is not moved to the landmark. The
`role="dialog"` has no `aria-modal` and is labelled `"Ouvrir le menu"` — the trigger's
name reused as the dialog's.

**file:line** `packages/ui/src/components/Sheet.tsx`; `apps/web/src/components/AppShell.tsx:118`.

---

### F-10 · P2 — Pending work is surfaced on the overview and cannot be reached by clicking

**Observed.** On the home card, "Dernière fiche <title>" and "N corrections en attente"
and "N élèves à surveiller" are all plain text — the only links on the card are the class
code and (when empty) the CTA. Worse, `GET /api/v1/scans` exists on the API but there is
**no `/scans` index route** (`/fr/scans` → 404) and no client function for it; the nav's
"Corrections" goes straight to `/scans/new`. A teacher who uploads a scan, closes the tab
and comes back has no way to reach `/scans/[id]` by clicking. This is the same defect
`sheets/page.tsx`'s own docstring records fixing for sheets — the `/sheets` route was
added, but home still prints the sheet title as plain text.

**file:line** `apps/web/src/app/[locale]/page.tsx:96-123`; `apps/web/src/components/AppShell.tsx:34`.

---

### F-11 · P2 — At 390 px in a non-touch window the class detail page pans 233 px

**Repro.** Two contexts, same viewport, after the matrix has rendered:
```
Pixel7 (isMobile+touch): {"panned":0,   "docScrollW":623, "docClientW":390}
plain 390 (no isMobile): {"panned":233, "docScrollW":623, "docClientW":390}
```
`reviewer-390-nontouch-panned-right.png` shows the header, the "Nouvelle fiche" button,
the filter card and the matrix dragged off the left edge with an empty violet band on the
right, while the fixed bottom tabs stay put.

The matrix's own scroller is correct (`overflow-x: auto`, `clientW 358 / scrollW 646`).
On a real phone the rule holds. But `responsive.spec.ts`'s guard runs only in the `phone`
project (`devices['Pixel 7']`, touch), so the configuration that fails is the one the test
does not cover — and `documentElement.scrollWidth` is 623 in both.

**file:line** `apps/web/e2e/responsive.spec.ts:9`; `apps/web/src/app/[locale]/classes/[classId]/page.tsx`.

**Direction.** Find the 623 px-wide unclipped node; add a non-touch narrow-viewport case
to the guard.

---

### F-12 · P2 — The language choice is never persisted, and the saved preference is never read

**Observed.** `settings/page.tsx:46` handles the language control with
`router.replace(pathname, { locale: next })` and nothing else — zero non-GET requests fire
on a language switch. Only `update()` (theme/contrast/motion/calm) calls
`updatePrefs.mutate`, and it sends the **current URL** locale, so a language choice reaches
the server only as a side effect of later touching a display toggle. And nothing reads it
back: `login/page.tsx:21` is `router.push('/')` in the current URL locale, never
`teacher.preferences.locale`. `i18n/routing.ts:5` asserts *"the teacher's choice is
persisted server-side (`TeacherPreferences.locale`)"* — it is not.

There is a green test named `the locale switch persists across a reload`
(`apps/web/e2e/locales.spec.ts:39`) — but its body never operates the switch. It navigates
straight to `/de`, reloads, and asserts `html[lang="de"]`, i.e. it tests that Next's locale
routing works. A reader scanning test names would conclude this behaviour is covered.

**file:line** `apps/web/src/app/[locale]/settings/page.tsx:46`; `apps/web/src/app/[locale]/login/page.tsx:21`; `apps/web/src/i18n/routing.ts:5`; `apps/web/e2e/locales.spec.ts:39`.

---

### F-13 · P2 — The demo seed cannot demonstrate the phase

**Observed.** `run_seed` creates one school, one teacher, one class (`DEMO_CLASS_CODE = "7B"`)
and one subject. R1's tenancy, R3's switching and R4's scoping are all undemonstrable from
`docker compose up` alone — I had to fabricate a second teacher and extra classes to test
them at all. For a phase whose subject is moving between classes and subjects, the demo
shows nothing to move between.

**file:line** `apps/api/alppy/seed/demo.py:21`; `apps/api/alppy/seed/__init__.py:163-186`.

---

### F-14 … F-20 · P3

- **F-14** Both `<nav>` landmarks are labelled `"Accueil"` (`AppShell.tsx` passes
  `aria-label={t('home')}` to the rail *and* the bottom tabs) — that is a destination's
  name, not a region's. And `document.title` is the bare string `"Alppy"` on every route,
  so tab, history and screen-reader announcements cannot tell home from a class.
- **F-15** `/sheets` renders each sheet as a `Panel` directly on the page canvas
  (`sheets/page.tsx:61`). Per CLAUDE.md a panel is *a subdivision of the object you are
  already in*; these are separate objects on the canvas, and `/classes` correctly uses
  `Card` for the same shape. The list also shows no class.
- **F-16** `/classes` reuses `home.title`, so `/fr` and `/fr/classes` both render
  `<h1>Vos classes</h1>`; `classes.title` ("Classe {code}") belongs to the detail page.
  Nine `classes.*` keys are translated three times and referenced nowhere.
- **F-17** A class with `subject_ids: []` makes `classes/[classId]/page.tsx:49` yield
  `undefined`, which requests `/chapters?subject_id=undefined` and populates the filter with
  **every** chapter in the school.
- **F-18** `ErrorState` prints the server's raw English `message` in a `<pre>` to a French
  teacher (`no session cookie`, `boom`).
- **F-19** `_last_sheets` does not filter on `Sheet.target`, so the demo class's headline
  "Dernière fiche" is `"Fiches adaptées"` — a per-student adaptive batch, not a sheet given
  to the class. Defensible, but decide it rather than inherit it.
- **F-20** `fmt.date` renders `06.09.2026` identically in fr, de and en. This looks
  deliberate (Swiss convention, documented in `format.ts`), but `dateLong()` sits unused in
  the same file, which is a signal either way. Flagged, not asserted.

---

## 5. Not checked

- **What the green e2e suite does not cover.** The suite itself I did run: **101 passed,
  7 skipped**. But every one of those 101 ran against `lib/api/mock/fixtures.ts` — the
  `desktop` and `phone` projects set `NEXT_PUBLIC_ALPPY_MOCK=1`, and the only specs that
  touch a real API, `live-loop.spec.ts`, are **among the 7 skipped**
  (`test.skip(!API || !WEB, 'set ALPPY_LIVE_API and ALPPY_LIVE_WEB to run')`, and neither
  variable is set by the default invocation or by `pnpm test:e2e`). So in its normal form the
  suite never contacts the backend, which is why F-2, F-4 and F-7 all survived a green run.
  Whether the live journey passes today is **UNVERIFIED** — I did not set those variables.
- **Lighthouse LCP — UNVERIFIED.** `npx lighthouse@12` fails to parse its own config under
  this Node (v23.7.0): `SyntaxError: Invalid or unexpected token` in `default-config.js:44`.
  Substituted an unthrottled `PerformanceObserver` measurement on localhost against a
  production build — `LCP 164 ms, FCP 44 ms, CLS 0` — which is **not** a Lighthouse score and
  should not be quoted as one.
- **Real hardware.** All mobile evidence is Chromium device emulation. F-11 in particular
  turns on touch emulation, so confirm it on a real phone and in a narrow desktop window.
- **Screen readers.** axe-core found 0 violations, but axe does not test announcement order;
  F-9 and F-14 were found by DOM inspection and warrant a VoiceOver/NVDA pass.
- **Privacy / AI call log.** Not exercised: F7 makes no model calls, so there is nothing on
  these screens that could carry a name to a provider. The gate itself is F4's to verify.
- **200 students in the UI.** The API caps a class at 99 (`MAX_STUDENT_NUMBER`) and a single
  roster POST at 40, both returning clean 422s, so an 80-student class is the largest I
  rendered. The matrix at 99 students is unverified.
- **Whether school-wide class visibility is intended.** I could not resolve F-2's severity
  from the repo: the requirement says teacher-scoped, the model docstring says school-scoped,
  and no decision records the conflict. That is a question for the owner, not a fact I can
  establish.

---

## 6. Reviewer changes

**Source files: none.** No fix was applied; nothing in `apps/`, `packages/` or `infra/` was
edited.

**Database (created and then removed).** To test R1 at all I had to fabricate a second
teacher — the demo seed ships only one. Created, via `psql` and the API: teacher
`teacherb@alppy.ch` + class `7C` + 2 students in the demo school; a second school with
teacher `teacherc@alppy.ch` + class `7B` + 2 students; classes `7Z` (0 students), `7Y`
(2 students, incl. `Noémie D'Amico` for the accent/apostrophe case), `7X` (80 students);
and two temporary `sheet` rows dated 2020 and 2030 to test `_last_sheets` ordering.

**All of it has been deleted** and the database verified back at the shipped demo state:
```
7B|18|demo@alppy.ch     teachers|1     schools|1     sheets|1
GET /api/v1/home -> classes: [('7B', 18, 'Fiches adaptées')]  subjects: ['mathematics']
```
One consequence worth naming: the design agent observed the home card briefly showing
`"Feuille future (later)" / 01.01.2030`. That was my 2030 test row, not a product bug — the
non-determinism it appeared to show does not exist.

**Files added:** this report, and ≈60 screenshots under `docs/reviews/screenshots/F7/`.

---

## 7. Fix brief

> You are fixing phase **F7 (navigation and overview)** of the Alppy repo. Read `CLAUDE.md`,
> `DESIGN.md`, `docs/plan.md` and `docs/decisions-log.md` first. The full evidence is in
> `docs/reviews/F7-review.md`. Add a regression test for **every** item below — the reason
> most of these shipped is that the e2e suite runs against `lib/api/mock/fixtures.ts`
> (`NEXT_PUBLIC_ALPPY_MOCK=1`) and the backend tenancy fixtures only ever compare two
> *schools*, so no test could see any of it.
>
> **P0-1 — Build the class/subject context.**
> Repro: log in; there is no class or subject switcher at 1440×900 or 390×844; `/fr/adaptive`
> has zero class controls and hard-codes `classes.data[0]` (`adaptive/page.tsx:85-86`);
> `/fr/classes/<id>/subjects/<id>/mastery` 404s; `localStorage`/`sessionStorage` are empty
> after a deep link and reload. The i18n keys `nav.currentClass|currentSubject|switchClass|switchSubject`
> already exist in all three catalogues and are referenced nowhere; `subjectId` is already
> plumbed from `endpoints.ts:190` through `queries.ts:170` to the API's `subject_id` parameter
> and is passed by no caller.
> Accept when: the shell shows both switchers; the pair lives in the URL and survives reload
> and a fresh-context deep link; `/adaptive`, `/sheets/new`, `/sheets`, `/scans/new` and the
> mastery matrix all scope to it; `useClassMastery` actually sends `subject_id`. Test with two
> classes and two subjects, keyboard-only.
>
> **P1-2 — Close the cross-teacher read path.**
> Repro: `POST /auth/login` as a second teacher in the *same* school, then
> `GET /classes/<other teacher's class>/students` → 200 with 18 named children. `/home` and
> `/classes` also list the other teacher's classes. `Class.teacher_id` is `NOT NULL` and
> indexed and is never filtered on in `class_service.py`.
> Accept when: the boundary is *decided and written into `decisions-log.md`*, then enforced —
> 404 for a non-owned class on `/classes/{id}`, `/students`, `/mastery`, and absent from
> `/home` and `/classes`. Regression test: a fixture with **two teachers in one school**
> (`test_api_fixtures.py:make_tenant` currently makes a new School per tenant, which is why
> this was never covered).
>
> **P1-3 — Add an auth guard.** Repro: no cookie, visit `/fr` → full chrome plus
> *"Quelque chose n'a pas fonctionné"* and the English string `no session cookie` in a French
> UI; `ApiError.isUnauthorized` has zero callers. Accept when an unauthenticated visit to any
> route lands on `/fr/login` and no server `message` is shown to a teacher.
>
> **P1-4 — Fix the wrong home stat.** Repro: the demo class card reads *"S'efface · 23 réponses"*;
> `select count(*) from attempt` is 559, and 23 is `band_counts.fading`, a competency-cell
> count. `page.tsx:126` passes it to `mastery.attempts` ("# réponses"). Accept when the caption
> names competencies; regression test asserts the rendered caption against a known
> `band_counts` payload.
>
> **P1-5 — Make the onboarding actions work.** Repro: home's "Créer une classe" → `/fr/classes`,
> whose `EmptyState` has no action (`classes/page.tsx:32`); `classes/[classId]/page.tsx:119`
> renders a bare `<button>` with no handler — clicking changes nothing. `createClass`
> (`endpoints.ts:80`) has no caller; `RosterInput` and nine `classes.*` strings are built and
> unused. Accept when a teacher with zero classes can create one and paste a roster entirely by
> clicking; regression test drives it end to end.
>
> **P1-6 — Render subjects on home.** `GET /home` returns `subjects`; the subject id appears 0
> times in the rendered HTML. Accept when R1's "classes **and subjects**" is visibly satisfied,
> or `subjects` is removed from `HomeOut`.
>
> **Before any of the above:** the suite is green (101 passed) only because it is entirely
> mocked — `live-loop.spec.ts` is skipped unless `ALPPY_LIVE_API` and `ALPPY_LIVE_WEB` are
> set, and nothing sets them. Wire the live project into `pnpm test:e2e` (or CI) first, or
> every regression test you add below will pass against fixtures while the product stays
> broken.
>
> Then the P2s, each with a test: the `<dt>`/`<dd>` both rendering `home.pendingCorrections`
> (`page.tsx:110-115`); ghost buttons losing `--focus-ring` to an equal-specificity later rule
> (`recipes.css:49` vs `:88`); drawer Escape returning focus to `<body>` and `#main` lacking
> `tabindex="-1"`; no `/scans` index so a pending review is unreachable by clicking, and home's
> stats being unlinked text; 233 px of document pan at 390 px in a **non-touch** context
> (`responsive.spec.ts` covers only `devices['Pixel 7']`); the language switch never persisting
> and `TeacherPreferences.locale` never being read at login (`routing.ts:5` claims otherwise);
> and a demo seed with two teachers, two classes and two subjects so the next reviewer can
> exercise R1/R3/R4 from `docker compose up` alone.
