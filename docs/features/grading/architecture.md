# Grading Architecture

## Component diagram

```
                     ┌────────────────── pure, no I/O ──────────────────┐
                     │  scan/grading.py                                 │
   AnswerKey ───────▶│    _GRADERS: {mcq, true_false, open}             │
   DetectedAnswer ──▶│    grade_item ─▶ dispatch ─▶ GradedItem          │
                     │    score_for(key, correct) ── the only sign flip │
                     │    register_grader(type, fn)  ◀── public seam    │
                     └───────────────────▲──────────────────────────────┘
                                         │ install() at import of alppy.scan
                     ┌───────────────────┴──────────────────────────────┐
                     │  scan/open_grading.py::grade_open_vision         │
                     │    PENDING        → ungradeable                  │
                     │    BLANK          → 0.0, gradeable               │
                     │    verdict None   → ungradeable                  │
                     │    verdict bool   → score_for(...)               │
                     └──────────────────────────────────────────────────┘

  ── the job that FORMS a verdict (never the one that interprets it) ──
  services/open_answer_grading.py
     pending_detections(scan) ─▶ for each: grade_one()
        ├─ not grounded, or no crop  → NOT_GRADEABLE, no call     (I-grading-06)
        ├─ grading_context()  statement + expected (or NO_EXPECTED_ANSWER)
        ├─ ai.complete(prompt=grade_open_answer.v2, images=(crop,), temperature=0.0)
        ├─ record_calls()  audit row: hash, tokens, latency — never content
        ├─ any exception     → NOT_GRADEABLE                      (I-grading-05)
        ├─ written is False  → BLANK
        ├─ correct not bool  → NOT_GRADEABLE (+ reference kept)
        └─ else → DETECTED | LOW_CONFIDENCE, verdict written once (I-grading-07)
                  committed per row, so a crash keeps what was graded

  ── confirmation ──
  services/scan_service.py::confirm_scan
     ├─ already CONFIRMED / FAILED         → conflict
     ├─ any page unassigned & not discarded → conflict, naming the pages
     ├─ pending_detections and a live job   → conflict "still being read"
     ├─ pending_detections and no job       → settle_abandoned()   (I-grading-05)
     ├─ _answer_key(exercise, sheet_item, sheet)   ← barème resolves LIVE
     ├─ grade_item(...)  → Attempt for gradeable, skipped count for the rest
     ├─ supersede prior attempts for (student, exercise, sheet)   (I-grading-10)
     └─ mastery_service.recompute_for_students(...)
```

## Data flow

### The three dataclasses

```python
@dataclass(frozen=True)
class AnswerKey:
    type: ExerciseType
    answer_index: int | None      # mcq
    answer_bool: bool | None      # true_false — bubble 0 is true, always
    option_count: int
    points_correct: float = 1.0   # the teacher's barème
    penalty: float = 0.0          # a MAGNITUDE; score_for applies the sign

@dataclass(frozen=True)
class DetectedAnswer:
    outcome: DetectionOutcome
    index: int | None
    confidence: float
    transcription: str | None     # written answers only
    verdict_correct: bool | None  # None means "no opinion" — never coerced

@dataclass(frozen=True)
class GradedItem:
    correct: bool
    score: float
    gradeable: bool               # False → no Attempt is written at all
    outcome: DetectionOutcome
    confidence: float
    reason: str                   # shown to the teacher
```

`gradeable` is the load-bearing field. `correct=False, gradeable=False` is not a wrong
answer; it is the absence of an answer, and `confirm_scan` writes nothing for it.

### Where the barème resolves — and why not at print time

`_resolve_policy(sheet_item, sheet)`: the item's own value, else the sheet's default,
else the historical 1.0 / 0.0. `NULL` on a `SheetItem` means "use the sheet's
default", so each column is tested with `is not None` — a deliberate `0` is a real
override (a bonus item worth nothing) and must not read as absent.

It resolves **at grading time**, from the rows as they stand, deliberately unlike an
answer box's rectangle. A rectangle is a physical fact about a page the browser laid
out; recomputing it would crop the wrong pixels from a real photograph. A barème
touches no coordinate — it is arithmetic applied after every physical fact is fixed.
And the correctness key beside it has always resolved live: a teacher who fixes a
typo'd answer after printing grades against the fix. Freezing what an answer is
*worth* while leaving what it *is* live would split one question down the middle.

## Component interaction

### `grade_item` — the dispatcher that never raises

An unknown type returns `ungradeable(...)`. That is the fail-closed default, and it
is why adding a type cannot accidentally score anybody.

### `_grade_choice` — shared by MCQ and true/false

Order matters, and it is the order of the invariants:

1. `BLANK` → `score 0.0`, **gradeable** (the student saw it and left it)
2. `MULTIPLE` → ungradeable ("more than one bubble marked")
3. no index → ungradeable
4. no expected answer → ungradeable ("exercise has no answer key")
5. otherwise compare and call `score_for`

True/false maps bubble 0 to *true* always. The printed glyph changes with the sheet
language (V/F · R/F · T/F); the positions never do, which is why the detector can
read a German sheet without knowing it is German.

### `grade_open_vision` — interprets a verdict, never forms one

The vision model has already compared the transcription against the expected answer
inside its own prompt. What arrives here is that verdict, the teacher's correction of
it, or the absence of either — and the absence is never turned into a score.

## Edge cases

- **The provider is down.** Every box lands `NOT_GRADEABLE`; confirmation proceeds and
  reports them as skipped. Nothing waits forever.
- **The grading job died mid-pile.** Rows are committed as they land, so what was
  graded stays graded; `settle_abandoned` closes the rest at confirm time.
- **The teacher confirms while grading is running.** Conflict, with
  `code="scan_open_grading_pending"` — confirming now would lock the pile with a
  child's answer unrecorded.
- **A teacher overrules the model.** `_correct_written_answer` sets the teacher's
  verdict; `machine_transcription` / `machine_verdict_correct` stay untouched.
- **No expected answer anywhere.** The prompt carries `NO_EXPECTED_ANSWER`; the model
  works the answer out first and returns it as `reference`, which is kept on the
  detection for the teacher to see. Never a placeholder (I-grading-08).
- **A true/false detection "corrected" to a bubble that was never printed.** Refused.
- **A scan that can grade nothing at all.** Refused at confirm, rather than writing an
  empty confirmation.
- **A sheet total below zero** (heavy penalties). Floored at zero for the printed
  total; the underlying attempts keep their scores, and **mastery ignores the barème
  entirely** — it is a weighted mean over `correct`, not over points.

---

**Companion:** [`README.md`](README.md) §2 for the load-bearing rules.
