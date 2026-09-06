# F1 — Exercise selection and sheet generation · independent review

> **Status: fixed.** Every P0 and P1 below has been addressed and re-verified
> against `docker compose up`; see [`F1-fixes.md`](F1-fixes.md) for what changed
> and what was run. This document is kept as the record of what was found, not
> as the current state of the code.

Reviewer: independent agent (three parallel lanes: API/print, UI-in-browser, static/design).
Date: 2026-09-06. Commit reviewed: `2a5b531`, tree clean at start.
Scope: F1 checklist R1–R13 plus the Block 0 cross-cutting checks.

---

## 1. Verdict

**FAIL** — the printed artefact is genuinely excellent and the sheet geometry is the
strongest work in the repository, but a teacher cannot complete the F1 loop at any point:
the upload request is malformed and rejected 422 with no feedback, no background job is ever
enqueued so nothing is ever ingested or rendered, and in the shipped default configuration the
extraction path fabricates exercises and files them under the teacher's own textbook with a real
page number.

**3 P0 · 12 P1 · 14 P2 · 5 P3.**

The three P0s are independent: fixing any one of them still leaves the loop broken.

---

## 2. What I ran

macOS 24.6.0 (arm64) · Docker 24.0.6 · Node 23.7.0 · pnpm 9.15.4 · Python 3.11.11 ·
Playwright 1.62 + Chromium 151.

### Stack
```bash
docker compose up -d --build                            # FAILED, exit 17 (P1-5)
docker compose up -d postgres redis minio minio-init    # infra only, healthy
POSTGRES_PORT=55432 docker compose up -d postgres       # host 5432 owned by a native postgres
alembic -c alembic.ini upgrade head                     # 0001 applied
python -m alppy.cli seed                                # 1.0 s
python -m uvicorn alppy.main:app --port 8000            # /health: db, redis, storage all true
python -m alppy.worker.main                             # arq worker up, connected
cd apps/web && npx next dev -p 3100                     # web app, real API
```
Seed: 18 students · 7 chapters · 34 competencies · 63 chunks · 63 exercises · 559 attempts.
Re-seed: `created=0 updated=63 attempts_created=0` — **idempotent**.

### Driven in a real browser
Logged in through the form as `demo@alppy.ch`; 12 Playwright scripts across `/`, `/sources`,
`/sheets/new`, `/sheets/[id]` at 390×844 and 1440×900, in fr/de/en, under
`data-theme` light/dark, `data-contrast` high, `data-motion` off, `data-calm` on.
**57 screenshots** in `docs/reviews/screenshots/F1/` (prefixes `01`–`93`).

### API probes
```bash
POST /auth/login                                   -> 200
POST /sheets/propose  x3 identical bodies          -> byte-identical
POST /sheets/propose  intents: "fractions" | "fraction irréductible simplifier"
                               | "géométrie triangle angles" | null
POST /sources  two-column.pdf, no-exercises.pdf, image-only.pdf, big-300.pdf
POST /sources  two-column.pdf again                -> same source id (sha256 dedup)
POST /sources  without subject_id                  -> 422 (what the web client sends)
POST /sheets · PATCH /sheets/{id} · POST /sheets/{id}/render · GET /sheets/{id}/preview
```

### PDF rendering — executed for the first time (the handover records this path as never run)
```bash
scratchpad/render_probe.py   # mixed / many40 / long40 -> HTML + PDF
scratchpad/r6.py             # real DB sheet, 18 copies -> real-blank.pdf, real-key.pdf
scratchpad/r10.py            # class of 1, class of 28, UID edge cases
pdftoppm -r 150              # page-1 rasterisation + ink measurement at layout.py coordinates
```

### Adversarial corpus I built (no textbook PDF exists in the repo)
`scratchpad/pdfs/{two-column,no-exercises,image-only,big-300}.pdf` (reportlab).

### Checks
```bash
pytest apps/api/tests -q          # 277 passed, 0 skipped, 14.06 s
node scripts/check-i18n.mjs       # 239 keys in sync across fr, de, en
pnpm --filter @alppy/ui build     # pass
pnpm typecheck                    # pass (3/3)
pnpm lint:css                     # pass
pnpm lint                         # 0 tasks executed          (P1-10)
ruff check apps/api               # All checks passed
mypy apps/api/alppy               # 20 errors                 (P1-10)
python scripts/export-layout.py   # layout.generated.ts not stale
```

---

## 3. Requirement trace

| # | Requirement | How verified | Result | Evidence |
|---|---|---|---|---|
| R1 | Upload a PDF via the UI; background job with visible progress; survives an API restart | Dropped a valid PDF on `/sources` in the browser; watched network, `job` table and `arq:queue`; started the worker | **FAIL** | Client omits `subject_id` → 422, no UI feedback (P0-3). Even by API, the job is written to Postgres but never pushed to Redis; `LLEN arq:queue`=0 while 5 jobs sit `QUEUED` (P0-1). `/sources` never polls for progress (P2-6). |
| R2 | Structured `Exercise` rows: statement, type, answer key, difficulty, chapter/competency tags, source page; check ≥10 against the source; nothing invented or merged | Ran `run_ingest` directly with a storage loader; compared DB rows against the actual PDF text | **FAIL** | DB says `Calcule 8 × 3.`; the PDF says `Calcule l'aire d'un triangle…`. A prose-only PDF yields 5 exercises. 0/107 rows carry a chapter or a competency (P0-2, P1-7). |
| R3 | Adversarial ingestion: image-only, two-column, 300-page, no-exercises, re-upload | Built and ingested all five | **PARTIAL** | image-only → truthful, teacher-readable failure ✅. Re-upload → same source id, no duplicates ✅. 300-page → 10.3 s, no crash, but silently caps extraction at 200 of 1200 chunks (P2-1). Two-column → columns interleaved (P2-2). No-exercises → 5 invented items (P0-2). |
| R4 | Pick class, subject, chapter(s), free-text intent; ranked list relevant; provenance per item; deterministic | 3× identical requests diffed; 4 intents compared; builder driven in the browser | **PARTIAL** | Determinism ✅ byte-identical. Provenance panel renders source + page + excerpt ✅. **No class or subject picker exists** (P1-11). Relevance ❌: intent `"fractions"` gives similarity 0.000 on every item (P1-8). |
| R5 | Keep / remove / reorder / edit text; reorder persists; source not mutated; provenance intact | API: create → PATCH reversed → re-GET → DB check. UI: inspected the item controls | **PARTIAL** | **API layer is correct**: order persisted, `statement_override` survived, source `statement` byte-identical, `source_id` intact, accents/apostrophes fine ✅. **The UI has no edit-text affordance at all** (P1-12), and reordering before creation is lost on reload. |
| R6 | Two PDFs, blank + answer key; browser and server render identical | Rendered both; diffed HTML; rasterised page 1; called `/preview` | **FAIL** | Two documents ✅ differing only in title, `CORRIGÉ` badge and `data-key` marks ✅. But `/sheets/{id}/preview` 500s (P1-1), and the in-app preview is a different document — no answer grid, no UID grid (P1-2). PDFs are undownloadable in the app (P0-1). |
| R7 | Header + class + UID, numbered items, bubbles on the fixed grid, fiducials as real borders, `.print-page` = one page, `.print-item` unsplit, A4, 14 mm | Rasterised at 150 dpi with `print_background=False`; measured ink at the `layout.py` coordinates | **OK** | Fiducials 95.8–97.9 % ink at exactly (18,18)/(192,18)/(18,279)/(192,279) mm. UID grid band 36 % ink. Key bubbles present on the key, absent on the blank. 36 pages → 36 headers. The border-instead-of-background trick in `geometry.css.j2:50-63` genuinely works. |
| R8 | No student-facing text below `body-l` (1.125 rem), by computed style | Chromium `getComputedStyle` under `emulate_media('print')` | **FAIL** | `.print-bubble-letter` 13.33 px, `.sheet-grid-number` 13.33 px, `.sheet-ai-mark` 14 px, `.sheet-grid-open` 14 px, against an 18 px floor (P1-9). |
| R9 | Colour also carries an underline style and appears in the legend; greyscale legible | `print.css:162-167`; rendered legend; greyscale raster | **OK** | Five bands, five distinct underline styles (solid/dashed/dotted/double/wavy) plus text labels; legend shows both channels. |
| R10 | 28 students → 28 instances with distinct UIDs; class of 1; one MCQ + one TF + one open; 40 items paginate with a header per page | Rendered each case | **OK** | 1→1 page. 28→28 pages, 28 distinct UIDs, 28 headers. Mixed sheet correct. 40 items → 20 pages, header on every page. |
| R11 | A 40-line statement moves to the next page **whole**, with header + UID | Rendered `long40-blank.pdf`, inspected page 2 | **FAIL** | Own page with header + UID ✅, but the text is cut mid-sentence at "Ligne 32" and the grid caption overlaps it (P1-6). |
| R12 | `layout_version` stored on the sheet and embedded in the PDF | DB read + rendered footer + markup attribute | **OK** | `sheet.layout_version='v1'`; footer prints `mise en page v1`; `data-layout-version="v1"`; storage key embeds `/v1/`. |
| R13 | Research doc separates verified fact from assumption; no overclaiming | Read `docs/research/textbook-access-ch.md` | **OK** | "Verified — with source URL and date accessed" vs "Needs human confirmation"; secondary sources flagged; §5 caveats on method; defers explicitly to a Swiss lawyer. |

---

## 4. Findings

### P0

#### P0-1 · Background jobs are never enqueued — nothing is ever ingested or rendered
```bash
curl -b c -X POST localhost:8000/api/v1/sources -F file=@x.pdf -F subject_id=<id>   # 202 "queued"
python -m alppy.worker.main                                    # worker up, connected
docker compose exec redis redis-cli LLEN arq:queue             # -> 0
psql -c "select kind,status,count(*) from job group by 1,2"    # INGEST_SOURCE|QUEUED|4
                                                               # RENDER_SHEET |QUEUED|1
```
Expected: the handler enqueues an arq job, the worker runs it, `Source.status` → `SUCCEEDED`.
Observed: a `Job` row is committed to Postgres and **nothing is pushed to Redis**.
`grep -rn 'enqueue' apps/api/alppy` returns only docstrings. There is no cron and no DB poller
in `worker/main.py`. Jobs stay `QUEUED` forever.

`api/v1/sources.py:113-125` — writes the `Job`, calls `load_optional(...)`, commits. Its own
docstring (`sources.py:3`) says the handler does "validate, store, **enqueue**". Identical
omission at `sheets.py:130` (render), `adaptive.py:113` (batch), `scan_service.py:105` (scan),
so F2, F4 and F5 carry the same defect.

In the browser: "Générer les PDF" polls `/jobs/{id}` every 900 ms forever, no timeout, no error
(`sheets/[sheetId]/page.tsx:44`, `queries.ts:294-303`); `blank_pdf_url` stays `null` across a
reload. **Downloading the two PDFs is unachievable in the product.**

*Fix:* create an arq pool at API startup; enqueue by function name after commit.

#### P0-2 · The default configuration fabricates exercises and files them as textbook content
```
no-exercises.pdf contains only prose. After ingestion:
  source_page | type | origin   | statement
  1           | MCQ  | TEXTBOOK | Calcule 4 × 3.     (5 rows, from a PDF with zero exercises)

two-column.pdf page 1 really reads: "1. Calcule l'aire d'un triangle de base 3 cm…"
DB rows for that page:              "Calcule 8 × 3.", "Calcule 4 × 8.", …  (21 rows)
```
`EchoChatProvider.complete` (`ai/providers.py:25-35`) **ignores `chunk_text` entirely** — it
hashes the prompt and returns 2–4 invented `Calcule a × b.` MCQs. `pipeline._build_exercise`
stores them with `origin=TEXTBOOK` and the real `source_id` / `source_page`.

Why this is P0 and not a harmless stub:
- `ALPPY_AI_CHAT_PROVIDER=echo` is the **docker-compose default** (`docker-compose.yml:96`) —
  what a reviewer, a demo, and any keyless deployment get.
- `origin=TEXTBOOK` exempts the rows from the approval gate, which checks only `ai_generated`
  (`retrieval.py:202-206`) — so they are immediately proposable and printable.
- Not being `ai_generated`, they never get the mandarin accent, so the teacher receives **no
  signal** that a model wrote them.
- They carry the teacher's filename and a page number, so the provenance panel actively asserts
  they came from that page — the "provenance is a lie" failure `ingest/extract.py:8-12` exists
  to prevent.

*Fix:* the offline provider must not serve `purpose="extract_exercises"`; extraction should
yield zero exercises and record why on the `Source` when no real model is configured.

#### P0-3 · Uploading a textbook through the UI is impossible, and fails silently
`apps/web/src/lib/api/endpoints.ts:100-104` builds the multipart body with `file` only.
`api/v1/sources.py:76` requires `subject_id: Annotated[uuid.UUID, Form()]`. Reproduced:
```
POST /api/v1/sources -F file=@no-exercises.pdf
→ HTTP 422 {"loc":["body","subject_id"],"msg":"Field required"}
```
The `/sources` page has no subject picker at all. In the browser, at 0.3 / 1 / 3 / 6 s after
dropping a valid 3-page PDF: `role=alert` empty, `role=status` empty, list length unchanged.
`useUploadSource` has no `onError` (`queries.ts:181-187`) and the page renders only
`upload.isPending` (`sources/page.tsx:70-74`). Screenshot
`63-sources-upload-silent-failure-light-fr-1440.png`.

*Fix:* add a subject picker and send `subject_id`; give the mutation an error path.

### P1

**P1-1 · `GET /sheets/{id}/preview` always 500s.** `api/v1/sheets.py:148` calls
`render_html(db, sheet_id=sheet.id)`; the resolved function is
`html.render_sheet_html(sheet_data: SheetData, *, kind=...)`, re-exported into
`sheets.render`'s namespace so `load_optional` finds it and the bad call site is never caught at
import. Reproduced: `TypeError: render_sheet_html() got an unexpected keyword argument
'sheet_id'`. The endpoint is specified in `docs/plan.md` §4 and is dead; no test covers it.

**P1-2 · The in-app print preview is a different document from the printed sheet.**
`sheets/[sheetId]/page.tsx:132-191` hand-rolls the sheet in React. Against the server truth it
lacks: the **fixed answer grid** (it puts bubbles inline beside each option — precisely the
arrangement `layout.py:66-72` and handover assumption #1 deliberately reject); **any true/false
answering affordance at all**; the **UID grid**; ruled lines for open items; the instructions
line; pagination and footer; and `geometry.css.j2`, so no `layout.py` coordinate applies. It
also hardcodes `{'ABCD'[oi]}` (`page.tsx:178`) where the server prints `V/F`, `R/F`, `T/F` via
`layout.tf_letters(locale)` — confirmed in the rendered PDF markup. Compare
`90-server-truth-printed-sheet-page1.png` with `20-preview-light-fr-1440.png`. The teacher
cannot check the paper before printing, and the preview omits both machine-readable elements the
scan pipeline depends on.

**P1-3 · Every button loses its variant ink; the primary CTA is 2.82:1.**
`packages/ui/src/index.css:4` imports `base.css` **unlayered** while line 8-10 imports
`recipes.css` inside `@layer components`. Unlayered normal declarations beat every layered one
regardless of specificity, so `base.css:102-105` `button { color: inherit }` overrides
`.ard-btn { color: var(--face-ink) }`. Measured from the rendered screenshot pixels:
face `rgb(91,63,240)`, glyph `rgb(27,23,53)` → **2.82:1** (AA needs 4.5; it would be 6.15:1 with
the intended white). High contrast makes it *worse*: 2.00:1 light, 1.89:1 dark. Affects every
`.ard-btn` variant product-wide. The e2e screenshot baselines were recorded with this bug, so CI
is green on it.

**P1-4 · A created sheet becomes permanently unreachable.** There is no `/sheets` index route —
only `sheets/new/page.tsx` and `sheets/[sheetId]/page.tsx`. Nav points at `/sheets/new`
(`AppShell.tsx:33`); home renders the last sheet title as plain text, not a link
(`page.tsx:99`). Enumerating every `a[href]` on `/fr` and `/fr/classes/{id}` after creating a
sheet returns no link to it. The only route in is the `router.push` immediately after creation.

**P1-5 · `docker compose up` fails, for two independent reasons.** (a) `apps/web/Dockerfile:16`
copies `packages/shared/package.json`, which was never committed
(`git log --all -- packages/shared/package.json` is empty) → *"failed to compute cache key…
not found"*. (b) With a manifest supplied, the build fails on `Module not found: Can't resolve
'@alppy/ui'`: the package resolves via `./dist/index.js`, `.dockerignore:9-10` excludes `dist`
and `**/dist`, and the web image never runs `pnpm --filter @alppy/ui build`. Both deterministic.

**P1-6 · An over-long statement is silently truncated mid-sentence.** `long40-blank.pdf` page 2
stops at "Ligne 32 de cet énoncé délibérément"; lines 33–40 are gone, the "Grille de réponses"
caption overlaps the clipped text, and the ruled answer lines are clipped away entirely.
`pagination.py:247-253` computes `Page.overflowing` (True here: 345 mm vs a 134 mm region) but
nothing surfaces it — no API field, no UI warning, no log. `geometry.css.j2:127-134`
(`.sheet-items { overflow: hidden }`) performs the clip.

**P1-7 · Ingested exercises get no chapter and no competency.**
```sql
-- 107 exercises from uploaded sources: with_chapter = 0, with_competency = 0
```
`ingest/pipeline.py:318-366` never sets `chapter_id` and never appends to
`exercise.competencies`; `_copy_from_twin` *does* copy `chapter_id`, so the omission looks
accidental. Consequence: `competency_fit` is 0.20 of the ranking weight and the builder filters
by chapter, so **every exercise a teacher ingests is invisible to the builder's main path**.

**P1-8 · The free-text intent is inert, and typing one makes every score worse.**
```
intent="fractions"                        -> similarity 0.000 on every item, flat 0.550,
                                             top result is a symmetry exercise
intent="fraction irréductible simplifier" -> "Simplifie la fraction 18/24" ranks 1st (0.265)
intent=null                               -> scores 0.775 ×5, 0.625 ×4
```
Root cause proven directly: `cos(embed("fractions"), embed("… la fraction 18/24 …")) = 0.0000`
versus `0.3333` for the singular — `HashEmbeddingsProvider` hashes whole tokens with no
stemming, and is the docker-compose default. Compounding it, `NEUTRAL_SIMILARITY = 0.5` when no
intent is given (`retrieval.py:80-82`), so `0.45 × 0.5 = 0.225` is awarded to everything; with a
real (≈0) cosine, **typing an intent subtracts 0.225 from every candidate** while separating
almost nothing. Two semantically opposite intents returned the same nine items in near-identical
order. The provenance panel still prints *"proche de votre intention « fractions »
(similarité 0.00)"*. Disclosed in the handover and ADR 0001 — but R4's named spot-check fails in
the shipped configuration.

**P1-9 · Four student-facing sizes on the printed sheet are below the `body-l` floor.**
`.print-bubble-letter` 13.33 px (`print.css:149-152`, `10pt`), `.sheet-grid-number` 13.33 px
(`geometry.css.j2:233-243`, `10pt`), `.sheet-ai-mark` 14 px, `.sheet-grid-open` 14 px — against
an 18 px floor. The bubble letter is the glyph a student reads to choose an answer; the grid
number is what they match against the statement (`_answer_grid.html.j2:5-7` says so). Two are
raw `pt` literals bypassing the type scale. `[data-student-facing]` sets the floor by
inheritance (`base.css:133-137`), so any class-level `font-size` silently defeats it — and the
answer grid is not inside that container at all.

**P1-10 · mypy strict and ESLint are not actually enforced.**
```
mypy apps/api/alppy                                   -> 20 errors   (the command in CLAUDE.md:41)
mypy --config-file apps/api/pyproject.toml apps/api/alppy -> clean
```
`[tool.mypy] strict = true` lives in `apps/api/pyproject.toml`; mypy reads only the cwd and
there is no root config. `.github/workflows/ci.yml:57` runs the broken form, so CI runs mypy
with **default** settings. Separately `pnpm lint` executes **0 tasks** — no package defines a
`lint` script and there is no ESLint config or dependency anywhere, so CI's `turbo run lint` is
a silent no-op and "no `any`" is enforced by `tsc` alone.

**P1-11 · The builder has no class or subject picker.**
`sheets/new/page.tsx:50-51`: `const [classId] = useState('')` and
`const [subjectId] = useState('')` — declared without setters. The page always uses
`classes.data[0]` / `subjects.data[0]` (lines 62-63), and `useChapters(subjectId || undefined)`
therefore issues an unfiltered `GET /chapters`. `count: 12`, `target: 'class'` are hardcoded and
`difficulty` is never sent. R4 requires picking class and subject.

**P1-12 · There is no way to edit an item's statement in the UI.** Zero `contenteditable`
elements and zero textareas in the proposal list; `useUpdateExercise` (`queries.ts:214-222`) has
no consumers; the translated strings `sheets.editStatement` and `sheets.why` exist in all three
catalogues and are rendered nowhere. `SheetItem.statement_override` works correctly server-side
(I verified it end to end via the API) but nothing in the product can set it. R5's edit clause
is unimplemented; its "does editing mutate the source?" sub-question is therefore
**UNVERIFIABLE through the UI** — though the API answer is correct.

### P2

**P2-1** A 300-page upload silently indexes only the first 200 of 1200 chunks for exercises
(`pipeline.py:52-56`, `MAX_EXTRACTION_CHUNKS`); `Source` reports `SUCCEEDED` with no message.
R3 requires a truthful status.

**P2-2** Two-column extraction interleaves the columns:
`"1. Calcule l'aire d'un triangle de base 3 cm 7. Calcule l'aire d'un triangle de base 9 cm"` —
exercises 1 and 7 merged onto one line, which also defeats `chunk.is_exercise_start` for the
right-hand column. Known risk (handover §4), now measured.

**P2-3** The sheet's language is taken from whichever item happens to be first:
`sheets/new/page.tsx:95` `language: kept[0]?.exercise.language ?? locale`. Proposals for the
francophone 7B class contain 5 fr + 4 de items and **all are auto-kept** (`page.tsx:74`), so
promoting a German item flips the whole sheet to `v1 · DE` and prints German instructions above
French exercises. `retrieval.py:35-39` states the opposite principle: *"Printing a German
exercise on a French sheet is a defect, not a trade-off."* The fallback in
`select_diverse` (`retrieval.py:292-297`) exhausts the in-language pool then crosses over, with
no badge or warning.

**P2-4** The displayed proposal score contradicts the displayed order: for
`intent="géométrie triangle angles"` the returned sequence is
`0.689, 0.610, 0.591, 0.584, 0.645, 0.550…`. `select_diverse` (`retrieval.py:154`) orders
greedily with a diversity penalty; `build_proposal` (`retrieval.py:164`) is called with the
default `taken=()`, so the number shown is the *unpenalised* base score.

**P2-5** `/sheets/new` ships no error state. A 500 from propose falls through to the **empty
state** — the teacher clicks "Propose exercises" and is told they have no sheets
(`page.tsx:164-171`); a 500 from create produces nothing at all (`page.tsx:176-184`). CLAUDE.md
requires every screen to ship empty, loading and error states; this one has two of three.

**P2-6** `/sources` never polls for ingestion progress: `useSources` has no `refetchInterval`
(`queries.ts:169-171`) and the page never uses `useJob`, so "Indexation en cours…" persists
past 30 s without a manual reload.

**P2-7** Extracted exercises cannot be viewed — only a count. There is no `/sources/[id]` route
and `useSourceExercises` (`queries.ts:173-179`) has zero consumers, although
`GET /sources/{id}/exercises` works. R1's "see extracted exercises" is unmet.

**P2-8** The `ModelCall` audit table is never written. `client.py:8-9` says the client "writes
an audit row for every call"; `grep -rn 'ModelCall' apps/api/alppy` finds **no writer** —
records accumulate in the in-memory `AiClient.records` and are discarded. After a full ingestion
run, `select count(*) from model_call` = 0. (The schema is clean of content columns, which is
right.) The audit trail `docs/privacy.md` relies on does not exist.

**P2-9** The PII gate's name check is inert unless the caller passes the roster.
`assert_no_pii(text, names=None)` checks only e-mail/AHV patterns; the ingestion path calls
`ai.complete(...)` (`pipeline.py:271-277`) with no `student_names`. Demonstrated:
`assert_no_pii("Léa Progin scored 4/10", names=None)` does **not** raise; with the roster it
does. **No actual leak was demonstrated for F1** — extraction prompts carry textbook text, a
page number and a language, and I confirmed no student name reaches the provider in normal
operation. This is a defence-in-depth gap, not a live P0, but CLAUDE.md's claim that `scrub.py`
"is the gate" overstates the guarantee.

**P2-10** In dark theme the preview shows dark "paper" and the fiducials cover content.
`.print-page` uses `background: var(--c-surface)` and `[data-fiducial]` uses
`color: var(--c-ink-900)` (`print.css:28,46`), both of which invert under `data-theme="dark"`.
The A4 preview renders as dark navy paper with **white** fiducial squares; the top-left one
covers the first letters of the title ("▪vue F1 ordre") and another covers the end of the
student UID ("7B_▪") — the code that attributes a paper to a child.
`20-preview-dark-fr-1440.png`. The printed PDF is unaffected (`@media print` pins the tokens).

**P2-11** Dark-theme contrast failures beyond the CTA: `a.ard-nav` "Accueil" 3.23:1, "Fiches"
2.78:1, `.ard-chip` "FRACTIONS" 2.78:1, skip link 3.58:1 — all from `base.css:90`
`a { color: var(--c-primary-700) }`, a token that darkens for light backgrounds and is therefore
too dark on dark ones.

**P2-12** `/sheets/new` scrolls the body sideways at 390 px: `scrollWidth` 408 vs `clientWidth`
390. The chip "GÉOMÉTRIE PLANE ET THÉORÈME DE PYTHAGORE" measures 368 px from x=22 inside a
flex-wrap `<ul>` with no `min-width:0` (`sheets/new/page.tsx:124-149`). `docs/plan.md` §9: "The
page body never scrolls sideways." `92-builder-390-horizontal-overflow.png`.

**P2-13** `ProvenancePanel` renders a permanently-green bar and a naked "0".
`ProvenancePanel.tsx:70-72` passes `threshold={0}`, so `low = ratio < 0` is never true and the
`lowLabel` warning path is dead; `ConfidenceBar.tsx:64-73` prints `{percent}` with **no `%`
sign** and the label only in `aria-label`. So a 0 %-similarity match displays as a green bar
reading "0". Separately, `provenance.reason` — the one genuinely useful field, carrying chapter,
competency codes, difficulty and page — is used only as a *fallback* when `source_filename` and
`excerpt` are null (`sheets/new/page.tsx:229-231`), so it is effectively never shown, while the
`excerpt` that is shown is verbatim the statement already displayed above it.

**P2-14** `packages/shared` is orphaned and the documented contract does not exist. CLAUDE.md
and `docs/plan.md` §4 state the frontend consumes it, "generated from the served OpenAPI schema
— never from assumptions". In fact `grep -rn '@alppy/shared\|SHEET_LAYOUT\|layout.generated'
apps packages` returns **no hits**; the package holds one generated layout file nothing imports,
and `apps/web/src/lib/api/types.ts` states in its own header that it is *hand-mirrored* from
`alppy/schemas/__init__.py`. CI's `layout-contract` job faithfully guards a file with zero
consumers while the hand-transcribed millimetres in `print.css`/`tokens.css` that actually
position the browser preview are guarded by nothing.

### P3

**P3-1** UID encoding rejects a 3-digit student index — `encode_uid("7B_100")` →
`InvalidUidError`; a class of 100+ cannot be printed. `7B_01` (leading zero) is handled
correctly.

**P3-2** The login form can submit natively before hydration, producing
`GET /fr/login?email=…&password=…` — a plaintext password in the URL, history and access logs on
a slow connection. The handler does `preventDefault` (`login/page.tsx:19`), so this is a
pre-hydration window, not a logic error.

**P3-3** Caveat (`--font-hand`) is imported for every visitor (`layout.tsx:4`, ~300 kB) and used
on zero pages; `.hand` (`base.css:67-70`) has no consumers. The once-per-page rule is satisfied
vacuously, and the chalk gesture central to the "Craie Alpine" identity is absent from the
product. The rule has no automated guard.

**P3-4** Hardcoded user-visible strings on F1 screens: `sheets/[sheetId]/page.tsx:103` (` — `
and `%`, bypassing the `common.percent` catalogue entry, so French renders `40%` not `40 %`);
`·` separators at `sources/page.tsx:101,102` and `sheets/[sheetId]/page.tsx:55`; `'________'` at
`sheets/[sheetId]/page.tsx:155`. Also `page.tsx:99-103` concatenates title and date with no
separator ("Review sheet F106.09.2026"). The API's ingestion error is surfaced raw and
unlocalised — English text inside the French page (`sources/page.tsx:124-128`).

**P3-5** Four translated-but-dead i18n keys on the F1 surface: `sheets.editStatement`,
`sheets.why`, `sheets.pageOf`, `common.percent`.

### Notable: the tests cannot see any of this

- `grep -rn 'enqueue\|arq\|worker' apps/api/tests` returns one comment. **No test covers the
  request-handler → queue → worker seam**, which is why P0-1 shipped alongside 277 green tests.
- `apps/web/playwright.config.ts:52-53` runs the entire e2e suite with
  `NEXT_PUBLIC_ALPPY_MOCK=1`, served by `src/lib/api/mock/handlers.ts`. The fixture layer accepts
  `POST /sources` without `subject_id`, completes jobs on a tick counter, and never returns a
  mixed-language proposal set — so **none of P0-1, P0-3, P1-4, P1-11, P1-12, P2-3 or P2-5 is
  detectable by the suite as configured**.
- 8 tests assert only a status code, but all are rejection cases where the code is the
  meaningful assertion; not a finding.

### Clean

Colour literals (218 hits, all inside `tokens.css`/`print.css`); mandarin accent discipline in
components and recipes (`AiBadge` requires a text label; `.sheet-ai-mark` gated on
`item.ai_generated` and carries the word "IA"); Card vs Panel (radius `lg` + solid edge + shadow
vs radius `md` + border + no shadow — no panel anywhere carries a shadow); i18n key parity
(239 × 3, verified independently of the script, no untranslated placeholders, no hardcoded UI
chrome); `layout.generated.ts` freshness and its CI guard; ruff; `pnpm typecheck`;
`pnpm lint:css`; seed idempotency; sheet-render determinism; touch targets ≥ 44 px at both
viewports; `data-motion=off` and `data-calm=on` regress nothing; empty and loading states on
`/sources` and `/sheets/[id]`.

One documented conflict rather than a defect: all seven illustrations place `--c-accent-500` on
their focal dot (`illustrations/set.tsx:25,37,…`), two of which (`IlloSheet`, `IlloCompass`)
render on F1 empty states. DESIGN.md §7 mandates this; CLAUDE.md forbids any accent that is not
marking AI-generated content. One of the two documents needs correcting.

---

## 5. Not checked

- **Real extraction quality.** No `ALPPY_ANTHROPIC_API_KEY`, and the `anthropic` SDK is not
  installed in the venv. R2's semantic fidelity against a real model is **UNVERIFIED**; what I
  verified is that the *default* provider fabricates. P0-2 may look entirely different with a
  real model — but the default is what ships and what a reviewer runs.
- **A real textbook PDF.** None exists in the repo. The demo corpus is JSON loaded straight to
  chunks and exercises by `seed/loader.py`, bypassing `extract_pdf` and the extraction prompt
  entirely — so the demo cannot exercise the path R2 is about. My adversarial PDFs are synthetic
  and do not represent a real Lehrmittel's marginalia, boxed exercises or hyphenation.
- **`docker compose up` as a whole.** Never reached a running stack (P1-5), so the Dockerfiles,
  the entrypoint retry loop and container networking are unexercised. Everything was verified
  against infra-in-Docker with the API, worker and web app run locally.
- **Printing on real paper.** All PDF verification is 150 dpi rasterisation and ink measurement.
  No physical printer, no photocopier, no greyscale hardware — R9 is verified structurally
  (distinct underline styles present in the legend), not physically.
- **The scan round-trip.** Out of F1 scope. I did not confirm that a printed sheet registers
  against the detector, which is the only real proof the geometry is right.
- **`pnpm test:e2e`.** Not run — the UI lane held the dev server, and the baselines are
  macOS-only. I read its configuration (mock-backed) but did not execute it.
- **Load.** 200 students, concurrent uploads and a corpus of thousands of chunks were not
  tested; `_greedy` selection is O(n²) in the picked set and untested at scale.
- **`AiBadge` at runtime.** The seed contains `TEXTBOOK | 170` and no `ai_generated` rows, so no
  proposal can carry the badge; the code path is correct on inspection but **UNVERIFIED**
  in the browser.
- **Accessibility beyond contrast.** No screen-reader or keyboard-only pass.

---

## 6. Reviewer changes

Three, all outside the phase's source of truth, none intended to stand:

1. **Created `packages/shared/package.json`** (5 lines, `@alppy/shared`, private) solely to get
   past the first `docker compose` failure and reach the second. Untracked. **Delete it or
   commit a considered version** — see P1-5 and P2-14.
2. **Installed `uvicorn` into `.venv`** — declared at `apps/api/pyproject.toml:8` but missing
   locally. No repo file changed.
3. **Installed `reportlab` and `pillow` into `.venv`** to build the adversarial PDFs. No repo
   file changed.

Environment actions: pruned Docker **build cache and dangling images only** (the VM disk was
full and Postgres could not `initdb`); no named image, container or volume belonging to the user
was removed. Postgres was published on host port **55432** because a native Postgres already
owns 5432 on this machine. The UI lane ran the web app on port 3100 (3000 was occupied by an
unrelated process).

Artefacts written: `docs/reviews/F1-review.md` and `docs/reviews/screenshots/F1/` (57 PNGs,
9 PDFs, rasterisations). Nothing under `apps/` or `packages/` was modified apart from item 1.

---

## 7. Fix brief

> You are fixing phase F1 of Alppy. Work from the repo root. Every item was reproduced against a
> running stack (infra in Docker, API + worker + web run locally; Postgres on host port 55432).
> Add a regression test for each fix and state which test covers which item. **Do not change
> `layout.py` geometry — the printed page is correct and verified.**
>
> **P0-1 · Jobs are never enqueued.** `POST /api/v1/sources` writes a `Job` row
> (`api/v1/sources.py:113-125`) and commits, but nothing is pushed to arq. `grep -rn 'enqueue'
> apps/api/alppy` finds only docstrings; `redis-cli LLEN arq:queue` is 0 while `job` rows sit
> `QUEUED`. Same at `sheets.py:130`, `adaptive.py:113`, `scan_service.py:105`. Additionally
> `worker/tasks.py:129` calls the ingest pipeline with **no `loader`**, so `default_loader`
> reads the filesystem while the bytes are in MinIO (`FileNotFoundError` — reproduced). Fix
> both: enqueue by function name after commit, and inject a storage-backed loader.
> *Acceptance:* with the worker running, an uploaded PDF reaches `SUCCEEDED` and its exercises
> appear without manual intervention; "Générer les PDF" produces two downloadable files.
> *Regression test:* an integration test that posts a source, asserts a job was enqueued, runs
> the task, and asserts `Source.status == SUCCEEDED` with chunks present.
>
> **P0-2 · The default provider fabricates exercises and files them as textbook content.**
> `EchoChatProvider.complete` (`ai/providers.py:25-35`) ignores `chunk_text` and returns invented
> `Calcule a × b.` MCQs; `pipeline._build_exercise` stores them as `origin=TEXTBOOK` with the
> real `source_id`/`source_page`, which exempts them from the approval gate
> (`retrieval.py:202-206`) and from the mandarin accent. Reproduce with a prose-only PDF: it
> yields 5 exercises. `ALPPY_AI_CHAT_PROVIDER=echo` is the docker-compose default.
> *Acceptance:* ingesting any PDF with the echo provider yields 0 exercises and a `Source`
> message explaining that extraction needs a configured model.
> *Regression test:* assert a prose-only PDF yields 0 exercises under the default provider, and
> that no `origin=TEXTBOOK` row is ever created from model output.
>
> **P0-3 · Upload is impossible from the UI and fails silently.**
> `apps/web/src/lib/api/endpoints.ts:100-104` sends `file` only; `api/v1/sources.py:76` requires
> `subject_id`. Reproduced: HTTP 422 `{"loc":["body","subject_id"],"msg":"Field required"}`.
> `/sources` has no subject picker, `useUploadSource` has no `onError` (`queries.ts:181-187`),
> and the page renders only `isPending` — so the teacher sees nothing at all.
> *Acceptance:* a teacher picks a subject, drops a PDF, and sees either progress or an error.
> *Regression test:* a non-mocked test asserting the multipart body carries `subject_id`, plus a
> UI test asserting an error is rendered on a 4xx.
>
> **P1-1 · `/sheets/{id}/preview` always 500s.** `api/v1/sheets.py:148` calls
> `render_html(db, sheet_id=…)`; the function is `render_sheet_html(sheet_data: SheetData, *,
> kind=…)`. Build the `SheetData` first. *Acceptance:* the endpoint returns the same HTML the
> PDF renderer prints. *Regression test:* assert 200 and that the body contains
> `sheet-grid-row` and `print-uid-grid`.
>
> **P1-2 · The in-app preview is a different document.** `sheets/[sheetId]/page.tsx:132-191`
> hand-rolls the sheet: no fixed answer grid (bubbles are inline, the arrangement `layout.py`
> deliberately rejects), no true/false answering at all, no UID grid, no ruled lines, hardcoded
> `'ABCD'` where the server prints `V/F`. Once P1-1 is fixed, render the preview from that
> endpoint. *Acceptance:* preview and PDF are the same document. *Regression test:* assert the
> preview markup contains the answer grid and the UID grid.
>
> **P1-3 · Every button loses its variant ink (primary CTA 2.82:1).**
> `packages/ui/src/index.css:4` imports `base.css` unlayered while `recipes.css` sits in
> `@layer components`, so `base.css:102-105` `button { color: inherit }` beats
> `.ard-btn { color: var(--face-ink) }`. Measured on the rendered CTA: `rgb(27,23,53)` on
> `rgb(91,63,240)` = 2.82:1; high contrast is worse (2.00 light, 1.89 dark). Put `base.css` in a
> `base` layer (or scope the reset). Note the e2e baselines encode the bug and must be
> regenerated. *Acceptance:* every `.ard-btn` variant meets AA in all four theme/contrast
> combinations. *Regression test:* a contrast assertion on the primary CTA in each mode.
>
> **P1-4 · A created sheet is unreachable.** No `/sheets` index route exists; nav points at
> `/sheets/new` (`AppShell.tsx:33`) and home renders the sheet title as plain text
> (`page.tsx:99`). *Acceptance:* a sheet created yesterday can be reopened by clicking.
>
> **P1-5 · `docker compose up` fails twice.** (a) `apps/web/Dockerfile:16` copies
> `packages/shared/package.json`, never committed. (b) `@alppy/ui` resolves via `./dist/index.js`,
> `.dockerignore:9-10` excludes `dist`, and the image never builds it. A reviewer left an
> untracked `packages/shared/package.json` on disk — delete or replace it.
> *Acceptance:* `docker compose up` on a clean checkout serves the seeded demo.
> *Regression test:* a CI job that builds both images.
>
> **P1-6 · Over-long statements are silently truncated.** `long40-blank.pdf` page 2 cuts
> mid-sentence at "Ligne 32"; the grid caption overlaps the text and the ruled lines are gone.
> `pagination.py:247-253` computes `Page.overflowing` (345 mm vs 134 mm) and nothing surfaces it;
> `geometry.css.j2:127-134` clips. *Acceptance:* the statement either flows across pages intact
> or the render fails naming the item — never a silent cut. *Regression test:* assert no
> character of a 40-line statement is missing from the rendered HTML.
>
> **P1-7 · Ingested exercises get no chapter or competency.** 0 of 107 rows carry either
> (`ingest/pipeline.py:318-366`; `_copy_from_twin` copies `chapter_id`, so the omission looks
> accidental). They are therefore invisible to chapter-filtered proposals — the builder's main
> path. *Acceptance:* after ingesting a PDF, its exercises appear in a proposal filtered to
> their chapter. *Regression test:* assert `chapter_id` and ≥1 competency on every extracted row.
>
> **P1-8 · Intent is inert and penalises everything.** `intent="fractions"` gives similarity
> 0.000 on every item and returns a symmetry exercise first; the singular works.
> `cos(embed("fractions"), embed("… la fraction 18/24 …")) = 0.0` vs `0.333` — no stemming in
> `HashEmbeddingsProvider`, the compose default. Separately `NEUTRAL_SIMILARITY = 0.5`
> (`retrieval.py:80-82`) means typing an intent subtracts 0.225 from every score. Ship the
> ADR-0001 embedder; fix the neutral-similarity arithmetic so an intent cannot lower every
> candidate; stop printing "proche de votre intention … (similarité 0.00)" when similarity is 0.
> *Acceptance:* intent `fractions` ranks the fraction exercises above the geometry ones.
>
> **P1-9 · Sub-floor student-facing type on paper.** `.print-bubble-letter` 10pt and
> `.sheet-grid-number` 10pt (13.33 px), `.sheet-ai-mark` and `.sheet-grid-open` 14 px, against an
> 18 px floor. Move both `pt` literals onto the type scale and raise all four to `body-l`.
> *Regression test:* a computed-style assertion over the rendered sheet.
>
> **P1-10 · mypy strict and ESLint are not enforced.** `mypy apps/api/alppy` from the root
> reports 20 errors because `[tool.mypy]` lives in `apps/api/pyproject.toml`; with
> `--config-file apps/api/pyproject.toml` it is clean, and `ci.yml:57` runs the broken form.
> `pnpm lint` executes 0 tasks — no `lint` script, no ESLint anywhere.
> *Acceptance:* CI fails on a deliberately introduced `Any` and on a mypy-strict violation.
>
> **P1-11 · No class or subject picker.** `sheets/new/page.tsx:50-51` declares `classId` and
> `subjectId` with `useState('')` and no setters; the page always uses the first of each, and
> `useChapters` therefore fetches unfiltered chapters. *Acceptance:* a teacher with two classes
> can build a sheet for the second one.
>
> **P1-12 · No way to edit an item's statement.** No editable field exists;
> `useUpdateExercise` has no consumers; `sheets.editStatement` and `sheets.why` are translated
> and rendered nowhere. `SheetItem.statement_override` works server-side (verified end to end).
> *Acceptance:* a teacher edits a statement, the sheet shows the edit, and the source exercise is
> unchanged. *Regression test:* assert the source `Exercise.statement` is byte-identical after
> an override is saved.
>
> **Before re-review, also fix the test blind spots that let all of this ship:** add at least one
> e2e path that runs against the real API rather than `NEXT_PUBLIC_ALPPY_MOCK=1`
> (`apps/web/playwright.config.ts:52-53`), and one integration test for the
> handler → queue → worker seam.
>
> Then re-verify the full R1–R13 trace in §3 and re-run: `pytest apps/api/tests -q`,
> `mypy --config-file apps/api/pyproject.toml apps/api/alppy`, `node scripts/check-i18n.mjs`,
> `python scripts/export-layout.py`, `pnpm test:e2e`, and a `docker compose up` smoke test.
