# F3 — what was fixed, and how each was verified

Companion to [`F3-review.md`](F3-review.md). Every P1, P2 and P3 from that
report is closed except the four listed under "Not addressed" at the end, each
with a reason. Each item below names the change, the
regression test that pins it, and what was observed on the running stack.

Verification environment: `docker compose up` with the demo seed
(`demo@alppy.ch` / `alppy-demo-2026`), class 7B
`40c54794-838f-4cd8-a8c8-c64b99213c0b`. Screenshots in
`screenshots/F3-after/`.

---

## One review finding was wrong

**P2-1 — "the matrix page overflows the document horizontally on a phone" is a
false positive, and no code needed changing.**

The review measured `documentElement.scrollWidth - clientWidth = 396px` on the
matrix route and called it an overflow. Re-measured properly: the scroller is
380px wide inside a `.ard-card` with `overflow: hidden`, it scrolls internally
(`scrollWidth` 722 vs `clientWidth` 380), and **the window does not move** —
`window.scrollTo(5000, 0)` leaves `window.scrollX === 0`, after a programmatic
scroll and after a real touch drag. `documentElement.scrollWidth` reports the
union of descendant bounding boxes and counts content an ancestor already clips,
so it claims overflow for a page that cannot pan a pixel.

The review hedged this ("reproduced in one of two runs"), and the hedge was the
right instinct. What was actually wrong is the *predicate*: `responsive.spec.ts`
asserts on `scrollWidth`, so it can report an overflow that does not exist — and
would equally miss a real one behind a clipping ancestor. That guard now scrolls
the window and looks at `scrollX`, which is the property a teacher experiences.

---

## P1-1 · "Not yet seen" rendered as a bold `0`

`docs/mastery-model.md` §2 sets it in bold: a competency nobody has assessed is
not the same as one a student fails. The API always modelled it correctly; the
rendering collapsed the two.

- `MasteryCell` now derives `hasScore = band !== 'none' && score !== null` and
  suppresses both the numeral and the `· 0 %` in the accessible name. Enforced in
  the component, not at the call site, so no caller can reintroduce it —
  `packages/ui/src/components/domain/MasteryCell.tsx`.
- The class page also maps `band === 'none'` to `score: null` at the API
  boundary, because the API's `score` field is not nullable.
- The mock fixture now emits `none` cells the way the API does (band `none`,
  `attempts_count` 0, `score` 0) instead of omitting the cell entirely. Omitting
  it let the UI fall back to a null score, which is exactly why the e2e suite
  could never have caught this.

**Observed:** on 7B, `none` cells with a digit = **0**; a `none` cell's
accessible name is `"Anna Meier, Comparer, ordonner … : Pas encore vu"` with no
percentage (see P2-8 for why it is a translated sentence rather than a joined
list); a `fading` cell at zero still shows its `0`.
**Test:** `e2e/mastery.spec.ts` — *a never-assessed cell shows no number, and a
zero score does*.

## P1-2 · No drill-down from a cell to its attempts

Clicking a cell went to the student profile with the competency discarded, and
no attempt list existed anywhere in the product. The provenance was already on
the row (`Attempt.sheet_id`, `sheet_instance_id`, `detection_id`); only the seam
was missing.

- New endpoint `GET /students/{id}/competencies/{cid}/attempts`
  (`api/v1/mastery.py`, `services/mastery_service.py:competency_attempts`),
  returning each attempt with its date, outcome, difficulty, the statement, the
  exercise origin, whether the teacher overrode the scanner, and the ids of the
  sheet and scan behind it.
- New `AttemptList` component and a `CellDrillDown` slide-over. Correctness
  carries the word as well as the mark — the green/red pair is the one a
  colour-blind reader loses. An AI-written exercise is marked with `AiBadge`.

**Observed:** clicking Léa × MA.1.A.3 opens a panel naming the competency, with
**6 attempts**, one carrying `Fiche : F2 verification` and `Voir la copie
scannée` (`screenshots/F3-after/01-drilldown.png`).
**Tests:** `test_api_mastery.py` — *drills down to the attempts behind it*,
*carries provenance back to the sheet and the scan*, *refuses another school's
student* (404), *needs a session* (401); `e2e/mastery.spec.ts` — *a cell drills
down to its attempts*.

## P1-3 · No sort, no chapter filter

- `GET /classes/{id}/mastery` now takes `chapter_id` and `sort=roster|weakest`.
  An unknown or foreign chapter narrows to nothing rather than leaking that it
  is unknown or silently falling back to the whole matrix; an unknown `sort` is
  a 422 rather than being ignored.
- `_weakest_first` orders by each student's worst **assessed** cell. A
  never-assessed cell is deliberately not a weakness — counting it would sort
  every student who simply missed a lesson to the top of a list whose entire
  purpose is "who needs help". A student with nothing assessed sorts last.
- Both controls are on the class page, above the grid.

**Observed, against a SQL ground truth:** three chapters gave API 3/2/1
competencies vs SQL 3/2/1, unfiltered 7. `sort=weakest` puts the students whose
worst cell is 0.0 first and is monotonically non-decreasing across the roster.
**Tests:** `test_api_mastery.py` — *narrows to one chapter*, *a chapter from
another school narrows to nothing*, *can be sorted weakest first*, *an unknown
sort is rejected*; `e2e/mastery.spec.ts` — *the chapter filter narrows the
columns and the sort reorders the rows*.

## P1-4 · The trend curve never rendered, and no sheet history

The curve was gated on `history.length > 1`, and every seeded student had
exactly one point: the seed called `recompute_for_students` once. So the panel
was dead code against the shipped demo.

- The seed now recomputes at **each lesson date**, oldest first, then today
  (`seed/demo.py:lesson_moments`, `seed/__init__.py`).
- That needed a real fix, not just more calls: `recompute_for_students` fed the
  model *every* attempt regardless of the date it was computing for, so a
  backfilled point would carry today's number and the curve would be flat.
  `load_attempt_inputs` now takes an `as_of` cut-off and the recompute passes
  its own `now`.
- The profile gained a **Historique** section listing the sheets the student
  actually sat, each linking to the sheet and to the scan it was read from.
  `sheets_taken` was an integer that nothing rendered; it is now backed by a
  `sheets` list and the count is derived from it.

**Observed:** backfilling the demo produced **886 snapshot rows across 10
distinct days** for 161 pairs, and the cell counts grow with the term (41 at the
first lesson → 90 → 161 today), which is the `as_of` cut-off working. Léa's
profile now shows history lengths `[10, 8, 1, 10, 9, 1, 8]`, five rendered
curves, and three sheets with scan links
(`screenshots/F3-after/04-profile.png`).
**Tests:** `test_api_mastery.py` — *a later day appends a point rather than
overwriting*, *a recompute only sees the evidence that existed at the time*,
*the profile lists the sheets the student sat*; `e2e/mastery.spec.ts` — *the
profile shows the trend and the sheets behind it*.

## P1-5 · No arrow-key navigation

`MasteryMatrix` now runs a roving tabindex: the grid is **one** tab stop, arrows
move between cells, Home/End jump to the ends of a row (Ctrl+Home/End to the
grid), Enter and Space drill down. The cursor is clamped on render rather than
stored as a cell id, so a filter or a re-sort cannot strand focus on a cell that
no longer exists.

**Observed:** ArrowRight/ArrowDown/ArrowUp/ArrowLeft return focus to the
starting cell; `button[tabindex="0"]` count is **1**, not 175.
**Test:** `e2e/mastery.spec.ts` — *arrow keys move between cells and Enter opens
the drill-down*.

## P1-6 · Contrast: dark unreadable, high contrast never reached the cells

`--c-mastery-*` was defined on bare `:root` only. The `-tint` values are
`color-mix(…, var(--c-surface))`, so they re-blended against a dark surface into
something the calibration never checked, while the fixed inks did not move at
all: the `ok` numeral sat at **1.03:1** in dark. And `data-contrast="high"`
restyled the page chrome while leaving every data cell byte-identical.

The values are **derived, not eyeballed** — the script is in the commit trail:
each tint is the shipped hue mixed toward that theme's surface until it hits a
target luminance, and each ink is that hue pushed to whichever pole clears the
floor (4.5:1 normally, 7:1 in high contrast). Five blocks now carry a band
scale: system-dark, explicit dark, high contrast, high-contrast+dark, and
high-contrast+system-dark.

One thing the review did not flag and this found: `-ink` was an **alias for the
shipped `-glyph` colour**, which put the numeral at 2.27:1 on a `solid` cell in
the *default light theme* too. The shipped brand file
(`alppy-mastery-tokens.css`) ships `--c-mastery-*`, the `-glyph` colours and the
background opacities — `-tint` and `-ink` are this repo's derivations, so giving
`-ink` its own value contradicts nothing. The shipped `-glyph` tokens are
untouched; the glyph is drawn with the legible `-ink` because it is the channel
that has to survive greyscale, and the calibration targets *equal* contrast
across bands rather than legibility on the blend.

**Observed, measured in the browser in all four states:**

| state | min ink-on-tint | greyscale ramp | min step |
|---|---|---|---|
| light | **4.50:1** | monotonic | 0.064 |
| dark | **4.52:1** | monotonic | 0.027 |
| light + high contrast | **7.04:1** | monotonic | 0.072 |
| dark + high contrast | **7.00:1** | monotonic | 0.016 |

(was 2.27–4.16:1 light, **1.03:1** dark, and high contrast identical to light.)
**Test:** `e2e/mastery.spec.ts` — *the bands stay legible in every display
state*, asserting both the contrast floor and a monotonic greyscale ramp.

## P1-7 · `days_until_review` returned `None` for the most urgent cells

A student who got everything wrong scored 0.0 and returned `None`, so the
profile captioned the worst cells with a neutral answer count instead of *à
revoir maintenant*. 28 of 175 cells in the shipped seed were in that state. The
guard read `accuracy <= 0.0` as "nothing to predict"; zero accuracy is maximally
due, not exempt.

Also removed: the unreachable `accuracy * RECENCY_FLOOR >= BAND_OK` branch —
`1.0 × 0.55 = 0.55 < 0.75`, so it can never be true — and the sentence in
`mastery-model.md` §4 promising a `None` the constants make impossible. §4 now
says `None` means "never assessed" and nothing else, and a test pins the
invariant so the claim cannot silently become true again.

**Observed:** cells with score 0 and attempts > 0 whose `days_until_review` is
null: **0** (was 28).
**Tests:** `test_mastery.py` — *a student who got everything wrong is due now,
not never*, *never assessed is the only None review prediction*, *the recency
floor never holds a score above the threshold*.

## P1-8 · The e2e "matrix" tests screenshotted the wrong page

All nine `matrix renders in …` tests navigated to `/fr/classes`, the class
index, which has no matrix on it — I opened `classes-light-desktop-darwin.png`
and it is two cards on an empty page. So eighteen baselines were pictures of the
wrong screen and the matrix had no visual-regression coverage in any theme or
locale. `the matrix scrolls in its own container` looked for
`[data-matrix-scroll]`, which existed only in the test, so it skipped forever.

- `helpers.ts` gained `MATRIX_CLASS_ID`, `matrixPath()` and `gotoMatrix()`, and
  the three specs use them.
- `MasteryMatrix` renders `data-matrix-scroll`, so the scroller test asserts
  instead of skipping.
- The sideways-scroll guard's path list now includes the matrix route.
- All eighteen baselines re-recorded against the real screen.

**Observed:** `73 passed, 0 failed, 7 skipped` across both viewports (the seven
skips are the phone-only touch-target and drawer tests skipping on desktop, and
vice versa).

---

## P2s closed alongside

- **P2-2 · The legend mapped nothing.** Five identical grey `<Chip>`s named the
  bands without saying which cell was which — under a comment claiming the
  opposite. New `MasteryLegend` carries the same three channels the cells do:
  tint, glyph and word, plus the `mastery.bandHelp.*` thresholds that shipped
  translated in all three catalogues and were referenced by nothing.
- **P2-3 · A never-assessed student read as `0`.** The profile now shows an
  empty state instead of a zero ring, and the ring takes the band colour (not
  the action violet) and a `centre` carrying the `%`, so the headline number is
  no longer colour-plus-digit with no label.
- **P2-4 · Profiles unreachable in an unassessed class.** Roster names are links
  now, so a coloured cell is not the only route to a student, and the profile
  has a back link — it used to contain zero links of any kind.
- **P2-5 · `packages/ui` was never linted.** It had no `lint` script, and every
  F3 component lives there. It has one now, with the same config as the web app.
  (`pnpm test` still runs nothing — there is no JS unit-test layer to add here
  without inventing one; the Playwright suite is the frontend coverage.)
- **P2-6 · Nothing proved `MasterySnapshot` was a time series.** The only test
  asserted the opposite property. Covered now, including the `as_of` cut-off and
  the profile history behind it.
- **P2-7 · Confirming a scan left the matrix stale.** `useConfirmScan`
  invalidated only the scan and the home summary, so with `staleTime: 30_000` a
  teacher returning to the grid within 30s saw pre-scan numbers. It now
  invalidates the `classes` and `students` prefixes.
- **P2-8 · Dead translated strings.** `mastery.cellLabel` now builds every
  cell's accessible name, with a new `cellLabelNotAssessed` for the `none` band
  (which has no percentage to report). This is what the finding was really
  about: the library's fallback joins with a hard-coded `' · '` and a
  French-spaced `' %'`, so English read `82 %` instead of `82%`. Verified live —
  fr: `"… : À revoir, 85 %"`, en: `"…: To review, 85%"`. `MasteryMatrix` had to
  learn to forward `formatLabel` for this to be reachable at all.
  `mastery.bandHelp.*` feed the legend, `mastery.provisional` marks a
  provisional band in the drill-down, `student.overall` labels the profile ring,
  `student.history` names the sheets section. `mastery.score` and
  `mastery.notAssessed` had no honest home and were **deleted** from all three
  catalogues — a string kept alive by inventing a place to put it is still debt.
  311 keys in sync.
- **P3-4 · Card vs Panel.** The first pass got this wrong and made it worse: it
  added two more top-level `Panel`s, so the class page had Panel/Panel/Card and
  the profile Card/Card/Panel/Panel as siblings — Panel used as a quieter Card,
  which is exactly the confusion CLAUDE.md forbids. All six regions on the two
  screens are now `Card`s: each is a separate object sitting on the page canvas,
  and no `Panel` remains on either screen.
- **P3-5 · Two vocabularies for one scale.** `MasteryMeter`'s second channel was
  `.ard-mastery-dot`, a plain 10px circle identical for all five bands — it
  carried no information without colour, and taught a different shape language
  from the matrix. It now draws the same `BandGlyph` (disc 4/4 · 3/4 · 2/4 · 1/4
  · dashed ring). `.ard-mastery-dot` is deleted from `recipes.css`; the dead
  `uid` prop on the matrix's student mapping is gone too.
- **P3 · Stale docs.** `docs/plan.md` §6 printed the superseded one-factor
  formula; it now matches `mastery-model.md` and D4. The §3 fade schedule said
  day 14 was `0.90 · Solid / To review`; the computed value is `0.898` and the
  band is unambiguously `to review`.

## Not addressed

- **`pnpm test` still executes zero tests.** No package defines a `test` script
  and there is no vitest/jest setup. Adding a JS unit-test layer is a bigger
  decision than a review fix; flagging rather than inventing one.
- **No coverage tooling.** Neither `pytest-cov` nor `coverage` is installed, so
  the review's coverage question still cannot be answered numerically.
- **`.print-band` is still unused.** `print.css` defines the five underline
  styles DESIGN.md §9 requires for paper, and no component applies the class.
  The matrix has no print path today, so wiring it needs a decision about what
  printing a matrix should produce.
- **`data-motion` / `data-calm` on these screens remain UNVERIFIED**, as in the
  review: no sampled value differs and no animation frames were captured.

## Beyond the review

- **The band glyph was too small to function as the third channel.** The shipped
  tile is 44 units with the disc at `r 8.624`, so the mark occupies 39% of its
  own frame — rendered inline at 12px the disc was under 5px across. The viewBox
  is now cropped to the disc plus its stroke and the default size raised to
  15px. Every coordinate, radius and path is still exactly as shipped: cropping
  a frame is not redrawing the mark.
- **The profile ring's caption overflowed it.** Wiring `student.overall` into
  `centreCaption` wrapped "Score global" onto two lines and spilled it outside
  the 88px stroke. The label sits under the ring now; the centre holds a
  percentage and nothing else.
- **The trend curve floated in the middle of its panel.** `MasteryCurve` keeps
  its aspect ratio with a fixed height, so a container wider than 320:H centred
  the plot and left dead space to its left. Anchored `xMinYMid` — time runs left
  to right — and the profile lays the curves two-up from `lg`.
