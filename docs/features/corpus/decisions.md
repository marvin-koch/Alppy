# Corpus Decisions Log

D-numbers follow the repo-wide [`docs/decisions-log.md`](../../decisions-log.md).

---

## D40 · A textbook exercise is cut from the page, not transcribed from its text layer

**Date:** 2026-09 · **Affected invariant:** I-corpus-05

**Background.** A real textbook is not a wall of text. In the Romandy maths books (MER,
*Mathématiques 9e–11e*) an exercise is a header line — a code such as `NO64` and a
title, set bold in the domain's colour — followed by a body that is more often than not
a figure, a table, a column of fractions or a photo of a newspaper clipping.

**Considered alternatives**
- A) *Transcribe the body with a model.* Rejected: it loses exactly the part the student
  is meant to look at, and a transcription of `3n²/n` has no way of being "precise".
- B) *A vision model describing the figure.* Rejected for the same reason plus cost: the
  student needs the figure, not a description of it.
- C) **Find where each exercise is, typographically, and cut it out as an image.**
  Chosen.

**Tradeoff**
- ✅ Deterministic — same file, same regions, same crops, same text, no model
- ✅ The student sees what the book shows
- ✅ A book with no coded headers yields no regions and falls back to
  chunk-and-transcribe
- ❌ The crop is exempt from the `body-l` floor (it reproduces the book at 1:1), which is
  a real exception to a real rule (I-design-08)
- ❌ Storage: one image per exercise

**Do not weaken the header rule to catch more books.** The fallback is the safety net.

---

## D26 · The builder navigates the document's own chapters, not just the teacher's

**Date:** 2026-09 · **Affected invariant:** I-corpus-07

**Background.** `Exercise.chapter_id` is inferred at ingest from competency overlap and
is legitimately `NULL`: it needs the teacher to have created chapters, those chapters to
carry competency codes, **and** the extraction to have tagged the item. On a real
textbook a large minority of rows fail one of those — and `pipeline._chapter_for`'s own
docstring names the consequence: *"an untagged exercise is invisible to the builder's
chapter filter, which is the only way a teacher finds it."*

**Chosen.** `SourceSection`: the chapter the **document** declares, read from its
headings at ingest. It is a fact about the file, needs no setup, cannot be null for an
exercise that came from a page, and is how a teacher actually navigates 400 pages. It
is the builder's **primary** filter; the curriculum chapter stays secondary, because
only that one answers "fractions across every book I own".

**Detection is deliberately conservative.** A false heading shatters the outline into
noise, which is worse than a coarse one. Sections are contiguous and gapless; a
document with no recognisable headings becomes one section; pages before the first
heading become a leading section rather than being attached to chapter 1.

**Revisit if** teachers report bad outlines on real textbooks — the next step is letting
them rename and merge sections, deliberately not in this pass.

---

## D27 · A chapter is read by the model on first open, not at import

**Date:** 2026-09 · **Affected invariants:** I-corpus-06, I-corpus-09

**Background.** `MAX_EXTRACTION_CHUNKS = 200` used to be a per-*upload* ceiling: roughly
the first 50–80 pages of a book became exercises, and the teacher was told to split the
PDF by hand.

**Chosen.** It is now the budget for **eager** extraction at import; the remainder waits
with `SourceSection.extracted_at IS NULL` until somebody opens that chapter
(`POST /sources/{id}/sections/{sid}/extract`).

**Two properties this keeps**
- **Nothing that worked before needs a click.** Import walks sections in book order and
  extracts while the budget lasts — a worksheet, a single chapter and every test fixture
  still arrive complete. And it stops **before** a section that will not fit whole,
  because half a chapter is the worst outcome available: the teacher sees exercises and
  cannot tell the back half is missing.
- **A book nobody teaches from costs nothing.** A 400-page textbook is indexed and
  searchable for the price of embeddings, and its chapter 19 is never sent to a model
  unless someone asks for it.

**Consequence.** De-duplication moved from a per-run set to `_existing_statements`,
reading the database: sections are extracted separately and their page ranges abut, so a
chunk carrying the tail of one chapter and the head of the next could otherwise offer
the same exercise twice.

---

## D28 · A teacher-written exercise is its own origin

**Date:** 2026-09 · **Affected invariant:** I-design-01 (the accent), I-adaptive-03

`ExerciseOrigin.TEACHER`, for items written with the builder's plus button.

- Filing them under `TEXTBOOK` would claim a provenance they do not have — a source
  filename and a page the teacher could check against the book on the desk.
- Filing them under `AI_GENERATED` would put the mandarin accent on a sentence a human
  wrote, which is the one thing that accent must never mean.

They need no approval gate — the teacher approved it by writing it — so `approved_at` is
stamped at creation and `approval.is_printable` keeps working unchanged. They are corpus
rows rather than sheet-local ones, because `SheetItem.exercise_id` is a non-null FK and
because a teacher who writes a good true/false item should get it back next term.

---

## D31 · Scanned paper still needs OCR, and is still refused rather than faked

**Date:** 2026-09 · **Affected invariant:** I-corpus-02 · **A recorded gap**

There is no OCR anywhere in the repo. `ingest.extract` fails an image-only PDF outright
(`NO_TEXT_LAYER_ERROR`), and the teacher gets a `FAILED` source with a message telling
them why — not a green tick over an empty document, which is the failure mode that
branch exists to prevent. The builder handles it honestly: such a document never appears
in the picker, since only `SUCCEEDED` sources are offered.

**The integration point** when this is taken on is `extract.document_from_pages()`, which
already accepts pre-extracted text: an OCR pass ahead of `extract_pdf` in
`pipeline._ingest_fresh` feeds it without touching anything downstream.

---

## D11 / D12 · Curriculum data is shared, and both curricula live in one table

**Date:** M1 · **Affected invariant:** I-platform-02 (tenancy)

LP21 and PER are public reference data shared by every tenant — the **one** exception to
"every row carries `school_id`". They live in one `Competency` table discriminated by
`curriculum` with a hierarchical `parent_id`, so a teacher's chapter can reference codes
from either. See [`docs/curriculum.md`](../../curriculum.md).

---

## When policy changes

```json
{
  "change": "accept a PDF with a thin text layer instead of failing it",
  "reason": "some scans have a few OCR'd words",
  "date": "YYYY-MM-DD",
  "decision": "rejected — violates I-corpus-02",
  "rationale": "MIN_DOC_CHARS exists because a handful of stray glyphs is exactly what
                an OCR-less producer emits. Accepting them produces a SUCCEEDED source
                with nothing in it, which is the failure this rule was written for."
}
```
