# Feedback Decisions Log

D-numbers follow the repo-wide [`docs/decisions-log.md`](../../decisions-log.md).

---

## D34 · Feedback is its own document, because a page inside the copy misgrades the class

**Date:** 2026-09 · **Affected invariants:** I-feedback-01, I-feedback-02

**Background.** Per-student feedback had to reach paper. The obvious shape — one more
page at the end of each copy, which `html.physical_pages` already supports — is a
**silent misgrading bug**.

**Considered alternatives**
- A) *A trailing page inside each copy.* Rejected. `scan_processing._copies_by_uid`
  recomputes each copy's pagination independently from the copy's items, and
  `process_scan` maps a page with `page_in_copy = seen[uid] % len(printed_pages)`. A
  page the renderer emits that this count does not know about rotates every later page
  of that copy onto the wrong item list — with confident detections, and with every
  unit test still green.
- B) *Make the two paginators agree* via a shared "append a blank trailing page"
  helper. Rejected, and this is the interesting rejection: it makes the detector's page
  count depend on **mutable feedback state**. Print a copy with feedback, discard the
  note afterwards (`feedback_id` is `ON DELETE SET NULL`), and scan-time pagination
  computes one page fewer than was printed. The same bug through the back door.
- C) **`SheetKind.FEEDBACK`: a third document beside the blank and the answer key,
  built from its own `FeedbackData`, never passing through `paginate`.** Chosen.

**Tradeoff**
- ✅ The scanner's page count depends only on the answer pages, which are immutable
  once printed
- ✅ A feedback page carries no fiducials, no UID grid, no answer grid — so a stack fed
  into the scanner by accident is *rejected* rather than read as blank answers
- ❌ A third document for the teacher to print and hand out

**Not a layout version bump:** `layout.py` is untouched.

**How it reinforces I-feedback-02:** "A page that is never scanned must not look like
one that is."

---

## D35 · Generated feedback is grounded-only, and gated like an exercise

**Date:** 2026-09 · **Affected invariants:** I-feedback-03, I-feedback-04, I-feedback-05

**Background.** `adaptive_feedback` joined `providers.TRANSCRIPTION_PURPOSES`. The
reason is **stronger** than the one that put `extract_exercises` there: an invented
exercise is a bad question a teacher can reject on sight; an invented misconception is
a claim about how one named child thinks, printed and handed to that child. The offline
`EchoChatProvider` cannot read its prompt, so anything it said about a student's
mistakes would be fiction with a real UID attached.

**A consequence worth recording.** The echo provider had to answer in the **caller's**
empty shape — `{"notes": []}`, not `{"exercises": []}` — because a feedback caller
handed the other envelope reports "the model did not return usable JSON", which blames
the provider for a refusal that is correct.

**Approval.** `MisconceptionNote.approved_at` mirrors `Exercise.approved_at` and is
enforced by the same module at the same two doors: batch creation and render.

**Evidence.** A note is only ever written from an answer we can actually read. An
attempt whose detection is missing, `LOW_CONFIDENCE`, `MULTIPLE` or `BLANK` is skipped
rather than guessed at — explaining a distractor we did not read is exactly the
fabrication the grounding rule exists to prevent. A student with a clean paper gets no
note and costs no model call.

**Where it runs.** `JobKind.GENERATE_FEEDBACK` in the worker, not inside
`POST /adaptive/propose`: one model call per student, and a class of twenty inside a
request handler is a timeout with a half-written batch behind it (I-platform-05).

---

## When policy changes

```json
{
  "change": "write a note from a LOW_CONFIDENCE detection, marked as uncertain",
  "reason": "more students would get feedback",
  "date": "YYYY-MM-DD",
  "decision": "rejected — violates I-feedback-04",
  "rationale": "the uncertainty is about which bubble was marked. A note explaining
                the wrong distractor is not 'uncertain feedback', it is feedback
                about something the child did not do."
}
```
