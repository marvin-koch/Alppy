# Feedback Architecture

## Component diagram

```
  a COMMON sheet, scanned and confirmed
        │
        ▼
  services/feedback_service.py::generate_for_sheet
        │  per student:
        ▼
     wrong_attempts(student, sheet)
        │  Attempt ──(attempt.detection_id)──▶ Detection
        │  keep only: incorrect AND readable
        │  skip:  detection is None · LOW_CONFIDENCE · MULTIPLE · BLANK
        ▼
     Mistake(statement, given, expected)         ← what was marked, what was right
        │  _option_text / _given_index / _expected_index
        ▼
     _format_mistakes → scrub(...) → the prompt block
        ▼
     ai.complete(generate_feedback.v1,
                 student=to_ref(uid), student_names=roster)
        │  ungrounded provider → {"notes": []}   ← the CALLER's empty shape
        ▼
     GeneratedFeedbackIn validation
        ▼
     MisconceptionNote(student_id, sheet_id, notes[], approved_at=None)
        │
        │  teacher reads → approve_feedback()
        ▼
  sheets/render.py::build_feedback_data ── ensure_notes_printable()
        ▼
  sheets/html.py::render_feedback_html   SheetKind.FEEDBACK
        │  its OWN FeedbackData / FeedbackCopy — never paginate()
        ▼
  render_feedback_pdf → a separate document
```

## Data flow

### Where the wrong answer comes from

`Attempt` records **whether** the answer was right, never **what it was**. What the
student actually marked lives on the `Detection` — `detected_index`, `detected_bool` —
reachable through `Attempt.detection_id`.

```python
@dataclass(frozen=True)
class Mistake:
    statement: str
    given: str      # the option text the student marked, or the word they saw
    expected: str   # the option text that was right
```

For a true/false item, `given` is the **word the student saw** (V/F · R/F · T/F in the
exercise's language), not a boolean. A note that says "you answered false" about a
sheet that printed "F" for *faux* is a note the child cannot check.

### The empty shape matters

`adaptive_feedback` is in `TRANSCRIPTION_PURPOSES`, so the offline provider returns an
empty payload — and it must be the **caller's** empty shape, `{"notes": []}`, not
`{"exercises": []}`. A feedback caller handed the other envelope reports "the model did
not return usable JSON", which blames the provider for a refusal that is correct.

### The third document

```python
@dataclass(frozen=True)
class FeedbackCopy:
    student_uid: str
    notes: list[str]

@dataclass(frozen=True)
class FeedbackData:
    title: str
    copies: list[FeedbackCopy]
    kind: SheetKind = SheetKind.FEEDBACK
```

It never passes through `paginate()`, and it carries **no fiducials, no UID grid, no
answer grid**.

## Component interaction

### Why not a page inside the copy — the bug D34 prevented

`scan_processing._copies_by_uid` recomputes each copy's pagination independently, from
that copy's **items**, and `process_scan` maps a photographed page with
`page_in_copy = seen[uid] % len(printed_pages)`.

A page the renderer emits that this count does not know about **rotates every later
page of that copy onto the wrong item list** — with confident detections, and with
every unit test still green. `_stamp` would have written a wrong
`SheetInstance.page_count` for the same reason.

Making the two paginators agree (a shared "append a blank trailing page" helper) would
work, and was rejected: it makes the detector's page count depend on *mutable* feedback
state. Print a copy with feedback, discard the note afterwards — `feedback_id` is
`ON DELETE SET NULL` — and scan-time pagination computes one page fewer than was
printed. The same bug, through the back door.

### Why it must not look scannable

A stack of feedback pages fed into the scanner by accident is **rejected** rather than
read as a page of blank answers for the child whose UID is printed on it. That is why
I-feedback-02 is about what the page *lacks*.

`layout.py` is untouched by any of this, so feedback was **not** a layout version bump.

## Edge cases

- **A clean paper.** → no mistakes, no note, **no model call**.
- **An unreadable detection.** → skipped. There is no distractor to explain, and
  guessing which one they chose is the fabrication the grounding rule prevents.
- **An offline provider.** → `{"notes": []}`, nothing written, no half-note.
- **An empty or padded response.** → rejected by `GeneratedFeedbackIn`.
- **A discarded note after printing.** → `feedback_id` is `ON DELETE SET NULL`; because
  feedback is its own document, nothing about the *answer* pages changes.
- **A class of twenty.** → twenty model calls, in the worker, reporting progress through
  `Job` — never inside `POST /adaptive/propose`.

---

**Companion:** [`README.md`](README.md) §2 for the load-bearing rules.
