# F3 — Individual student tracking · independent review

Reviewed at `1ea7ee6` (working tree carries the uncommitted F2 fix set).
Date: 2026-09-06. Reviewer: independent agent, adversarial pass.

---

## 1. Verdict

**FAIL** — the mastery model itself is excellent and provably correct, but three
checklist requirements (R5 drill-down, R10 sort/filter, and the trend/history half
of R6) are **not implemented at all**, the matrix renders "not yet seen" as a bold
`0` in direct contradiction of the model doc, and the high-contrast switch never
reaches the data cells.

**0 P0 · 8 P1 · 9 P2 · 5 P3.**

---

## 2. What I ran

Stack was the real one, not fixtures: `docker compose` services already up
(`alppy-{postgres,redis,minio,api,worker,web}`), web at `http://localhost:3000`
(production build, `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1`),
API at `http://localhost:8000`, seeded demo data
(`demo@alppy.ch` / `alppy-demo-2026`, school "Collège de démonstration",
class 7B `40c54794-838f-4cd8-a8c8-c64b99213c0b` 25 students,
class 8A `5c6638c2-5b00-4b3a-bb09-e12e612a0b6a` 2 students).

### Commands

```bash
# backend
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q -rsxX     # 320 passed, 0 skipped
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_mastery.py \
    apps/api/tests/test_api_mastery.py -v                                  # 41 passed
.venv/bin/ruff check apps/api                                              # All checks passed
.venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/alppy        # Success, 67 files
# gates
pnpm typecheck    # 3 tasks, FULL TURBO (cache)   pnpm lint  # 1 task (web only)
pnpm test         # 0 tests exist — see P2-5      pnpm i18n:check  # ok, 287 keys in sync
# e2e
cd apps/web && PLAYWRIGHT_CHANNEL=chrome pnpm exec playwright test --project=desktop
                  # 26 passed, 2 skipped, 1 failed (browser-launch timeout, environmental)
# model
PYTHONPATH=apps/api .venv/bin/python <r2.py, r2b.py>          # hand recomputation, §4 R2
docker exec -w /app -e PYTHONPATH=/app alppy-api-1 python /tmp/r7_snap.py   # snapshot semantics
# API probes (cookie jar from POST /api/v1/auth/login)
curl -b jar.txt localhost:8000/api/v1/classes/{7B}/mastery
curl -b jar.txt localhost:8000/api/v1/students/{id}/mastery
# UI: Playwright against localhost:3000, login through the real /fr/login form
```

### Screenshots

`docs/reviews/screenshots/F3/` — 59 files. The ones the findings cite:
`03-class-7b-matrix.png`, `05-student-profile-full.png`,
`12-cell-none-zoom.png` / `12-cell-fading-zoom.png` (the `0` collapse),
`13-matrix-{default,dark,contrast-high,motion-off,calm-on}.png`,
`13-profile-{default,dark,contrast-high,motion-off,calm-on}.png`,
`15-matrix-all-switches-on-via-settings-ui.png`,
`16-matrix-forced-colors-active.png`, `17-matrix-grayscale.png`,
`18-band-{none,fading}-{normal,grayscale,forced}.png`,
`19-student-8a-no-attempts.png`, `20-matrix-{fr,de,en}.png`,
`21-profile-{fr,de,en}.png`, `RV-matrix-shipped-seed-1440.png`,
`RV-phone-matrix-scrolled-right.png`.

> Note on screenshot scale: screenshots numbered `03`–`21` were taken while a
> temporary 30×25 scale fixture was loaded (§6), which widened 7B from 7 to 12
> competency columns. `RV-*` were taken after teardown, at the shipped seed
> (25 × 7 = 175 cells). No finding depends on which was loaded; both were
> re-measured after teardown.

---

## 3. Requirement trace

| # | Requirement | How verified | Result | Evidence |
|---|---|---|---|---|
| **R1** | Doc states formula, decay constants, five thresholds; code implements exactly that | Transcribed `docs/mastery-model.md` §1 into an independent implementation using the doc's own `2^(−x/H)` notation and diffed against `alppy/mastery/model.py` numerically over every §3 worked example | **OK, with one divergence** | All 9 worked examples + the 7-row fade schedule agree to <1e-9. Constants `H=21`, `R=45`, `GRACE=7`, `FLOOR=0.55`, `MIN_EVIDENCE=1.5`, difficulty map, and thresholds 0.90/0.75/0.60 match `model.py:36-77` line for line. **Divergence:** `days_until_review` — see P1-7. Also `docs/plan.md` §6 still prints the superseded one-factor formula (P3-1). |
| **R2** | Hand-computable check + boundaries at exactly 0.90 and 0.75 | Hand computation written out in §4 below; planted the four attempts in the live DB and read the number back from `GET /classes/{id}/mastery` | **OK** | Hand: `0.803436`. API: `0.803435980418111`, band `ok`. Boundaries via API: score exactly `0.9` → **`solid`**; exactly `0.75` → **`ok`**. Both inclusive at the bottom, as `mastery-model.md` §2 states. |
| **R3** | "Not yet seen" distinct from score 0 | API inspection of all 175 cells; zoomed 5× screenshots of a `none` cell and a `fading`-at-zero cell | **API OK · UI FAIL** | API: 14 cells `band:"none", attempts_count:0, last_attempt_at:null` vs 28 cells `band:"fading", score:0.0, attempts_count>0`. Correctly separated. **But both render a bold `0` on screen** — `12-cell-none-zoom.png` vs `12-cell-fading-zoom.png`. P1-1. |
| **R4** | Cell = dot + label + tint density; five bands survive `data-contrast="high"` and greyscale | `getComputedStyle` sampling of one cell per band in each switch state (run twice, independently); `emulateMedia({forcedColors:'active'})`; CSS `grayscale(1)` | **PARTIAL FAIL** | Dot ✓ (disc 4/4·3/4·2/4·1/4·dashed ring, transcribed from the shipped brand SVGs). Tint density ✓. **Visible text label ✗** — the band word exists only in `aria-label`. Greyscale (light) ✓ — luminance ramp 0.605/0.685/0.772/0.836/0.910, strictly monotonic. Forced-colors ✓ — glyph is the sole surviving channel and it holds. **`data-contrast="high"` ✗** — all five cells byte-identical to default (P1-6). **Dark ✗** — `ok` ink-on-tint 1.03:1 (P1-6). |
| **R5** | Drill-down from a cell to the attempts behind it, each linking back to its sheet and scan | Clicked cells in the running UI; enumerated `main a` on the destination; grepped the whole API surface for an attempts endpoint | **FAIL — not implemented** | Clicking any cell goes to `/classes/{id}/students/{studentId}`; the competency is discarded (`page.tsx:146-148`). No attempt list, no dates, no correct/incorrect marks, and `main a` on the profile returns `[]` — **zero links**. No `/attempts` endpoint exists (`api/v1/__init__.py` registers 10 routers, none of them attempts). `Attempt` already carries `sheet_id`, `sheet_instance_id`, `detection_id` — the data is there, the endpoint is not. P1-2. |
| **R6** | Profile: strengths, gaps, trend over time (ring + curve), history of sheets | Loaded the profile for every one of the 25 seeded students; read the API payload; screenshotted | **PARTIAL FAIL** | Strengths ✓, gaps ✓, ProgressRing ✓. **Trend ✗** — gated on `history.length > 1`; max history length across all 25 students is **1**, so `MasteryCurve` never mounts (`05-student-profile-full.png` — the lower half of the page is empty). **Sheets/assessments history ✗** — the API returns `sheets_taken: 3` (an integer, not a list) and the page never renders even that. P1-4. Consistency of trend vs matrix: **UNVERIFIED** — no trend exists to compare. |
| **R7** | New scan updates matrix and profile; `MasterySnapshot` retains the previous value (time series) | Confirmed scan `03f02ceb` through the API and diffed the matrix before/after; ran `recompute_for_students` three times (twice same day, once next day) against the live postgres | **OK** | Confirm returned `students_affected:25, competencies_updated:272`; snapshot rows 273→384. Time-series probe: day-1 pass → 28 rows; second same-day pass → **28 rows (updated in place, count unchanged)**; day-2 pass → **56 rows, 2 distinct days**. Append, not overwrite — confirmed on real postgres. The matrix is computed live from attempts (`mastery_service.py:241-273`), not read from snapshots, so it is never stale. Caveat: in-app navigation can serve a 30 s stale cache (P2-7). |
| **R8** | 30 × 25 renders <2 s and is keyboard-navigable (arrows between cells, Enter to drill down) | Seeded a temporary 30-student × 25-competency class with 4 500 attempts over 3 weeks; timed the API ×5 and the UI ×4; drove the keyboard cell by cell | **Speed OK · Keyboard FAIL** | API at 30×28 (840 cells, 244 KB): **83 / 110 / 146 / 191 / 405 ms**. UI time-to-first-cell: **152 / 186 / 193 / 250 ms**. Comfortably under 2 s. **Arrows do nothing** — ArrowRight/Left/Up/Down/Home/End all leave `document.activeElement` unchanged; no `onKeyDown` and no roving tabindex anywhere in `MasteryMatrix.tsx` (`tabindex` survey: `{"(none)": 300}`). Tab does step cell-to-cell and **Enter does drill down**. At 30×25 a teacher tabs up to 750 times. P1-5. |
| **R9** | Matrix endpoint refuses another teacher's class | Created a second school + teacher + class + student directly in the running postgres, then probed as the demo teacher | **OK** | Foreign class → `404 not_found`; foreign student profile → `404 not_found`; both **indistinguishable from a non-existent id** (same code, same message shape), so existence is not leaked. Unauthenticated → `401`. Malformed uuid → `422`. Also covered by `test_api_tenancy.py:27,39`. Rows deleted afterwards. |
| **R10** | Sort students by weakest competency; filter to a chapter; correct against SQL | Grepped the whole API and web surface; probed the one filter that exists against a SQL ground truth | **FAIL — not implemented** | **No sorting anywhere.** **No chapter filter** — `class_mastery` accepts only `subject_id` (`api/v1/mastery.py:28`); the class page renders no sort or filter control at all. The `Chapter` model with `competency_ids` exists and is unused here. The `subject_id` filter that does exist is *correct* (API 12 competencies = SQL 12; unknown subject → 0 cells) but is weakly discriminated: the seed has exactly one subject, so passing it and omitting it are indistinguishable. P1-3. |
| **X-cut** | Design tokens | `grep -rnE "#[0-9a-fA-F]{3,8}\b\|rgb\(" apps/ packages/ --include=*.tsx --include=*.ts --include=*.css` | **OK** | Only hit outside `tokens.css`/`print.css` is a *comment* at `apps/web/e2e/themes.spec.ts:41`. `--c-mastery-*` values are byte-identical to the shipped `docs/design/alppy-brand-assets/brand/alppy-mastery-tokens.css` (`--c-mastery-ok: #86cf5b` ✓); all five `-glyph` tokens present; band glyph geometry transcribed from the shipped SVGs, not redrawn. |
| **X-cut** | Mandarin accent | `grep -rn "c-accent"` over the F3 surface | **OK** | Zero `--c-accent-*` on either F3 screen. Only sanctioned owners (`AiBadge`, the accent chip/button recipes, the single point-of-attention dot in the shipped illustrations). |
| **X-cut** | Caveat once per page | `grep -rn "font-hand\|Caveat"` | **OK** | Zero uses on both F3 screens. (`.hand` is in fact unused product-wide.) |
| **X-cut** | i18n fr/de/en | `pnpm i18n:check`; screenshotted all three locales on both screens; diffed band labels against `mastery-model.md` §2 | **OK** | 287 keys in sync. Every string changes across locales, including API-served curriculum labels. Band labels match the doc exactly in all three languages. No French leaking into de/en. No hard-coded visible strings in the page files. **No dates are rendered anywhere on either screen** (elapsed time is a relative phrase), so locale *date* formatting is UNVERIFIED — there is nothing to format. |
| **X-cut** | Privacy — no student name reaches a model provider | Grepped the F3 server path for AI imports; checked the `model_call` audit table after the whole review | **N/A — OK** | `alppy/mastery/`, `services/mastery_service.py` and `api/v1/mastery.py` import nothing from `alppy.ai`. `select count(*) from model_call` = **0** after the entire session. F3 makes no model call, so there is no prompt to leak into. |
| **X-cut** | `tabular-nums` on every numeral | `getComputedStyle(el).fontVariantNumeric` walked up the parent chain | **OK** | Matrix cell score, ProgressRing centre, MasteryMeter percent, student UID all report `"tabular-nums"`. Nothing containing a digit reports `"normal"`. |
| **X-cut** | Reachability by clicking | Navigated the running app by click only | **PARTIAL** | Matrix: 2 clicks from home ✓. Profile: reachable **only** by clicking a coloured cell — student names in the roster column are plain `<th>`, not links, and a class with no attempts has no cells at all, so its students' profiles are unreachable. P2-4. |

---

## 4. The R2 hand computation (repeatable)

Written out so the next reviewer can redo it on paper.

**Setup.** One student, one competency, all four items at difficulty 3 (so
`d = 1.0` and drops out of the arithmetic). `H = HALF_LIFE_DAYS = 21`.

| # | outcome | age (days) | `w = 2^(−age/21)` | `w · correct` |
|---|---|---|---|---|
| 1 | correct | 0 | `2^0 = 1.000000` | 1.000000 |
| 2 | correct | 7 | `2^(−1/3) = 0.793701` | 0.793701 |
| 3 | **wrong** | 21 | `2^(−1) = 0.500000` | 0 |
| 4 | correct | 42 | `2^(−2) = 0.250000` | 0.250000 |
| | | | **Σw = 2.543701** | **Σw·c = 2.043701** |

```
accuracy = 2.043701 / 2.543701           = 0.803436
last attempt = today → idle = 0 − 7 = −7 ≤ 0 → recency = 1.0
score    = 0.803436 × 1.0                = 0.803436   → band `ok` (0.75 ≤ s < 0.90)
```

**Observed from `GET /api/v1/classes/{id}/mastery`** after planting exactly these
four attempts:

```json
{"score": 0.803435980418111, "band": "ok", "attempts_count": 4,
 "provisional": false, "days_until_review": 12}
```

Agreement to 1e-9. ✓

**Boundaries.** Both constructed so the score is exact in binary:

| Case | Construction | API score | API band | Which side |
|---|---|---|---|---|
| exactly **0.90** | 9 correct + 1 wrong, all today, d3 → `9/10 × 1.0` | `0.9` | **`solid`** | **inclusive at the bottom of `solid`** |
| exactly **0.75** | 3 correct + 1 wrong, all today, d3 → `3/4 × 1.0` | `0.75` | **`ok`** | **inclusive at the bottom of `ok`** |
| exactly **0.60** | 3 correct + 2 wrong, all today, d3 | `0.6` | `weak` | inclusive at the bottom of `weak` |
| 0.89 / 0.74 / 0.59 | 89, 74, 59 correct of 100 today | — | `ok` / `weak` / `fading` | the band below, as expected |

This matches `mastery-model.md` §2 ("Thresholds are **inclusive at the bottom**
of each band: exactly `0.90` is solid") and `model.py:149-159`.

**Fade schedule** (5 correct, then nothing) reproduced against `model.py`:
day 0–7 → 1.00 solid · **day 14 → 0.8978 → `ok`** · day 21 → 0.8060 `ok` ·
day 28 → 0.7236 `weak` · day 35 → 0.6497 `weak` · day 42 → 0.5833 `fading` ·
day 56+ → 0.55 `fading`. The doc's table rounds day 14 to "0.90 · Solid / To
review"; the actual value is 0.8978 and the band is unambiguously `ok` (P3-2).

---

## 5. Findings

### P1-1 · "Not yet seen" renders as a bold `0`, collapsing the band the model exists to protect

**Severity P1.** `docs/mastery-model.md` §2 puts this in bold: *"'Not yet seen' is
a band, not a zero. A competency nobody has assessed is not the same thing as one
a student fails, and collapsing the two would send a child remedial work on
material they have never been taught."* The API honours it. The rendering does not.

**Repro.** Open `http://localhost:3000/fr/classes/40c54794-838f-4cd8-a8c8-c64b99213c0b`,
find a grey cell (14 exist in the shipped seed) and a pale-pink cell whose student
genuinely scored zero.

**Expected.** A never-assessed cell shows no number — the component already
supports this: `MasteryCell.tsx:142` renders the numeral only `if score !== null`,
and `MasteryMatrix.tsx:50` defines `EMPTY = { band: 'none', score: null }` for
exactly this case.

**Observed.** Both cells display a bold **`0`**. The only differences are the tint
and the 12 px glyph. The accessible name is worse: `"Anna Meier · … · Pas encore
vu · 0 %"` — it asserts "not yet seen" and "0 %" in the same breath.

| | `none` | `fading` at zero |
|---|---|---|
| visible text | **`0`** | **`0`** |
| `data-band` | `none` | `fading` |
| bg / ink | `rgb(245,244,249)` / `rgb(119,115,140)` | `rgb(255,230,230)` / `rgb(238,84,89)` |

**Cause.** `apps/web/src/app/[locale]/classes/[classId]/page.tsx:44-53` builds
every cell as `{ band: cell.band, score: cell.score }`, and the API sends
`score: 0.0` (not `null`) for the `none` band — `mastery_service.py:229-238`
passes `result.score`, which `model.py:184` sets to `0.0` for an empty history.
The `EMPTY` sentinel is therefore never reached.

**File:line.** `apps/web/src/app/[locale]/classes/[classId]/page.tsx:47-50`;
`packages/ui/src/components/domain/MasteryCell.tsx:142`;
`apps/api/alppy/services/mastery_service.py:229-238`.

**Fix direction.** Map `band === 'none'` to `score: null` at the web boundary (or
make the API send `score: null` for that band) so the numeral is suppressed, and
drop the `· 0 %` from the accessible name for that band.

**Evidence.** `docs/reviews/screenshots/F3/12-cell-none-zoom.png`,
`12-cell-fading-zoom.png`, `18-band-none-grayscale.png`.

---

### P1-2 · R5 is not implemented: no attempt drill-down, no link back to sheet or scan, and the clicked competency is discarded

**Severity P1.** R5 is a whole checklist requirement with no implementation.

**Repro.** On the matrix, click the cell for *Léa Progin × MA.1.A.3* (aria-label
`"… Effectuer les opérations de base … · À revoir · 79 %"`).

**Expected.** A view of the attempts behind that cell — each with its date,
correct/incorrect, and a link back to the sheet and the scan it came from.

**Observed.** Navigation to `/fr/classes/{classId}/students/{studentId}` — no
competency id, no query param, no fragment. The destination shows the whole
student (1 gap + 5 strengths = 6 of her 12 competencies) and never mentions the
competency that was clicked; click one of the other 6 and the destination does not
name it at all. There is **no attempt list**. Enumerating `main a` on the
destination returns **`[]`** — the profile has zero links, to a sheet, a scan, or
anywhere else.

**File:line.** `apps/web/src/app/[locale]/classes/[classId]/page.tsx:146-148`
destructures only `{ studentId }` and throws away `competencyId`;
`apps/api/alppy/api/v1/__init__.py:26-37` registers ten routers and none of them
serves attempts; `StudentProfileOut` (`schemas/__init__.py:398-404`) carries no
attempt data. Note `MasteryCell.tsx:104-107` documents the intended behaviour —
*"a real `<button>`: every cell drills down to the attempts behind it"* — which is
not what happens.

**Fix direction.** Add a `GET /students/{id}/competencies/{cid}/attempts` endpoint
projecting `Attempt.sheet_id` / `sheet_instance_id` / `detection_id` (all already
on the row), and open it from the cell as a panel or a `?competency=` deep link.

**Evidence.** `04-cell-click-result.png`, `05-student-profile-full.png`.

---

### P1-3 · R10 is not implemented: no sort by weakest competency, no chapter filter

**Severity P1.**

**Repro.** Load the matrix; look for any control to sort or filter.

**Expected.** Sort students by weakest competency; filter the matrix to a chapter.

**Observed.** Neither exists in the UI (the class page renders a title, a legend
`Panel` and the matrix `Card` — nothing else) nor in the API. `class_mastery`
accepts exactly one optional parameter, `subject_id`. Students are always ordered
by `Student.number` (`mastery_service.py:138`) and competencies always by
`Competency.code` (`:164`). The `Chapter` model exists with a `competency_ids`
list (`schemas/__init__.py:124-129`) and is not used on this screen.

**File:line.** `apps/api/alppy/api/v1/mastery.py:24-31`;
`apps/api/alppy/services/mastery_service.py:131-170`;
`apps/web/src/app/[locale]/classes/[classId]/page.tsx:83-153`.

**Fix direction.** Add `chapter_id` alongside `subject_id` on the endpoint, and a
client-side sort key (worst cell per student) — the matrix payload already carries
everything needed for the sort.

**Sub-note (not a separate finding).** The one filter that does exist is correct:
API returns 12 competencies with `subject_id` set and 12 without, matching the SQL
ground truth `select count(distinct ec.competency_id) … = 12`; an unknown subject
yields 0 cells. But the seed has a single subject, so the positive path is not
discriminated by the data — the same weakness the unit test has
(`test_api_mastery.py:104-107`).

---

### P1-4 · The trend curve never renders, and the sheet/assessment history is absent

**Severity P1.** R6 asks for "trend over time (ProgressRing + curve), history of
sheets/assessments". Two of the four are missing in the shipped product.

**Repro.** Open any student profile in the seeded demo.

**Expected.** A curve of the score over time, and a list of the sheets the student
sat.

**Observed.** The trend panel is gated on
`data.all_competencies.some((c) => c.history.length > 1)`. Queried all 25 students
in 7B: **maximum history length = 1; competencies with more than one point = 0.**
`MasteryCurve` therefore never mounts, and the lower two-thirds of the profile is
empty white space. The cause is upstream: the seed calls `recompute_for_students`
**once** (`seed/__init__.py:77-83`), so `select count(distinct date(computed_at))
from mastery_snapshot` = **1** — one snapshot day for the whole demo, despite the
seed simulating three weeks of attempts.

The sheet history is worse: the API returns `sheets_taken: 3` — an integer count,
not a list — and the profile page never renders even that number. Nothing on the
page names a sheet or a date, in any locale.

**File:line.** `apps/web/src/app/[locale]/classes/[classId]/students/[studentId]/page.tsx:115`
(the gate) and `:90-140` (no sheet list);
`apps/api/alppy/services/mastery_service.py:346-360` (`sheets_taken` reduced to a
count); `apps/api/alppy/seed/__init__.py:77-83` (one recompute).

**Fix direction.** Have the seed recompute at each simulated session date so the
curve has points; return `sheets_taken` as a list of `{sheet_id, title, date}` and
render it.

**Evidence.** `05-student-profile-full.png`, `21-profile-{fr,de,en}.png`.

---

### P1-5 · No arrow-key navigation in the matrix

**Severity P1.** R8 asks explicitly for "arrow keys between cells, Enter to drill
down". Enter works; arrows do not.

**Repro.** Focus the first cell of the first row, press ArrowRight.

**Expected.** Focus moves to the next cell.

**Observed.** `document.activeElement` is unchanged after ArrowRight, ArrowLeft,
ArrowUp, ArrowDown, Home and End — verified one key at a time by reading the
active element's `aria-label` after each. There is no `onKeyDown` handler and no
roving tabindex: a `tabindex` survey of the grid returns `{"(none)": 175}`, i.e.
every cell is a natural tab stop. Tab does walk left-to-right along the row, so at
the R8 scale of 30 × 25 a teacher presses Tab up to **750 times** to cross the
grid. Enter does navigate, and the focus ring is clearly visible
(`box-shadow: rgb(91,63,240) 0 0 0 2px, rgb(236,231,255) 0 0 0 6px`).

**File:line.** `packages/ui/src/components/domain/MasteryMatrix.tsx:81-160` — no
key handling. The pattern exists elsewhere in the same library
(`SegmentedControl.tsx:57-58`, `CodeInput.tsx:74`), so this is an omission, not a
gap in capability.

**Fix direction.** Roving tabindex on the grid with arrow/Home/End handling, so
the grid is one tab stop and arrows move within it.

---

### P1-6 · `data-contrast="high"` never reaches the matrix cells, and dark theme makes the scores unreadable

**Severity P1.** Violates the cross-cutting requirement that nothing becomes
unreadable in any of the four switch states, and defeats the switch a low-vision
teacher would reach for first.

**Repro.** Open the matrix, set `document.documentElement.setAttribute('data-contrast','high')`
(or use the real Settings UI — the two behave identically). Then add
`data-theme="dark"`.

**Expected.** High contrast raises the contrast of the data cells; dark theme
keeps the numerals legible.

**Observed** — computed styles, sampled twice independently:

| band | default bg / ink → ratio | `contrast=high` | `theme=dark` → ratio |
|---|---|---|---|
| solid | `rgb(118,223,193)` / `rgb(0,153,109)` → 2.27 | **byte-identical to default** | 1.52 |
| ok | `rgb(186,228,162)` / `rgb(86,133,58)` → 3.06 | **byte-identical** | **1.03** |
| weak | `rgb(255,225,146)` / `rgb(148,117,35)` → 3.40 | **byte-identical** | **1.12** |
| fading | `rgb(255,230,230)` / `rgb(238,84,89)` → 2.93 | **byte-identical** | 3.87 |
| none | `rgb(245,244,249)` / `rgb(119,115,140)` → 4.16 | **byte-identical** | 2.95 |

Under `data-contrast="high"` the body goes `rgb(255,255,255)` and the chrome flips
to black-on-white, but every band cell's background, ink **and** border are
unchanged — the switch styles the frame and skips the data. No band clears 4.5:1
in any state.

Under `data-theme="dark"` the numerals in the `ok` (1.03:1) and `weak` (1.12:1)
cells are effectively invisible — visible in `13-matrix-dark.png`, where the green
and mustard cells show no readable number while the teal `solid` cells still read
"100". Dark + high-contrast together is worse: the canvas goes pure black, tints
stay saturated, ink is unchanged.

**Cause.** `--c-mastery-*` is defined **only** on bare `:root`
(`packages/ui/src/design/tokens.css:78-108`). There is no override in the
`prefers-color-scheme: dark` block, the `:root[data-theme='dark']` block, the
`:root[data-contrast='high']` block, or the dark+HC block. The `-tint` values are
`color-mix(…, var(--c-surface))`, so the tint follows the theme surface while the
calibrated opacities and the fixed `-ink` colours do not. Resolving the same
tokens against each theme's surface:

```
light  #ffffff : greyY 0.605 0.685 0.772 0.836 0.910   monotonic ✓
dark   #1f1b3a : greyY 0.140 0.184 0.222 0.028 0.028   ramp broken; |fading−none| = 0.00009
hc-dk  #000000 : greyY 0.106 0.145 0.178 0.008 0.007   ramp broken
```

So in dark theme `fading` and `none` also land 0.0001 apart in greyscale — the two
bands the P1-1 `0` collapse already confuses.

**File:line.** `packages/ui/src/design/tokens.css:78-108` (the only definitions);
`packages/ui/src/components/domain/MasteryCell.tsx:8-14` (consumes `-tint`/`-ink`).

**Fix direction.** Ship `--c-mastery-*-tint`/`-ink` overrides for the dark and
high-contrast blocks, re-deriving the opacities against those surfaces so the ramp
stays monotonic, rather than letting `color-mix` re-blend a light-surface
calibration.

**Evidence.** `13-matrix-dark.png`, `13-matrix-contrast-high.png`,
`15-matrix-all-switches-on-via-settings-ui.png`, `13-profile-dark.png`.

---

### P1-7 · `days_until_review` returns `None` for the most urgent cells, contradicting the doc

**Severity P1** — this is an R1 doc↔code divergence with a user-visible consequence.

**Repro.** Plant five wrong attempts on one competency for one student, then load
that student's profile.

**Expected.** `docs/mastery-model.md` §4: *"It returns `0` when already due, and
`None` when the recency floor holds the score above the threshold indefinitely, or
when the competency has never been assessed."* A score of 0.0 is maximally due, so
`0`.

**Observed** (live API):

```
MSN 32.1  score=0.0  band=fading  n=5  provisional=false  days_until_review=None
```

The profile's `MasteryMeter` caption chain
(`students/[studentId]/page.tsx:73-81`) therefore falls to the
`days_until_review === null` branch and renders `mastery.attempts` → **"5
réponses"** instead of `mastery.reviewOverdue` → **"à revoir maintenant"**. The
teacher's most urgent gap is captioned with a neutral attempt count. In the
shipped seed **28 of 175 cells** are in this state (`score == 0` with
`attempts_count > 0`).

**Cause.** `model.py:170` — `if last_attempt_at is None or accuracy <= 0.0: return None`.

**Same function, second divergence.** `model.py:172-173`
(`if accuracy * RECENCY_FLOOR >= BAND_OK: return None`) is **unreachable**:
`accuracy ≤ 1.0` and `1.0 × 0.55 = 0.55 < 0.75 = BAND_OK`. The docstring at
`:166-168` and doc §4 both describe a "the floor keeps it above the threshold
forever" case that the shipped constants make impossible; line `:177` is dead for
the same reason. So doc §4 is wrong in both directions — it documents a `None`
case that cannot happen and omits the one that does.

**File:line.** `apps/api/alppy/mastery/model.py:170`, `:172-177`;
`docs/mastery-model.md` §4;
`apps/web/src/app/[locale]/classes/[classId]/students/[studentId]/page.tsx:73-81`.

**Fix direction.** Return `0` when the current score is already below `BAND_OK`
(including accuracy 0), reserve `None` for "never assessed", and delete the
unreachable floor branch and the doc sentence describing it.

---

### P1-8 · Every e2e test named "matrix renders in …" screenshots the class *list*; the matrix has zero visual-regression coverage

**Severity P1.** The suite asserts coverage it does not have, and the one test
guarding the documented responsive hard case always skips.

**Repro.**

```bash
cd apps/web && PLAYWRIGHT_CHANNEL=chrome pnpm exec playwright test --project=desktop
```

**Expected.** Six theme states × two viewports and three locales of the mastery
matrix, pinned by screenshot.

**Observed.** All nine `matrix renders in …` tests navigate to **`/fr/classes`** —
the class *index*, which contains no matrix
(`apps/web/src/app/[locale]/classes/page.tsx` has no `MasteryMatrix` import). I
opened a baseline to confirm: `e2e/themes.spec.ts-snapshots/classes-light-desktop-darwin.png`
is a page with two class cards and nothing else. So all 12 `classes-*` and 6
`classes-locale-*` baselines are screenshots of the wrong page, and the matrix has
**no** visual-regression coverage in any theme, contrast or locale.

Separately, `the matrix scrolls in its own container with a sticky name column`
**always skips** — it locates `[data-matrix-scroll]`, and that attribute exists
nowhere in the product (`grep -rn "data-matrix-scroll" apps/web packages/ui`
returns exactly one hit: the test itself). Run output:
`26 passed, 2 skipped` with `- 10 [desktop] › responsive.spec.ts:24:1 › the matrix
scrolls in its own container…`.

And `the page never scrolls sideways` (`responsive.spec.ts:11-22`) iterates
`['/fr', '/fr/classes', '/fr/sources', '/fr/adaptive', '/fr/settings']` — it never
visits `/fr/classes/{classId}` either, which is why it does not catch P2-1.

**File:line.** `apps/web/e2e/themes.spec.ts:26-30`; `apps/web/e2e/locales.spec.ts:18-22`;
`apps/web/e2e/responsive.spec.ts:11-31`.

**Fix direction.** Point all three at `/fr/classes/{seeded classId}`, render
`data-matrix-scroll` on the scroller in `MasteryMatrix`, and re-baseline.

---

### P2-1 · The matrix page overflows the document horizontally on a phone

**Severity P2** (P1 by the project's own predicate, reduced because the visible
pan did not reproduce in both runs).

**Repro.** Pixel 7 viewport, logged in, `/fr/classes/{classId}`.

**Observed** (shipped seed, 7 competency columns):

```
/fr/classes                 doc.scrollWidth=412 clientWidth=412 → overflow   0 px
/fr/classes/{classId}       doc.scrollWidth=808 clientWidth=412 → overflow 396 px
                            body.scrollWidth=412   html/body overflow-x: visible
offender: TABLE.min-w-max…  getBoundingClientRect() left=16 right=815
```

That is exactly the quantity `responsive.spec.ts:11-22` asserts to be `≤ 1` — the
matrix route fails the project's own guard by 396 px (811 px at 12 columns). The
overflow escapes past the `overflow-x-auto` wrapper at `<html>`, most likely via
the `-mx-4 px-4` negative-margin bleed (`MasteryMatrix.tsx:86`).

**Honest caveat.** The *visible* consequence did not reproduce consistently: the
independent UI run measured `window.scrollX = 833` after `scrollTo` with the page
visibly slid off-screen; two of my own runs measured `window.scrollX = 0` after
both a programmatic scroll and a real touch drag, and the screenshot
(`RV-phone-matrix-scrolled-right.png`) shows a correctly-behaved page with a
working sticky name column. The document-level overflow is reproducible; whether
the window pans appears to depend on the gesture target.

**File:line.** `packages/ui/src/components/domain/MasteryMatrix.tsx:82-90`;
`apps/web/e2e/responsive.spec.ts:12`.

**Fix direction.** Clip at the scroller (or drop the negative-margin bleed on
small viewports), and add `/fr/classes/{classId}` to the sideways-scroll test's
path list so this is guarded.

---

### P2-2 · The legend maps nothing: five identical grey chips, no colour, no glyph, no tint

**Severity P2.** The cells carry colour + tint density + glyph but **no visible
band name**; the legend carries names but no colour, no glyph and no density. So
nothing on the class page connects a cell's appearance to a band's name — which is
the only job a legend has.

**Repro.** Look at the legend on the matrix screen in any theme.

**Observed.** `<Chip>{bandLabels[band]}</Chip>` with no `variant`, so all five
render the neutral recipe (`--chip-bg: var(--c-surface-2)`,
`--chip-ink: var(--c-ink-700)`) — five identical grey pills. Confirmed visually in
`13-matrix-default.png` and `RV-phone-matrix-scrolled-right.png`. The comment
directly above the code says the opposite of what the code does: *"The legend is
not decoration: colour is never the only channel, so the words have to be on the
page next to the grid."*

Everything needed is already built and unused: `BandGlyph` is exported from the
library entry point, `.ard-mastery[data-band]` gives each band its own tint/ink,
and the catalogue ships `mastery.bandHelp.{solid,ok,weak,fading,none}` — the
threshold explanations — in all three locales, referenced by no source file.

**File:line.** `apps/web/src/app/[locale]/classes/[classId]/page.tsx:112-123`;
`packages/ui/src/components/domain/MasteryCell.tsx:129,141-142`.

**Fix direction.** Render each legend entry as glyph + tint swatch + name (+
`bandHelp` threshold), i.e. reuse `MasteryMeter`'s vocabulary.

---

### P2-3 · A never-assessed student's profile reads "0"

**Severity P2.** The P1-1 collapse again, at the profile level.

**Repro.** `/fr/classes/{8A}/students/{Hugo Blanc}` — a student with zero attempts.

**Observed.** `overall_score: 0.0`, `all_competencies: []`. The page renders the
normal chrome with "Aucune lacune détectée." / "Pas encore de point fort établi."
and a **ProgressRing reading `0`**. A child who has never been assessed is
presented as scoring zero out of a hundred. There is no empty state for this case.

Two aggravating details on the same ring: it is painted `stroke-primary-500`
(violet — the *action* colour, per CLAUDE.md "Violet is ink… It marks action. It
is never decorative") because the page never passes the `band` prop the component
supports; and it renders a bare integer with **no `%` and no band word**, so the
profile's single most prominent number is colour-plus-digit with no label.

**File:line.** `apps/web/src/app/[locale]/classes/[classId]/students/[studentId]/page.tsx:48,93-97`;
`apps/api/alppy/services/mastery_service.py:344` (`overall = … if entries else 0.0`);
`packages/ui/src/components/domain/ProgressRing.tsx:98` (`band ? BAND_STROKE[band] : 'stroke-primary-500'`).

**Fix direction.** Render an empty state when `all_competencies` is empty; pass
`band` and a `centre` carrying the unit for the assessed case.

**Evidence.** `19-student-8a-no-attempts.png`.

---

### P2-4 · A class with no attempts has no clickable route to any student profile, and the profile is a dead end

**Severity P2.**

**Repro.** Click through to class 8A (2 students, 0 attempts).

**Observed.** The matrix is replaced by the "Aucune donnée de maîtrise" empty
state, so there are no cells. Since clicking a cell is the **only** route to a
profile — the roster names in the sticky column are plain `<th>`, not links, and
`main` on the matrix page contains exactly one `<a>` (`/fr/sheets/new`) — neither
8A student's profile is reachable by clicking, though both return 200 from the
API. Once on a profile, `main a` returns `[]`: no breadcrumb, no link back to the
class, no link anywhere.

**File:line.** `packages/ui/src/components/domain/MasteryMatrix.tsx:124-134` (row
header is a plain `<th>`); `apps/web/src/app/[locale]/classes/[classId]/page.tsx:99-109`
(the empty state replaces the whole matrix, roster included).

**Fix direction.** Make the roster name a link to the profile, and keep the roster
visible alongside the "no mastery data yet" message; add a back-link on the profile.

---

### P2-5 · `pnpm test` runs zero tests, and `packages/ui` is never linted

**Severity P2.** Both gates named in CLAUDE.md pass vacuously for the F3 UI.

**Observed.**

```
pnpm test  →  Tasks: 1 successful (that task is @alppy/ui:build)   exit 0
pnpm lint  →  Tasks: 1 successful (@alppy/web:lint only)           exit 0
```

No package defines a `test` script (`apps/web`: `dev build start typecheck
test:e2e test:e2e:update e2e:server lint`; `packages/ui`: `build clean typecheck`;
`packages/shared`: no `scripts` key). `turbo.json`'s `"test": {"dependsOn":
["^build"]}` is why a build shows up as a "successful task". There is no vitest or
jest config anywhere outside `node_modules`. Separately, `packages/ui` has no
`lint` script — and **every F3 UI component lives there** (`MasteryMatrix`,
`MasteryCell`, `MasteryMeter`, `MasteryCurve`, `ProgressRing`), so all of it is
outside ESLint. There is also no coverage tooling: neither `pytest-cov` nor
`coverage` is installed, so no coverage number can be produced for the model.

**Fix direction.** Add a `lint` script to `packages/ui`, and either add a real
frontend unit-test layer or remove `test` from the root scripts so it stops
reading as a green gate.

---

### P2-6 · No test proves `MasterySnapshot` is a time series

**Severity P2.** The behaviour is correct (verified by hand, R7) but unguarded.

**Observed.** The only test in this area,
`test_recompute_is_idempotent_within_a_day` (`test_api_mastery.py:134-142`),
asserts the *opposite* property — that a same-day recompute does **not** append
(`len(after) == len(before) == 2`). The append branch
(`mastery_service.py:203-216`) is only ever reached on the very first write.
`recompute_for_students` takes a `now` parameter precisely so a second day can be
simulated, and **no test ever passes it**: both call sites
(`test_api_mastery.py:71`, `:139`) omit it. Profile history is only ever asserted
at length 1 (`:130`), and `MAX_HISTORY_POINTS = 30` truncation
(`mastery_service.py:52`, applied at `:293`) is entirely untested.

Related weak assertions in the same file, worth fixing while there:
`:129-131` accepts `band in {"solid","fading"}` — the only two bands the fixture
produces, so it cannot fail; `:104-107` asserts the subject filter returns 2
competencies, which the *unfiltered* matrix also returns; and every API test calls
`.json()` without checking `.status_code` — including
`test_profile_of_a_student_with_no_attempts_is_empty_not_an_error` (`:145`), whose
name is a claim about not erroring that it never checks.

**Fix direction.** One test that recomputes at `now` and `now + 1 day` and asserts
two rows with the earlier value preserved.

---

### P2-7 · Confirming a scan does not invalidate the mastery queries

**Severity P2.**

**Observed.** `useConfirmScan` invalidates `queryKeys.scan(scanId)` and
`queryKeys.home` only — not `['classes', id, 'mastery', …]` or
`['students', id, 'mastery']`. With the client default `staleTime: 30_000` and
`refetchOnWindowFocus: false`, a teacher who looked at the matrix, then confirmed
a scan, then navigated back within 30 s is served the pre-scan matrix from cache.
A hard reload fixes it (fresh QueryClient), which is why R7's "beyond reload"
wording is satisfied — but the in-app path is stale.

**File:line.** `apps/web/src/lib/api/queries.ts:303-314`;
`apps/web/src/components/Providers.tsx:16`.

**Fix direction.** Add the two mastery keys to the `onSuccess` invalidation list.

---

### P2-8 · 15 translated strings are dead, including the one that makes the cell's accessible name translatable

**Severity P2.**

**Observed.** Present and in sync in all three catalogues (so `i18n:check` is
happy) but referenced by no source file:
`mastery.cellLabel` (`"{student}, {competency} : {band}, {percent} %"`),
`mastery.bandHelp.{solid,ok,weak,fading,none}`, `mastery.provisional`,
`mastery.notAssessed`, `mastery.score`, `student.{profile,history,overall}`.

`mastery.cellLabel` matters: `MasteryCell` exposes a `formatLabel` prop for exactly
this, and `grep -rn "formatLabel"` finds no caller outside the component's own
file. So every cell falls back to `defaultLabel` (`MasteryCell.tsx:97-101`), which
hard-codes the separator `' · '` and the unit `' %'` with a leading space — French
convention, wrong for English (`82%`). `mastery.bandHelp.*` is precisely the
legend copy that P2-2 is missing.

**File:line.** `packages/ui/src/components/domain/MasteryCell.tsx:97-101`;
`apps/web/src/app/[locale]/classes/[classId]/page.tsx:126-150`.

---

### P2-9 · The paper channel is defined and never used

**Severity P2.** DESIGN.md §9 and CLAUDE.md both require that on paper a band
carries a distinct underline style, because the sheets get photocopied.
`print.css:174-179` defines exactly that — solid / dashed / dotted / double / wavy
per band. `grep -rn "print-band" apps/web/src packages/ui/src` returns **nothing**:
no component ever applies the class. Print the matrix today and the five bands
reduce to five tints with no underline distinction, leaving the 12 px glyph as the
only non-colour channel.

**File:line.** `packages/ui/src/design/print.css:174-179`.

---

### P3 findings

1. **`docs/plan.md` §6 prints the superseded one-factor formula**
   (`score = Σ(w_i·correct_i)/Σ(w_i)`, no recency). `decisions-log.md` D4 and
   `mastery-model.md` §1 supersede it, and the code follows the latter. Stale doc.
2. **`mastery-model.md` §3 fade schedule rounds day 14 to `0.90` / "Solid / To
   review"**; the computed value is `0.8978` and the band is unambiguously `ok`.
   Harmless, but it is the one row a reader would use to check the threshold.
3. **Dead code in `days_until_review`** — `model.py:173` and `:177` are
   unreachable given the shipped constants (see P1-7).
4. **Panel used at top level on both F3 screens.** `page.tsx:114` (legend) and
   `students/…/page.tsx:116` (trend) sit directly on the page canvas; the latter is
   a direct sibling of two `Card`s holding equivalent content-regions. Per CLAUDE.md
   a Panel is a *subdivision of the object you are already in*, so these read as a
   size knob rather than a different object.
5. **`MasteryMeter`'s dot is not `BandGlyph`.** `.ard-mastery-dot` is a plain
   10 px filled circle, identical in shape for all five bands, while the matrix
   uses the quarter-turn glyph. Two visual vocabularies for one set of five bands.
   Also: `page.tsx:131` passes `uid` into `students`, and `MatrixStudent` has no
   such field — dead prop.

---

## 6. Not checked

- **Whether `data-motion="off"` actually suppresses animation.** Every sampled
  computed value on both screens is byte-identical to default and the static
  screenshots are indistinguishable; I did not capture animation frames. The cells
  do carry `transition-transform hover:-translate-y-px`. **UNVERIFIED.**
- **`data-calm="on"` beyond colour.** Same — no sampled difference on either F3
  screen. Whether it correctly removes decorative illustrations is covered
  elsewhere (`themes.spec.ts:47`) but not on these screens. **UNVERIFIED.**
- **Locale date formatting.** There is not a single date rendered on either F3
  screen in any locale — elapsed time is always a relative phrase ("dans 26 jours"
  / "in 26 Tagen"). Nothing to format, so nothing to check. **UNVERIFIED by
  absence.**
- **Trend-vs-matrix consistency (R6, second half).** Requires a curve; no seeded
  student has more than one history point. **UNVERIFIED.**
- **The printed matrix.** I did not exercise a print path for the class page; the
  P2-9 finding is from the absence of any `print-band` consumer, not from a
  rendered PDF.
- **`pnpm test:e2e` on the phone project.** I ran only `--project=desktop`; one
  test failed there for an environmental reason (Chrome launch timeout at 180 s
  under parallel load), not a product defect. The phone project's touch-target and
  drawer tests were therefore not re-run by me.
- **Screen-reader behaviour.** I read `aria-label`s and roles programmatically but
  did not drive an actual screen reader. The `MasteryCurve` renders no text at all
  (no axis, no labels) and the profile passes it no `description`, so an AT user
  gets the word "Évolution" and nothing about the trend — noted but unverified in a
  real AT.
- **Concurrency / large-class API behaviour beyond 30 students.** R8's ceiling was
  tested at 30 × 25; I did not probe 200 students.
- **Whether the intermittent phone window-pan (P2-1) depends on the gesture
  target.** Reproduced in one of two independent runs; I did not isolate the cause.

---

## 7. Reviewer changes

**No file under `apps/`, `packages/` or `docs/` was modified.** Additions:

- `docs/reviews/F3-review.md` (this file).
- `docs/reviews/screenshots/F3/` — 59 PNGs.

**Temporary changes to the running demo database, all reverted:**

1. Created a second school + teacher + school_year + class + student
   (`1111…`/`2222…`/`3333…`/`4444…`/`5555…`) to probe R9 cross-tenant isolation
   against the live API. **Deleted** — `select count(*) from school` = 1.
2. Created a temporary class `ZZ` (30 students, 4 500 attempts) plus 23
   `exercise_competency` rows, to build the R8 30 × 25 scale case; and planted
   controlled attempt sets on four of those students for the R2 hand-computation
   and boundary checks. **Deleted**, including the 111 orphaned
   `mastery_snapshot` rows the exercise created.
3. The UI agent created class `9Z` to test the "class with no students" empty
   state (the API exposes no DELETE). **Deleted directly in SQL.**

**Post-teardown state verified identical to the pre-review state:** 1 school,
classes 7B (25) and 8A (2), 543 attempts, 161 snapshots across 1 day, and the 7B
matrix back to 25 × 7 = 175 cells with the same band distribution as my first
fetch (`fading 69, ok 39, solid 33, weak 20, none 14`).

**One change I could not revert:** confirming scan `03f02ceb-4d1d-484b-a7a0-fb0182c99186`
to exercise R7 moved it from `NEEDS_REVIEW` to `CONFIRMED` and superseded 50
attempts (`attempts_created: 0, attempts_superseded: 50`). I also assigned its
orphan page to student `7B_03` and assigned a page of scan `405aa244…` to `7B_01`.
Scores were unchanged (the same detections regrade identically), but the scan's
status is not restorable through the API. Re-seed if a pristine scan queue matters.

**Environment note (not a repo defect).** A host-native postgres owns
`127.0.0.1:5432` and shadows the container's published port, so anything on the
host connecting to `localhost:5432` gets `FATAL: role "alppy" does not exist`. I
worked around it by running scripts inside `alppy-api-1`.

---

## 8. Fix brief

> Copy-pasteable prompt for the fixing session.

You are fixing phase F3 (individual student tracking) of the Alppy repository,
against the findings in `docs/reviews/F3-review.md`. Read `CLAUDE.md`,
`DESIGN.md` and `docs/mastery-model.md` first. **Add a regression test for every
item below** — a `pytest` test for the API/model items, a Playwright spec for the
UI items. Do not close an item without a test that fails before your change.

The stack runs with `docker compose up`; log in as `demo@alppy.ch` /
`alppy-demo-2026`; class 7B is `40c54794-838f-4cd8-a8c8-c64b99213c0b`.

**P1-1 — "not yet seen" renders as `0`.**
Repro: open the 7B matrix, compare a grey `none` cell with a pale-pink `fading`
cell whose score is 0. Both show a bold `0`.
Accept: a `none` cell shows the dashed-ring glyph and **no numeral**; its
accessible name no longer says "0 %". `fading`-at-zero still shows `0`.
Test: a Playwright assertion that `button[data-band="none"]` has no digit in its
text content, and that `button[data-band="fading"]` does.
Files: `apps/web/src/app/[locale]/classes/[classId]/page.tsx:47-50`,
`packages/ui/src/components/domain/MasteryCell.tsx:142`.

**P1-2 — R5 drill-down does not exist.**
Repro: click any matrix cell; you land on the student profile with no competency
context, no attempt list, and zero links.
Accept: clicking a cell reaches a view of the attempts behind *that* (student,
competency) pair — each row showing the date, correct/incorrect, and a working
link to the sheet and to the scan it came from. `Attempt` already carries
`sheet_id`, `sheet_instance_id` and `detection_id`.
Test: an API test asserting the new endpoint returns the right attempts with
provenance ids and is tenant-scoped (404 for another school), plus a Playwright
test that clicks a cell and asserts the competency code appears on the destination.
Files: new endpoint in `apps/api/alppy/api/v1/mastery.py`,
`apps/web/src/app/[locale]/classes/[classId]/page.tsx:146-148`.

**P1-3 — R10 sort and chapter filter do not exist.**
Accept: the matrix endpoint accepts `chapter_id` alongside `subject_id`; the class
page offers a chapter filter and a "sort by weakest" control; both give results
matching a direct SQL check.
Test: an API test comparing the filtered competency set against a SQL query, and a
UI test asserting the row order changes and the first row's worst cell is the
worst in the class.
Files: `apps/api/alppy/api/v1/mastery.py:24-31`,
`apps/api/alppy/services/mastery_service.py:131-170`, the class page.

**P1-4 — trend curve never renders; no sheet history.**
Repro: every student's `history` array has length 1, so the gate
`history.length > 1` is never true; `sheets_taken` is an integer and is not shown.
Accept: the seed recomputes at each simulated session date so the demo has a real
time series; the profile shows a curve and a list of the sheets the student sat
(name + date), each linking to the sheet.
Test: a test asserting the seeded demo produces more than one distinct
`date(computed_at)` per (student, competency), and a UI test asserting a curve
`<svg>` is present on a seeded profile.
Files: `apps/api/alppy/seed/__init__.py:77-83`,
`apps/api/alppy/services/mastery_service.py:346-360`, the profile page.

**P1-5 — no arrow-key navigation.**
Accept: the grid is a single tab stop (roving tabindex); Arrow keys move focus
between cells, Home/End jump to row ends, Enter drills down.
Test: a Playwright test pressing each arrow and asserting `document.activeElement`
moves as expected.
File: `packages/ui/src/components/domain/MasteryMatrix.tsx:81-160`.

**P1-6 — high contrast skips the cells; dark theme makes scores unreadable.**
Repro: sample `getComputedStyle` on one cell per band with `data-contrast="high"`
— all five are byte-identical to default. With `data-theme="dark"`, `ok` is
1.03:1 and `weak` 1.12:1.
Accept: `--c-mastery-*-tint` and `-ink` are overridden in the dark,
high-contrast and dark+high-contrast blocks, with the opacities re-derived against
those surfaces so the greyscale ramp stays strictly monotonic and no band's
ink-on-tint falls below 4.5:1.
Test: a Playwright test sampling all five bands in all four states and asserting
both the contrast floor and the monotonic luminance ramp.
File: `packages/ui/src/design/tokens.css:78-108`.

**P1-7 — `days_until_review` returns `None` when it should return `0`.**
Repro: a student with 5 wrong attempts on one competency returns
`days_until_review: null`, so the profile caption reads "5 réponses" instead of
"à revoir maintenant". 28 of 175 seeded cells are in this state.
Accept: `0` whenever the current score is already below `BAND_OK` (accuracy 0
included); `None` only for "never assessed". Delete the unreachable
`accuracy * RECENCY_FLOOR >= BAND_OK` branch and correct `mastery-model.md` §4,
which documents a `None` case the constants make impossible and omits the one that
occurs.
Test: extend `test_fresh_failure_is_fading` to assert `days_until_review == 0`.
Files: `apps/api/alppy/mastery/model.py:170,172-177`, `docs/mastery-model.md` §4.

**P1-8 — the e2e "matrix" tests screenshot the wrong page.**
Repro: all nine `matrix renders in …` tests go to `/fr/classes` (the class index,
which has no matrix); `the matrix scrolls in its own container` always skips
because `[data-matrix-scroll]` exists only in the test.
Accept: those tests navigate to `/fr/classes/{classId}`; `MasteryMatrix` renders
`data-matrix-scroll` on its scroller; baselines re-recorded; the skip is gone.
Files: `apps/web/e2e/themes.spec.ts:26-30`, `apps/web/e2e/locales.spec.ts:18-22`,
`apps/web/e2e/responsive.spec.ts:11-31`,
`packages/ui/src/components/domain/MasteryMatrix.tsx:82-90`.

**Then re-verify, in the running stack:** the R2 hand computation still returns
`0.803436` for four d3 attempts at 0/7/21/42 days; exactly `0.90` is still `solid`
and exactly `0.75` still `ok`; a cross-tenant class id still 404s; the 30 × 25
matrix still renders under 2 s; and
`PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q`,
`.venv/bin/ruff check apps/api`,
`.venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/alppy`,
`pnpm typecheck`, `pnpm lint` and `pnpm i18n:check` are all green.
