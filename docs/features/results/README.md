# Results

**Status:** describes `main` as of 2026-09-09
**Audience:** developers, LLM agents, reviewers

---

## 1 · What it does

Results answers the question the mastery matrix deliberately does not: **what did
they score?** Two read-only views over rows that already exist —

- **Class points** (`GET /classes/{id}/points`) — per student, the points earned
  and possible across the class's sheets; per sheet, the class average.
- **Item confidence** (`GET /sheets/{id}/confidence`) — per printed item, how many
  copies read low-confidence, ambiguous, or teacher-corrected.
- **One pupil's copy** (`GET /students/{id}/sheets/{id}`) — question by question:
  what they put, what was expected, what it was worth, and the total.

and the screens that draw them: `/results`, and the breakdown at
`/classes/{c}/students/{s}/sheets/{sheet}`.

The drill-down is the point: **Suivi → pupil → the sheet they sat → the answers.**
Each step narrows from a class to a paper without ever changing what a number
means.

Nothing here is stored. Both are computed fresh from `Attempt` and `Detection`,
exactly as the mastery matrix is, so neither can disagree with the rows it
summarises.

```
  Attempt.score ──┐
  (the barème)    ├─▶ sheet_service.class_points_totals ──▶ GET /classes/{id}/points
  Sheet.items ────┘        │                                        │
  SheetInstance.item_plan ─┘  (per-copy `possible`, reused,          ▼
                               never re-derived)              /results screen
  Detection.outcome ──▶ scan_service.confidence_by_item ──▶ GET /sheets/{id}/confidence
```

### Key properties

1. **A score is not a band.** Mastery is decayed evidence about a competency; a
   score is what the teacher's barème says the paper was worth. They answer
   different questions, so they get different screens and different visual
   vocabulary — `PointsCell` shares the grid shell with `MasteryCell` and none of
   its colour ramp.
2. **Absent is not zero.** `points_earned` is `null` for a copy nobody has marked,
   all the way from the SQL to the cell, which prints an em dash.
3. **A report names a piece of paper, never a child.** Item confidence is keyed by
   question so a badly printed item reads as a badly printed item.

---

## 2 · Invariants (load-bearing)

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-results-01 | **`points_earned` is `null`, never `0`, for anything ungraded** — per copy, per sheet and per term. | `sheet_service.class_points_totals`, `web/src/lib/points.ts::aggregatePoints` | A term with two of five sheets marked is not three failures | A pupil who has been assessed once reads as failing the year |
| I-results-02 | A class rollup **reuses `_possible_by_student`**, never re-derives what a differentiated copy was worth. | `services/sheet_service.py::_possible_by_student` | Two places computing it separately will disagree, and both are shown to the same teacher | The dashboard and the sheet page report different totals for one pupil |
| I-results-03 | The **points scale never borrows the mastery band ramp.** | `packages/ui/src/components/domain/PointsCell.tsx` | The five bands are a calibrated encoding of decayed competency; a raw score is a different measurement | "71 %" silently asserts a mastery band nobody computed |
| I-results-04 | All three reports are **computed, never stored.** | `api/v1/reports.py` | A stored total is one more place to disagree with the attempts the first time one detection is corrected | A dashboard that contradicts the sheet it links to |
| I-results-05 | A breakdown item with **no attempt reports `correct: null` and `points_earned: null`**, never `false`/`0`. | `services/results_service.py::student_sheet_breakdown` | "Not graded" and "graded wrong" are different claims about a child | An unmarked question shown as a lost mark |
| I-results-06 | An answer is rendered as **text a teacher can read** — "B. 2/3", "Vrai", the transcription — never a bare bubble index. | `services/results_service.py::_readable_choice` | The breakdown is read while handing the paper back, beside the pupil | A screen that says "2" where the paper says "C. 3/4" |

---

## 3 · Module map

| Path | Owns | Depends on |
|---|---|---|
| `alppy/api/v1/reports.py` | Both routes | `sheet_service`, `scan_service` |
| `alppy/services/sheet_service.py` | `_possible_by_student`, `_earned_by_sheet`, `points_totals_for_sheet`, `class_points_totals` | `models` |
| `alppy/services/scan_service.py` | `ItemConfidence`, `confidence_by_item` | `models` |
| `alppy/services/results_service.py` | `StudentSheet`, `student_sheet_breakdown`, `_readable_choice` | `models`, `sheets.layout` |
| `apps/web/.../students/[studentId]/sheets/[sheetId]/` | The per-pupil breakdown | `useStudentSheet` |
| `apps/web/src/app/[locale]/results/` | The dashboard | `PointsMatrix`, `useClassPoints` |
| `apps/web/src/lib/points.ts` | `pointsRatio`, `aggregatePoints`, `averageRatio` — the "null is not zero" rule, in one place | — |
| `packages/ui/.../Matrix.tsx` | The headless grid shell both matrices share | — |
| `packages/ui/.../PointsCell.tsx`, `PointsMatrix.tsx` | The points vocabulary | `Matrix` |

---

## 4 · How to extend this feature

**Adding a metric.** Add it to `ClassPointsReport`, not to the route. The route
shapes; the service computes. If it needs a per-copy total, call
`_possible_by_student` — never re-implement the `item_plan` walk (I-results-02).

**Adding a chart.** There is no chart library in this repo and none may be added.
`MasteryCurve` is the template: inline SVG, no dependency, print-safe,
`role="img"` with a written label.

**LLM checklist**
- [ ] Is every ungraded value still `null` rather than `0`, at every level?
- [ ] Does anything new borrow `--c-mastery-*` for a score? It must not.
- [ ] Does the mandarin accent appear? It marks AI-generated content only.
- [ ] Three states shipped: empty, loading (with a `shape`), error?
- [ ] Keys added to all three catalogues, `pnpm i18n:check` green?

---

## 5 · Privacy & safety

Both reports are school-scoped through `Scope` and the owned-class check, like
every other read. Neither reaches a model provider, so the PII gate is not on this
path — but item confidence deliberately aggregates *away* from the student, which
is the safety property worth keeping: it is a report about paper.

---

## 6 · Testing strategy

| Invariant | Test |
|---|---|
| I-results-01 | `test_reports.py::test_a_student_graded_on_nothing_yet_earns_null_not_zero`, `::test_a_sheet_nobody_has_scanned_has_no_average` |
| I-results-02 | `test_reports.py::test_a_class_total_agrees_with_each_sheets_own_numbers` |
| I-results-04 | `test_reports.py::test_the_reports_are_reachable_over_http`, `::test_the_students_copy_is_reachable_over_http` |
| I-results-05 | `test_reports.py::test_an_unmarked_copy_shows_no_points_rather_than_zero` |
| I-results-06 | `test_reports.py::test_a_students_copy_shows_what_they_put_and_what_was_expected` |

---

## Companion documents

- [`architecture.md`](architecture.md) — how the pieces talk
- [`decisions.md`](decisions.md) — why it is like this
- [`../grading/README.md`](../grading/README.md) — where `Attempt.score` comes from
- [`../mastery/README.md`](../mastery/README.md) — the other number, and why it is other
