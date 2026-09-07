# F4 — what was fixed, and how it was verified

Companion to [`F4-review.md`](F4-review.md), which recorded the findings. This
records what changed and what was actually run to confirm it. Every claim below
was verified by executing it against the running stack, not by reading the diff.

Scope: the **1 × P0 and 8 × P1** findings, plus the two checklist requirements
the review found had no implementation at all (R6 edit/regenerate/discard, R7
group sheets) — those are P1 by the severity scale ("a stated requirement is
missing"), and the review's own §7 listed them as work to do. The P2 and P3
findings are **not** in scope — three of them fell out of the P1 work and the
rest stand, all listed under [Still open](#still-open).

The planning core was sound and is barely changed: gap targeting, the
retrieve-before-generate ordering, competency targeting (100 % on-target),
per-student page isolation in the batch PDF and the PII gate all passed the
review and still do. What was broken was the two ends — the browser-to-API
contract, and the approval/print boundary — and that is where the diff is.

---

## The P0

**"Exporter le lot PDF" never produced a PDF.** `POST /adaptive/batch` returns a
`SheetOut` (201) and rendering is a *second* call, but the web client declared
the batch call as returning a `JobOut`, so it fed the new sheet's id into
`useJob` and polled `GET /jobs/<sheet-id>` — a 404, 27 times in 25 seconds, for
ever. The render endpoint was never called by anything.

The client now types the batch call as `SheetOut` and chains
`POST /adaptive/batch/{id}/render`, polls the job that call returns, and reads
the finished PDFs off the sheet. `tsc` could not catch the original drift
(`apiRequest<T>` is an unchecked assertion over hand-mirrored types), so the
guard is a test that clicks the button:
`e2e/adaptive.spec.ts::produces a downloadable PDF and its answer key` asserts
both download links appear, that the render endpoint was called exactly once,
and that **no sheet id was ever polled as a job id**.

The mock API was fixed at the same time and for the same reason: it had agreed
with the wrong client (returning a job from `/adaptive/batch`), which is how a
mocked suite can be green while the product is broken.

*Verified:* driven in a real browser against the real API. The network trace is
now `201 POST /adaptive/batch` → `202 POST /adaptive/batch/{id}/render` →
9 × `200 GET /jobs/{job id}` → `200 GET /sheets/{id}` → two download links → a
129-page PDF on disk (`screenshots/F4-after/ui-downloaded.pdf`).

---

## The P1s

**Unapproved AI exercises were printed (F2).** `ensure_printable` existed, was
tested, and had **zero** production callers; the docstring said "call it in the
render path" and nothing did. The gate now lives in its own module,
`services/approval.py`, deliberately free of any dependency on the adaptive
planner — the routers load planning through `deps.load_optional`, and a gate
that can fail to import is a gate that can be off. It is called at both doors:
`create_adaptive_sheet` (so the teacher hears about it while still looking at
the plan) and `render_adaptive_batch` / `render_sheet_pdfs` (so a re-render, or
an item un-approved after the sheet was built, cannot slip through).

*Verified:* posting a plan with 12 unapproved items now returns **422** naming
the offending ids; before, it returned 201 and the render put
`14. IA Calcule 4 × 9.` on page 128.

**"Tout approuver" approved nothing (F3).** It was `onClick={() =>
setApproved(true)}` — React state, zero requests, `approved_at` untouched. There
is now a real endpoint, `POST /adaptive/approve`, and the button calls it. It
returns *the ids it actually stamped*, which is not necessarily the ids asked
for: only AI-generated rows in the caller's school are touched, so a client
cannot believe it approved something it did not.

*Verified:* `approved: 12` over the API and `approved_at is not null` → 12 rows;
in the browser the export button is disabled before the click and enabled after.

**Generated exercises followed the UI locale (F4).** `language = payload.language
or teacher.locale or default` — the source material was never consulted, so a
teacher reading Alppy in English got 12 exercises stored as `language='en'` with
French statements. `source_language()` now reads the modal language of the
*textbook* corpus for that subject; the teacher's locale is the last resort for a
subject with nothing indexed. This is not cosmetic: `Exercise.language` chooses
the printed true/false glyphs (V/F · R/F · T/F) while the detector reads bubbles
by position, so a mislabelled item prints the wrong letters beside the right
holes.

*Verified:* with the teacher's UI locale set to `en`, `/adaptive/propose` now
answers `language: "fr"` and all 12 generated rows are French.

**Generation failed silently, and the PII gate fired on textbook prose (F5).**
Three of 25 students were quietly given a 15-item sheet because the seeded
exercise *"…Léa en mange 1/3, Noah en mange 1/4…"* was used as a style example
and class 7B contains Léa Progin and Noah Bettschen. Nothing leaked — the
property held — but decisions-log D10's claim that the roster match "has no
false positives on content" is wrong for first names, and the failure was
invisible in the UI *and* in the audit log.

Two changes. Style examples are now **scrubbed** on the way into the prompt
(`scrub()` redacts; `assert_no_pii` stays armed as the final assertion, because
the gate is what proves the property). And `AdaptiveProposeResponse` carries a
`failures[]` list — `provider_error`, `unparsable_response`, `pii_gate`,
`incomplete` — which the screen renders, so a short sheet always says why.
Separately, `assert_no_pii` moved *inside* the audited try block in
`ai/client.py`: it still runs before the provider, but a blocked prompt now
leaves a `ModelCall` row instead of a silent gap.

*Verified:* the same 25-student proposal now returns 16 items for every student
and `failures: []`. Fault injection covers the rest — see
`test_adaptive_fixes.py`, including a provider that falls over on the second of
three students while the other two complete.

**No answer key with the batch (F6).** `render_adaptive_batch` rendered
`SheetKind.BLANK` only. It now renders both from the same `SheetData`, so the
two piles come out in the same copy order, and returns `(blank_key, answer_key)`.
A differentiated pile is precisely the case a teacher cannot correct from memory:
no two children answered the same questions.

*Verified:* 171-page blank and 171-page key, same UID sequence page for page,
key pages headed `CORRIGÉ`.

**The quality gate let through items that could not be printed or graded (F7).**
The hand-rolled validator accepted `type: "open"` (never auto-gradable), silently
defaulted a missing `type` to `mcq`, ignored unknown fields, accepted two
identical options with the key on one of them, accepted empty options, and
accepted **17 options against `layout.MAX_OPTIONS = 4`** — six printed options
and four bubbles means the correct answer has no hole to fill and every child is
marked wrong. Parsing is now a strict Pydantic model, `GeneratedExerciseIn`, with
`extra="forbid"`, `type` restricted to the two auto-gradable kinds, options
constrained to `2..MAX_OPTIONS`, distinct and non-empty, and `answer_index`
required to address an option that exists. A bad item costs one slot, not the
sheet. The prompt states the option cap and the distinctness rule too, and
`Exercise.option_count` now caps at `MAX_OPTIONS` so it agrees with
`pagination.Item.option_count`.

*Verified:* a 14-row table test, each row something that used to reach paper.

**The accent approve button was unreadable in three of four display states
(F8).** Measured 1.84:1 in dark, 3.14:1 in high contrast, 1.65:1 in dark + high
contrast. The variant pinned `--face-ink: var(--c-ink-900)`, which flips to
near-white in dark — while `--c-accent-500` *also* becomes lighter, because dark
is not an inversion. The accent surface now has its own ink token,
`--c-accent-ink`, declared per theme against its own face: 7.3 / 8.4 / 6.7 /
13.7:1.

**Every card lost its edge in high contrast (F9).** `--shadow-ambient: none`
composed into `box-shadow: 0 2px 0 0 <edge>, none`, which is invalid CSS — `none`
is legal only as the sole value — so the browser dropped the whole declaration.
Card background then equalled canvas background: measured 1.00:1, no border, no
shadow, in the one mode a low-vision teacher reaches for. The token is now
`0 0 0 0 transparent`, which paints nothing and stays a valid `<shadow>`.

*Verified for both:* `e2e/adaptive.spec.ts` computes the WCAG ratio of the
approve button and checks card-vs-canvas separation in all four states, on both
viewports.

---

## The two missing requirements

**R6 — edit, regenerate, discard.** The screen never rendered a single
statement: it showed a count and a badge, and asked the teacher to approve nine
exercises it did not show them. That is not an approval step. Each proposed item
is now expandable and rendered in full — statement, options, the marked answer,
difficulty, provenance — with generated ones carrying the mandarin `AiBadge` and
three actions:

- **edit** → `PATCH /exercises/{id}` (already existed, was never wired up);
- **regenerate** → `POST /adaptive/regenerate`, which discards the old row and
  creates a replacement in the same transaction, so it *replaces* and never
  appends, and the replacement needs approving like any other generated item. If
  no replacement can be produced the transaction rolls back and the original is
  left alone — throwing away the teacher's only version and handing back nothing
  is worse than a bad item;
- **discard** → `POST /adaptive/discard`, which sets a new `Exercise.discarded_at`
  (migration `0004`) rather than deleting the row, because an `Attempt` may
  already point at it.

Discards are durable: `retrieval.gather_candidates` filters them out
unconditionally, and generation compares new statements against the discarded
set, so a rejected item is never proposed again.

*Verified:* regenerate returned a different id with the old row
`discarded=t, approved=f`; a re-proposal after discarding two statements offered
neither.

**R7 — group sheets.** `SheetTarget.GROUP` existed in the enum with zero usages.
`POST /adaptive/propose` now takes `group: true`, builds one shared item list
against the **union** of the selection's gaps — ranked by how many of the group
need each competency, then by how badly, because an item only two of five need is
a per-student sheet with extra steps — and reports, per item, which students it
is for. It returns the group plan *and* a per-student plan for each child with
the same items, so the batch export is unchanged and every page still carries its
own UID grid.

*Verified:* five students, four targeted competencies, eight shared items, all
five plans identical, and per-item attribution like
`7B_01, 7B_02, 7B_03, 7B_05 | Léo a un certain montant…`.

---

## Two incidental fixes

Both are inside the offline `EchoChatProvider`, which is a shipped production
fallback (D8) and was making F4 untestable offline.

- **It ignored the requested language.** It tested for `"language: de"` while the
  prompt emits `"Language: de"`, so every offline run came back French and no
  test could see a regression in the language path. It now reads the language,
  the count and the difficulty it was asked for.
- **Every generated key was option A** — 39 of 39, against a well-spread textbook
  distribution. On paper that is a column of A bubbles a child can fill without
  doing any arithmetic. The correct answer now moves, deterministically from the
  seed, and the prompt asks a real model to vary it too.

The screen also gained the `ErrorState` it never had (the review's F12): failures
of propose, batch, render and the job poll were all silent, which is why the P0
presented as "the button does nothing" rather than as an error.

---

## What was run

```
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q
  → 391 passed          (334 at review time + 44 new + 13 from concurrent scan work)
.venv/bin/ruff check apps/api                        → All checks passed!
.venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/alppy
                                                     → no issues in 68 source files
pnpm lint | typecheck                                → pass
pnpm i18n:check                                      → 361 keys in sync across fr, de, en
npx playwright test --project=desktop --project=phone
  → 101 passed, 3 skipped (the 3 skips pre-date this work)
```

44 new backend tests in `apps/api/tests/test_adaptive_fixes.py` and 14 new
browser tests in `apps/web/e2e/adaptive.spec.ts` (7 behavioural × 2 viewports,
plus 8 display-state assertions). One test or one table per finding.

**End-to-end, against `docker compose up` on a database dropped and re-seeded
from scratch** (which also proved migration `0004` applies to a clean install):

| Step | Result |
|---|---|
| Teacher locale `en`, propose 16/student | `language: "fr"`, 15 generated, all French, `failures: []` |
| Batch **without** approving | **422**, naming the 12 unapproved ids |
| `POST /adaptive/approve` | `approved: 12`, `approved_at` set on 12 rows |
| Batch + render | job succeeded in 13 s, **two** keys in the result |
| The two PDFs | 171 pages each, identical UID sequence, key headed `CORRIGÉ` |
| Regenerate | new id returned; old row `discarded=t, approved=f` |
| Discard, then re-propose | neither discarded statement offered again |
| Group mode, 5 students | 4 competencies, 8 shared items, per-item attribution |
| **The browser, end to end** | `201 batch` → `202 render` → `200 jobs/{id}` ×9 → `200 sheets/{id}` → both download links → 129-page PDF saved |

Screenshots and the downloaded PDF: `screenshots/F4-after/`.

---

## Still open

Not touched, because the brief was P0 and P1. Each keeps its finding number from
[`F4-review.md`](F4-review.md).

Three P2s were closed incidentally, because the P1 work ran through them:
**F11** (the answer key now moves — offline provider and prompt; nothing shuffles
at persist time, so a biased real provider could still cluster it), **F12** (the
screen has an `ErrorState` and renders every item), and **F24** (unused i18n
keys). The rest stand:

- **F10 (P2)** — retrieval falls back to the other language when the in-language
  corpus runs out, so a French class still gets German items (measured 7 of 16)
  with nothing on the printed sheet to say so. Still visible in the PDF this work
  produced: page 4 carries `9. Welcher Bruch ist gleichwertig zu 3/4?` under a
  French instruction line.
- **F14 (P2)** — `ai/audit.py` swallows a failed audit write without
  `rollback()`, so the poisoned session turns the *next* statement into a 500.
- **F16 (P2)** — 171 A4 pages for 25 students; the pagination estimate is
  deliberately pessimistic and it multiplies.
- **F17 (P2)** — the `AiBadge` label itself is 2.84:1. Deliberately left alone:
  fixing it means moving `--c-accent-600`, which is also the accent button's
  edge, and that is a calibrated palette change rather than a bug fix.
- **F18 (P2)** — the `Toggle` is a 48 × 28 touch target, under the 44 px floor.
- **F15 (P2), partly** — the adaptive flow now has 44 backend and 14 browser
  tests, but `pnpm test` still runs **zero** frontend unit tests: `@alppy/web`
  and `@alppy/shared` have no `test` task at all.
- **F19–F23, F25 (P3)** — `ConceptTag` still shows a UUID fragment; the batch
  title is still the UI-locale string; `model_call` still carries no student
  reference; `aiNotice` still explains the mark by colour; the
  illustrations/accent conflict between CLAUDE.md and DESIGN.md §7 is unresolved;
  `PATCH /teachers/me/preferences` still wipes preferences a partial body omits.
  (**F24 is closed** — the four unused `adaptive.*` keys are gone.)
- **Generated content quality is still unverifiable offline.** The shipped
  provider now honours language, count and difficulty, but it does not read the
  competency, so an offline demo still produces times-table questions tagged as
  linear equations (F13). Nothing here has been run against a real model.
