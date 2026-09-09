# Mastery

**Status:** describes `main` as of 2026-09-09
**Audience:** developers, LLM agents, reviewers
**Authority on the constants:** [`docs/mastery-model.md`](../../mastery-model.md)

---

## 1 · What it does

Mastery is the five-band matrix a teacher reads: students down the side,
competencies across the top, one colour-and-label per cell. It is computed from
confirmed `Attempt` rows and nothing else, by a model deliberately simple enough that
a teacher can be told *why* a cell is amber.

```
  score = accuracy × recency          ∈ [0, 1]

  accuracy = Σ(wᵢ · correctᵢ) / Σ(wᵢ)      wᵢ = 2^(-ageᵢ/21d) · difficulty_weightᵢ
  recency  = 1 if idle ≤ 7d, else max(0.55, 2^(-idle/45d))

  bands    ≥0.90 solid · ≥0.75 ok · ≥0.60 weak · <0.60 fading · no attempts → none
```

Two factors, not one, and that is the whole design. Weighted accuracy is
scale-invariant under uniform time decay: without `recency`, a student who was perfect
a year ago would still read as mastered forever and the "fading" band would never
fade.

```
  Attempt[]  ──▶  mastery/model.py  (pure functions, no database)
                        │  compute_mastery(attempts, now) -> MasteryResult
                        ▼
              services/mastery_service.py
                        │  one MasterySnapshot per (student, competency, DAY)
                        ▼
        ┌───────────────┴────────────────┐
        ▼                                ▼
  class_matrix()                   student_profile()
  GET /classes/{id}/mastery        GET /students/{id}/mastery
        │                                │
        └──▶ adaptive targeting ◀────────┘
```

### Key properties

1. **Pure model, thin service.** `mastery/model.py` has no idea a database exists, so
   the whole model is unit-testable in milliseconds, and it is.
2. **Explainable.** Every number in a cell can be traced to attempts the teacher can
   drill into: `GET` the cell, get the attempts, the sheet and the scan behind it.
3. **Never-assessed is a band, not a zero.** `NONE` exists so an empty matrix does not
   read as a class that has failed everything.

---

## 2 · Invariants (load-bearing)

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-mastery-01 | The score is **accuracy × recency**. Both factors, always. | `mastery/model.py::compute_mastery` | Accuracy alone is scale-invariant under time decay | "Fading" never fades; a year-old perfect record reads as mastered |
| I-mastery-02 | `HALF_LIFE_DAYS` (21) and `RECENCY_HALF_LIFE_DAYS` (45) are **different constants** measuring different things. | `mastery/model.py` | One is how fast evidence ages, the other how fast knowledge fades | Sharing 21 made a perfect record read "fragile" three weeks after the lesson |
| I-mastery-03 | **Never-assessed is a band**, not a score of zero. | `model.band_for(has_attempts=False)`, `MasteryBand.NONE` | A blank matrix is not a failing class | Every new class reads as catastrophic |
| I-mastery-04 | Recency **never drives the score to zero** — `RECENCY_FLOOR = 0.55`. | `model.compute_recency` | Stale evidence is stale, not void | A once-mastered competency reads as "never seen" |
| I-mastery-05 | The model is **pure**: no clock, no session, no ORM row inside `mastery/model.py`. `now` is always passed in. | `mastery/model.py` (imports: math, datetime, enums) | Testability, and reproducible recomputation at a past date | The model becomes untestable and time-dependent |
| I-mastery-06 | A **provisional** band is flagged when `effective_n < MIN_EVIDENCE` (1.5). | `model.compute_mastery`, surfaced in the matrix | One lucky MCQ is not mastery | A guess presented to a teacher as a finding |
| I-mastery-07 | Snapshots are **one row per (student, competency, day)**; a second recompute the same day updates it. | `services/mastery_service.py::recompute_for_students` | Four scans in one afternoon is one point on the curve, not four | The profile curve becomes unreadable |
| I-mastery-08 | Only **confirmed** attempts count, and mastery **ignores the barème**. | `scan_service.confirm_scan` → `recompute_for_students`; `AttemptInput(correct, answered_at, difficulty)` | A teacher's weighting of a test must not move a child's bands | Re-weighting a test silently rewrites a term's mastery |
| I-mastery-09 | A rolled-up band (Theme, Competence, Branch) is the **evidence-weighted mean** of its children's scores; a never-assessed child weighs nothing. | `mastery/model.py::roll_up_mastery` | A parent must not be dragged down by a competency nobody examined, nor pulled up by one lucky guess | A Theme reads "fragile" because two of its competencies were never taught yet |
| I-mastery-10 | Attempts are **never pooled across competencies**; only results are combined. | `mastery_service::pool_by_competency` (students only) + `roll_up_mastery` | One recency derived from a mixture launders staleness, in the model whose purpose is fading | A competency last practised in June reads as fresh because a sibling was drilled last week |
| I-mastery-11 | A **sheet-level band is a roll-up of per-competency results**, never a mean of item correctness — and every competency the sheet covers is a child, including the ones it got no evidence for. | `services/mastery_service.py::sheet_mastery`, `sheet_mastery_overall` | I-mastery-10 at a new altitude: a mean over items derives one recency from a mixture. The unassessed children are what make the coverage honest | A sheet reads "acquis" on the strength of the two competencies it happened to examine, out of five |
| I-mastery-12 | **The branch curve is a cache; every read recomputes.** `mastery_branch_snapshot` is written only by `recompute_for_students` and stores its own coverage. No read path answers a band from it. | `services/mastery_service.py::_write_branch_snapshots`; proved by `test_no_read_path_answers_a_band_from_the_cache` | The score decays, so a stored number is wrong the next morning — but history is the one thing recomputation cannot give you | A matrix opened on Friday showing Monday's numbers |

---

## 3 · Module map

| Path | Owns | Depends on |
|---|---|---|
| `alppy/mastery/model.py` | Every constant, `decay`, `compute_accuracy`, `compute_recency`, `band_for`, `days_until_review`, `compute_mastery` | `math`, `datetime`, `models.enums` — nothing else |
| `alppy/services/mastery_service.py` | `load_attempt_inputs`, `recompute_for_students`, `class_matrix`, `student_profile`, `competency_attempts` (the drill-down), `band_summary`, `sheet_mastery` / `sheet_mastery_overall` (the sheet altitude), `mastery_out` / `weakest_assessed_band` (the shared roll-up serialiser the tree also uses) | `mastery.model`, `models` |
| `alppy/api/v1/mastery.py` | `GET /classes/{id}/mastery`, `GET /students/{id}/mastery`, the cell drill-down | `mastery_service` |
| `apps/web/src/components/CellDrillDown.tsx` | The attempts behind one cell, with provenance back to the sheet and the scan | `packages/shared` |
| `packages/ui` `--c-mastery-*` + `mastery/` glyphs | The five bands on screen and on paper: colour **and** label **and** tint density **and** a glyph | brand assets |

---

## 4 · How to extend this feature

Constants are tuned, not guessed: [`docs/mastery-model.md`](../../mastery-model.md)
carries the worked examples each one was set against. Changing one without re-running
those examples is how the 21/45 conflation (I-mastery-02) happened the first time.

`days_until_review` powers the caption a teacher actually reads ("62 % · revision dans
2 jours"). It returns `0` when already due — including an accuracy of zero, the most
urgent case there is — and `None` **only** when the competency has never been
assessed. A zero accuracy returning `None` sent the worst cells in the matrix to a
neutral caption; that is a bug class, not a detail.

### LLM checklist

- [ ] Read §2 — these are not suggestions
- [ ] Did a constant move? Then `docs/mastery-model.md` and its worked examples move too
- [ ] Does anything inside `mastery/model.py` now touch a database or `datetime.now()`? (I-mastery-05 — never)
- [ ] Does a change make `NONE` indistinguishable from a low score? (I-mastery-03)
- [ ] Does points/barème arithmetic leak into `AttemptInput`? (I-mastery-08 — never)

---

## 5 · Privacy & safety

| Data | Where it is stopped | Why |
|---|---|---|
| Student name | Never leaves for a model; targeting hands `adaptive` a UID | `I-ai-01` |
| The matrix itself | Tenant- and teacher-scoped (`owned_class_ids`) | A colleague's class is not visible |

**The pedagogical safety rule.** A band is a claim about a child, shown to a teacher
who will act on it. `provisional` (I-mastery-06) and `NONE` (I-mastery-03) are the two
mechanisms that let the model say "not enough evidence" instead of making one up.

**Never colour alone.** Every band carries a colour *and* a text label *and* a
differing tint density, plus a distinct glyph and underline on paper. The photocopier
is black and white, and roughly one boy in twelve is colour-blind — see
[`../design-system/`](../design-system/).

---

## 6 · Testing strategy

| Invariant | Proved by |
|---|---|
| I-mastery-01 | `test_mastery.py::test_mastery_fades_without_practice`, `::test_fresh_perfect_run_is_solid` |
| I-mastery-02 | `test_mastery.py::test_retention_half_life_is_longer_than_the_evidence_half_life`, `::test_a_perfect_record_walks_the_bands_the_way_the_names_describe`, `::test_evidence_ageing_is_unaffected_by_the_retention_constant` |
| I-mastery-03 | `test_mastery.py::test_never_assessed_is_a_band_not_a_zero`, `::test_empty_history_is_the_none_band`, `test_api_mastery.py::test_profile_of_a_student_with_no_attempts_is_empty_not_an_error` |
| I-mastery-04 | `test_mastery.py::test_recency_never_falls_below_the_floor`, `::test_the_recency_floor_never_holds_a_score_above_the_threshold` |
| I-mastery-05 | `test_mastery.py` runs with no database at all; `::test_future_timestamps_cannot_inflate_weight` |
| I-mastery-06 | `test_mastery.py::test_a_single_answer_is_flagged_provisional`, `::test_enough_evidence_clears_the_provisional_flag` |
| I-mastery-07 | `test_api_mastery.py::test_recompute_is_idempotent_within_a_day`, `::test_a_later_day_appends_a_point_rather_than_overwriting` |
| I-mastery-09 | `test_mastery.py::test_a_roll_up_weights_by_evidence_not_by_child_count`, `::test_a_never_assessed_child_does_not_drag_a_roll_up_down`, `test_api_tree.py::test_a_theme_reports_the_coverage_behind_its_band` |
| I-mastery-10 | `test_mastery.py::test_a_roll_up_score_is_not_accuracy_times_recency`, `test_api_tree.py::test_student_id_narrows_the_tree_to_one_child` |
| I-mastery-11 | `test_api_sheets.py::test_a_sheet_reports_a_band_per_student_and_one_for_the_class`, `::test_a_sheet_band_ignores_the_bareme` |
| I-mastery-08 | `test_api_mastery.py::test_a_recompute_only_sees_the_evidence_that_existed_at_the_time`, `test_scan_processing.py::test_mastery_is_untouched_by_the_bar` |

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_mastery.py \
  apps/api/tests/test_api_mastery.py -q
```

`test_mastery.py` is 31 tests over pure functions and runs in well under a second.
That is the return on I-mastery-05, and it is why the model can be changed with
confidence at all.

---

## Companion documents

- [`architecture.md`](architecture.md) — the two factors, the snapshot table, the drill-down
- [`decisions.md`](decisions.md) — D4, D15, D32, and the 21/45 correction
- [`../../mastery-model.md`](../../mastery-model.md) — the authority on the constants
- [`../adaptive/`](../adaptive/) — the consumer that turns bands into the next sheet

**Last updated:** 2026-09-09
