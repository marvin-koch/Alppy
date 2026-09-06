# Alppy — Verification prompts per phase

How to use: start a **fresh Claude Code session** for each review (`/clear` or a new session — a reviewer that wrote the code will rationalise it). Paste **Block 0** followed by the block for the phase you want checked. Run reviews in order F7 → F1 → F2 → F3 → F4 when possible, since later phases depend on earlier ones. Each review writes its findings to `docs/reviews/<phase>-review.md` and does **not** fix anything — fixing is a separate session, fed by the report, so the reviewer stays adversarial and the fixer stays focused.

---

## Block 0 — Reviewer contract (paste before every phase block)

```
You are an independent reviewer of the Alppy repository. Another agent implemented a feature phase; your job is to determine whether it is actually correct, complete, and faithful to the product brief — not whether it looks plausible.

Read these first, in this order: `CLAUDE.md`, `DESIGN.md`, `docs/plan.md`, `docs/decisions-log.md`, then the phase-specific files named below.

## Principles

1. **Run, don't read.** A claim is verified only when you have executed it: start the stack, call the endpoint, click the screen, print the PDF, run the test. Reading code and concluding "this looks right" is not verification. If something cannot be run, say so explicitly and mark it UNVERIFIED.
2. **Evidence for every finding.** Each finding cites the file:line, the command you ran, and what you observed vs. what was expected. No finding without reproduction steps.
3. **Trace requirements to behaviour, not to code.** For each requirement in the checklist, find the user-visible behaviour that satisfies it. "There is a function called X" does not satisfy a requirement; "I did Y in the UI and observed Z" does.
4. **Be adversarial on inputs.** Empty states, a class with one student, a sheet with one item, 200 students, a rotated phone photo, a PDF with no extractable text, a name with an accent or an apostrophe, a UID with a leading zero.
5. **Do not fix.** Write the report. If a fix is under five lines and blocks further verification (e.g. a missing env var in `docker compose`), you may apply it, but log it under "Reviewer changes" and continue.
6. **Use subagents** to parallelise independent checks (e.g. one runs the backend tests and API probes, one drives the UI with Playwright, one audits design tokens and i18n). Merge their evidence; do not merge their conclusions without checking them.
7. **Think before you conclude.** Before writing the verdict, list what you did NOT check and why. A confident verdict with a blind spot is worse than a hedged one.

## Severity scale

- **P0** — the phase's core loop does not work, or data is wrong/lost, or student PII leaks (e.g. names sent to an LLM).
- **P1** — a stated requirement is missing or wrong, or a non-negotiable rule (§3, §4) is violated.
- **P2** — works but fragile, untested, or diverges from the brief in a way a teacher would notice.
- **P3** — quality, naming, docs, minor design drift.

## Cross-cutting checks (apply to every phase)

- **Design:** `grep -rnE "#[0-9a-fA-F]{3,8}\b|rgb\(" apps/ packages/ --include=*.tsx --include=*.ts --include=*.css` returns hits only in `tokens.css`. Buttons use `.ard-btn` with a solid `--edge` and Fredoka labels. Cards vs panels used per the rule. Mandarin accent (`--c-accent-*`) appears only in AI-generated-exercise UI. Caveat at most once per page. Toggle `data-theme`, `data-contrast`, `data-motion`, `data-calm` on `:root` in the browser and screenshot the main screen of this phase in each state; nothing becomes unreadable, nothing keeps a light colour on the dark canvas.
- **i18n:** switch the teacher locale to fr, de, en; every string on this phase's screens changes; `pnpm i18n:check` (or equivalent) reports no missing keys; numbers/dates format per locale.
- **Privacy:** enable the AI call log and exercise the phase; inspect the logged prompts — no student first/last names, only UIDs. Any violation is P0.
- **Tests:** run the full suite; note failures, skips, and any test that asserts nothing meaningful (e.g. `assert response.status_code == 200` with no body check).
- **Reachability:** every feature in the checklist must be reachable from the UI by clicking, not only via API.

## Output

Write `docs/reviews/<PHASE>-review.md` with exactly these sections:

1. **Verdict** — PASS / PASS WITH P2s / FAIL, in one sentence, with the count per severity.
2. **What I ran** — commands, URLs, seeds used, screenshots saved to `docs/reviews/screenshots/<PHASE>/`.
3. **Requirement trace** — a table: requirement → how verified → result (OK / FAIL / UNVERIFIED) → evidence.
4. **Findings** — ordered by severity, each with: title, severity, repro steps, expected vs observed, file:line, suggested direction of fix (one line, no code).
5. **Not checked** — what you could not or did not verify, and why.
6. **Reviewer changes** — anything you touched.
7. **Fix brief** — a self-contained, copy-pasteable prompt for a fixing session: the P0/P1 list with repro steps, the acceptance criteria to re-verify, and an instruction to add a regression test for each.

Finish by printing the Verdict section to the terminal.
```

---

## Block F7 — Navigation and overview

```
# Phase under review: F7 — Navigation and overview

Files to read first: `apps/web/src/app/**` (routes), `packages/ui/src/**`, `apps/api/alppy/api/routers/{classes,subjects,overview}*.py`, migrations touching Class/Subject/Teacher.

## Requirement checklist

R1. Teacher home shows **all** the teacher's classes and subjects, and nothing from other teachers (tenancy).
R2. Quick stats per class/subject: last sheet, pending corrections, students needing attention. Each stat is correct against the seed data — compute the expected number from the database and compare.
R3. Switching class/subject is fast and persistent: switch, reload, deep-link — the context survives and every subsequent screen is scoped to it.
R4. Every screen in the app is scoped to the current class + subject; no screen shows cross-class data unless explicitly designed to.
R5. Empty states: new teacher with zero classes; class with zero students; class with students but zero sheets. Each shows an `EmptyState` with a next action, not a blank page or a crash.
R6. Loading states use `LoadingState` with a `shape` matching the coming page, not a bare spinner.
R7. Navigation is keyboard-complete: Tab order sane, focus ring visible (`--focus-ring`), class switcher operable without a mouse.
R8. Mobile viewport (390 px): the shell is usable, the scan-upload entry point is reachable in ≤ 2 taps.

## Procedures

- Seed two teachers with overlapping class codes (both have a `7B`). Log in as each; confirm no leakage in the home screen, the switcher, and any API endpoint (probe `/api/classes`, `/api/overview` with the other teacher's IDs — expect 404/403, never 200 with data).
- For R2, write a throwaway SQL query for each stat and compare to the UI for at least three classes.
- Deep-link test: open `/classes/<id>/subjects/<id>/mastery` directly in a fresh browser; confirm the switcher reflects it.
- Run Lighthouse or equivalent on the home screen; report LCP and any a11y errors.
- Run the cross-cutting checks from Block 0 on the home screen and switcher.

Write the report to `docs/reviews/F7-review.md`.
```

---

## Block F1 — Exercise selection and sheet generation

```
# Phase under review: F1 — Exercise selection and sheet generation

Files to read first: `apps/api/alppy/ingest/**`, `apps/api/alppy/rag/**`, `apps/api/alppy/sheets/**`, `apps/api/alppy/ai/prompts/**`, `packages/ui/src/domain/WorksheetPrintSheet*`, `packages/ui/src/design/print.css`, `docs/adr/*` relevant to embeddings and PDF rendering, `docs/research/textbook-access-ch.md`.

## Requirement checklist

R1. Upload a textbook PDF per subject via the UI; ingestion runs as a background job with visible progress; the job survives an API restart (check the worker, not just the request).
R2. Extraction produces structured `Exercise` rows with: statement, type (mcq | true_false | open), answer key when present, difficulty estimate, chapter/competency tags, source page. Verify against the demo corpus: for at least 10 exercises, open the source page and confirm the fields are right, the page number is right, and no exercise was invented or merged with its neighbour.
R3. Adversarial ingestion: a scanned image-only PDF, a PDF with two-column layout, a 300-page PDF, a PDF with no exercises at all, a re-upload of the same file. Each is handled without a crash, with a truthful status message, and without duplicate exercises.
R4. Proposal flow: pick class, subject, chapter(s), optional free-text intent. The ranked list is relevant (spot-check: "fractions" intent returns fraction exercises above others), each item shows provenance (source, page) in the `ProvenancePanel`, and the ranking is deterministic for the same inputs.
R5. Editing: keep / remove / reorder / edit text. Reorder persists after reload. Editing text creates a copy or a version — the source exercise is not mutated, and provenance still points to the original.
R6. PDF generation produces **two** files: blank sheet and answer key. Print them (real print-to-PDF from the browser and the server-side render) and diff visually: identical layout.
R7. Sheet anatomy: header with class + student UID, numbered items, MCQ/TF answer bubbles on the fixed grid, corner fiducials rendered as real borders (turn off "background graphics" in Chromium print settings and confirm they still print), `.print-page` = one physical page, `.print-item` never split across pages. A4, 14 mm margins.
R8. Typography floor: no student-facing text below `body-l` (1.125rem) on the sheet. Verify computed styles, not source.
R9. Black-and-white photocopy rule: any label carrying colour also carries a distinct underline style and appears in the legend. Print to greyscale and confirm the sheet remains fully legible.
R10. Class sheet for a class of 28 produces 28 instances with distinct UIDs; a class of 1 works; a sheet with one MCQ, one TF, one open item works; a sheet with 40 items paginates correctly with a header on each page.
R11. Overflow test: an exercise whose statement is 40 lines. It must move to the next page whole, and that page must carry header + UID.
R12. `layout_version` is stored on the sheet and embedded in the PDF (visible text or metadata) so the scanner can identify it later.
R13. Research doc exists, separates verified facts from assumptions, and does not overclaim.

## Procedures

- Ingest the demo corpus from a clean DB and time it; record exercise count. Ingest again; count must not change.
- For R4, run the same proposal request 3× via the API and diff the results.
- For R6/R7, save both PDFs to `docs/reviews/screenshots/F1/` and rasterise page 1 of each at 150 dpi for side-by-side comparison.
- Inspect the RAG prompts under `ai/prompts/`: confirm they are versioned files, that the class/student context passed contains UIDs only, and that generation temperature/settings are documented.
- Run the cross-cutting checks from Block 0 on the sheet builder screen and the print preview.

Write the report to `docs/reviews/F1-review.md`.
```

---

## Block F2 — Scan and correction

```
# Phase under review: F2 — Scan and correction (MCQ + true/false)

Files to read first: `apps/api/alppy/scan/**`, `apps/api/alppy/grading/**`, the layout constants shared with `sheets/`, `packages/ui/src/domain/{ScanReviewOverlay,ConfidenceBar}*`, tests under `apps/api/tests/scan/**`, and the synthetic-degradation test fixtures.

## Requirement checklist

R1. Upload path accepts multi-page PDF, JPEG, PNG, HEIC-if-claimed; rejects oversized/unsupported files with a clear message; processing runs in the worker with per-page progress.
R2. Registration: the pipeline finds the four fiducials, deskews, and maps to the layout identified by `layout_version`. A page from a different `layout_version` is detected as such, not silently misread.
R3. UID identification from the printed UID (text and digit grid). Fallback to manual assignment when confidence is low; the manual assignment UI lists only students of the sheet's class.
R4. Mark detection for MCQ and TF, with a confidence per item. Empty answers, double-marked answers, erased-then-remarked answers, and marks slightly outside the bubble each produce a sensible result (empty / ambiguous / best-guess-with-low-confidence), never a silent wrong answer at high confidence.
R5. Grading against the answer key is correct per item and aggregated per competency; open-type items are shown as "not auto-graded" and never scored.
R6. Review UI: scanned page with detections overlaid at the right coordinates (check alignment visually on a skewed scan), `ConfidenceBar` per item, low-confidence items surfaced first, one-click override, override is stored as a teacher correction distinct from the detection (both retained). Confirm → attempts written. Re-opening a confirmed scan shows it as confirmed.
R7. Idempotency: uploading the same scan twice does not create duplicate attempts; confirming twice does not double-count.
R8. The pipeline exposes a grader interface where a free-text grader could be registered; no free-text grading is implemented.
R9. Privacy: the vision-model fallback, if present, is off by default, sends only the page image and UID — no roster — and is logged.

## Procedures

- **Synthetic round-trip (the critical test):** take the F1-generated PDF for class 7B, fill known answers programmatically (or by hand on 3 printed pages), then degrade: rotate 3°, 7°, −5°; add perspective as from a phone at 20°; add JPEG artefacts at quality 40; reduce to 150 dpi; add a shadow gradient. Feed each through the pipeline and compare to ground truth. Report per-item accuracy, UID accuracy, and the confidence distribution for correct vs. incorrect detections. If confidence does not separate correct from incorrect, that is a P1 — the review UI's prioritisation depends on it.
- Real-world sample: if `docs/samples/scans/` exists, run it; if it does not, note that the phase was verified on synthetic data only (P2).
- Mixed batch: 28 pages where 2 belong to another class and 1 is a blank page. Expect 25 assigned, 2 flagged as wrong class, 1 flagged as unreadable.
- Timing: report seconds per page on the dev machine.
- Read the tests under `tests/scan/`: do they exercise degradation, or only a clean render? A clean-only test suite is P2.
- Run the cross-cutting checks from Block 0 on the upload and review screens; specifically verify the review flow is fully keyboard-operable (next low-confidence item, override, confirm).

Write the report to `docs/reviews/F2-review.md`.
```

---

## Block F3 — Individual student tracking

```
# Phase under review: F3 — Individual student tracking

Files to read first: `docs/mastery-model.md`, `apps/api/alppy/mastery/**`, `packages/ui/src/domain/{MasteryCell,MasteryMatrix,MasteryMeter,MasteryCurve,ProgressRing}*`, `packages/ui/src/design/tokens.css` (the `--c-mastery-*` tokens), tests under `apps/api/tests/mastery/**`.

## Requirement checklist

R1. `docs/mastery-model.md` states the formula (weighted recent accuracy per competency with time decay, output in [0,1]), the decay parameters, and the five band thresholds (≥0.90, 0.75–0.90, 0.60–0.75, <0.60, none). The code implements exactly that document — diff them line by line.
R2. Hand-computable check: construct a student with 4 attempts on one competency at known dates and outcomes; compute the expected score by hand from the documented formula; compare to the API. Repeat for a boundary case exactly at 0.90 and at 0.75 (document which side each falls on).
R3. "Not yet seen" is distinct from "score 0": a student with no attempts shows the `none` band, not `fading`.
R4. Matrix (students × chapters/competencies): each cell shows dot + label + tint density — never colour alone. Switch to `data-contrast="high"` and to greyscale (emulate `forced-colors` or screenshot and desaturate): the five bands remain distinguishable.
R5. Drill-down from a cell to the underlying attempts, each attempt linking back to the sheet and scan it came from.
R6. Student profile: strengths, gaps, trend over time (ProgressRing + curve), history of sheets/assessments. The trend is consistent with the matrix for the same competency at the same date.
R7. Update path: confirm a new scan (from F2) and observe the matrix and profile update without a manual refresh action beyond reload; the `MasterySnapshot` history retains the previous value (time series, not overwrite).
R8. Scale: seed a class of 30 students × 25 competencies with 3 weeks of attempts; the matrix renders in under 2 s and remains navigable by keyboard (arrow keys between cells, Enter to drill down).
R9. Tenancy: the matrix endpoint refuses class IDs belonging to another teacher.
R10. Sorting/filtering: sort students by weakest competency, filter to a chapter; results are correct against a SQL check.

## Procedures

- Write the hand computation for R2 into the report so the next reviewer can repeat it.
- Query `MasterySnapshot` directly to confirm time-series semantics for R7.
- Run the cross-cutting checks from Block 0 on the matrix and profile screens in all four switch states; save screenshots.
- `tabular-nums` must be active on every numeral in the matrix and rings — check computed `font-variant-numeric`.

Write the report to `docs/reviews/F3-review.md`.
```

---

## Block F4 — Personalised exercise generation

```
# Phase under review: F4 — Personalised exercise generation (adaptive sheets)

Files to read first: `apps/api/alppy/adaptive/**`, `apps/api/alppy/ai/prompts/generate_exercise*`, `apps/api/alppy/ai/log*`, the batch export code under `sheets/`, `packages/ui/src/domain/*` components using `--c-accent-*`, tests under `apps/api/tests/adaptive/**`.

## Requirement checklist

R1. From a student's gaps (F3 bands weak/fading) the system assembles a targeted sheet: retrieval first, generation only to fill gaps. Verify the order by inspecting the job log: retrieval ran, its results were counted, generation was called only for the shortfall.
R2. Retrieved exercises target the right competencies: for a student weak in competency X, ≥ 80% of retrieved items are tagged X (or its children). Report the actual proportion.
R3. Generated exercises match the requested competency, type (mcq/tf only, since they must be auto-gradable), difficulty, and **language of the source sheet, not the UI locale**. Test with UI in `en` and a French class: generated items must be French.
R4. Every generated exercise carries `origin = ai_generated`, is visibly marked with the mandarin accent in the UI, and is **not** included in a PDF until the teacher approves it. Verify by generating, not approving, exporting — the item must be absent.
R5. The accent colour is used for AI-generated items and nowhere else in the app (`grep -rn "accent" packages/ui apps/web` and check each hit).
R6. Teacher can edit, regenerate, or discard a generated item; a regenerated item replaces, not appends; discarded items are not re-proposed on the next run.
R7. Group sheet: pick 5 students with overlapping gaps; the sheet targets the union sensibly and the UI explains which student each item is for.
R8. Batch: one differentiated sheet per student for a class of 28 → one PDF, one `.print-page` per physical page, each page with its own header and UID, sheets of different lengths never bleed into each other (student 12 with 3 pages followed by student 13 with 1 page). Answer keys are exported alongside, in the same order.
R9. Quality gate on generation: an answer key is present and internally consistent (the marked correct option exists; TF has exactly one truth value); statement is not a near-duplicate of an existing textbook exercise (report how this is checked, if at all).
R10. Cost and logging: each generation call is logged with prompt hash, tokens, latency, cost estimate; the log contains UIDs and no names. Report the cost of a full 28-student batch.
R11. Failure handling: the LLM provider returns an error or a malformed JSON; the batch completes for other students, the failed ones are reported, nothing is half-written.

## Procedures

- Run one full batch end-to-end from the UI and open the PDF; measure the time; save it to `docs/reviews/screenshots/F4/`.
- Read 15 generated exercises as a teacher would: are they correct, at the right level, well-formed in the target language? Record any that are wrong — a factually wrong generated exercise that a teacher could print is P1.
- Inspect the generation prompt file: does it include the source-exercise style examples, the competency description, the difficulty, and the output schema? Is the schema parsed strictly (rejecting extra/missing fields)?
- Simulate provider failure (point the provider env var at an invalid endpoint mid-batch) for R11.
- Run the cross-cutting checks from Block 0 on the adaptive builder and batch export screens.

Write the report to `docs/reviews/F4-review.md`.
```

---

## Optional Block M6 — Release readiness (run last)

```
# Phase under review: Release readiness (definition of done)

On a clean checkout in a fresh container/VM with only Docker installed, follow `README.md` literally. Do not use any knowledge from the repository beyond what the README says. Record every point where you had to guess, look elsewhere, or fix something.

Then execute the definition of done in one continuous run and time it: log in → matrix → upload textbook → build sheet + key → upload sample scans → review → confirm → matrix updates → adaptive batch → PDF. Repeat in fr, de, en; in light, dark, high-contrast.

Also verify: CI is green on `main` (`gh run list`); git history is granular Conventional Commits; `docs/handover.md` lists assumptions and next milestones; `CLAUDE.md` would let a new agent be productive in ten minutes (test this by asking a subagent to add a trivial feature using only `CLAUDE.md`).

Write `docs/reviews/RELEASE-review.md` in the Block 0 format, plus a "Time to first demo from clean machine" figure.
```
