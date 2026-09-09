# Mastery Decisions Log

D-numbers follow the repo-wide [`docs/decisions-log.md`](../../decisions-log.md).
[`docs/mastery-model.md`](../../mastery-model.md) is the authority on the constants.

---

## D4 · Mastery = accuracy × recency, two factors

**Date:** M4 · **Affected invariants:** I-mastery-01, I-mastery-04

**Background.** The MVP needs a score a teacher can act on and we can explain in one
sentence.

**Considered alternatives**
- A) *Bayesian knowledge tracing.* Rejected for the MVP: four latent parameters per
  skill, no cohort data to fit them against, and no sentence that explains a cell to
  a teacher.
- B) *Weighted recent accuracy alone.* Rejected — and this is the interesting one.
  Weighted accuracy is **scale-invariant under uniform time decay**: multiply every
  weight by the same factor and the ratio is unchanged. So a student who was perfect a
  year ago still reads 100 %, and the "fading" band never fades. The bug is not a
  tuning problem; it is structural.
- C) **accuracy × recency.** Chosen.

**Tradeoff**
- ✅ Explainable in one line, cheap to recompute, testable as a pure function
- ✅ The band names mean what they say over time
- ❌ Two constants to tune instead of one, and they are easy to conflate (see below)

**Revisit** once there is real cohort data to calibrate against.

---

## The 21/45 correction · the two half-lives are not the same constant

**Date:** M4, shortly after D4 · **Affected invariant:** I-mastery-02

The two half-lives were briefly one value. They measure different things:

- `HALF_LIFE_DAYS = 21` — how fast **evidence ages relative to newer evidence**.
- `RECENCY_HALF_LIFE_DAYS = 45` — how fast **knowledge fades** without practice.

Sharing 21 made a student with a perfect record read as *fragile* three weeks after
the lesson, which is far too harsh: three weeks is a normal gap between a chapter and
its revision. At 45 the walk down the bands matches the band names, and
`test_a_perfect_record_walks_the_bands_the_way_the_names_describe` holds it there.

Recorded as its own entry because it is the exact mistake a future simplification
("why do we have two constants that look the same?") would reintroduce.

---

## D15 · `--c-mastery-*` maps onto the state families

**Date:** M0 · **Affected invariant:** I-design-04 (see `design-system/`)

The five bands are not five arbitrary colours: they map onto the design system's state
families, and each band ships a `-glyph` colour at a **constant luminance of 0.46**
with a *computed* background opacity, so the ramp stays monotonic in greyscale.

That calibration is the whole point — the sheets get photocopied. Do not re-derive
these by eye. Band glyphs are disc 4/4, 3/4, 2/4, 1/4 and a dashed ring: the third
channel after colour and label.

---

## D32 · `SOLID` is a stretch target, because skipping it inverted the ZPD

**Date:** 2026-09 · **Affected invariant:** I-adaptive-02 (see `adaptive/`)

Targeting reads the bands weakest-first. The first version skipped `SOLID` entirely as
"nothing to work on" — so a student who had mastered everything fell through to the
default: the difficulty-2 diagnostic set. Easier work than they could already do, for
the strongest child in the room.

`SOLID` is now a **stretch** target at lowest priority: one per sheet, and the whole
sheet for a student who has nothing else. Recorded here as well as in `adaptive/`
because the bug was in how the *bands* were read, not in how the sheet was built.

---

## Why mastery ignores the barème

**Date:** 2026-09 · **Affected invariant:** I-mastery-08

A teacher's barème says what a question is *worth on this test*. Mastery says what a
child *knows*. `AttemptInput` carries `correct`, `answered_at` and `difficulty` — and
deliberately not `score`.

If it carried points, a teacher who re-weighted a test would silently rewrite that
class's mastery history, and two teachers with different marking traditions would
produce incomparable matrices. Difficulty already expresses "this was a harder
question", which is the part mastery genuinely needs.

---

## When policy changes

```json
{
  "change": "RECENCY_FLOOR 0.55 -> 0.30",
  "reason": "old competencies should decay further",
  "date": "YYYY-MM-DD",
  "decision": "requires re-running the worked examples in docs/mastery-model.md",
  "watch": "test_the_recency_floor_never_holds_a_score_above_the_threshold, and
            whether a once-mastered competency now reads as 'never seen' (I-mastery-04)"
}
```


## 2026-09-09 · Rolling mastery up above a competency

**Affected invariants:** I-mastery-09, I-mastery-10 (new). I-mastery-01 is now
explicitly leaf-only.
**Repo decision:** D58.

**Background.** `(student, competency)` was the only grain the model computed, and
§6 of `docs/mastery-model.md` said so plainly. The `Class → Branch → Competence →
Theme` navigation needs a band at every level, so aggregation is new work rather
than something already computed and merely unexposed.

**Considered alternatives.**

*Pool the raw attempts of a Theme and call `compute_mastery` once.* Simplest, and
wrong: one recency would be derived from the mixture, so a competency practised
last week launders the staleness of one last touched in June. Rejected on the
model's own terms — fading is the point of `RECENCY_HALF_LIFE_DAYS`.

*Worst-band-wins.* With three or four competencies per chapter every Theme would
read amber or red permanently — a constant, not a signal. `_weakest_first` sorts
students for triage; it does not claim a group equals its minimum.

*Plain mean.* Would let one lucky guess weigh as much as twenty confirmed
attempts, reintroducing exactly what `effective_n` and `MIN_EVIDENCE` prevent a
level down.

**Tradeoff.** The evidence-weighted mean costs two honest breaks, both documented
in `docs/mastery-model.md` §6 rather than hidden: `score == accuracy × recency`
does not hold above a leaf, and `days_until_review` becomes the earliest child's
rather than a re-derivation. In exchange no new tunable constant enters a model
whose every constant is individually justified, and the five bands and their
thresholds are unchanged — so no new colour vocabulary, and DC-colour-08 needs no
re-litigating.

**Revisit** if a Theme's competencies ever need explicit weights (a chapter where
one competency is the point and two are incidental). Today every child is weighted
purely by the evidence behind it.

## D78 · The branch curve is a cache, and a separate table

**Affected invariant:** I-mastery-12 (new)

A Branch-level history needs stored points: the score decays, so yesterday's number cannot be
derived from today's attempts. History is the one question recomputation cannot answer.

**Considered alternatives.** (A) A nullable `competency_id` on `MasterySnapshot`: rejected —
it turns every `(student, competency)` key in `latest_snapshots` into an optional and lets
I-mastery-07's "one row per student, competency, day" silently admit two kinds of row.
(B) Compute the curve on read by replaying attempts at N past dates: correct but O(N) full
recomputes for one chart. **(C) A separate `mastery_branch_snapshot`** — chosen.

**Nothing reads it to answer a band.** Every read path recomputes (`data-model.md` §4), and
`test_no_read_path_answers_a_band_from_the_cache` poisons the cache with a perfect score to
prove the tree ignores it.

It is rolled up with `roll_up_mastery` over the same `MasteryResult`s the tree uses, never by
pooling raw attempts across competencies — that would derive one recency from a mixture
(I-mastery-10). It stores `child_count` and `assessed_child_count` beside the score, because a
band over one assessed competency and one over three are different claims (DC-content-07).

**The branch is resolved through `exercise_competency` → `Exercise.subject_id`, not through
`chapter_competency`.** A competency is assessed by exercises, and an exercise always has a
subject; a Theme crediting it may not exist yet. Resolving through chapters left every curve
empty until somebody filed a Theme — D57's circularity again, and a failing test is what
found it.
