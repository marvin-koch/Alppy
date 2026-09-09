# Grading Decisions Log

D-numbers follow the repo-wide [`docs/decisions-log.md`](../../decisions-log.md).

---

## D5 · A blank answer is a graded zero; an ambiguous one is not graded at all

**Date:** M3 · **Affected invariants:** I-grading-02, I-grading-03

**Background.** Both cases produce no usable index. Treating them the same would be
simpler — and wrong in opposite directions.

**Considered alternatives**
- A) *Both are zeros.* Rejected: two bubbles filled means the student answered; we
  simply could not tell which. Scoring it zero asserts something nobody knows.
- B) *Both are skipped.* Rejected: a blank is evidence. The student saw the item and
  left it, which is exactly what a mastery model should learn from.
- C) **Blank → gradeable zero; ambiguous → ungradeable, no attempt.** Chosen.

**Tradeoff**
- ✅ Every zero in the database was asserted by someone
- ✅ The teacher gets a short list of genuine ambiguities, not a pile of zeros
- ❌ Two outcomes where a naive design has one

**How it reinforces I-grading-03:** "A blank is a graded zero; an ambiguous mark is
not graded at all."

---

## D13 · `open` exercises are stored and printable but never auto-graded

**Date:** M2 · **Superseded in part by D42**

The original position: free-text items print, and grading them is out of scope, so
`_grade_open` returns `NOT_GRADEABLE`. The docstring promised a plug-in seam for the
day a grader arrived, and `register_grader` is that seam — the free-text grader
installs itself through it rather than by editing the dispatcher.

The stub is still there, deliberately. Importing `scan.grading` alone grades a
written answer as *nothing* rather than as *something*.

---

## D42 · A written answer is graded on a verdict

**Date:** 2026-09-08 · **Affected invariants:** I-grading-04, I-grading-05, I-grading-06

**Background.** To grade a child's handwriting we need something that can read it. The
tempting cheap version is string comparison against the expected answer.

**Considered alternatives**
- A) *Normalise and compare strings.* Rejected outright. "8 cm", "8cm", "huit
  centimètres" and a correct answer with a spelling mistake are all the same answer,
  and a comparison that gets that wrong marks a right answer wrong — invisibly, at
  scale, on children.
- B) *Fuzzy matching with a threshold.* Rejected: the same failure with a tuning knob.
- C) **A vision model returns a transcription and a verdict; Alppy scores only the
  verdict.** Chosen.

**Tradeoff**
- ✅ The judgement is made by something that read the answer, and can be overruled
- ✅ Alppy's grading code stays a pure function of `verdict_correct`
- ❌ A model call per box, and a whole class of "the model was unsure" outcomes
- ❌ Offline, nothing is graded at all — which is the honest outcome (I-grading-06)

**How it reinforces I-grading-04:** "A written answer is graded on a verdict, never on
a heuristic. Do not add text matching, and never let a missing verdict become a zero."

---

## D43 · The expected answer is the teacher's, per sheet item, and optional

**Date:** 2026-09-08 · **Affected invariant:** I-grading-08

**Background.** v1 substituted a placeholder string when no expected answer existed.
The model dutifully judged every child's answer against the placeholder.

**Chosen.** `SheetItem.expected_answer` (the teacher's, for this sheet) falls back to
`Exercise.answer_text` (the book's). When both are empty the prompt carries the
literal `NO_EXPECTED_ANSWER` marker and the model is told to work the answer out
first, returning it as `reference` — which is kept on the detection so the teacher can
see what it judged against.

**Tradeoff**
- ✅ The model always knows which case it is in
- ✅ An item with no key is still gradeable, transparently
- ❌ Two prompt branches and a `reference` column

**Never** substitute a placeholder for a missing answer. That is the bug this decision
exists to prevent.

---

## The barème · a magnitude, and one place that applies the sign

**Date:** 2026-09 · **Affected invariant:** I-grading-09

`points_correct` and `points_penalty` are stored as non-negative magnitudes, bounded
`0..MAX_ITEM_POINTS` by check constraints, on both `Sheet` (defaults) and `SheetItem`
(overrides, nullable). `scan.grading.score_for` is the only place a sign is applied.

Two consequences that are easy to break:

1. A teacher who types `0.25` and a teacher who types `-0.25` cannot mean two
   different things.
2. A blank never reaches `score_for` — each grader returns `0.0` for a blank
   unconditionally, *before* the barème is consulted. No penalty can turn an item the
   student left empty into a negative one.

`MAX_ITEM_POINTS` lives in `layout.py` rather than here, because the printed points
label is a pagination concern: `POINTS_LABEL_W_MM` has to reserve room for the widest
label a teacher can ask for.

**Mastery ignores the barème entirely.** It is a weighted mean over `correct`, not
over points, so a teacher changing the weighting of a test does not move a child's
bands.

---

## When policy changes

```json
{
  "change": "grade a written answer when the model's confidence is below LOW_CONFIDENCE",
  "reason": "too many items reaching the teacher",
  "date": "YYYY-MM-DD",
  "decision": "rejected — violates I-grading-04",
  "rationale": "a low-confidence reading is exactly the case where a verdict is a
                guess. The teacher seeing it is the feature, not the cost."
}
```

---

## D48 · "Revised" is derived from a count, not a fourth `ScanStatus`

**Date:** M4 · **Affected invariants:** I-grading-11, I-grading-12

**Background.** Confirmation was a dead end: `CONFIRMED` had no reverse edge, and a
teacher who spotted a mis-read bubble afterwards had no way back. The ask was three
states — pending → validated → revised.

**Considered alternatives**
- A) *Add `ScanStatus.REVISED`.* Rejected. Walk every site that reads the status and
  ask whether it needs to tell a twice-confirmed pile from a once-confirmed one. None
  does — `confirm_scan`'s guard, `set_page_discarded`'s guard, `PENDING_SCAN_STATUSES`,
  and the web's `status === 'confirmed'` all mean "is this signed off?", and a revised
  pile still answers yes. Every one of them would become a two-member test, and each
  one missed silently unlocks a signed-off pile. The enum also does not save the
  bookkeeping: `confirm_scan` still has to consult a counter to know which member to
  write.
- B) **`confirmed_at` + `reopened_at` + `confirmation_count`, label derived.** Chosen.
  `revised == confirmation_count > 1`. Not one existing status check moved. The
  columns are also strictly more informative than a status could be — "reopened on the
  5th, still open" is a sentence the agenda can write.

**Consequence.** The lifecycle a teacher reads is four states, derived in one place:
pending · validated · revised · reopened.

---

## D51 · Undo re-derives from the detections; there is no history table

**Date:** M4 · **Affected invariants:** I-grading-11

**Background.** Reopening has to undo what a confirmation wrote. But a confirmation
*supersedes* — it overwrites the attempt an earlier pile wrote, destroying the old
values. So what does undo restore?

**Considered alternatives**
- A) *Snapshot the previous values* (`previous_score`, `previous_scan_id`). Rejected:
  it stores what is already derivable, and goes stale the moment the barème changes —
  which D46 explicitly allows.
- B) *Just delete.* Rejected: a re-scanned pile would blank a pupil who did answer.
- C) **Re-derive.** Chosen. `grade_item` is pure, `Detection` rows are never deleted by
  confirmation, and mastery is already a pure recompute over attempts. So reopening
  deletes what the pile owned, finds the newest *other* still-confirmed detection for
  each freed item, and replays the grader over it.

**What made it possible.** `Attempt.confirmed_scan_id` — the one genuinely missing
fact. `detection_id` names the reading but not the pile that currently owns the grade.

**Cost.** An item whose only reading was on the reopened pile goes back to having no
attempt. That is the honest record — nobody has asserted anything about it — and it is
the same rule as D5: an absent grade is not a zero.
