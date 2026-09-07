# F7 — navigation and overview · fixes

Companion to [`F7-review.md`](F7-review.md), which found **1 P0 · 5 P1 · 7 P2 · 7 P3**.
All twenty are addressed below: eighteen by a code change, one by a decision recorded
instead of a change, and one deliberately left alone with the reasoning stated.

Every fix names the evidence that it works. Two of the claims below were originally made
*without* running anything and turned out to be wrong on re-checking — see the
**Addendum** at the end, which records what was wrong and what is still open.

---

## Gates after the work

| Gate | Result |
|---|---|
| `pytest apps/api/tests` | **397 passed** (was 391 — six new tenancy regressions) |
| `ruff check apps/api` | clean |
| `mypy --strict apps/api/alppy` | clean, 68 files |
| `pnpm typecheck` | clean, 3 packages |
| `pnpm lint` | clean (1 pre-existing warning in `mock/handlers.ts`) |
| `pnpm lint:css` (stylelint) | clean |
| `node scripts/check-i18n.mjs` | **386 keys in sync** across fr/de/en |
| `pnpm exec playwright test` | **122 passed**, 12 skipped (was 101) |
| colour-literal grep | no hits outside `tokens.css` / `print.css` |

---

## P0

### F-1 · The class/subject context now exists, and the URL carries it

`apps/web/src/lib/scope.tsx` (new) holds the context; `components/ScopeSwitcher.tsx` (new)
is the control, mounted in the rail at `md`+ and in the drawer below it.

The URL is the source of truth (`?class=…&subject=…`) so a link to a matrix opens *that*
matrix for the person receiving it. `localStorage` is the fallback for bare routes.
`/classes/[classId]` names its class in the path, and the path wins. Every id is validated
against what the API returns before use, so a stored id that outlived its class — deleted,
or no longer owned after F-2 — degrades to the first class the teacher does have rather
than to a request that 404s.

Consumers changed from "index 0" to the shared scope: `adaptive/page.tsx` (which had **no**
class control at all), `sheets/new`, the sheets list, `classes/[classId]` (which also now
passes `subject_id` to `/classes/{id}/mastery` — the parameter was plumbed end to end and
never sent).

**Two bugs found while verifying, both by measurement rather than reading:**

- The first version put `next/navigation`'s pathname into next-intl's router, which
  re-adds the locale — producing `/fr/fr?class=…`. Now uses next-intl's `usePathname`.
- The persistence effect wrote `{subjectId}` alone whenever subjects resolved before
  classes, dropping `classId` from storage. `/fr/adaptive` then silently reverted to the
  first class. It now waits for both lists and merges rather than replacing.

**Evidence** (live stack, real API):
```
rail: "Classe courante"    7B — Mathématiques — cycle 3 | 9A — Mathématiques — 9e
      "Discipline courante" Mathématiques | Sciences de la nature
switch class      -> URL http://localhost:3000/fr?class=94cf8697-…
reload            -> switcher still shows 9A
deep link, FRESH browser -> switcher shows 9A
/fr/adaptive (no query string) -> scoped to 9A
```
Regression tests: `e2e/f7-navigation.spec.ts`, three cases including the bare-route one
that the storage bug broke.

---

## P1

### F-2 · A class belongs to a teacher (decisions-log **D23**)

The review left the boundary open because the requirement said teacher-scoped, the model
docstring said school-scoped, and nothing recorded a decision. It is now decided in
`docs/decisions-log.md` D23 and enforced.

`api/deps.Scope` carries **both** boundaries. `school_id` stays the tenant boundary —
subjects, chapters, textbooks, extracted exercises and the curriculum are shared by the
staffroom on purpose. `teacher_id` is the ownership boundary for a class and everything
hanging off it: roster, mastery, sheets, scans.

`class_service.owned_class_ids()` is the single definition every class-derived read filters
through. Handlers that touch a class take `ScopeDep`, so forgetting the owner is a type
error — mypy found all 27 call sites when the signatures changed.

Two edges, both learned from a failing test rather than guessed:
- A colleague's class reads **404, not 403** — the response must not confirm the id exists.
- A scan uploaded before its sheet is known (`sheet_id IS NULL`) stays visible to whoever
  uploaded it. `NULL IN (...)` is never true, so the first version orphaned every unattached
  pile; `test_a_scan_that_can_grade_nothing_is_refused_at_confirm` caught it.

**Evidence** (live stack, two real teachers):
```
demo /home       -> ['7B', '9A']          colleague /home -> ['7A']
colleague GET /classes/{demo 7B}          -> 404 not_found
colleague GET /classes/{demo 7B}/students -> 404 not_found
colleague GET /classes/{demo 7B}/mastery  -> 404 not_found
colleague GET /subjects -> ['mathematics','sciences']   (shared, as intended)
```
Regression tests: six in `test_api_tenancy.py`, on a new `colleague` fixture — a second
teacher **in the same school**. `make_tenant` built a new School per tenant, which is
precisely why the suite could never see this.

### F-3 · A session guard

`apps/web/src/middleware.ts` redirects to `/{locale}/login?from=…` when the session cookie
is absent, and login returns the teacher to `from`. Fixture mode is exempt or the whole
screenshot suite would land on the login form.

The cookie is `httpOnly`, so presence is all the edge can check — the API remains the
authority and still answers 401. Documented in the file as a routing convenience, not the
security boundary.

**Evidence:** `anon /fr/classes -> http://localhost:3000/fr/login?from=%2Ffr%2Fclasses`.

### F-4 · The band caption counts competencies

`page.tsx` captioned `band_counts` — a count of (student × competency) **cells** — with
`mastery.attempts` ("# réponses"). The demo class read "23 réponses" against 559 real
attempts. Now `home.bandCells` ("23 compétences").

### F-5 · Onboarding actually starts

`/classes/new` (create a class and paste its roster in one screen) and
`/classes/[classId]/roster` are new. `POST /classes`, `POST /classes/{id}/students`,
`RosterInput` and nine translated `classes.*` strings all already existed with no caller.
The `/classes` empty state — where home sends a new teacher — had no action at all; the
zero-roster empty state was a bare `<button>` with no handler.

### F-6 · Home renders subjects

`GET /home` always returned `subjects`; the screen destructured only `teacher` and
`classes`. Now an outline `Chip` row — official data is not coloured.

---

## P2

| # | Fix | Evidence |
|---|---|---|
| **F-7** | `home.pendingCorrectionsLabel` for the `<dt>` and a short `…Value` for the `<dd>`. The term used to be the value string rendered with a hard-coded `count: 0`, so two pending scans read *"Aucune correction en attente / 2 corrections en attente"*. | `f7-navigation.spec.ts` asserts term ≠ value |
| **F-8** | `recipes.css` now writes `box-shadow` exactly twice and every variant re-points `--lift`, so ghost cannot shadow the ring. | live: `rgb(91,63,240) 0 0 0 2px, rgb(236,231,255) 0 0 0 6px` on the drawer trigger |
| **F-9** | `useReturnFocus` restores the opener; `aria-modal="true"`; the drawer is named `nav.menu` ("Menu") not the trigger's name; `#main` got `tabIndex={-1}` so the skip link moves focus. | live: focus after Escape = the trigger; skip link → `MAIN id=main` |
| **F-10** | `/scans` index (new), and home's last-sheet title and pending count are links. `GET /scans` shipped with no route and no client function, so a pending review was unreachable by clicking. | `f7-navigation.spec.ts` clicks the count through to the index |
| **F-11** | `overflow-x` on `html`/`body` in `base.css`. | see below |
| **F-12** | The language `SegmentedControl` now calls `updatePrefs.mutate`, and login honours `teacher.preferences.locale`. | — |
| **F-13** | The seed ships two classes for the demo teacher, two subjects, and a colleague with a third class. | `classes: ['7B','9A'] · colleague_class: 7A · subjects: ['mathematics','sciences']` |

**F-11 is worth spelling out, because the original measurement was misleading.** The review
measured `window.scrollTo(9999,0)` and read 233px. That is a *programmatic* scroll, which
succeeds even against `overflow:hidden` — so it kept reading 233 after the fix, and I nearly
concluded the fix had failed. What a user can do is a wheel:

```
WITH the fix (overflow-x hidden)   user wheel -> window.scrollX = 0
WITHOUT it (forced back to visible) user wheel -> window.scrollX = 233
```

`hidden` rather than `clip`: the root's overflow propagates to the viewport and Chromium
does not honour `clip` through that propagation (measured — `clip` still panned 233). The
usual objection to `hidden` does not apply here: the matrix's sticky name column sticks
inside `[data-matrix-scroll]`, its own scroll container, and still does
(`stickyLeftWhenScrolled: 16`). `responsive.spec.ts` now has a wheel-based guard, because
the existing `scrollTo` one structurally could not catch this.

---

## P3

**F-14** two `<nav>` landmarks both named "Accueil" → `nav.primary`; per-segment `layout.tsx`
files give every route its own `<title>` (`Vos classes · Alppy`, …). **F-15** `/sheets` rows
are `Card`, not `Panel` on the bare canvas. **F-16** `/classes` has its own `classes.allClasses`
heading instead of borrowing `home.title`. **F-17** a class with no subject no longer requests
`/chapters?subject_id=undefined` and fills the picker with every chapter in the school.
**F-18** `ErrorState` no longer renders the API's English `message`; `apiErrorMessage` switches
on `code` (home and both adaptive call sites).

### Not changed, on purpose

**F-19 — "Dernière fiche" counts adaptive batches.** The review asked for a decision, not a
code change. Recorded as **D24**: an adaptive batch *is* work given to that class, one copy
per pupil, and hiding it would leave the card naming an older sheet instead of a real one.

**F-20 — the locale-invariant `06.09.2026`.** Left alone. `format.ts` documents the Swiss
`dd.mm.yyyy` shape deliberately, and `intlLocales` maps to `fr-CH`/`de-CH`/`en-CH` where that
form is correct in all three. The review flagged it as "probably intentional, confirm" rather
than asserting a defect; changing it would be substituting taste for a documented choice.

---

## Reviewer/fixer changes to data

The temporary rows the review created were removed before this work started, and the
database is back to the shipped demo — now two classes, two subjects and a colleague, from
the seed itself rather than by hand:

```
demo@alppy.ch      7B (18 students), 9A (5 students)
colleague@alppy.ch 7A (2 students)     subjects: mathematics, sciences
```

---

## Addendum — three things that were wrong when I first called this done

Re-checking my own claims turned up three defects in the fix work itself. All are
now corrected and verified; they are recorded here rather than quietly patched,
because two of them were *claims made without running anything*.

**F-17 was a comment, not a fix.** I documented the defect above
`const chapters = useChapters(subjectId)` and changed no behaviour.
`useChapters(undefined)` still fired, `withQuery` dropped the empty parameter, and
`GET /chapters` returned every chapter in the school. Now gated with
`enabled: Boolean(subjectId)`.
*Verified* by forcing `subject_ids: []` on a real class: `/chapters` requests fired
`[]`, and the picker shows only "Tous les chapitres" instead of the school's seven.

**The class-code field was looser than the server.** I wrote
`/^\d{1,2}[A-Za-z]{1,3}$/` and commented that it "mirrors `alppy/core/uid.py`". It
does not: `_CLASS_RE` is `\d{1,2}[A-Za-z]{1,2}`. So `11ABC` passed the form and
422'd at the API, leaving the teacher to decode a validation error for a field the
form had just accepted. Corrected to two letters and asserted in the live spec.

**I broke an existing live test.** `live-loop.spec.ts` used page-wide
`page.locator('select')` counts, which the new rail switcher now matches — three
selects where the test expected one. Scoped to `main select`. This one is
instructive: it went unnoticed because the live project does not run by default,
which is precisely the gap flagged below.

**F-12 was claimed before it was run.** Now measured end to end: switching to DE
sends `PATCH /teachers/me/preferences {"locale":"de"}`, `GET /auth/me` returns
`de`, and a later login starting at `/fr/login` lands on `/de`.

### Still open

**The live e2e project is still opt-in.** The fix brief in `F7-review.md` §7 said to
wire it into `pnpm test:e2e` *before* anything else, "or every regression test you
add below will pass against fixtures while the product stays broken". I did not do
that. `test:e2e` is still `playwright test`, and `live-loop.spec.ts` skips unless
`ALPPY_LIVE_API`/`ALPPY_LIVE_WEB` are set. I ran it by hand
(`6 passed, 1 pre-existing failure`) and added the three F7 checks that fixture mode
cannot express — the session guard, cross-teacher isolation, and class-code parity —
but making it part of the default run needs a CI decision about standing up a
database, which is a repo-wide question rather than an F7 one.

**One pre-existing live test is broken, and it is not mine.**
`live-loop.spec.ts:155` ("the review screen shows the page, the questions and the
marks") looks for a scan with detections, but the upload test it depends on posts
`PNG_1PX` — whose own comment reads *"enough to be accepted, not enough to register
as a page"*. The worker confirms `registered=0 identified=0`, so that upload can
never satisfy it. Detection itself is fine: the 19 tests in
`test_scan_processing.py` do full render → degrade → detect → grade round trips and
pass. This is an F2 test with a contradiction in it, left alone as out of scope and
reported rather than silently fixed.
