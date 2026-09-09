# Adaptive

**Status:** describes `main` as of 2026-09-09
**Audience:** developers, LLM agents, reviewers

---

## 1 · What it does

The adaptive sheet is the focal deliverable of the product: **one PDF for a whole
class in which each child gets the work they actually need.** Everything upstream
exists to make it possible and trustworthy.

For each student the service reads the latest `MasterySnapshot` per competency, picks
the weakest ones, fills the sheet from **indexed textbook exercises first**, and calls
a model only for what retrieval could not supply. Every generated item arrives with
`approved_at = None` and cannot be printed until a teacher reads it.

```
  MasterySnapshot[]  ──▶ latest_snapshots ──▶ pick_gaps  (weakest first, SOLID as stretch)
                                                  │  target_difficulty(score, band)
                                                  ▼
                                        retrieval.gather_candidates
                                                  │  textbook exercises: vetted, in the
                                                  │  right language, free, page-citable
                                                  ▼
                                     shortfall? ──▶ _generate (generate_exercises.v1)
                                                  │   origin=AI_GENERATED, approved_at=NULL
                                                  ▼
                          POST /adaptive/propose  →  the teacher reads, approves, discards,
                                                     regenerates, moves a student
                                                  ▼
                          POST /adaptive/batch → Job → ONE PDF, one .print-page per page
```

Three targeting modes, one planner:

| Mode | `n_groups` | What it is |
|---|---|---|
| Class | 1 | Today's single shared sheet: the union of the class's gaps |
| Groups | 2..N | N partitions by principal gap (D33) |
| Per student | ≥ class size | One plan per child |

### Key properties

1. **Retrieval first, generation as the remainder.** A textbook exercise is already
   pedagogically vetted, in the class's language, tied to a page the teacher can open,
   and free. A generated one is none of those until a teacher reads it.
2. **The gap targeting is defensible in a staffroom.** Weakest band first; a *fading*
   competency is practised one level below, a *fragile* one at level, a *solid* one
   one level above, as stretch.
3. **No group entity is persisted.** The partition is recomputed from mastery each
   time, because a stored group is stale the moment the next scan lands.

---

## 2 · Invariants (load-bearing)

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-adaptive-01 | **Retrieval before generation.** A model is called only for the shortfall. | `services/adaptive_service.py::_plan_for_student`, `_plan_for_group` | Textbook items are vetted, cited, in-language and free | Cost, and unvetted content where a book would have done |
| I-adaptive-02 | **`SOLID` is a stretch target at lowest priority**, practised one level *above*; `MAX_STRETCH_COMPETENCIES = 1`, lifted only for a student with no gaps at all. | `pick_gaps`, `target_difficulty` | Skipping it sent a fully-mastered child to the difficulty-2 diagnostic | The strongest child in the room gets the easiest sheet |
| I-adaptive-03 | Every generated exercise is created **`approved_at = NULL`** and is reported in its own `generated` list. | `_build_generated_exercise`, `_generated_proposal` | The teacher must read model output before a child does | Unreviewed AI on paper |
| I-adaptive-04 | The **print path refuses unapproved items**, at both doors. | `services/approval.py::ensure_printable` ← `sheet_service.create_adaptive_sheet` **and** `render.render_adaptive_batch` | A sheet built before the gate, or un-approved afterwards, must not slip through | The one state that must never be printed, printed |
| I-adaptive-05 | The gate **raises, never filters**. | `services/approval.py` | A sheet quietly missing 3 of its 12 items is worse at a photocopier than an error naming them | A teacher prints a sheet with holes in it |
| I-adaptive-06 | The **language of a generated exercise follows the source material**, never the teacher's UI locale. | `source_language`, `_build_generated_exercise` | `Exercise.language` chooses the printed true/false glyphs (V/F · R/F · T/F), and the detector reads bubbles by position | The wrong letters printed next to the right holes |
| I-adaptive-07 | A student's **name never reaches a provider**: the prompt gets `to_ref(uid)` and the gate is armed with the roster. | `_generate`, `ai.scrub` | `I-ai-01` | A roster in a third-party log |
| I-adaptive-08 | A **schema-invalid generated item is dropped, not repaired** — and does not poison the valid items beside it. | `GeneratedExerciseIn` | An MCQ claiming five options has no fifth bubble to fill | An item that prints but cannot be graded |
| I-adaptive-09 | A **generation failure shortens the sheet honestly** and is reported; it never silently substitutes. | `_failure`, `_first_error`, `AdaptiveGenerationError` | The teacher must know what they are printing | A short sheet with no explanation |
| I-adaptive-10 | The **partition is recomputed, never stored**; what survives is `SheetInstance.group_label` and `Sheet.target = GROUP`. A student moved between groups takes the receiving group's **items** as well as its label. | `cluster_students`, `_plan_for_groups` | A stored group is stale after the next scan | A sheet headed "Groupe 3" holding group 1's exercises |

---

## 3 · Module map

| Path | Owns | Depends on |
|---|---|---|
| `alppy/services/adaptive_service.py` | `latest_snapshots`, `pick_gaps`, `target_difficulty`, `_plan_for_student`, `_plan_for_group`, `cluster_students`, `_generate`, `regenerate_exercise`, `source_language` | `mastery`, `retrieval`, `ai`, `models` |
| `alppy/services/approval.py` | `is_printable`, `ensure_printable`, `approve_exercises`, `discard_exercises` (+ the feedback equivalents). **Deliberately its own module** | `models` only |
| `alppy/sheets/render.py::render_adaptive_batch` | One PDF for the whole class, one `.print-page` per physical page | `sheets.html`, `approval` |
| `alppy/services/sheet_service.py::create_adaptive_sheet` | Turning a proposal into a `Sheet` + per-student `SheetInstance` | `approval`, `models` |
| `alppy/ai/prompts/generate_exercises.v1.md` | The generation prompt | — |
| `alppy/api/v1/adaptive.py` | `POST /adaptive/propose`, `POST /adaptive/batch`, approve / discard / regenerate | `adaptive_service`, `deps.load_optional` |
| `apps/web/src/app/[locale]/adaptive/`, `components/AdaptiveItem.tsx` | Gap targeting UI, accent-marked AI items, batch export | `packages/shared` |

**Why `approval.py` is its own module.** The routers treat adaptive planning as an
optional workstream loaded through `deps.load_optional`. The *gate* must never be
optional: the render path has to import it with no chance of an `ImportError` turning
the rule off. It therefore depends on nothing but the model.

---

## 4 · How to extend this feature

**Changing targeting.** `pick_gaps` and `target_difficulty` are pure functions over
snapshots. Change them there, not in the planner, and re-read D32 first — the last
change to this logic inverted the zone of proximal development for the strongest
students in a class.

**Changing generation.** The prompt is a versioned file. A new response field goes
through `GeneratedExerciseIn`, which validates against what can actually be *printed
and graded* — an MCQ can never claim more options than the grid draws.

### LLM checklist

- [ ] Read §2 — these are not suggestions
- [ ] Does a model get called before retrieval is exhausted? (I-adaptive-01)
- [ ] Is any generated row created approved, or approved by anything but a teacher? (I-adaptive-03)
- [ ] Does any new print path skip `ensure_printable`? (I-adaptive-04 — never)
- [ ] Does the language come from the corpus or from the UI locale? (I-adaptive-06)
- [ ] Does a bad item get repaired instead of dropped? (I-adaptive-08)
- [ ] Is a group being persisted? (I-adaptive-10 — no)

---

## 5 · Privacy & safety

| Data | Scrubbing point | Why |
|---|---|---|
| Student name | `to_ref(student.uid)` in the prompt; `student_names=roster` arms `assert_no_pii` | I-ai-01, I-ai-02 |
| Textbook style examples | `scrub`-ed on the way in | Swiss textbook prose is full of Léa, Noah and Emma — who are also in the class |
| Generation metadata | Records the UID, never the name | `test_generation_meta_records_the_uid_never_the_name` |

**The pedagogical safety rule:** `approved_at` is the boundary between "a model
suggested this" and "a teacher stands behind this". Nothing in this subsystem may
cross it on the model's behalf.

---

## 6 · Testing strategy

| Invariant | Proved by |
|---|---|
| I-adaptive-01 | `test_adaptive.py::test_retrieval_fills_the_sheet_and_the_model_is_never_called`, `::test_generation_only_covers_the_shortfall` |
| I-adaptive-02 | `test_adaptive.py::test_weakest_bands_come_first_and_solid_trails_as_stretch`, `::test_a_fully_mastered_student_gets_stretch_not_the_easy_diagnostic`, `::test_stretch_never_crowds_out_real_gap_work`, `::test_a_fading_competency_is_practised_one_level_below_a_fragile_one` |
| I-adaptive-03 | `test_adaptive.py::test_generated_items_are_persisted_unapproved_and_marked`, `::test_a_textbook_sheet_never_offers_the_unapproved_generated_items` |
| I-adaptive-04 | `test_adaptive_fixes.py::test_a_batch_cannot_be_built_out_of_unapproved_items`, `::test_the_render_path_refuses_an_unapproved_item`, `test_adaptive.py::test_generated_items_cannot_be_printed_without_approval` |
| I-adaptive-05 | `test_adaptive.py::test_ensure_printable_accepts_approved_and_textbook_items`, `test_adaptive_fixes.py::test_approval_from_another_school_does_nothing` |
| I-adaptive-06 | `test_adaptive_fixes.py::test_the_sheet_language_is_read_off_the_corpus_not_the_teacher_locale`, `::test_source_language_prefers_the_modal_textbook_language`, `::test_an_empty_corpus_falls_back_to_the_teachers_locale` |
| I-adaptive-07 | `test_adaptive.py::test_no_roster_name_appears_in_a_generation_prompt`, `::test_the_armed_gate_would_actually_fire` |
| I-adaptive-08 | `test_adaptive_fixes.py::test_the_schema_rejects_items_that_could_not_be_printed_or_graded`, `::test_a_bad_item_does_not_poison_the_good_ones_beside_it`, `::test_more_options_than_bubbles_never_becomes_a_row` |
| I-adaptive-09 | `test_adaptive.py::test_generation_failure_degrades_to_a_shorter_sheet`, `test_adaptive_fixes.py::test_a_provider_failure_is_reported_rather_than_silently_shortening_a_sheet`, `::test_one_students_failure_does_not_cost_the_rest_of_the_batch` |
| I-adaptive-10 | `test_grouping.py` (whole file — 9 tests), `test_adaptive_fixes.py::test_a_group_sheet_targets_the_union_and_says_who_each_item_is_for` |

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_adaptive.py \
  apps/api/tests/test_adaptive_fixes.py apps/api/tests/test_grouping.py \
  apps/api/tests/test_api_adaptive.py -q
```

---

## Companion documents

- [`architecture.md`](architecture.md) — targeting, planning, grouping, generation
- [`decisions.md`](decisions.md) — D32, D33, and the approval gate
- [`../mastery/`](../mastery/) — where the gaps come from
- [`../feedback/`](../feedback/) — the other half of a corrected common sheet

**Last updated:** 2026-09-09
