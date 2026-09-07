# F4 — Personalised exercise generation (adaptive sheets) · independent review

Reviewer: independent verification pass. Date: 2026-09-06.
Commit under review: `1ea7ee6` (working tree carries uncommitted F3 work; no F4 file is modified in it).
Stack: `docker compose` (api, worker, web, postgres+pgvector, redis, minio), demo seed,
offline `echo` chat provider / `hash` embeddings provider (the shipped default, no API key present).

---

## 1. Verdict

**FAIL** — the phase's demoable outcome (one differentiated PDF for a whole class) cannot be
produced from the UI at all, the "never print an unapproved AI exercise" rule is not enforced
anywhere in the render path, and three checklist requirements (R6 edit/regenerate/discard,
R7 group sheet, R8 answer keys) are simply absent.

**1 × P0 · 8 × P1 · 9 × P2 · 7 × P3.**

> **Update.** The P0 and all eight P1s, plus the two unimplemented requirements
> (R6, R7), were fixed after this review. See
> [`F4-fixes.md`](F4-fixes.md) for what changed and what was run to confirm it.
> The P2 and P3 findings below still stand.

The parts that *are* built are built well: gap targeting, retrieve-before-generate ordering,
competency targeting, per-student page isolation in the batch PDF, the prompt itself, and the PII
gate are all correct and verified by running them. The failures are concentrated at the two ends —
the browser-to-API contract, and the approval/print boundary.

---

## 2. What I ran

**Environment.** The stack was already up; I verified it (`GET /api/v1/health` →
`{"status":"ok","database":true,"redis":true,"storage":true}`). Login `demo@alppy.ch` /
`alppy-demo-2026`. School `72fa7283…`, class `7B` (25 students) `40c54794…`,
subject `mathematics` `ae21f635…`.

**Backend suite, linters**

```
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q -rs
  → 334 passed, 0 failed, 0 skipped, 1 unrelated Starlette deprecation warning (49.6 s)
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_adaptive.py \
    apps/api/tests/test_retrieval.py apps/api/tests/test_api_adaptive.py -v
  → 57 passed (24 + 29 + 4)
.venv/bin/ruff check apps/api                                   → All checks passed!
.venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/alppy
                                                                → Success: no issues found in 67 source files
pnpm lint          → 2 tasks successful
pnpm typecheck     → 3 tasks successful
pnpm test          → runs ZERO frontend tests (no `test` task in @alppy/web or @alppy/shared)
pnpm i18n:check    → i18n check: ok — 312 keys in sync across fr, de, en.
```

**API probes** (cookie jar from `POST /auth/login`)

```
POST /api/v1/adaptive/propose  class=7B items_per_student=8   → 200 in 5.5 s, 25 plans, 0 generated
POST /api/v1/adaptive/propose  class=7B items_per_student=16  → 200 in 4.4 s, 25 plans, 9 generated
POST /api/v1/adaptive/propose  teacher locale=en, no payload language → 200, language:"en"
POST /api/v1/adaptive/propose  class=8A (2 students) items=1  → 200, 2 plans × 1 item
POST /api/v1/adaptive/propose  items_per_student=17           → 422 (cap le=16)
POST /api/v1/adaptive/propose  unknown student id             → 404 not_found
POST /api/v1/adaptive/batch    (plans containing 9 UNAPPROVED ai items) → 201 SheetOut
POST /api/v1/adaptive/batch/{sheet}/render                    → 202, job succeeded in 23 s
POST /api/v1/classes + /classes/{id}/students                 → new class 9C, 28 students
POST /api/v1/adaptive/propose + /batch + /render for 9C       → 112-page PDF
```

**Database inspection** — `docker compose exec postgres psql -U alppy -d alppy` on `exercise`,
`model_call`, `sheet`, `student`.

**Service-level fault injection** — scripts run inside the api container against the live database
(`docker compose exec api python /tmp/…`): a provider that fails on every 2nd call, a provider
returning non-JSON prose, a provider returning schema-violating JSON, and a direct table-driven
exercise of `_build_generated_exercise` with 17 malformed items.

**Browser** — Playwright (chromium, 1440×900 and 390×844) driving the real web app at
`http://localhost:3000`, with the network log captured: login → `/fr/adaptive` → slider to 16 →
"Préparer les fiches" → "Tout approuver" → "Exporter le lot PDF".

**Artefacts saved to `docs/reviews/screenshots/F4/`**

| File | What |
|---|---|
| `01-adaptive-empty.png` | Empty state |
| `02-adaptive-proposed.png` | After a 25-student proposal with 9 AI items |
| `03-adaptive-approved.png` | After clicking "Tout approuver" |
| `04-adaptive-after-export.png` | 25 s after clicking "Exporter le lot PDF" — nothing happened |
| `theme-{light,dark,system}.png`, `contrast-high.png`, `dark-contrast.png`, `motion-off.png`, `calm-on.png` | Display states |
| `locale-{fr,de,en}.png`, `phone-fr.png` | Locales, phone viewport |
| `adaptive-batch-unapproved.pdf` | 171-page batch, 25 students, containing 9 **unapproved** AI items |
| `pdf-ai-item-unapproved.png` | Page 128 of that PDF — the unapproved AI item on paper |
| `adaptive-batch-28.pdf` | 112-page batch, 28 students |
| `page-001.png`, `page-002.png`, `page-003.png`, `student2-first-008.png` | Batch page structure |

---

## 3. Requirement trace

| # | Requirement | How verified | Result | Evidence |
|---|---|---|---|---|
| R1 | Retrieval first, generation only for the shortfall | Ran two proposals (8 and 16 items/student) against the live API and read the structured log | **OK** | With `items=8` retrieval filled every sheet and **no model call was made** (`model_call` table empty, `generated_count: 0`). With `items=16` the log shows `adaptive.generate requested=1 produced=1`, `requested=3 produced=2` per student — never `requested=16`. `adaptive_service.py:300-341` orders retrieve → shortfall → generate. **Caveat:** the retrieval *count* is not in the log; `retrieval.propose` (`retrieval.py:170`) is emitted only by the *phase* F1 sheet-builder path, never by the adaptive path, so the log alone does not show "retrieval ran and its results were counted" — I had to read it off the API response. |
| R2 | ≥80 % of retrieved items tagged with the targeted competency | Computed the intersection of each proposal's `competency_ids` with the plan's `targeted_competency_ids` over the whole class | **OK** | **200/200 = 100.0 %** on-target across 25 students × 8 items. Per-student 8/8 for every student. |
| R3 | Generated items match competency, type (mcq/tf), difficulty, and the **source** language not the UI locale | Set the teacher locale to `en` and proposed against the French/German class 7B with no `language` in the payload | **FAIL** | Response `language: "en"`; 12 exercises persisted with `language='en'` whose statements are French (`Calcule 8 × 2.`). `adaptive.py:64` computes `language = payload.language or teacher.locale or default_locale` — the source material is never consulted. Type: mcq/tf is *requested* by the prompt but the validator also accepts `open` (see F7). Competency: on the shipped offline provider the content is single-digit multiplication regardless of the competency requested (see F13). |
| R4 | `origin=ai_generated`, accent-marked in the UI, **absent from the PDF until approved** | Generated 9 items, did **not** approve them, created the batch, rendered it, and read the PDF text | **FAIL** | All 9 carry `origin=ai_generated`, `approved_at=NULL` (OK) and the UI shows an `AiBadge` count (OK). But `POST /adaptive/batch` accepted them (201) and the render produced them on paper: `pdftotext` line 4184 `14. IA Calcule 4 × 9.` — see `pdf-ai-item-unapproved.png`. `approved_at` was still NULL afterwards (`select count(*) … approved_at is null` → 21). |
| R5 | `--c-accent-*` used for AI-generated items and nowhere else | `grep -rn "accent" packages/ui/src apps/web/src`, every hit classified | **OK with one documented conflict** | `AiBadge.tsx:26` is the only chip using it; `StatusVariant` (`lib/types.ts:10`) and `CardTint` (`lib/types.ts:4`) both *exclude* `accent`, so `Badge`/`Chip`/`Card` cannot reach it. The approve CTA (`adaptive/page.tsx:126`) is accent but is the AI-approval action. **Conflict:** all seven illustrations in `packages/ui/src/illustrations/set.tsx:25,37,50,62,74,87,98` paint `--c-accent-500` as their focal dot, and `IlloSummit` renders on the F4 empty state (`adaptive/page.tsx:109`). DESIGN.md §7 mandates this; CLAUDE.md forbids it. Also dead-but-reachable CSS: `recipes.css:133` defines `.ard-card[data-tint='accent']` that nothing emits. |
| R6 | Teacher can edit / regenerate / discard a generated item; regenerate replaces; discards are not re-proposed | Read the adaptive screen in the browser; grepped the API surface | **FAIL — not implemented** | The adaptive screen never renders a single exercise statement (see `02-adaptive-proposed.png`): it shows one `Panel` per student with a UID, an item count and an "IA · N" badge. There is no edit, regenerate or discard control, and no endpoint for any of them (`grep -rni "regenerate\|discard" apps/api/alppy/services/adaptive_service.py apps/api/alppy/api/v1/adaptive.py` → no matches). The teacher is asked to approve 9 exercises it never shows them. |
| R7 | Group sheet targeting a union of gaps, UI explaining which student each item is for | Grepped for the feature; drove the UI | **FAIL — not implemented** | `SheetTarget.GROUP` exists in `models/enums.py:39` and has **zero** usages anywhere in `apps/api/alppy` or `apps/web/src`. No endpoint, no UI, no per-item student attribution. |
| R8 | 28 students → one PDF, one `.print-page` per physical page, own header + UID, no bleed, answer keys alongside in the same order | Built class 9C with 28 students (accented names, apostrophes), proposed, batched, rendered, analysed the PDF page by page; and separately analysed the 25-student variable-length batch | **PARTIAL** | **Structure OK:** 112 pages, 28 distinct UIDs, **every page carries exactly one UID**, every page has its own `Code élève` header and a `Page n/112` counter, zero pages with no UID or with two. Variable-length bleed test on the 25-student batch: 6/7/8 pages per student (7B_13 → 8 pages, 7B_14 → 6) with no page shared. No student *name* is printed. **Answer keys: FAIL.** `render_adaptive_batch` (`sheets/render.py:386-405`) renders only `SheetKind.BLANK`; `answer_key_pdf_key` is NULL on both batches I rendered. |
| R9 | Quality gate: answer key present and internally consistent; near-duplicate check | Drove `_build_generated_exercise` with 17 adversarial items inside the container; queried the answer-position distribution over all generated rows | **PARTIAL / FAIL** | **Correctly rejected:** answer_index out of range, MCQ with no options, MCQ with no answer_index, TF with a non-bool `answer_bool`, TF with no `answer_bool`, unknown type, statement < 8 chars. **Wrongly accepted:** `type:"open"` (not auto-gradable); a missing `type` silently defaults to `mcq`; unknown extra fields ignored; two identical options with the key on one of them; empty-string options; **17 options** while `layout.MAX_OPTIONS = 4`. **Near-duplicate check: none exists** — `_generate` (`adaptive_service.py:396-480`) contains no comparison against the corpus. |
| R10 | Every generation call logged with prompt hash, tokens, latency, cost; UIDs and no names; cost of a 28-student batch | Queried `model_call`; grepped an hour of api+worker logs for all 25 roster names; inspected the table schema | **OK, with one gap** | 26 rows, all `purpose='adaptive_generate'`, `prompt_name='generate_exercises'`, `prompt_version='v1'`, `prompt_sha256` non-null on 100 %, token counts and latency present, `cost_estimate_chf` present. **No name leaked:** 0 hits for every roster surname and for `Léa/Noah/Mathis/Amélie` across 1 316 log lines; `model_call` has no name column and stores no prompt content; the UID lives in `Exercise.generation_meta.student_ref` (`{"student_ref": "7B_19", …}`). **Gap:** `model_call` carries no student reference at all, so a call cannot be attributed to a UID from the audit table alone. **Cost:** measured **CHF 0.00** (echo provider is priced at 0). Projected from the real measured prompt size (190 input tokens/call — the prompt is real, only the completion is synthetic): 28 calls ≈ CHF 0.019 on Haiku 4.5, 0.057 on Sonnet 5, 0.285 on Opus 5. Output tokens are understated by the stub, so treat these as lower bounds. |
| R11 | Provider error / malformed JSON: batch completes for others, failures reported, nothing half-written | Injected three broken providers (fails every 2nd call, returns prose, returns schema-violating JSON) into a 6-student proposal against the live database | **PARTIAL** | **Good:** all three returned a complete 6-plan response, other students were unaffected, and **nothing was half-written** — `ai_exercises +0`, `model_calls +0` across all three runs. **Bad:** the failures are **invisible**. `generated_count=0`, `needs_approval=False`, and `AdaptiveProposeResponse` has no field in which a failure could be reported (`['plans','language','generated_count','needs_approval']`). The affected student silently receives a shorter sheet. |

---

## 3b. Cross-cutting checks — what passed

Recorded here because the negatives matter as much as the findings.

| Check | Result |
|---|---|
| Colour literals outside `tokens.css` / `print.css` | **Clean.** The full grep over `apps/ packages/ --include=*.tsx,*.ts,*.css` returns two hits, both *comments* in Playwright specs (`e2e/themes.spec.ts:41`, `e2e/mastery.spec.ts:135`). Every rendered value is a token. |
| Accent reachable from generic components | **Blocked by design.** `StatusVariant` (`lib/types.ts:10`) excludes `accent`, so `Badge variant="accent"` and `Chip variant="accent"` do not compile; `CardTint` (`:4`) excludes it too. Only `AiBadge` and the approve CTA use it in TSX. (Dead CSS at `recipes.css:133` — F23.) |
| Caveat / `--font-hand` at most once per page | **Zero uses anywhere.** `.hand` (`base.css:69`) and the `font-hand` utility are never applied; the font is loaded and unused. No violation. |
| Card vs Panel on the F4 screen | **Correct** in the default themes: `Card` for the settings block and the AI notice (separate objects), `Panel` for the status strip and the 25 student rows (subdivisions). Breaks only in high contrast — F9. |
| "Never colour alone" on paper | **Holds.** The AI mark prints as an outlined pill reading **IA**, at `--text-body-l` (`geometry.css.j2:156-165`), and the footer band legend carries colour **and** a word **and** a distinct underline (solid / dashed / dotted / double / wavy) — see `pdf-ai-item-unapproved.png`. |
| Student-facing type floor | **Holds** for statements and options: `_item.html.j2:10,12` mark them `data-student-facing`, `print.css:123-126` and `geometry.css.j2:171-176` set `--text-body-l` (1.125 rem). Two exceptions, one documented as a known gap (`print.css:151-165`, bubble letters at 10 pt, tied to layout v1 geometry) and one not (`print.css:97`, `.print-uid-text` at 12 pt = 1.0 rem). |
| i18n | **Clean.** `pnpm i18n:check` → *"312 keys in sync across fr, de, en"*. The `adaptive` block has 24 leaf keys in all three, no missing key, no value duplicated across locales. Every user-visible string on the screen changes between fr/de/en (`locale-fr/de/en.png`); the only string identical in all three is the brand mark *Alppy*. Plurals go through ICU (`t('needsApproval', {count})`). |
| Responsive | **No horizontal scroll** in any state, including 390 px (`scrollWidth 390 === clientWidth 390`, and a sweep found zero elements overflowing the right edge). |
| Motion / calm | **Correct.** `data-calm="on"` hides the one `[data-decorative]` element on the empty state (`checkVisibility()` true → false, rule at `base.css:120`); the proposal view has none, so the screenshot is byte-identical to light. Nothing on this view animates at rest. |
| `data-theme="system"` | Resolves correctly in both OS preferences (verified by re-running with `colorScheme: 'dark'`). |
| **Privacy** | **PASS, and the gate demonstrably fires.** Zero hits for all 25 roster surnames and for `Léa / Noah / Mathis / Amélie` across 1 316 lines of api+worker log. `model_call` has no name column and stores no prompt content, only a SHA-256. `Exercise.generation_meta` carries `"student_ref": "7B_19"` — the UID. The printed sheets carry the UID and never a name (checked against `O'Brien`, `Müller`, `Zoé`, `Ysée`, `Đoković` in a 28-student batch: 0 hits). And `assert_no_pii` really raised in production during this review (F5) rather than passing silently. |
| Adversarial inputs | Class with 2 students × 1 item → 200, correct. `items_per_student: 17` → 422. Unknown student id → 404. Class with no students → 422 (`adaptive.py:59`). 28 students with accents, apostrophes and non-Latin diacritics (`O'Brien`, `Đoković`, `Þórsdóttir`, `Nguyễn`) → roster created, UIDs `9C_01`…`9C_28` with leading zeros, all 112 pages decoded a single UID. |

---

## 4. Findings

Ordered by severity. `F<n>` labels below are *findings*, not phases; where a phase is meant it
is written out ("phase F2").

### F1 · P0 — "Exporter le lot PDF" never produces a PDF; the button polls a 404 forever

**Repro**
1. `http://localhost:3000/fr/adaptive`, log in as the demo teacher.
2. Drag the slider to 16, click **Préparer les fiches**, wait for the 25 plans.
3. Click **Tout approuver**, then **Exporter le lot PDF**.
4. Watch the network panel for 25 s.

**Expected** — a job starts, the button shows its busy state, `batchReady` appears, a PDF is
downloadable.

**Observed** — one `201 POST /api/v1/adaptive/batch`, then `GET /api/v1/jobs/<id>` returning
**404, 27 times in 25 seconds** and continuing. The button never enters its busy state (because
`job.data?.status` is `undefined`), no success panel appears, no error appears, and no PDF is ever
requested. Screenshot `04-adaptive-after-export.png`. The sheet row it created has
`blank_pdf_key = NULL` and `answer_key_pdf_key = NULL`:

```
select id, title, blank_pdf_key is not null, answer_key_pdf_key is not null from sheet …
 565e1e31-af93-418b-af69-459cce3dba1d | Fiches adaptées | f | f
```

**Cause** — `POST /adaptive/batch` returns a **`SheetOut`** with `status_code=201`
(`apps/api/alppy/api/v1/adaptive.py:78-95`), and rendering is a *separate* call,
`POST /adaptive/batch/{sheet_id}/render` (`adaptive.py:98-123`). The web client declares the batch
call as returning a `JobOut` (`apps/web/src/lib/api/endpoints.ts:210-211`,
`apps/web/src/lib/api/queries.ts:357-359`), so `adaptive/page.tsx:157` feeds the **sheet id** into
`useJob`, and the render endpoint is never called by anything. `tsc` cannot catch it because
`apiRequest<JobOut>` is an unchecked assertion, and the types are **hand-mirrored**
(`apps/web/src/lib/api/types.ts:1-11`: "hand-mirrored from `apps/api/alppy/schemas/__init__.py`")
rather than generated from the OpenAPI document as `docs/plan.md` §4 requires.

**Direction** — call the render endpoint after the batch is created and poll the job it returns;
generate the client types from the served OpenAPI schema so a return-type drift fails the build.

*(The pipeline itself works: driving the two endpoints by hand produced a valid 171-page PDF in
23 s, and a 112-page one for 28 students. Only the browser path is broken.)*

---

### F2 · P1 — Unapproved AI-generated exercises are printed; the approval gate is dead code

**Repro**
1. `POST /adaptive/propose` with `items_per_student: 16` → 9 generated items, all
   `approved_at: null`.
2. Post that response verbatim to `POST /adaptive/batch` (no approval step).
3. `POST /adaptive/batch/{sheet}/render`, download `blank_pdf_url`, `pdftotext`.

**Expected** — CLAUDE.md: *"AI-generated exercises are never printed without teacher approval
(`Exercise.approved_at`)."* The batch should be refused, or the items excluded.

**Observed** — 201, then a successful render, then on paper:

```
4184:14. IA Calcule 4 × 9.
4209:15. IA Calcule 2 × 2.
4215:16. IA Calcule 9 × 9.
… 9 items in total
```

`select count(*) from exercise where origin='AI_GENERATED' and approved_at is null` → 21, i.e. the
render changed nothing. See `pdf-ai-item-unapproved.png` (page 128, student 7B_19).

**Cause** — `adaptive_service.py:22` says *"call it in the render path"*, and nothing does.
`grep -rn "ensure_printable\|is_printable\|approve_exercises" apps/api/alppy/` returns **only the
three definitions** (`adaptive_service.py:162, 182, 188`) plus that docstring. `sheet_service.create_adaptive_sheet`
(`sheet_service.py:179-241`) loads exercises via `_load_exercises` at `:203` with no approval
filter; `sheets/render.py` never imports `adaptive_service`. The gate is tested
(`test_adaptive.py:238-260`) but never wired.

**Direction** — call `ensure_printable` in `create_adaptive_sheet` **and** in
`render_adaptive_batch`, so neither an API client nor a re-render can bypass it.

---

### F3 · P1 — "Tout approuver" approves nothing: approval is browser state only

**Repro** — click **Tout approuver** on `/fr/adaptive` and watch the network panel; then query the
database.

**Expected** — a request that sets `Exercise.approved_at`.

**Observed** — zero network requests. `apps/web/src/app/[locale]/adaptive/page.tsx:126`:

```tsx
<Button variant="accent" onClick={() => setApproved(true)}>{t('approveAll')}</Button>
```

The React state flips, the export button un-disables, and `approved_at` stays `NULL` in the
database for every generated exercise. `PATCH /exercises/{id}` (`api/v1/sources.py:177-199`) can set
it and `apps/web/src/lib/api/endpoints.ts:120` wraps it — but the adaptive page never calls it, and
`adaptive_service.approve_exercises` has no caller at all.

**Direction** — make the approve action a real mutation over the generated exercise ids, and make
the export path depend on the server's answer rather than on local state. Fixing F2 without fixing
this locks the teacher out entirely, so the two must land together.

---

### F4 · P1 — Generated exercises follow the UI locale, not the source material

**Repro**

```
PATCH /api/v1/teachers/me/preferences  {"locale":"en"}
POST  /api/v1/adaptive/propose  {class 7B, subject maths, items_per_student:16}   # no language field
```

**Expected** — CLAUDE.md: *"Exercise content follows the language of the source material, never the
UI locale."* Class 7B's corpus is French and German; generated items should be French.

**Observed** — response `language: "en"`; retrieved items came back `fr`/`de` as stored, and the
generated ones were persisted as:

```
Calcule 8 × 5.  | language=en
Calcule 10 × 5. | language=en
Calcule 2 × 4.  | language=en
… 12 rows with language='en' and French statements
```

`select language, count(*) from exercise where origin='AI_GENERATED' group by 1` → `en 12, fr 27`.

**Cause** — `apps/api/alppy/api/v1/adaptive.py:64`:
`language = payload.language or str(teacher.locale) or get_settings().default_locale`. Nothing
derives the language from the class's corpus or from the sheet. The value is then stamped onto
`Exercise.language` (`adaptive_service.py:546`) without ever being read back from the model, which
is why `test_adaptive.py:427` passes tautologically.

**Why it matters beyond a wrong label** — `Exercise.language` drives the printed true/false glyphs
(`pagination.py` → `layout.tf_letters(self.language)`, V/F · R/F · T/F). A mislabelled item prints
the wrong glyphs next to its bubbles while the detector reads by position.

**Direction** — derive the sheet language from the class/subject corpus (or the sheet being
targeted), pass it as the generation language, and validate that the returned statement is actually
in it before storing.

---

### F5 · P1 — Generation failures are silent, and the PII gate false-positives on textbook content

**Repro (reproduced twice, once through the HTTP API and once at the service level)**

```
POST /api/v1/adaptive/propose {class 7B, items_per_student:16}
→ per-student totals: Counter({16: 22, 15: 3})     # three students silently one item short
```

api log at the same moment:

```
[warning] adaptive.generate.failed  error=PiiLeakError  student_uid=7B_04
```

**Expected** — either the item is generated, or the teacher is told it could not be.

**Observed** — the exception is swallowed (`adaptive_service.py:440-446` returns `[]`), the plan
comes back one item short, `generated_count` and `needs_approval` say nothing, and
`AdaptiveProposeResponse` has no field that could report it
(`['plans','language','generated_count','needs_approval']`). I confirmed the same silence for a
provider failing every 2nd call, a provider returning prose instead of JSON, and a provider
returning schema-violating JSON — all three returned a clean 6-plan response with
`generated_count=0` and **no** database side effects (`ai_exercises +0, model_calls +0`).

**The false positive is the interesting half.** The seeded textbook exercise *"Une pizzeria de Sion
partage une pizza en parts égales. **Léa** en mange 1/3, **Noah** en mange 1/4…"* is selected as a
`style_example` (`adaptive_service.py:337`). Class 7B contains **Léa Progin (7B_01)** and **Noah
Bettschen (7B_02)**. `assert_no_pii` (`ai/scrub.py:84-89`) matches the roster against the rendered
prompt and raises. Nothing leaked — the property holds — but generation is abandoned for any class
where a pupil shares a first name with a name in the corpus, which in Suisse romande is the common
case. `docs/decisions-log.md` D10 claims the roster match *"has no false positives on content"*;
it does, on first names.

A second consequence: `assert_no_pii` runs at `ai/client.py:135-136`, **before** the try/except that
builds a failed `CallRecord`, so a gate rejection leaves no row in `model_call` either. It is
invisible in the audit trail as well as in the UI.

**Direction** — scrub the style examples through `scrub()` (which redacts) before they enter the
prompt, keep `assert_no_pii` as the final assertion; and add a `failures: [{student_uid, reason}]`
field to `AdaptiveProposeResponse` that the screen renders.

---

### F6 · P1 — No answer key is exported with the batch

**Repro** — render either batch, then read the sheet.

**Expected** — R8, and DESIGN.md §9: *"Always two sheets: the blank version and the answer key."*

**Observed** — `answer_key_pdf_url: null` on both the 25-student and the 28-student batch; the job
result carries a single key: `{"batch_pdf_key": "sheets/…/adaptive-batch.pdf"}`.
`sheets/render.py:386-405` renders `SheetKind.BLANK` only and sets only `sheet.blank_pdf_key`,
whereas the ordinary path `render_sheet_pdfs` (`render.py:361`) produces both.

**Direction** — render the answer-key pass in `render_adaptive_batch` with the same instance order
and store it in `answer_key_pdf_key`.

---

### F7 · P1 — The generated-item quality gate lets through items that cannot be printed or graded

**Repro** — `_build_generated_exercise` driven with 17 adversarial items inside the api container
(`docker compose exec api python /tmp/r9.py`).

**Correctly rejected** (6 of 6 answer-key consistency cases): `answer_index` out of range, MCQ with
no options, MCQ with no `answer_index`, TF with `answer_bool: "oui"`, TF with no `answer_bool`,
unknown type, statement shorter than 8 characters.

**Wrongly accepted**

| Item | Accepted as | Consequence |
|---|---|---|
| `{"type":"open", …}` | `type=open` | Zero bubbles on the answer grid, `NOT_GRADEABLE` forever — an AI item that can never feed the mastery loop, on a sheet whose whole purpose is to feed it. The prompt asks for `mcq \| true_false`; the validator's `else` branch (`adaptive_service.py:535-536`) accepts any other valid `ExerciseType`. |
| `{"statement": …, "options": …}` with **no `type`** | `type=mcq` | `str(item.get("type") or "mcq")` (`:514`) — a missing required field is silently defaulted rather than rejected. |
| `{… ,"surprise":"boom"}` | accepted | Unknown fields are ignored; the schema is not parsed strictly. |
| `options: ["49","49"], answer_index: 1` | accepted | Two identical options, one marked correct. A student picking the other identical option is scored **wrong**. This is exactly the internal consistency R9 asks for. |
| `options: ["",""]` | accepted | Two blank options printed next to two bubbles. |
| 17 options, `answer_index: 16` | accepted | **`layout.MAX_OPTIONS = 4`.** Verified through the real print path: `Item(options=ABCDEF, answer_index=5).option_count → 4`, `option_letters → "ABCD"`, and pagination places the item with all six options *printed* but only four bubbles. The correct answer has no bubble to fill, so every student is graded wrong on that item. |

**No near-duplicate check exists.** `_generate` performs no comparison against the corpus. Measured
effect on the shipped provider: 39 generated rows, **20 distinct statements** — a 49 % exact-duplicate
rate across the corpus (no duplicates landed on a single student's sheet, because `select_diverse`
de-duplicates within a sheet). `retrieval.py:497 test_near_duplicate_statements_are_penalised` is a
*retrieval ranking* test and does not cover generation.

**Direction** — parse the model response with a strict Pydantic model (`extra="forbid"`, required
`type` restricted to `mcq|true_false`, `2 <= len(options) <= layout.MAX_OPTIONS`, distinct
non-empty options); state the option cap in the prompt; add a cheap similarity check against the
statements already on the sheet and against the corpus before persisting.

---

### F8 · P1 — The accent approve button is unreadable in dark and in both high-contrast modes

Measured in the browser on `/fr/adaptive` after a proposal, `getComputedStyle` on the
"Tout approuver" button:

| State | face | label ink | contrast |
|---|---|---|---|
| light | `#ff8a3d` | `#1b1735` | **7.34** ✅ |
| dark | `#ff9e5e` | `#f4f2ff` | **1.84** ❌ |
| high contrast (light) | `#a03c00` | `#000000` | **3.14** ❌ |
| dark + high contrast | `#ffbb85` | `#ffffff` | **1.65** ❌ |

Confirmed against the tokens rather than only the pixels: `recipes.css:76-80` pins
`--face-ink: var(--c-ink-900)` for the accent variant, and `--c-ink-900` flips to `#f4f2ff`
(`tokens.css:220, 300`) and `#ffffff` (`:452, 515`) in dark, while `--c-accent-500` *also* becomes
lighter in dark — `#ff9e5e` (`:265, 345`), `#ffbb85` (`:488, 548`). Face and ink move the same
direction, so both end up light. The light-contrast case fails the other way: near-black ink on a
`#a03c00` face.

This is the single sanctioned accent action in the product — the one control that gates F4's
approval step — and it is legible in exactly one of the four display states. Screenshots
`theme-dark.png`, `contrast-high.png`, `dark-contrast.png`.

**Direction** — give the accent variant its own `--face-ink` per theme rather than inheriting
`--c-ink-900`, and add the four display states to a contrast assertion in the e2e suite.

---

### F9 · P1 — In high contrast every `.ard-card` loses its edge entirely and becomes invisible

**Repro** — on any screen, set `data-contrast="high"` on `:root` and read the computed style of
`.ard-card`. Measured by me directly:

```
{}                                  boxShadow: "rgb(231,227,247) 0 2px 0 0, rgba(27,23,53,.18) 0 10px 30px -12px"
                                    cardBg rgb(255,255,255)  bodyBg rgb(247,245,255)
{"data-contrast":"high"}            boxShadow: "none"  borderWidth: "0px"
                                    cardBg rgb(255,255,255)  bodyBg rgb(255,255,255)   ← identical
{"data-theme":"dark"}               boxShadow: "rgb(52,46,92) 0 2px 0 0, rgba(0,0,0,.55) 0 10px 30px -12px"
{"data-theme":"dark","data-contrast":"high"}
                                    boxShadow: "none"  borderWidth: "0px"
                                    cardBg rgb(0,0,0)  bodyBg rgb(0,0,0)               ← identical
```

**Cause** — `recipes.css:125` writes `box-shadow: 0 2px 0 0 var(--tint-edge), var(--shadow-ambient)`
and `tokens.css:440` sets `--shadow-ambient: none` under `[data-contrast='high']`. The result,
`box-shadow: 0 2px 0 0 #000, none`, is **invalid CSS** — `none` is only legal as the sole value — so
the browser drops the whole declaration and falls back to `none`. `--tint-edge` is correctly
`#000` / `#fff`; it just never gets painted. `.ard-panel` keeps its `2px` border, so in high contrast
the Card/Panel hierarchy inverts: the subdivision has an edge and the object does not.

The AI-approval block on the F4 screen is a `Card tint="warm"`, whose tint also collapses
(`--c-canvas-warm: #ffffff` at `tokens.css:391`), so the one region that flags AI content floats with
no surface at all — visible in `contrast-high.png` and `dark-contrast.png`.

App-wide, not F4-specific, but high contrast is the switch a low-vision teacher reaches for and it
silently removes every card boundary in the product.

**Direction** — set `--shadow-ambient: 0 0 0 0 transparent` instead of `none`, or split the solid
edge out of the shadow shorthand.

---

### F10 · P2 — A French class gets German exercises on its sheet, with nothing on paper to say so

**Repro** — `POST /adaptive/propose {class 7B, subject maths, items_per_student:16, language:"fr"}`,
then count the languages of the retrieved items per student.

**Observed**

```
7B_01 {'fr': 9, 'de': 7}
7B_02 {'fr': 11, 'de': 5}
7B_03 {'fr': 6, 'de': 10}
```

On paper (`adaptive-batch-unapproved.pdf`, page 128, `pdf-ai-item-unapproved.png`), item 13 reads
*"Zwei Zahlen unterscheiden sich um 9. Ihre Summe beträgt 47. Wie lautet die grössere Zahl?"*
directly under the French instruction *"Remplis une seule bulle par ligne…"* and above a French
item 14.

This is a **deliberate** design (`retrieval.py:36`, `select_diverse` at `:350-354`: in-language
candidates are exhausted first, then others, and `build_proposal` adds a
`language_mismatch` line to the provenance). But the provenance panel is never rendered on the
adaptive screen (F12), and the printed sheet carries no marker at all, so the first person to notice
is a 13-year-old in Suisse romande. When the in-language corpus cannot fill a sheet, a shorter sheet
is the safer default than a bilingual one.

**Direction** — make the language fallback opt-in per sheet, and mark a cross-language item on the
sheet itself if it is kept.

---

### F11 · P2 — Every generated multiple-choice answer is option A

```
select origin, answer_index, count(*) from exercise where type='MCQ' group by 1,2;
 TEXTBOOK     | 0 | 11      AI_GENERATED | 0 | 39
 TEXTBOOK     | 1 |  9
 TEXTBOOK     | 2 | 11
 TEXTBOOK     | 3 | 10
```

**39 of 39** generated MCQs key `answer_index = 0`, against a well-spread textbook distribution.
On the printed grid that is a column of A bubbles. A pupil who spots it scores 100 % without doing
any arithmetic, and the mastery model then reads that as genuine mastery.

This is an artefact of the shipped `EchoChatProvider` (`providers.py:71`, `"answer_index": 0`
hard-coded), but nothing downstream shuffles option order or checks the distribution, so a real
provider with a position bias would produce the same failure. Neither the prompt nor the validator
mentions varying the position.

**Direction** — shuffle options (and re-point `answer_index`) when persisting a generated item;
assert a non-degenerate key distribution in a test.

---

### F12 · P2 — The adaptive screen has no error state and shows no exercise

`apps/web/src/app/[locale]/adaptive/page.tsx` imports `LoadingState` (:106) and `EmptyState` (:108)
but **no `ErrorState`**; `grep -n "isError\|\.error" ` on the file returns nothing. It is the only
page under `apps/web/src/app` that never imports `ErrorState` (eight others do). Failures of
`propose`, `batch`, `classes`, `subjects` and `job` are all silent — which is precisely why F1
presents as "the button does nothing" rather than as an error. This breaks CLAUDE.md's *"Every
screen ships empty, loading (with a `shape`) and error states."*

The same screen also never renders a statement, an option, a difficulty or a provenance for any
proposed item — retrieved or generated (see `02-adaptive-proposed.png`). The teacher gets counts
and UUID fragments.

---

### F13 · P2 — On the shipped offline provider, generated content ignores the competency it is tagged with

Fifteen generated exercises read as a teacher would:

```
Calcule 5 × 7. | ["35","40","28","36"] | key 0 | difficulty 2 | MA.1.C.1, MA.3.A.3
Calcule 2 × 2. | ["4","6","2","5"]     | key 0 | difficulty 2 | MA.1.C.1, MA.3.A.3
Calcule 7 × 8. | ["56","63","48","57"] | key 0 | difficulty 2 | MA.1.C.1, MA.3.A.3, MSN 31.1
… (12 more of the same shape)
```

**The arithmetic is correct in all 15** and the distractors are plausible mistakes (35+5, 35−7,
35+1), so there is **no factually wrong printable exercise** — the P1 trigger in the review brief is
not met. But every item is single-digit multiplication at difficulty 2, while the competencies it is
tagged with are `MA.1.C.1` (functional relations / linear equations) and the requested difficulty
was 3–4. The tag is what feeds the mastery model, so a pupil's "linear equations" band moves on the
strength of a times-table question.

This is the offline provider (`providers.py:61-77`), which ignores the prompt entirely — as its
docstring says. It is the right call for `docker compose up` with no key (D8). But it means **the
content quality of F4 is unverifiable on the shipped default**, and the demo the milestone promises
shows a differentiated sheet whose AI items are off-target. Worth an explicit note in the demo
script, and worth making the offline provider at least echo the requested difficulty and vary the
answer position.

---

### F14 · P2 — A failed audit write poisons the session and turns a proposal into a 500

Observed live when the Docker VM disk filled during this review:

```
[warning] ai.audit.write_failed
sqlalchemy.exc.PendingRollbackError: This Session's transaction has been rolled back due to a
  previous exception during flush … (psycopg.errors.DiskFull) …
  [SQL: INSERT INTO model_call …]
→ POST /api/v1/adaptive/propose  500 internal_error
```

`ai/audit.py:32-66` promises *"Never raises: an audit row that cannot be written must not fail the
ingestion that produced it"*, and it does swallow the exception — but it does not `rollback()`, so
the session is left unusable and the **next** statement (`adaptive_service.py:449`, outside the
try/except) raises and the request 500s. The audit write is not isolated from the work it audits.

**Direction** — write audit rows in a nested transaction (`db.begin_nested()`) and roll that back on
failure, or write them on a separate session.

---

### F15 · P2 — Nothing tests the adaptive flow above the service layer

- `pnpm test` runs **zero** frontend tests (no `test` task in `@alppy/web` or `@alppy/shared`).
- The only e2e touching `/adaptive` is `apps/web/e2e/responsive.spec.ts:22`, which loads the page in
  its empty state to assert it does not scroll sideways. Nothing clicks *Préparer* or *Exporter*.
- `apps/api/tests/test_api_adaptive.py:46` asserts `response.status_code in (200, 503)` and `:106`
  asserts `render.status_code in (202, 503)` — assertions that cannot fail on a behavioural
  regression. Its batch test builds its proposals from a hand-written `_proposal()` dict (`:16-31`)
  and then asserts on the ids it supplied itself.
- Generation is only ever exercised against `EchoChatProvider`, which always returns valid MCQ JSON,
  so every `return None` branch in `_build_generated_exercise` (`:508-536`) is unexercised, and
  `test_generated_exercises_follow_the_language_of_the_material` (`test_adaptive.py:427`) is
  tautological — it asserts `Exercise.language == "fr"` on a value the caller set.
- No test covers: a malformed model response, a provider failure inside a *multi-student* batch,
  near-duplicate detection, answer-key consistency of generated items, or the writing of
  `ModelCall` rows for `adaptive_generate`.

---

### F16 · P2 — 171 A4 pages for a class of 25

The 16-item batch produced 6–8 pages per student (171 total, ~2.3 items per page). Page 1
(`page-001.png`) carries two items and roughly a third of the sheet is blank below the answer grid.
The pagination estimate is deliberately pessimistic (`pagination.py:56-64`, `AVG_CHAR_EM = 0.5`,
"breaking early costs a sheet of paper"), which is the right instinct for one sheet and an expensive
one when multiplied by a class. A teacher standing at the photocopier with 171 sheets for 25 pupils
will notice.

---

### F17 · P2 — The `AiBadge` label itself fails AA contrast (2.84:1)

Measured on `/fr/adaptive` after a proposal, on `[data-ai-generated]`:

```
desktop  color rgb(224,106,34) on bg rgb(255,232,214)  →  2.84:1  at 13px
phone    identical
dark theme (measured separately)  rgb(201,106,40) on rgb(61,38,24)  →  3.74:1
```

AA for text under 18.66 px is 4.5:1. The badge is the one element in the product whose job is to tell
a teacher "a model wrote this" — the very signal CLAUDE.md protects by reserving the mandarin for it.
Both high-contrast variants are fine (7.61 and 9.21), so the calibration exists; it just is not
applied to the two default themes. Chip recipe at `recipes.css:246-250` (`-100` background, `-600`
text, border at 40 %).

---

### F18 · P2 — The "Autoriser la génération par IA" toggle is a 48 × 28 touch target

Measured at both 1440 px and 390 px: the only interactive control on the screen below the floor is
the `Toggle`, at **48 × 28** (`h = 28 < 44`). The other sub-44 element is the 1 × 1 visually-hidden
skip link, which is expected. CLAUDE.md: *"Touch targets ≥ 44 px"*; `Button.tsx:15` restates it as
non-negotiable. `Toggle` does not honour it, and the phone in the classroom is an explicit workflow
(plan.md §9).

---

### F19 · P3 — `ConceptTag` shows a UUID fragment instead of a curriculum code

`adaptive/page.tsx:197`: `<ConceptTag code={id.slice(0, 8)} />` renders `705bf6bd`, `2414f7ae`.
DESIGN.md §6 specifies *"`ConceptTag` places the curriculum **code** in an outline pill"* — the
codes exist (`MA.1.C.1`, `MSN 31.1`) and the API returns them elsewhere. As shipped the chips are
noise.

### F20 · P3 — The batch title is in the UI locale over source-language content

`adaptive/page.tsx:153-154` sends `title: t('title')` (the UI-locale string) alongside
`language: plan.language`. On a German UI with a French plan the printed header reads *"Angepasste
Blätter"* above French exercises.

### F21 · P3 — `model_call` rows carry no student reference

The table has no UID column, so the audit trail cannot answer "what did we spend generating for
7B_19". The UID does live in `Exercise.generation_meta.student_ref` and in the structured app log.
R10 asks the log to contain UIDs; it contains them, just not in `model_call`.

### F22 · P3 — The AI notice explains the marking by colour alone

`adaptive.aiNotice` in all three catalogues: *"…signalés en orange"* / *"orange markiert"* /
*"marked in orange"*. The badge itself carries the word IA/KI/AI, so the product is compliant with
"never colour alone"; the sentence that explains it is not.

### F23 · P3 — Accent-500 in all seven illustrations, including on this screen

`packages/ui/src/illustrations/set.tsx:25,37,50,62,74,87,98` use `--c-accent-500` as the focal
point, and `IlloSummit` renders in the F4 empty state (`adaptive/page.tsx:109`). DESIGN.md §7
mandates it ("accent-500 for the single point of attention"), CLAUDE.md forbids it ("Only `AiBadge`
and components explicitly marking generated content"). A documented conflict rather than a slip, but
it means the mandarin currently marks two different things, one of them decoration. Also:
`recipes.css:133` defines `.ard-card[data-tint='accent']`, which `CardTint` (`lib/types.ts:4`)
deliberately excludes — dead CSS that a raw `className` could still reach.

### F24 · P3 — Four `adaptive.*` i18n keys are defined and unused

`adaptive.generated`, `adaptive.aiGenerated`, `adaptive.approve`, `adaptive.empty.action` have zero
usages.

### F25 · P3 — `PATCH /teachers/me/preferences` wipes every preference not named in the body

Found in passing (outside F4). Reproduced:

```
GET   /auth/me                        → {locale:fr, theme:dark, contrast:high, motion:off, calm:on}
PATCH /teachers/me/preferences {"locale":"fr"}
                                      → {locale:fr, theme:None, contrast:None, motion:None, calm:None}
```

A partial PATCH resets theme, contrast, motion and calm. The demo teacher's seeded preferences were
restored after the test (see §6).

---

## 5. Not checked

Listed so a confident verdict does not hide a blind spot.

1. **Real model output.** No API key is present, so every generation ran against the shipped
   `EchoChatProvider`, which by construction ignores the prompt (`providers.py:31-33`). Everything I
   say about *content* quality (R3 competency match, R9 near-duplicates, the option-position bias,
   the answer-key consistency of real output) is therefore about the pipeline around the model, not
   the model. The 15 exercises I read as a teacher were stub output. **The content half of R3 and
   R9 is UNVERIFIED against a real provider.** The prompt itself I did read and render (§4 F7 and
   below) — it includes the competency labels, difficulty, count, style examples and an output
   schema; it does **not** include the competency code or description, does not state the
   `MAX_OPTIONS = 4` cap, and does not ask for a varied answer position.
2. **`docker compose up` from cold.** The stack was already running when I started. I did not tear
   it down and bring it up on a clean machine, so I cannot confirm the phase-F1 compose fixes still
   hold.
3. **The 28-student batch never exercised generation.** A brand-new class has no
   `MasterySnapshot`, so class 9C took the diagnostic path (retrieval only, `generated_count: 0`).
   R8's page-structure claims are verified at 28; the *generation* claims are verified at 25.
4. **A real phone.** "Phone" means a 390 × 844 Chromium viewport, not a device, and not a rotated
   camera photo (that is phase F2 territory anyway).
5. **Print output on paper.** I rendered the PDF and read it with `pdftotext` and `pdftoppm`; I did
   not print it, and I did not photocopy it to check the greyscale ramp of the band legend.
6. **Concurrency.** Two teachers proposing for the same class at once, and the `AiRateLimit`
   dependency's actual behaviour under load, were not exercised.
7. **The `open`-item hazard end-to-end.** I proved `_build_generated_exercise` accepts
   `type: "open"` and that `Item.option_count` is 0 for it; I did not push a generated `open` item
   all the way through a render, because the stub provider never emits one.
8. **Scaling past 40.** `AdaptiveProposeRequest.student_ids` is capped at 40 (`schemas:463`), but an
   **empty** `student_ids` means "every student in the class" with no cap at all
   (`adaptive.py:57`, `_students` at `adaptive_service.py:612-628`) — which is what the UI always
   sends. I did not build a 200-student class to find where that falls over.
9. **`docs/reviews/F3-review.md` and the uncommitted F3 working tree.** The tree carries 65
   modified and 14 untracked files of F3 work. I reviewed F4 as it stands on disk; I did not check
   whether that pending work changes any F4 behaviour.

---

## 6. Reviewer changes

**No repository source file was modified.** What I did touch:

1. **Docker disk.** The Docker VM's 59 GB disk filled mid-review and Postgres started returning
   `psycopg.errors.DiskFull`, which surfaced as a 500 from `/adaptive/propose` (this is how F14 was
   found). I ran `docker builder prune -af` and `docker image prune -af`, reclaiming 17.4 GB. No
   volume was pruned; no container was recreated.
2. **Demo database.** Verification wrote real rows to the running demo database:
   - class **9C** "F4 review — 28 students" with 28 students (`9C_01`…`9C_28`);
   - 39 `ai_generated` exercises, all with `approved_at = NULL`;
   - 26 `model_call` rows (`purpose='adaptive_generate'`, provider `echo`, cost 0);
   - 3 sheets: `7d0e0a16…` "F4 review batch (unapproved)", `565e1e31…` "Fiches adaptées" (the
     UI-created one that was never rendered), and the 28-student batch, plus their instances and
     rendered PDFs in MinIO.

   Re-running `alppy seed` (or recreating the postgres volume) restores a clean demo.
3. **Teacher preferences.** I set `locale` to `en` to test R3. The partial PATCH also wiped
   `theme`, `contrast`, `motion` and `calm` (that is F25). I **restored** the seeded values and
   verified them: `{locale: fr, theme: dark, contrast: high, motion: off, calm: on}`. Note that the
   UI screenshots `01`–`04` were taken while those preferences were blank, i.e. in the default
   display state rather than the teacher's saved dark+high-contrast one; the dedicated display-state
   screenshots force the attributes explicitly and are unaffected.
4. **Scratch files.** Probe scripts live in the session scratchpad and were copied into the api
   container at `/tmp/r9.py`, `/tmp/r9b.py`, `/tmp/r11.py`, `/tmp/prompt.py`. They vanish when the
   container is recreated.
5. **New files in the repo:** this report, and the artefacts in
   `docs/reviews/screenshots/F4/` (11 PNG screenshots, 5 PDF page renders, 2 PDFs).

---

## 7. Fix brief

> Copy the block below into a fresh session.

---

You are fixing phase **F4 (adaptive per-student sheets)** in the Alppy repository. Read `CLAUDE.md`,
`DESIGN.md`, `docs/plan.md` and `docs/decisions-log.md` first. An independent review found the
issues below; the full evidence is in `docs/reviews/F4-review.md`, with screenshots and PDFs in
`docs/reviews/screenshots/F4/`.

Bring the stack up with `docker compose up`. Log in as `demo@alppy.ch` / `alppy-demo-2026`. Class
`7B` has 25 students; `items_per_student: 16` is what forces generation on the demo corpus.
**Add a regression test for every item below** — a backend test for the API/service issues and a
Playwright e2e test for the UI ones. `pnpm test` currently runs no frontend tests at all; wire one
up.

### P0

**1 · The batch export button never renders a PDF.**
Repro: `/fr/adaptive` → slider to 16 → *Préparer les fiches* → *Tout approuver* → *Exporter le lot
PDF*. Observed: one `201 POST /adaptive/batch`, then `GET /jobs/<sheet-id>` **404 repeatedly** and
forever; no PDF, no error, no busy state. `POST /adaptive/batch/{sheet_id}/render` is never called.
Cause: `POST /adaptive/batch` returns a `SheetOut` (`api/v1/adaptive.py:78-95`) but the client types
it as `JobOut` (`apps/web/src/lib/api/endpoints.ts:210-211`, `queries.ts:357-359`) and feeds the
sheet id to `useJob` (`adaptive/page.tsx:157`). `tsc` cannot see it because the web API types are
hand-mirrored (`apps/web/src/lib/api/types.ts:1-11`) rather than generated from OpenAPI as
`docs/plan.md` §4 requires.
**Acceptance:** clicking *Exporter le lot PDF* produces a downloadable PDF from the browser, with a
visible busy state and a visible failure state. Generate the web API types from the served OpenAPI
document so this class of drift fails the build.

### P1

**2 · Unapproved AI exercises are printed.** `ensure_printable`, `is_printable` and
`approve_exercises` (`services/adaptive_service.py:162, 182, 188`) have **zero** production callers;
`create_adaptive_sheet` (`sheet_service.py:179-241`) and `render_adaptive_batch`
(`sheets/render.py:386-405`) apply no approval filter. Repro: propose with `items_per_student:16`,
post the response straight to `/adaptive/batch` without approving, render — nine unapproved items
appear on paper (`pdftotext … | grep "IA Calcule"`, and `pdf-ai-item-unapproved.png`).
**Acceptance:** `create_adaptive_sheet` **and** `render_adaptive_batch` both refuse an
`origin=ai_generated, approved_at IS NULL` exercise. Test both entry points, including a re-render
of an existing sheet.

**3 · "Tout approuver" approves nothing.** `adaptive/page.tsx:126` is
`onClick={() => setApproved(true)}` — pure React state, zero network calls, `approved_at` stays
`NULL`. **Acceptance:** the button issues a real mutation over the generated exercise ids, the
export gate reads the server's answer, and an e2e test asserts `approved_at` is set. Land this with
fix 2 — fixing 2 alone locks the teacher out.

**4 · Generated language follows the UI locale.** `api/v1/adaptive.py:64`:
`language = payload.language or str(teacher.locale) or default_locale`. Repro: `PATCH
/teachers/me/preferences {"locale":"en"}` then propose against 7B with no `language` — 12 exercises
persist with `language='en'` and French statements. `Exercise.language` drives `layout.tf_letters`,
so the printed V/F glyphs go wrong too. **Acceptance:** the generation language is derived from the
source corpus / sheet, never from the teacher's locale; a test proposes with the UI in `en` against
a French class and asserts French output. Note `test_adaptive.py:427` is currently tautological — it
asserts a value the caller set.

**5 · Generation failures are silent, and the PII gate false-positives on textbook names.**
Repro: propose 7B with `items_per_student:16` → three students silently get a 15-item sheet;
`adaptive.generate.failed error=PiiLeakError student_uid=7B_04` in the log. The seeded exercise
*"…**Léa** en mange 1/3, **Noah** en mange 1/4…"* is used as a `style_example`
(`adaptive_service.py:337`) and class 7B contains Léa Progin and Noah Bettschen, so `assert_no_pii`
(`ai/scrub.py:84-89`) raises. Nothing leaked — the failure mode is availability, not confidentiality
— but `docs/decisions-log.md` D10's claim of "no false positives on content" is wrong for first
names. Separately, `assert_no_pii` runs at `ai/client.py:135-136` *before* the try/except that
builds a failed `CallRecord`, so the rejection leaves no `model_call` row either.
**Acceptance:** run `scrub()` over style examples before they enter the prompt (keeping
`assert_no_pii` as the final assertion); add a `failures: [{student_uid, reason}]` field to
`AdaptiveProposeResponse` and render it on the screen; record a failed `ModelCall` for a gate
rejection. Tests: a roster name inside a style example still yields a full sheet; a provider that
fails for one student in a six-student batch leaves the other five complete **and reports the one**.

**6 · No answer key in the batch.** `render_adaptive_batch` renders `SheetKind.BLANK` only;
`answer_key_pdf_key` is NULL on every batch. DESIGN.md §9: *"Always two sheets."*
**Acceptance:** the batch job produces both PDFs, instances in the same order; a test asserts both
keys are set and that the key PDF has the same page count and UID sequence.

**7 · The generation quality gate is too permissive.** `_build_generated_exercise`
(`adaptive_service.py:495-564`) correctly rejects an out-of-range `answer_index`, a missing key and
a bad TF bool, but **accepts**: `type:"open"` (never auto-gradable); a *missing* `type` (defaults to
`mcq` at `:514`); unknown extra fields; two identical options with the key on one; empty-string
options; and **more than `layout.MAX_OPTIONS = 4` options** — verified through the real print path,
an item with 6 options prints all six but only four bubbles, so the key can point at a bubble that
does not exist and every student is graded wrong. There is also **no near-duplicate check** of any
kind (measured: 39 generated rows, 20 distinct statements).
**Acceptance:** parse the response with a strict Pydantic model (`extra="forbid"`, required `type`
restricted to `mcq|true_false`, `2 <= len(options) <= MAX_OPTIONS`, options distinct and non-empty);
state the option cap in `generate_exercises.v1.md`; add a similarity check against the sheet and the
corpus before persisting. Table-driven test over all of the above.

**8 · The accent approve button is unreadable in three of four display states.** Measured:
light 7.34 ✅, dark **1.84**, high contrast **3.14**, dark+high contrast **1.65**. Cause:
`recipes.css:76-80` pins `--face-ink: var(--c-ink-900)`, which goes light in dark while
`--c-accent-500` also goes light (`tokens.css:265, 345, 488, 548`).
**Acceptance:** ≥ 4.5:1 in all four states; assert it in the e2e suite.

**9 · Every `.ard-card` becomes invisible in high contrast.** `recipes.css:125` is
`box-shadow: 0 2px 0 0 var(--tint-edge), var(--shadow-ambient)` and `tokens.css:440` sets
`--shadow-ambient: none` under `[data-contrast='high']`. `box-shadow: … , none` is invalid CSS, so
the whole declaration is dropped: measured `boxShadow: "none"`, `borderWidth: "0px"`, card
background identical to the body background in both high-contrast modes. App-wide.
**Acceptance:** a card keeps a visible edge in all four states; assert card-vs-canvas contrast in
the e2e suite.

### Also missing (stated requirements with no implementation)

- **R6 — edit / regenerate / discard a generated item.** The adaptive screen never renders a single
  statement (see `02-adaptive-proposed.png`); it asks the teacher to approve nine exercises it does
  not show. No regenerate or discard endpoint exists. Needed: show each proposed item with its
  statement, options, difficulty and provenance; edit, regenerate (replacing, not appending) and
  discard, with discards excluded from the next run.
- **R7 — group sheet.** `SheetTarget.GROUP` (`models/enums.py:39`) has zero usages. Needed: target a
  group of students on the union of their gaps, with the UI saying which student each item is for.
- **Error state.** `adaptive/page.tsx` imports `LoadingState` and `EmptyState` but no `ErrorState`;
  it is the only page under `apps/web/src/app` that does not. This is why the P0 presents as "the
  button does nothing".

### Worth fixing while you are in there (P2)

- Retrieval falls back to the other language when the in-language corpus runs out, so a French class
  gets German items (measured 7 of 16 for 7B_01) with nothing on the printed sheet to say so.
- All 39 generated MCQs key option A; nothing shuffles option order or checks the distribution.
- `ai/audit.py:32-66` swallows a failed audit write but does not `rollback()`, so the poisoned
  session turns the next statement into a 500 (observed live under a full disk).
- The offline `echo` provider ignores the requested language (`providers.py:50` tests for
  `"language: de"` while the prompt emits `"Language: de"`), the requested count, and the requested
  difficulty — so the whole offline demo path generates times-table questions tagged as linear
  equations.
