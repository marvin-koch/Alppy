# Feedback

**Status:** describes `main` as of 2026-09-09
**Audience:** developers, LLM agents, reviewers

---

## 1 · What it does

A teacher runs a common sheet, scans it back, confirms the grades, and asks for
differentiated sheets. The differentiated sheet says *what to practise next*; it does
not say **why the child got it wrong**. This subsystem writes that — one
`MisconceptionNote` per student, from the answers they actually gave — and prints it
as **its own document**, never as a page inside the copy.

```
  a corrected COMMON sheet
        │
        ▼
  wrong_attempts(student, sheet)     Attempt → Detection → what was actually marked
        │   skips: no detection · LOW_CONFIDENCE · MULTIPLE · BLANK
        │   (a clean paper produces no note and costs no model call)
        ▼
  Job(GENERATE_FEEDBACK)  — one model call per student, in the worker
        │   prompt: to_ref(uid), the scrubbed mistake block, generate_feedback.v1
        │   ungrounded provider → {"notes": []}, and nothing is written
        ▼
  MisconceptionNote(notes[], approved_at=NULL)
        │   the teacher reads and stamps it
        ▼
  render_feedback_pdf  →  SheetKind.FEEDBACK
        a third document: no fiducials, no UID grid, no answer grid
```

### Key properties

1. **Grounded, or nothing.** An invented misconception is a claim about how a named
   child thinks, printed and put in that child's hands. A student with no note reads no
   note; a student with an invented one is told something false about themselves.
2. **Its own document.** Not a page appended to the copy — that shape is a silent
   misgrading bug (D34).
3. **Written only from an answer we could read.** Guessing which distractor a child
   chose is exactly the fabrication the grounding rule exists to prevent.

---

## 2 · Invariants (load-bearing)

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-feedback-01 | Feedback is **a third document** (`SheetKind.FEEDBACK`), built from its own `FeedbackData`, never passing through `paginate`. | `sheets/html.py::render_feedback_html`, `render.build_feedback_data` | A page inside the copy rotates every later page onto the wrong item list | A whole class silently misgraded, with every unit test green |
| I-feedback-02 | The feedback document carries **no fiducials, no UID grid, no answer grid**. | `templates`, `test_print_scan_roundtrip.py` | A page that is never scanned must not *look* like one that is | A stack of feedback pages fed to the scanner read as blank answers |
| I-feedback-03 | Generation is **grounded-only**: `adaptive_feedback` ∈ `TRANSCRIPTION_PURPOSES`. | `ai/providers.py`, `feedback_service.generate_for_student` | The echo provider cannot read its prompt | Fiction about a real child, with their UID attached |
| I-feedback-04 | A note is written **only from an answer that was actually read**. No detection, `LOW_CONFIDENCE`, `MULTIPLE` or `BLANK` → skipped. | `services/feedback_service.py::wrong_attempts` | `Attempt` records *whether* it was right, never *what was marked* — that lives on the `Detection` | A misconception explained about a distractor nobody read |
| I-feedback-05 | Every note is written **`approved_at = NULL`** and cannot print until a teacher stamps it — the same gate, the same two doors. | `services/approval.py::ensure_notes_printable` | Same boundary as a generated exercise | Unreviewed claims about a child, printed |
| I-feedback-06 | **No student name in the prompt.** `to_ref(uid)`, mistake block `scrub`-ed, gate armed. | `feedback_service.generate_for_student`, `_roster_names` | I-ai-01 | A roster in a third-party log |
| I-feedback-07 | Generation runs in the **worker** (`JobKind.GENERATE_FEEDBACK`), never inside a request. | `worker/tasks.py`, `api/v1/adaptive.py` | One model call per student; twenty in a handler is a timeout | A half-written batch behind a 504 |

---

## 3 · Module map

| Path | Owns | Depends on |
|---|---|---|
| `alppy/services/feedback_service.py` | `wrong_attempts`, `Mistake`, `_format_mistakes`, `generate_for_student`, `generate_for_sheet`, `latest_for_students` | `ai`, `models`, `scrub` |
| `alppy/services/approval.py` | `is_note_printable`, `ensure_notes_printable`, `approve_feedback`, `discard_feedback` | `models` |
| `alppy/sheets/html.py` | `FeedbackCopy`, `FeedbackData`, `render_feedback_html` | templates |
| `alppy/sheets/render.py` | `build_feedback_data`, `render_feedback_pdf` | `html`, `approval` |
| `alppy/ai/prompts/generate_feedback.v1.md` | The prompt | — |
| `apps/web/src/components/FeedbackNoteCard.tsx` | Reading and approving a note | `packages/shared` |
| `MisconceptionNote` (model) | `student × common sheet`, `notes[]`, `approved_at` | — |

---

## 4 · How to extend this feature

The temptation here is always the same: *make the note richer*. Everything in §2 is a
constraint on that. A richer note needs more evidence, and the only admissible evidence
is what a detection actually recorded.

If you need something the `Detection` does not hold, the fix is upstream — record it at
scan time — not a plausible reconstruction here.

### LLM checklist

- [ ] Read §2 — these are not suggestions
- [ ] Does a note get written from an attempt with no readable detection? (I-feedback-04 — never)
- [ ] Does anything append feedback to the student's copy? (I-feedback-01 — never)
- [ ] Does the feedback page gain a fiducial, a UID grid or an answer row? (I-feedback-02 — never)
- [ ] Is a note created approved, or approved by anything but a teacher? (I-feedback-05)
- [ ] Does generation happen inside a request handler? (I-feedback-07 — never)

---

## 5 · Privacy & safety

| Data | Scrubbing point | Why |
|---|---|---|
| Student name | `to_ref(student.uid)`; roster passed to `AiClient.complete` | I-ai-01 |
| Textbook statement naming a pupil | `scrub`-ed into the mistake block | Swiss textbook prose names pupils who are also in the class |
| The note itself | Stored per student, printed only after approval | It is a claim about a child |

**This is the strictest grounding requirement in the product**, stricter than the one on
generated exercises. A wrong exercise is a bad question a teacher rejects on sight. A
wrong misconception is a sentence about how a child thinks, printed and handed to that
child.

---

## 6 · Testing strategy

| Invariant | Proved by |
|---|---|
| I-feedback-01 | `test_print_scan_roundtrip.py::test_the_feedback_document_carries_nothing_the_scanner_registers_on` — the document is built by its own path, and proves it by carrying nothing `paginate` would have added |
| I-feedback-02 | `test_print_scan_roundtrip.py::test_the_feedback_document_carries_nothing_the_scanner_registers_on` |
| I-feedback-03 | `test_feedback.py::test_the_offline_provider_writes_no_note`, `::test_an_empty_or_padded_response_is_rejected` |
| I-feedback-04 | `test_feedback.py::test_an_unreadable_detection_is_never_guessed_at`, `::test_a_clean_paper_produces_no_note_and_no_model_call`, `::test_a_wrong_answer_carries_what_was_marked_and_what_was_right`, `::test_true_false_reports_the_word_the_student_saw` |
| I-feedback-05 | `test_feedback.py::test_a_note_is_written_unapproved_and_names_nobody` |
| I-feedback-06 | `test_feedback.py::test_a_note_is_written_unapproved_and_names_nobody` |
| I-feedback-07 | `test_jobs_queue.py::test_every_job_kind_names_a_task_the_worker_registers` |

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_feedback.py \
  apps/api/tests/test_print_scan_roundtrip.py -q
```

---

## Companion documents

- [`architecture.md`](architecture.md) — where the wrong answer comes from, and the third document
- [`decisions.md`](decisions.md) — D34, D35
- [`../adaptive/`](../adaptive/) — the other half of a corrected common sheet
- [`../grading/`](../grading/) — where a `Detection` gets its reading

**Last updated:** 2026-09-09
