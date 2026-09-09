# Grading

**Status:** describes `main` as of 2026-09-09
**Audience:** developers, LLM agents, reviewers

---

## 1 · What it does

Grading turns a reviewed pile of `Detection` rows into `Attempt` rows — the only
evidence the mastery model ever sees. It has three parts:

- **The pure graders** (`scan/grading.py`): one function per exercise type, mapping
  an `AnswerKey` and a `DetectedAnswer` to a `GradedItem`. No database, no I/O.
- **The vision grader** (`scan/open_grading.py` + `services/open_answer_grading.py`):
  one model call per cropped written answer, producing a transcription and a verdict.
- **Confirmation** (`services/scan_service.py::confirm_scan`): the teacher signs the
  pile off, attempts are written, mastery is recomputed.

The rule the whole subsystem is built around: **an item is graded on a verdict, never
on a heuristic, and a missing verdict is never a zero.**

```
  Detection[]  ──▶  review UI: the teacher fixes what the machine got wrong
       │                             │
       │  (open items)               │
       ▼                             │
  GRADE_OPEN_ANSWERS job             │
  one call per crop                  │
  transcription + verdict            │
       │                             │
       └──────────────┬──────────────┘
                      ▼   POST /scans/{id}/confirm
              _answer_key(exercise, sheet_item, sheet)   ← the barème resolves here
                      │
              grade_item(key, detected)  ──▶ GradedItem
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
   gradeable=True              gradeable=False
   Attempt(correct, score)     no Attempt — counted as skipped, reported to the teacher
        │
        ▼
   mastery recompute
```

### Key properties

1. **Nothing reaches mastery unconfirmed.** The pipeline detects; a human signs off.
2. **Every refusal is explicit.** `MULTIPLE`, `PENDING`, `NOT_GRADEABLE` and a missing
   answer key all produce *no attempt*, with a reason string, never a score of 0.
3. **A blank is different from an unreadable.** A blank means the student saw the item
   and wrote nothing: that counts, at zero. It is the one zero this subsystem asserts.

---

## 2 · Invariants (load-bearing)

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-grading-01 | Every type that has no automatic grader returns `NOT_GRADEABLE` instead of guessing. `grade_item` **never raises**. | `scan/grading.py::grade_item`, `_GRADERS` | A new exercise type must fail closed | An unknown type silently graded as wrong |
| I-grading-02 | An **ungradeable item produces no `Attempt`** — it is counted as skipped and reported. | `scan/grading.py::ungradeable`, `scan_service.confirm_scan` | A zero is a claim about the student; "unreadable" is not | A child's record carries a zero nobody asserted |
| I-grading-03 | A **blank is a graded zero**; an **ambiguous mark is not graded at all**. | `grading._grade_choice`, `open_grading.grade_open_vision` | Two bubbles filled is a question for the teacher | A guess between two marks becomes a fact |
| I-grading-04 | A **written answer is graded on a verdict** — the model's or the teacher's. No text matching, ever. A missing verdict is not a zero. | `scan/open_grading.py::grade_open_vision` | String similarity on a child's handwriting is not assessment | A right answer scored wrong for spelling |
| I-grading-05 | **Nothing stays `PENDING`.** A failed call, a dead provider, an unreadable box: every one lands `NOT_GRADEABLE`. | `services/open_answer_grading.py::grade_one`, `_ungradeable`, `settle_abandoned` | A pending row is a promise, and a down provider must not keep it forever | Confirmation blocked indefinitely |
| I-grading-06 | The **offline provider grades nothing**, without making a call. | `ai/providers.py::TRANSCRIPTION_PURPOSES`, `open_answer_grading.grade_one` | A stand-in that cannot see the image would be issuing verdicts from a hash | A real child judged by a deterministic hash |
| I-grading-07 | The **machine's verdict is written once**: `machine_transcription`, `machine_verdict_correct`. A teacher's correction goes beside it. | `services/scan_service.py::_correct_written_answer` | The model's accuracy must stay measurable | The disagreement — the interesting fact — is erased |
| I-grading-08 | The **expected answer is optional and never faked.** `SheetItem.expected_answer` → `Exercise.answer_text` → `NO_EXPECTED_ANSWER`. Never a placeholder. | `services/open_answer_grading.py::grading_context`, `grade_one` | v1 substituted a placeholder and the model judged against it | Every written answer marked wrong against a sentinel string |
| I-grading-09 | The **barème is a magnitude**; only `score_for` applies the sign, and a blank never reaches it. | `scan/grading.py::score_for`, `layout.py` (MAX_ITEM_POINTS) | A teacher typing `0.25` and one typing `-0.25` must mean one thing | A penalty applied twice, or a blank penalised |
| I-grading-10 | **Re-confirming supersedes**, it does not accumulate. | `services/scan_service.py::confirm_scan` | Mastery is a weighted mean; a second row doubles that lesson's weight | A re-scanned copy quietly outweighs the rest of the term |
| I-grading-11 | **Reopening withdraws exactly what that confirmation wrote**, and re-derives each freed item only from a `Detection` on another pile that is *still* confirmed. Never fabricates a grade; an item with no older reading has **no attempt**, which is not a zero. | `services/scan_service.py::unvalidate_scan`, `_newest_other_confirmed` | Undo has to be as honest as grading was | A reopened pile leaves a child scored on evidence nobody signed off |
| I-grading-12 | A **confirmed pile is read-only.** Correcting or reverting a reading is refused until it is reopened. | `services/scan_service.py::_refuse_when_confirmed` | The grade was computed from the reading as it stood; editing one underneath leaves the two disagreeing | A grade and its own evidence say different things |

---

## 3 · Module map

| Path | Owns | Depends on |
|---|---|---|
| `alppy/scan/grading.py` | `AnswerKey`, `DetectedAnswer`, `GradedItem`, `score_for`, the MCQ and true/false graders, `register_grader` (the public seam) | `models.enums` only — pure |
| `alppy/scan/open_grading.py` | `grade_open_vision`, installed over the stub by `install()` when `alppy.scan` is imported | `scan.grading` |
| `alppy/services/open_answer_grading.py` | The `GRADE_OPEN_ANSWERS` job: `pending_detections`, `grading_context`, `grade_one`, `settle_abandoned`, `chain_open_grading` | `ai`, `storage`, `models` |
| `alppy/services/scan_service.py` | `_answer_key`, `_resolve_policy`, `correct_detection`, `confirm_scan` | `scan.grading`, `mastery_service` |
| `alppy/ai/prompts/grade_open_answer.v2.*` | The versioned grading prompt | — |
| `apps/web/src/components/OpenAnswerCard.tsx` | The crop, the reading, and one gesture to overrule it | `packages/shared` |

---

## 4 · How to extend this feature

**Adding an exercise type.** Write a grader with the `ItemGrader` signature and
install it with `register_grader(ExerciseType.X, grade_x)`. Do not reach into
`_GRADERS`; the seam is public precisely so you do not have to. Call `score_for` for
the barème rather than re-deriving it — that is what keeps I-grading-09 true for a
type that did not exist when it was written.

**Changing what a verdict means.** It is a `bool | None`. `None` is the whole point:
it is how "no opinion" is expressed, and it must never be coerced.

### LLM checklist

- [ ] Read §2 — these are not suggestions
- [ ] Does any new path turn a missing verdict into a score? (I-grading-02/04 — never)
- [ ] Does it add text matching to a written answer? (I-grading-04 — never)
- [ ] Does it write `machine_*` a second time? (I-grading-07 — never)
- [ ] Does it substitute a string for a missing expected answer? (I-grading-08 — never)
- [ ] Does it call `score_for`, or invent its own arithmetic? (I-grading-09)

---

## 5 · Privacy & safety

| Data | Where it is stopped | Why |
|---|---|---|
| Student name | The grading prompt carries the statement, the expected answer and the crop — no identity at all | `I-ai-01` |
| Student UID | Not in the prompt, and geometrically excluded from the crop | `I-scanning-07` |
| The crop | Sent as bytes, never a URL; audited as a hash | `ai/base.py::ImagePart`, `I-ai-06` |

**The safety rule.** Three outcomes mean "no attempt": `PENDING`, `NOT_GRADEABLE`,
`MULTIPLE`. They exist so the system can decline. A change that makes any of them
produce an `Attempt` is a change that scores a child on something nobody read.

---

## 6 · Testing strategy

| Invariant | Proved by |
|---|---|
| I-grading-01 | `test_grading.py::test_missing_answer_key_is_not_gradeable`, `test_open_grading.py::test_the_stub_alone_grades_nothing`, `::test_importing_the_scan_package_installs_the_grader` |
| I-grading-02 | `test_scan_processing.py::test_ungradeable_items_are_reported_rather_than_vanishing`, `test_api_scans.py::test_confirm_grades_only_what_is_gradeable_and_moves_the_band` |
| I-grading-03 | `test_grading.py::test_blank_counts_as_wrong_but_gradeable`, `::test_multiple_marks_are_never_guessed` |
| I-grading-04 | `test_open_grading.py::test_no_verdict_is_not_a_zero`, `::test_a_verdict_is_a_score`, `::test_a_teacher_correction_grades_on_the_teachers_verdict` |
| I-grading-05 | `test_scan_processing.py::test_confirmation_waits_for_a_live_grader_and_settles_an_abandoned_one`, `::test_a_shaky_or_unreadable_verdict_is_surfaced_not_scored` |
| I-grading-06 | `test_scan_processing.py::test_the_offline_provider_grades_nothing_and_leaves_nothing_pending`, `test_ai_vision.py::test_the_offline_provider_never_invents_a_verdict` |
| I-grading-07 | `test_scan_processing.py::test_the_teacher_corrects_a_written_answer_and_the_machine_keeps_its_story` |
| I-grading-08 | `test_scan_processing.py::test_the_grader_judges_against_the_sheet_items_answer_and_wording`, `::test_without_an_expected_answer_the_model_works_one_out_and_it_is_kept`, `test_ai_vision.py::test_the_v2_grading_prompt_carries_the_reference_block` |
| I-grading-09 | `test_grading.py::test_a_wrong_answer_costs_the_penalty_and_the_grader_applies_the_sign`, `::test_a_blank_is_never_penalised_however_large_the_penalty`, `::test_zero_points_is_a_real_choice_not_an_absent_one` |
| I-grading-10 | `test_scan_processing.py::test_rescanning_supersedes_instead_of_duplicating`, `::test_confirming_the_same_scan_twice_is_still_a_conflict` |
| I-grading-11 | `test_scan_processing.py::test_reopening_withdraws_the_grades_that_confirmation_wrote`, `::test_reopening_a_rescan_falls_back_to_the_pile_it_superseded`, `::test_reopening_leaves_no_grade_rather_than_a_zero` |
| I-grading-12 | `test_scan_processing.py::test_a_confirmed_pile_refuses_both_correction_and_revert` |

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_grading.py \
  apps/api/tests/test_open_grading.py apps/api/tests/test_scan_processing.py \
  apps/api/tests/test_api_scans.py apps/api/tests/test_ai_vision.py -q
```

---

## Companion documents

- [`architecture.md`](architecture.md) — the two graders, the job, the barème
- [`decisions.md`](decisions.md) — D5, D13, D42, D43, and the barème
- [`../scanning/`](../scanning/) — where a `Detection` comes from
- [`../mastery/`](../mastery/) — what an `Attempt` becomes

**Last updated:** 2026-09-09
