# Handover

What is built, what is stubbed, what is not there, and the assumptions most
worth challenging. Written to be read by whoever picks this up next.

---

## 1. Where it stands

| Milestone | State |
|---|---|
| M0 — foundation, design system, i18n, nav | **Done** |
| M1 — classes, curriculum, ingestion, extraction | **Done**, ingestion unverified against a real textbook PDF |
| M2 — sheet builder, print, PDF + answer key | **Done** — PDFs render, and the printed page is now verified against the real detector |
| M3 — scan, registration, detection, review, grading | **Done**; now verified against a genuinely rendered page as well as synthetic degradation — still not against a photograph of real paper |
| M4 — mastery model, matrix, profiles | **Done** |
| M5 — adaptive per-student sheets, batch export | **Done**; the batch PDF renders |
| M6 — polish, e2e, screenshots | **Done** — Playwright passes on both viewports; screenshot baselines are macOS-only (see below) |
| M7 — ZPD stretch, N groups, per-student feedback | **Done**, and the printed feedback document is rendered and verified |
| M8 — the agenda (`event` log, `/timeline`) | **Done**, with an idempotent backfill for history that predates the log |

**Verified green, on this machine, just now:**

```
453 API tests pass        ruff: All checks passed
mypy strict: no issues found in 73 source files
@alppy/ui + @alppy/web typecheck clean, build, prerender fr/de/en
tokens.css: 125 tokens, all theme blocks consistent, @theme inline
i18n: 518 keys in sync across fr, de, en
print geometry: Python and generated TypeScript in sync
no colour literal outside tokens.css and print.css
Playwright: 115 behavioural tests pass across desktop and phone
alembic 0001..0008 apply and roll back on real Postgres (pgvector/pg16)
schema drift after a full migrate: none — migrations reproduce the models
print -> PDF -> raster -> detect: page registers, UID reads 7B_01 @ 0.965,
  every printed bubble read on the right item; the feedback document
  correctly REFUSES to register
```

---

## 2. The parts worth reading first

**`apps/api/alppy/sheets/layout.py`** — one source of truth for the printed page,
shared by the print CSS, the PDF renderer and the scan detector. Changing a
number is a layout version bump, not a tweak.

**`apps/api/alppy/scan/detector.py`** — registration and mark detection. The two
non-obvious decisions are documented in the code: bubble fill is measured
against a *local* ring of paper, and a page that reads mostly blank distrusts
its own blanks.

**`apps/api/alppy/mastery/model.py`** — two factors, both pure functions.
`docs/mastery-model.md` has the constants, the worked examples and the limits.

**`apps/api/alppy/ai/scrub.py`** — the PII gate. It raises rather than redacting.

---

## 3. Five bugs the work actually caught

Recorded because each one was invisible to the thing that should have caught it.

1. **The detector read a light pencil mark as blank with full confidence**, which
   silently scores a child zero. A global threshold cannot tell a faint mark from
   paper; a local annulus can. Found by the synthetic degradation suite.
2. **The photocopier simulation was wrong, not the detector.** Its transfer curve
   erased mid-grey pencil, which a real copier does not do. Worth separating,
   because it looked exactly like a detector failure and would have sent someone
   tuning the wrong component.
3. **A feedback page inside the copy would have misgraded the class.** Adding
   one page per student to the printed batch is what `physical_pages` is for,
   and it is a silent misgrading bug: the scan detector recomputes a copy's
   page count from its *items* and maps a photographed page with
   `seen[uid] % len(printed_pages)`, so a page the renderer adds and that count
   does not know about rotates every later page onto the wrong item list —
   confidently, with every test green. Feedback became its own document
   (decisions-log D34). Found by reading the detector before writing the
   renderer, not by a test.
4. **Skipping `SOLID` inverted the zone of proximal development.** A student
   who had mastered everything fell through gap targeting into the diagnostic
   branch and was handed difficulty 2 — easier work than they could already do
   (D32). Every test passed before and after; the tests pinned the behaviour,
   and the behaviour meant the wrong thing.
5. **The mastery model used one half-life for two different quantities.** How fast
   evidence ages and how fast knowledge fades are not the same thing, and sharing
   21 days made a perfect student read "fragile" three weeks after the lesson.
   **Every unit test passed before and after.** The demo seed found it, by
   producing a class in which nobody was ever "solid".

The pattern: the tests checked the arithmetic, and the arithmetic was right. What
was wrong was the meaning, and only running the thing end to end showed it.

---

## 4. What is stubbed, and what is missing

**Stubbed but honest**

- **AI providers.** `EchoChatProvider` and `HashEmbeddingsProvider` are
  deterministic offline stand-ins so `docker compose up` runs with no API key.
  The hash embedder is a hashing trick, **not** a semantic model: retrieval
  quality with it is a floor, not a preview. Set `ALPPY_AI_CHAT_PROVIDER=anthropic`
  and follow [ADR 0001](adr/0001-embeddings-provider.md) for the real embedder.
- **Exercise extraction from PDFs** runs, but has only been exercised against the
  self-authored corpus. A real Lehrmittel with two-column layouts, marginalia and
  boxed exercises will need work in `alppy/ingest/chunk.py`.

**Not there at all**

- **Linux screenshot baselines.** The 58-test Playwright suite exists and passes,
  but Playwright files baselines per operating system and the committed set is
  `-darwin`. CI therefore runs the behavioural specs enforcing and the screenshot
  specs reporting. [`CONTRIBUTING.md`](../CONTRIBUTING.md) has the one-line
  Docker command to generate the Linux set and the line to flip afterwards.
- ~~**The PDF path has never been executed.**~~ **Executed and verified.**
  Chromium is installed here after all; the claim was stale. All three
  documents render to real A4 PDFs (blank, answer key, feedback), and
  `tests/test_print_scan_roundtrip.py` now closes the loop the suite never
  closed: it renders a sheet through Chromium, rasterises it at 200 dpi and
  runs the **real** detector over it. The page registers, the UID grid
  round-trips to `7B_01` at 0.965 confidence, and every filled bubble is read
  on the right item. That test also asserts the feedback document does **not**
  register — a mis-fed stack must be refused, not scored as blanks.
- **`docker compose up` has never been run.** The Docker daemon was not running
  on this machine. Compose, Dockerfiles and entrypoints parse and are internally
  consistent, and the migration was diffed against the models — but the one
  command the README leads with is unproven. **Run it first.**
- **Free-text grading**, by design. The seam is `_GRADERS` in `scan/grading.py`.
- **The feedback PDF has never been executed**, for the same reason the other
  two have not: no Chromium here. `render_feedback_html` is tested at the HTML
  level (no fiducials, no UID grid, no bubbles, one page per student); the PDF
  step is unverified code.
- ~~**Five pre-existing index drifts.**~~ **Closed.** Migration `0008` creates
  the four missing foreign-key indexes; `ix_exercise_discarded` was kept and
  declared in the model instead (it is a deliberate partial index from `0004`).
  A fresh database now reproduces `Base.metadata` exactly, and
  `scripts/check-schema-drift.py` runs in CI so it cannot drift again — unit
  tests build the schema with `create_all()` from the models, which is the one
  thing that can never catch this.
- ~~**The event log starts empty.**~~ **Backfilled.**
  `python -m alppy.cli backfill-events` reconstructs the agenda from the
  timestamps that already exist — sources, chapters read, sheets created and
  rendered, scans uploaded, and confirmation dated from the attempts' own
  `answered_at`. Idempotent, so it is safe in a container entrypoint. It
  deliberately does **not** invent `SHEET_PRINTED`: nothing ever observed a
  print, and an agenda that guesses is worse than one with a gap.
- **`SHEET_PRINTED` fires when the blank PDF link is clicked**, which is the
  closest observable proxy for a trip to the photocopier. A teacher who
  downloads twice records two prints, and one who prints from a previously
  saved file records none.
- **A real integration test of the whole loop** — print, degrade, scan, grade,
  watch the matrix move — exists only in pieces.
- **The e2e suite runs against the fixture layer, not the API.** That is what
  makes it fast and hermetic, and it also means it cannot catch a contract drift
  between `alppy/schemas` and `apps/web/src/lib/api/types.ts`. Generating those
  types from the served OpenAPI document would close it.

---

## 5. The ten assumptions most worth challenging

1. **The answer grid is at a fixed position, not beside each question.** This is
   what makes detection robust without reading the page, and it is the decision a
   teacher is most likely to push back on. Watch a class use one before defending it.
2. **A misread student code must fail rather than resolve.** 32 bits with a
   CRC-8; every single- and double-bit error is rejected. A failed read asks the
   teacher, which is recoverable. This trades convenience for safety, deliberately.
3. **`HALF_LIFE = 21` and `RECENCY_HALF_LIFE = 45` days.** Argued from how a class
   moves through a chapter, **not fitted to data**. They set what every band means.
4. **A blank answer is a graded zero; an ambiguous one is not graded at all.**
5. **Mastery treats competencies as independent.** The curriculum says otherwise.
6. **Difficulty is an author's estimate**, never calibrated against how the cohort
   actually performed — so the difficulty weighting rests on a guess.
7. **MCQ guessing is uncorrected.** A 4-option item has a 25% floor from chance.
   The `provisional` flag mitigates; per-item discrimination would fix it.
8. **A teacher belongs to exactly one school**, and tenancy is `school_id` on every
   row. Swiss teachers frequently work across establishments.
9. **Names are redacted by matching the actual roster**, never guessed by pattern —
   pattern-matching would flag Pythagore, Zürich, Thalès. This means the gate is
   only as good as the roster it is given.
10. **Groups are recomputed, never stored.** A teacher's manual move survives
    only until the next propose. If they expect groups to persist across a
    unit, that assumption is wrong and `StudentGroup` becomes worth its cost
    (D33).
11. **A third-party SaaS may not index Swiss publisher content.** The reading in
    [the research note](research/textbook-access-ch.md) is that GT 7 does not cover
    it. **This needs a Swiss lawyer, not an engineer.** The MVP is built so the
    answer does not block it: teachers upload material they already hold.

---

## 6. Recommended next three milestones

(Numbered on from the plan, which now ends at M8.)

### M9 — Prove the loop on real paper (1–2 weeks)
Nothing else matters until this is done. Run `docker compose up` for the first
time, render a sheet, print it on an actual printer, have people fill it in with
actual pencils, photograph it with actual phones, and push it back through.
Expect the fiducial detection and the fill thresholds to need adjustment against
real ink, real paper and real lighting; the synthetic suite is a good proxy and
not a substitute. Generate the Linux screenshot baselines in the same milestone
so the UI stops depending on manual checking.

### M10 — Make retrieval real (2–3 weeks)
Swap `HashEmbeddingsProvider` for self-hosted `multilingual-e5-large`, then feed
in a genuine textbook PDF and read what extraction produces. Chunking is where
this will hurt: a two-column Lehrmittel page with boxed exercises does not
linearise the way the demo corpus does. Build a small labelled evaluation set —
twenty intents with the exercises a teacher would actually want — and measure,
because "the proposals look reasonable" is not a metric.

### M11 — Put it in front of one teacher (ongoing)
One teacher, one class, one term, alongside whatever they do today. The questions
worth answering are not technical: do the five bands mean anything to them, do
they trust the auto-grading enough to stop double-checking, and do they ever
actually print the adaptive sheets. Before real student data: the DPIA, processor
agreements and breach process listed as unresolved in
[`privacy.md`](privacy.md) §6 have to be genuinely closed, not noted.

---

## 7. If you read nothing else

The riskiest thing in this repository is not a piece of code, it is a habit: the
tests here are good at checking that the arithmetic is right and bad at noticing
when the arithmetic means the wrong thing. Every bug in §3 passed every test
that existed. Each was found by running the whole thing and looking at the output
like a teacher would.

Keep doing that.
