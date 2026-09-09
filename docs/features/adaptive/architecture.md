# Adaptive Architecture

## Component diagram

```
  POST /adaptive/propose  {class | students, subject, n_groups, source_sheet, generate?}
        │  202 → Job(PROPOSE_ADAPTIVE)      ← nothing blocks a handler on a model call
        ▼
  worker/tasks.py::propose_adaptive  (commit=False: the task owns the transaction)
        │
        ▼
  services/adaptive_service.py::propose_adaptive
        │
        ├─ sheet_performance(source_sheet)  the sheet the teacher just corrected, and
        │                                   what it could NOT attribute
        ├─ latest_snapshots(students)       the fallback: LATEST snapshot per competency
        │  └─ gaps_for_student picks between them, and says which it used
        │
        ├─ n_groups == 1 ─────▶ _plan_for_group(whole class)
        ├─ 1 < n < size  ─────▶ cluster_students ──▶ [llm_grouping? revise + validate,
        │                       │                     falling back to this partition]
        │                       └─▶ _plan_for_groups → _plan_for_group ×N
        └─ n >= size     ─────▶ _plan_for_student ×N
                    │
                    ▼   for each plan:
        pick_gaps(snapshots, limit=MAX_TARGET_COMPETENCIES,
                             max_stretch=MAX_STRETCH_COMPETENCIES)
                    │        band priority: fading → weak → ok → solid(stretch)
                    ▼
        target_difficulty(score, band)      fading −1 · weak/ok at level · solid +1
                    │
                    ▼
        retrieval.gather_candidates(competencies, difficulty, language)
                    │
                    ├─ enough?  → done, zero model calls          (I-adaptive-01)
                    └─ short?   → collector.register(ask)  ← deferred, not sent yet
                    ▼
        ONE pass over every ask: generate_for_asks, 8 plans to a call
                    │  per-plan failure → that plan alone comes up short
                    │  whole-call failure → retry ONCE, split into single-plan calls
                    ▼
                                  _generate(shortfall)
                                    ├─ scrub(style examples)
                                    ├─ ai.complete(generate_exercises.v1,
                                    │              student=to_ref(uid),
                                    │              student_names=roster)
                                    ├─ GeneratedExerciseIn validation, per item
                                    └─ Exercise(origin=AI_GENERATED, approved_at=None)
                    ▼
        AdaptiveProposal { retrieved: [...], generated: [...] }   ← two lists, always
                    ▼
        the teacher: approve · discard · regenerate · move a student between groups
                    ▼
        AdaptiveProposal row ──▶ GET /adaptive/proposal/{job_id}
                    │   (its own row: the screen polls the job every 900 ms, and
                    │    a class of 24 is close to a megabyte of statements)
                    ▼
  POST /adaptive/batch → Job(GENERATE_ADAPTIVE)   ← renders; generates nothing
        │
        ├─ sheet_service.create_adaptive_sheet ── ensure_printable()   ← door 1
        └─ render.render_adaptive_batch ───────── _refuse_unapproved() ← door 2
                    ▼
        ONE PDF: one .print-page per physical page, each with its own UID
```

## Data flow

### Targeting

```python
@dataclass(frozen=True)
class Gap:
    competency_id: UUID
    band: MasteryBand
    score: float
    target_difficulty: int   # 1..5
```

`pick_gaps` sorts by `(BAND_PRIORITY[band], score)`, takes real gaps up to `limit`,
then admits at most `max_stretch` SOLID entries **with whatever room is left**. A
student with four fading competencies gets four of those and no stretch at all.

The exception is the student with nothing but solid competencies: there is no gap work
to protect, so the cap lifts and the whole sheet is stretch.

```python
def target_difficulty(score, band) -> int:
    level = 1 + floor(3.0 * clamp(score) + 0.5)   # 1..4, monotone in the score
    if band is FADING: level -= 1                 # rebuild confidence first
    elif band is SOLID: level += 1                # stretch is the next thing UP
    return clamp(level, 1, 5)
```

Level 5 is reachable **only** through the SOLID branch. That is the shape of the rule:
a fading competency's evidence is stale, so the first item should rebuild rather than
test; a fragile one is practised at level, where the struggle actually is.

### Grouping

`cluster_students` is a partition placed **above** a planner that already worked.
`_plan_for_group` was always parameterised over an arbitrary `Sequence[Student]` — it
ranks the union of a group's gaps by how many members need each competency — and
nothing in it assumed "the whole class".

The rule, stated the way a teacher has to be able to defend it:

> **Students with the same principal gap go together. If that gives more groups than
> you asked for, the smallest merge. If fewer, the largest splits by severity.**

Both older modes fall out of it unchanged: `n_groups == 1` is the single shared sheet,
`n_groups >= class size` is the per-student path. The neediest group comes first, and
the partition is **stable across runs**.

### Generation

```python
class GeneratedExerciseIn(BaseModel):
    type: ExerciseType
    statement: str
    options: list[str]        # ≤ MAX_OPTIONS — the grid draws no more bubbles
    answer_index: int | None
    answer_bool: bool | None
    difficulty: int           # clamped 1..5
    language: str             # from the corpus, not the UI locale
```

Validation is per item: a malformed item is **dropped**, and the good items beside it
survive. Anything that could not be printed *and graded* is not an item.

## Component interaction

### The approval gate — two doors, one module

| Door | Where | Why both |
|---|---|---|
| Build | `sheet_service.create_adaptive_sheet` | The teacher finds out at the moment of the mistake |
| Render | `render.render_adaptive_batch`, `render_sheet_pdfs` | A sheet built before the gate existed, or un-approved *after* it was built, must not slip through on a re-render |

`ensure_printable` raises `UnapprovedExerciseError` **carrying the offending ids**, so
the caller can name them rather than saying "something is wrong".

### Regeneration and discard

- `regenerate_exercise` replaces one item with a fresh generation, linked to the one it
  came from. A failed regeneration leaves the original alone.
- `discard_exercises` makes an item un-proposable **permanently** — it is not offered
  again, and it is not retrievable even if someone approves it later.
- Regenerating something that is not generated is refused.

## Edge cases

- **A source sheet with no confirmed results for a student.** → that student falls back
  to their mastery snapshots, then to the diagnostic. Nobody gets an empty plan.
- **A source sheet read only in part.** → the plan still stands, and says so:
  `evidence_partial` reaches the screen. Three of twelve items presented as "how they
  did on this sheet" is the same class of error as a short sheet with no explanation.
- **Items no competency could be attributed to.** → counted, not ignored. The attempt
  join is an inner join, so a child who got everything wrong on untagged items would
  otherwise produce an empty summary and read as fine.
- **A model partition that is not a partition.** → rejected whole, and the deterministic
  one is used. Never repaired.
- **A batched call that comes back truncated.** → its own failure reason, and the chunk
  is split and retried. `unparsable_response` would have blamed the model for a
  configured limit.
- **A student with no mastery data at all.** → a diagnostic set at
  `FALLBACK_DIFFICULTY = 2`. This branch used to also catch fully-mastered students,
  which is the bug D32 fixed.
- **A student with every competency solid.** → stretch fills the sheet (I-adaptive-02).
- **Generation switched off.** → the sheet is what retrieval could supply, reported as
  such.
- **The provider fails for one student.** → that student's sheet is shorter and the
  failure is reported; the rest of the batch is unaffected.
- **An unparsable response.** → reported, and **nothing is written**.
- **An incomplete response.** → reports how short it came, rather than padding.
- **An empty corpus for the subject.** → the language falls back to the teacher's
  locale — the last resort, not the default (I-adaptive-06).
- **A group of one.** → works, and is the per-student path by another name.
- **A move between groups.** → the student takes the receiving group's *items* as well
  as its label. A sheet headed "Groupe 3" holding group 1's exercises is the one
  outcome a move must never produce.
- **Approval from another school.** → does nothing. The gate is tenant-scoped.

---

**Companion:** [`README.md`](README.md) §2 for the load-bearing rules.
