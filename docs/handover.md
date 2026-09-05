# Handover

What is built, what is stubbed, what is not there, and the assumptions most
worth challenging. Written to be read by whoever picks this up next.

---

## 1. Where it stands

| Milestone | State |
|---|---|
| M0 — foundation, design system, i18n, nav | **Done** |
| M1 — classes, curriculum, ingestion, extraction | **Done**, ingestion unverified against a real textbook PDF |
| M2 — sheet builder, print, PDF + answer key | **Mostly done** — PDF rendering never executed (no Chromium here) |
| M3 — scan, registration, detection, review, grading | **Done**, verified against synthetic degradation only |
| M4 — mastery model, matrix, profiles | **Done** |
| M5 — adaptive per-student sheets, batch export | **Done**, batch PDF unexecuted for the same reason as M2 |
| M6 — polish, e2e, screenshots | **Partial** — states and demo seed done, Playwright suite not written |

**Verified green, on this machine, just now:**

```
277 tests pass          ruff: All checks passed
mypy strict: no issues found in 65 source files
@alppy/ui typecheck clean       @alppy/web typecheck clean, builds, prerenders fr/de/en
tokens.css: 124 tokens, all theme blocks consistent, @theme inline
i18n: 239 keys in sync across fr, de, en
print geometry: Python and generated TypeScript in sync
no colour literal outside tokens.css and print.css
demo seed: 18 students, 559 attempts, 90 snapshots, idempotent on re-run
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

## 3. Three bugs the work actually caught

Recorded because each one was invisible to the thing that should have caught it.

1. **The detector read a light pencil mark as blank with full confidence**, which
   silently scores a child zero. A global threshold cannot tell a faint mark from
   paper; a local annulus can. Found by the synthetic degradation suite.
2. **The photocopier simulation was wrong, not the detector.** Its transfer curve
   erased mid-grey pencil, which a real copier does not do. Worth separating,
   because it looked exactly like a detector failure and would have sent someone
   tuning the wrong component.
3. **The mastery model used one half-life for two different quantities.** How fast
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

- **Playwright e2e and theme/locale screenshot tests.** The CI job is wired and
  skips cleanly; the specs are not written. This is the largest single gap.
- **The PDF path has never been executed.** `render.py` and the templates are
  written and the HTML is tested, but Chromium was never installed here, so
  `render_sheet_pdfs` and `render_adaptive_batch` are **unverified code**. Treat
  the first run as debugging, not as a smoke test.
- **`docker compose up` has never been run.** The Docker daemon was not running
  on this machine. Compose, Dockerfiles and entrypoints parse and are internally
  consistent, and the migration was diffed against the models — but the one
  command the README leads with is unproven. **Run it first.**
- **Free-text grading**, by design. The seam is `_GRADERS` in `scan/grading.py`.
- **A real integration test of the whole loop** — print, degrade, scan, grade,
  watch the matrix move — exists only in pieces.

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
10. **A third-party SaaS may not index Swiss publisher content.** The reading in
    [the research note](research/textbook-access-ch.md) is that GT 7 does not cover
    it. **This needs a Swiss lawyer, not an engineer.** The MVP is built so the
    answer does not block it: teachers upload material they already hold.

---

## 6. Recommended next three milestones

### M7 — Prove the loop on real paper (1–2 weeks)
Nothing else matters until this is done. Install Chromium, render a sheet, print
it on an actual printer, have people fill it in with actual pencils, photograph
it with actual phones, and push it back through. Expect the fiducial detection
and the fill thresholds to need adjustment against real ink, real paper and real
lighting; the synthetic suite is a good proxy and not a substitute. Land the
Playwright e2e and theme/locale screenshot suite in the same milestone so the UI
stops depending on manual checking.

### M8 — Make retrieval real (2–3 weeks)
Swap `HashEmbeddingsProvider` for self-hosted `multilingual-e5-large`, then feed
in a genuine textbook PDF and read what extraction produces. Chunking is where
this will hurt: a two-column Lehrmittel page with boxed exercises does not
linearise the way the demo corpus does. Build a small labelled evaluation set —
twenty intents with the exercises a teacher would actually want — and measure,
because "the proposals look reasonable" is not a metric.

### M9 — Put it in front of one teacher (ongoing)
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
when the arithmetic means the wrong thing. All three bugs in §3 passed every test
that existed. Each was found by running the whole thing and looking at the output
like a teacher would.

Keep doing that.
