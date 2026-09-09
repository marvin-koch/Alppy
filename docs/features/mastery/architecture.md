# Mastery Architecture

## Component diagram

```
  Attempt (student × exercise × sheet_instance, correct, answered_at)
      │        written only by scan_service.confirm_scan
      ▼
  services/mastery_service.py::load_attempt_inputs
      │   joins Attempt → Exercise → exercise_competency
      │   yields AttemptInput(correct, answered_at, difficulty)   ← no ORM beyond here
      ▼
  mastery/model.py::compute_mastery(attempts, now)
      │
      ├── compute_accuracy  → (accuracy, effective_n)
      ├── compute_recency   → recency
      ├── band_for(score)   → MasteryBand
      └── days_until_review(accuracy, last, now)
      ▼
  MasteryResult
      ▼
  recompute_for_students  →  MasterySnapshot (student, competency, computed_at::date)
      │                        upsert per DAY (I-mastery-07)
      ├──▶ class_matrix()      students × competencies, band + score + provisional
      ├──▶ student_profile()   strengths, gaps, history curve, sheets taken
      ├──▶ competency_attempts()  the drill-down: which attempts, which sheet, which scan
      └──▶ adaptive_service.latest_snapshots()  → gap targeting
```

## Data flow

### Input — deliberately not a database row

```python
@dataclass(frozen=True, slots=True)
class AttemptInput:
    correct: bool
    answered_at: datetime
    difficulty: int = 3      # 1..5, clamped
```

Three fields. Note what is *not* here: the score, the points, the exercise type, the
student. The model grades knowledge, not marks (I-mastery-08).

### Output

```python
@dataclass(frozen=True, slots=True)
class MasteryResult:
    score: float             # accuracy × recency, clamped to [0,1]
    band: MasteryBand        # SOLID | OK | WEAK | FADING | NONE
    accuracy: float          # the first factor, kept for the explanation
    recency: float           # the second factor, kept for the explanation
    attempts_count: int
    effective_n: float       # sum of weights, in units of a fresh difficulty-3 attempt
    provisional: bool        # effective_n < MIN_EVIDENCE
    last_attempt_at: datetime | None
    days_until_review: int | None
```

`accuracy` and `recency` survive into the result on purpose: the teacher-facing
explanation ("solid, but you last practised this in March") needs both, and a single
score cannot produce it.

## Component interaction

### The two factors, and why they are different constants

| Constant | Value | What it measures |
|---|---|---|
| `HALF_LIFE_DAYS` | 21 | How fast **evidence ages relative to newer evidence** — roughly the span over which a class moves through a chapter |
| `RECENCY_HALF_LIFE_DAYS` | 45 | How fast **knowledge fades** when it is not refreshed |
| `RECENCY_GRACE_DAYS` | 7 | No decay in the first week. Practising on Monday must not make Friday's matrix look worse |
| `RECENCY_FLOOR` | 0.55 | Stale evidence is stale, not void |
| `MIN_EVIDENCE` | 1.5 | Below this effective sample size, the band is provisional |

The two half-lives were briefly the same value. At 21 days, a student with a perfect
record read as "fragile" three weeks after the lesson — and three weeks is a normal
gap between a chapter and its revision. At 45, a perfect record walks the bands the
way the band names describe: solid for about two weeks, to-review by three, fragile by
five, fading by nine. `test_a_perfect_record_walks_the_bands_the_way_the_names_describe`
pins exactly that.

### `difficulty_weight`

`{1: 0.8, 2: 0.9, 3: 1.0, 4: 1.2, 5: 1.4}`. A correct answer on a hard item is
stronger evidence; a wrong answer on an easy one is worse news. Clamped at both ends,
so a malformed difficulty cannot inflate a weight.

### `days_until_review`

Walks forward day by day (up to `REVIEW_HORIZON_DAYS = 366`) until the projected score
drops below `BAND_OK`. Returns `0` when already due, `None` **only** when never
assessed. With the shipped constants the maximum possible product of accuracy and the
recency floor is `1.0 × 0.55 = 0.55`, comfortably under `0.75` — so every competency
eventually comes due, and a test pins that so a future constant change cannot quietly
create a competency that is never due again.

### `recompute_for_students`

Loads attempts, groups by `(student, competency)`, computes, and upserts one snapshot
per day. Called synchronously from `confirm_scan` — it is cheap arithmetic over rows
already in the session, not a model call, so it does not belong in the worker.

## Edge cases

- **No attempts at all.** → `MasteryBand.NONE`, `provisional=True`,
  `days_until_review=None`. Not a zero score presented as a finding.
- **One attempt.** → a real band, flagged `provisional`. The UI marks the cell.
- **A future timestamp** (clock skew). → `_age_days` floors at 0, so a weight can never
  exceed a fresh attempt's.
- **All answers wrong.** → accuracy 0, `days_until_review = 0` ("due now"), the most
  urgent cell in the matrix rather than a neutral caption.
- **Four scans confirmed in one afternoon.** → one snapshot row, one point on the
  curve (I-mastery-07).
- **An exercise tagged with no competency.** → contributes to no cell. It is invisible
  to the matrix, which is why `corpus` cares so much about tagging.
- **A recompute run later, over old attempts.** → the same numbers, because `now` is a
  parameter and the model has no clock (I-mastery-05).

---

**Companion:** [`README.md`](README.md) §2 for the load-bearing rules.
