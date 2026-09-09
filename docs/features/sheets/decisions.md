# Sheets Decisions Log

D-numbers here follow the repo-wide [`docs/decisions-log.md`](../../decisions-log.md)
so one decision has one identity. Entries below are the sheets-relevant subset,
restated in the framework's format with the invariant each one holds up.

---

## D1 · The answer grid is at a fixed position, not inline with the statements

**Date:** project start · **Affected invariants:** I-sheets-06, I-sheets-05

**Background.** Detection has to work on a phone photo of a photocopy. Statement
height varies with the text; a grid at a fixed position does not.

**Considered alternatives**
- A) *A bubble beside each question.* Rejected: the detector would have to know where
  each statement ended, i.e. parse the page — the one thing that fails on a bad scan.
- B) *A QR code carrying the answers.* Rejected: students write with pencils, not QR.
- C) **A fixed grid, 8 rows × 2 column groups = 16 items per physical page.** Chosen:
  every bubble is computable from the four fiducials alone.

**Tradeoff**
- ✅ The detector reads geometry only; no OCR, no text, no per-sheet calibration
- ✅ 16 items per page is a natural ceiling for pagination to enforce
- ❌ The student reads above and marks below, like a standard optical mark sheet

**Revisit if** teachers report the separation confuses younger classes.

---

## D3 · Class year is limited to 1–15 by layout v1

**Date:** project start · **Affected invariant:** I-sheets-03

Four bits of the 24-bit UID payload. Swiss Sek I is years 7–11, so it is comfortable.
Encoding a higher year **raises at print time** rather than producing a sheet that
decodes to somebody else. Widening the field is a layout version bump.

---

## D29 · A draft sheet is previewed by POST, and never stored

**Date:** 2026-08 · **Affected invariant:** I-sheets-10

**Background.** A teacher composing a sheet wants to see the paper before saving. The
obvious route — save a hidden draft, render it, delete it — writes rows for something
that may never exist and leaves orphans when the tab is closed.

**Chosen.** `POST /sheets/preview` takes the unsaved draft, runs
`build_draft_sheet_data` through the same pagination and the same markup, and returns
the real printed document. Nothing is persisted.

**Tradeoff**
- ✅ The preview is the document, not an approximation of it
- ✅ No draft rows, no cleanup job
- ❌ The endpoint takes a body large enough to describe a whole sheet

---

## D40 · A textbook exercise is cut from the page, not transcribed from its text layer

**Date:** 2026-09 · **Affected invariant:** I-sheets-09 (and `corpus` I-corpus-05)

A Romandy maths exercise is often a figure, a table or a photo. Transcribing it loses
the part the student is meant to look at. So the printed item can be an **image crop
of the book's own page**, and the crop is exempt from the `body-l` floor: it
reproduces the book at 1:1, and shrinking it would be worse than the rule it breaks.
Everything Alppy sets itself still obeys the floor.

---

## D42 · A written answer prints in a box that is measured, cropped, and graded on a verdict

**Date:** 2026-09-08 · **Affected invariants:** I-sheets-07, I-sheets-08

**Background.** `open` exercises were printable but never gradeable (D13). To grade
one, the scan job has to cut the student's handwriting out of the page — and it has
to cut it *where the box actually printed*, which only the browser knows.

**Considered alternatives**
- A) *Recompute the box from the `SheetItem` rows at scan time.* Rejected: a teacher
  who edits the sheet after printing would move what the scanner crops, silently.
- B) *A fixed box position, like the bubble grid.* Rejected: the box sits under a
  statement whose height the browser decides.
- C) **Measure every box in Chromium at render time and write `AnswerBoxPlacement`;
  crop at those rows.** Chosen.

**Tradeoff**
- ✅ The crop is where the ink is, on a phone photo as on a flatbed scan
- ✅ A sheet printed before boxes existed simply has no placements, and degrades to
  the old behaviour rather than to a wrong crop
- ❌ One more table, and a re-render must replace its rows

**How it reinforces I-sheets-07:** "An answer box is cropped where it printed, never
recomputed from `SheetItem`."

**And I-sheets-08:** `measure_answer_boxes` refuses a box outside
`ITEMS_TOP_MM..ITEMS_BOTTOM_MM`. The PII gate reads text; what keeps a student code
out of an image is geometry.

---

## D43 · The expected answer of a written item is the teacher's, per sheet item, and optional

**Date:** 2026-09-08 · **Affected invariant:** I-grading-08 (see `grading/`)

`SheetItem.expected_answer` (this sheet's) falls back to `Exercise.answer_text` (the
book's). When both are empty the grader sends `NO_EXPECTED_ANSWER` and the model
works the answer out first, returning it as `reference`, kept on the detection for
the teacher. **Never a placeholder string** — v1 substituted one and the model
judged against the placeholder.

---

## D44 · The statement keeps its size; a box that does not fit follows on the next page

**Date:** 2026-09-08 · **Affected invariant:** I-sheets-09

**Background.** D42 sized a textbook crop to whatever the answer box left over. With a
twelve-line box, that printed the book's type at a size nobody could read — seen on a
real sheet.

**Chosen.** `figure_room_mm` no longer subtracts the box. When statement and box
together do not fit, the item is placed twice: the statement on its page with no box,
and a *continuation* on the next — the number, "(suite)", and the box — each with its
own page-local `item_index`. The box moves whole; a crop cut in two is two crops for
the grader.

Any height from 1 to `ANSWER_BOX_MAX_LINES = 14` is allowed; the presets (3, 5, 8, 12)
are shortcuts. Fourteen is exactly the tallest box that still fits the statement
region alone once carried over — 133.3 mm of 134 mm — and a test fails if the
continuation height and the ceiling ever disagree.

**Not a layout version bump:** nothing at a fixed coordinate moved.

---

## D45 · The builder takes its class and subject from the sidebar

**Date:** 2026-09-09 · **Affected invariant:** none (UI)

The builder repeated the class and subject as two more selects above its tabs; the
sheets screen listed every sheet as its own card, most of them called "Nouvelle
fiche". The scope now comes from the sidebar, and the list is two piles — drafts and
printed — rather than one wall of badges.

---

## When policy changes

Any change to a number in `layout.py` is a **layout version bump** (I-sheets-03), and
that is not a judgement call. Record it here in this shape:

```json
{
  "change": "GRID_ROW_PITCH_MM 8.5 -> 9.0",
  "reason": "bubbles too tight for a 150 dpi photocopy",
  "date": "YYYY-MM-DD",
  "decision": "accepted — LAYOUT_VERSION v1 -> v2",
  "consequence": "sheets stamped v1 keep registering against v1; scan_processing
                  refuses to read a v1 page with the v2 map"
}
```
