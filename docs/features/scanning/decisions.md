# Scanning Decisions Log

D-numbers follow the repo-wide [`docs/decisions-log.md`](../../decisions-log.md).

---

## D2 · The UID is a 32-bit checksummed grid, not a QR code and not OCR

**Date:** project start · **Affected invariant:** I-scanning-02

**Background.** Every page has to say whose it is, on a photocopy, photographed by a
phone, possibly creased.

**Considered alternatives**
- A) *OCR the printed "7B_15".* Rejected: OCR on a phone photo of a photocopy is
  precisely where these systems fail.
- B) *A QR code.* Rejected: explicitly out of scope, and it spends a large area of
  the header on something a corner crease destroys.
- C) **A 4×8 grid: 24 payload bits + CRC-8.** Chosen.

**Tradeoff**
- ✅ Every single- and double-bit misread is *rejected*, verified by exhaustive test
- ✅ No OCR anywhere in the happy path
- ❌ 24 bits is a budget: class year 1–15, two class letters, student number 1–99 (D3)

**How it reinforces I-scanning-02:** a failed decode asks the teacher — recoverable.
A wrong decode files a child's answers under someone else's name — not recoverable,
and not detectable.

---

## D6 · Bubble fill is measured against a local annulus, not a global threshold

**Date:** M3 · **Affected invariant:** I-scanning-04

Found by the synthetic degradation suite. A global threshold reads a light pencil
mark as paper and silently scores the child zero; a photocopy's grey paper pushes the
same threshold the other way and reads noise as a mark. The local ring tracks both,
because it measures the bubble against the paper immediately around it.

**Tradeoff**
- ✅ Light pencil, grey paper and a dark photocopy all read correctly
- ❌ More expensive per bubble, and the annulus radius is now a tuned constant

---

## D7 · A mostly-blank page distrusts its own blanks

**Date:** M3 · **Affected invariant:** I-scanning-05

A page where a light pencil did not survive the copier is indistinguishable from a
genuinely empty page **at the level of one bubble** — but not at the level of a page.
Above 60 % blanks, every blank is downgraded to `LOW_CONFIDENCE` and sent to the
teacher rather than scored zero.

**Tradeoff**
- ✅ The most damaging failure mode — a whole copy silently zeroed — is caught
- ❌ A genuinely near-empty copy costs the teacher a review pass

**How it reinforces I-scanning-05:** the subsystem is allowed to say "I do not know".
It is never allowed to say "zero" when it means "I could not see".

---

## D31 · Scanned paper still needs OCR, and is still refused rather than faked

**Date:** 2026-09 · **Affected invariant:** none — a recorded gap

There is no OCR anywhere in the repo. An image-only PDF fails ingestion with
`NO_TEXT_LAYER_ERROR` and the teacher is told why, rather than getting a green tick
over an empty document. The integration point when this is taken on is
`extract.document_from_pages()`, which already accepts pre-extracted text.

Recorded here so it is not rediscovered as a bug.

---

## D37 · The print→scan loop is a test now, not an argument

**Date:** 2026-09 · **Affected invariants:** I-scanning-01, I-scanning-02, I-sheets-03

`tests/test_print_scan_roundtrip.py` renders a real sheet and scans the result: the
page registers, gives up its student code, and a filled bubble is read *at the
coordinate the layout promised*. Before it, the agreement between `layout.py`,
`print.css` and the detector was a claim in a document. Now it fails a test.

It is also what makes a layout version bump safe to attempt: the loop closes, or it
does not.

---

## D42 · A written answer is cropped where it printed

**Date:** 2026-09-08 · **Affected invariant:** I-scanning-07

See [`../sheets/decisions.md`](../sheets/decisions.md) for the full entry. The
scanning half: the crop is cut from the **registered** page at the rectangle the
renderer measured, Alppy's own furniture is painted out, and a box with no ink is
`BLANK` without a model call. Nothing here forms a verdict.

---

## When policy changes

A threshold in `detector.py` is a policy about how often a child is silently scored
zero. Any change to one gets an entry in this shape:

```json
{
  "change": "FILL_BLANK 0.18 -> 0.22",
  "reason": "a batch of dark photocopies read noise as faint marks",
  "date": "YYYY-MM-DD",
  "evidence": "synthetic suite: false-mark rate 3.1% -> 0.4%,
               light-pencil miss rate 0.2% -> 1.9%",
  "decision": "rejected — trades a visible false positive for an invisible false zero"
}
```

The asymmetry in that last line is the standing rule: a wrong mark the teacher sees
is cheap; a missed mark the teacher never sees is not.
