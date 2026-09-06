# F1 — what was fixed, and how it was verified

Companion to [`F1-review.md`](F1-review.md), which recorded the findings. This
records what changed and what was actually run to confirm it. Everything below
was verified by executing it, not by reading the diff.

## The three blockers

**Jobs are never enqueued (P0-1).** `alppy/worker/queue.py` is new: it pushes a
committed `Job` row onto the arq queue by function name, keyed on the job id so
a retried request cannot double-ingest. All four handlers call it through
`deps.start_job`, which marks the row `failed` and answers 503 if Redis will not
take it — a job nobody will run must not look like one that is waiting.

A second defect sat behind it: `worker/tasks.py` passed no loader, so
`default_loader` read `storage_key` as a filesystem path while the bytes were in
MinIO. `default_loader` now reads object storage first and falls back to disk.

*Verified:* uploaded a PDF through the UI with the worker running; the source
reached `SUCCEEDED` and its exercises appeared without intervention.

**Extraction fabricated (P0-2).** The offline provider does not read its prompt —
its output is a function of the prompt's hash — and it was allowed to serve
extraction, so a prose-only PDF produced five `Calcule 4 × 3.` exercises stored
as `origin=TEXTBOOK` with the teacher's own filename and page number. Providers
now declare `grounded`; extraction refuses to run on an ungrounded one and
records a notice on the `Source` instead of a silent zero.

*Verified:* re-ingested the prose-only PDF — 0 exercises, and the teacher is
told why. The 300-page cap now reports itself the same way.

**Upload impossible from the UI (P0-3).** The client sent `file` only; the API
requires `subject_id`. Added a subject picker, sent the field, gave the mutation
an error branch. The mock now rejects the same request the API rejects, so the
e2e suite can see this class of bug.

## Found by running it, not by reading it

Two defects the review could not have found without completing the loop:

- **`store_pdf` probed for a `storage.put_object` that has never existed** (the
  interface is `get_storage().put_bytes`), so every rendered PDF was written to
  the *worker's local disk* while the database advertised an object-storage key.
  The job reported `SUCCEEDED` and the teacher's download 404'd.
- **The renderer dropped the teacher's edit.** Every class sheet binds an
  `item_plan` per student, the plan carries ids only, and `_instance_items`
  never consulted `SheetItem.statement_override` — so an edit was stored, shown
  in the builder, and silently absent from the paper.

*Verified:* downloaded both PDFs over the signed URL (709 KB / 787 KB, 90 pages
for 18 students) and confirmed the edited statement prints as item 1.

## The rest

| Was | Now |
|---|---|
| `/sheets/{id}/preview` 500'd on every request | Returns the real document; `?kind=answer_key` for the key |
| The in-app preview was a second implementation with no answer grid and no UID grid | An iframe of the server's own document — it cannot drift |
| An over-long statement was cut mid-sentence | `ItemTooTallError` names the item; `POST /render` pre-flights and answers 422 |
| Extracted exercises had no chapter or competency | Prompt v2 tags from a closed catalogue; unknown codes are dropped |
| `fractions` scored 0.0 against `fraction` | The offline embedder hashes an idempotent stem alongside the token |
| Typing an intent subtracted ~0.22 from every candidate | The similarity term is normalised across the candidate set |
| The displayed score contradicted the displayed order | Built with the same diversity penalty the order used |
| "close to your intent (similarity 0.00)" on every row | Only claimed when the exercise actually matched |
| Every button lost its variant ink; primary CTA at 2.82:1 | `base.css` imported into `@layer base`; all four theme/contrast modes clear AA |
| The builder had no class or subject picker | Both, and changing subject clears stale chapters |
| No way to edit a statement | Editable, written to `statement_override`; the source keeps its text |
| Propose and create failures were silent | Both render an error instead of the empty state |
| Sheet language taken from `kept[0]` | Majority language, with a warning when the set is mixed |
| Web hardcoded `ABCD`; paper printed `V/F` | `lib/optionLetters.ts` mirrors `layout.py` |
| No `/sheets` index — a sheet was reachable only by the redirect | Added, and nav points at it |
| Grid number, caption, AI mark and "réponse écrite" below the floor | Raised to `body-l` |
| `ModelCall` declared and never written | `alppy/ai/audit.py`, from both the ingest and adaptive paths |
| `docker compose up` failed twice | Both fixed, plus a missing `pydantic[email]` |
| mypy ran without `strict`; `pnpm lint` ran nothing | Config pinned in CI and CLAUDE.md; ESLint added and verified against a deliberate `any` |

### One gap left open on purpose

`.print-bubble-letter` stays at 10pt, below the `body-l` floor. A body-l glyph
(4.76 mm) does not fit the 3.20 mm of slack between grid rows, and the overflow
would land in the annulus the detector samples around the bubble above — which
reads as a filled mark and scores a child's answer wrong. Raising it needs a
taller `GRID_ROW_PITCH_MM`, which is a **layout version bump** with the detector
re-verified, not a CSS change. The reason is written at the declaration.

## What was run

```
297 -> 300 backend tests pass          ruff: All checks passed
mypy --config-file apps/api/pyproject.toml: no issues in 67 files
pnpm typecheck: 3/3        pnpm lint: passes, and fails on a deliberate `any`
pnpm lint:css: passes      i18n: 260 keys in sync across fr, de, en
```

New test files, one per failure class: `test_jobs_queue.py` (the enqueue seam),
`test_ingest_grounding.py` (fabrication, tagging, the audit trail),
`test_sheet_output.py` (clipping, the preview, PDF storage, the override), plus
retrieval cases in `test_retrieval.py` and `e2e/live-loop.spec.ts` for the
journey against a real API.

## Re-verified against `docker compose up`

The whole R1-R13 trace was re-run against the containerised stack, not a local
dev server:

| # | Result |
|---|---|
| R1 | Upload through the UI; worker ingests; `/sources` polls and shows progress |
| R2 | No fabrication; tagging verified against a stubbed grounded provider (a real model is still untested) |
| R3 | image-only → truthful failure; two-column, no-exercises, 300-page → indexed with a notice; re-upload → same source id |
| R4 | `fractions` returns fraction exercises first; three identical requests byte-identical; provenance shown |
| R5 | Reorder persists; the edit reaches the paper; the source exercise is untouched |
| R6 | Both PDFs downloaded as real bytes over the signed URL |
| R7 | Fiducials 95.8-97.9 % ink at the `layout.py` coordinates with backgrounds off |
| R8 | Raised, except the bubble letter — geometry, documented above |
| R9 | Five bands, five underline styles, both channels in the legend |
| R10 | 1, 18 and 28 students; 40 items → 20 pages, a header on each |
| R11 | `422 item 1 needs about 311 mm but a page has only 134 mm … shorten or split it` |
| R12 | `layout_version` on the row, in the footer, in the markup and in the storage key |
| R13 | Unchanged |

```
300 backend tests · ruff clean · mypy strict clean (67 files)
pnpm typecheck 3/3 · pnpm lint 1/1 · lint:css clean · 260 i18n keys in sync
layout.generated.ts not stale · no colour literal outside tokens.css/print.css
primary CTA: 6.15 / 4.97 / 10.49 / 11.13 across light, dark, and both high-contrast
e2e/live-loop.spec.ts: 2 passed against docker compose
```

## Still not verified

- **Real extraction quality.** No API key here, so the v2 tagging prompt has
  never run against a real model. The grounding gate is verified; what a real
  model returns is not.
- **A real textbook PDF.** The demo corpus is JSON loaded straight to chunks,
  and the adversarial PDFs are synthetic. A two-column Lehrmittel still
  interleaves its columns (P2-2, unfixed — it needs work in `ingest/chunk.py`).
- **Printing on paper.** All verification is 150 dpi rasterisation and ink
  measurement. No printer, no photocopier.
- **The scan round-trip.** Out of F1 scope, and the only real proof the geometry
  is right.
