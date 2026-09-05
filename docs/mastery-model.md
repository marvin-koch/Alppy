# The mastery model

The number in a matrix cell decides what a child is asked to do next. A teacher
must be able to understand it, disagree with it, and check it against what they
already know about the student. So the model is deliberately simple, fully
explainable, and written as pure functions in
[`apps/api/alppy/mastery/model.py`](../apps/api/alppy/mastery/model.py).

No Bayesian knowledge tracing in the MVP. BKT would need per-competency
parameters we have no data to fit, and its output is hard to justify to the
person who has to act on it.

---

## 1. The formula

For one student and one competency:

```
score = accuracy × recency          ∈ [0, 1]
```

### accuracy — weighted recent correctness

```
w_i      = 2^(−age_days_i / H) × d(difficulty_i)
accuracy = Σ(w_i · correct_i) / Σ(w_i)
```

where `H = HALF_LIFE_DAYS = 21`, so an attempt from three weeks ago carries half
the weight of one from today, and

| difficulty | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| `d` | 0.8 | 0.9 | 1.0 | 1.2 | 1.4 |

A correct answer on a hard item is stronger evidence than on an easy one, and a
wrong answer on an easy item is worse news.

### recency — how much we still trust that accuracy

```
idle    = days_since_last_attempt − GRACE
recency = 1                               if idle ≤ 0
        = max(FLOOR, 2^(−idle / R))       otherwise
```

with `GRACE = 7` days, `FLOOR = 0.55`, and `R = RECENCY_HALF_LIFE_DAYS = 45`.

**`R` is deliberately not `H`.** The two constants measure different things and
were briefly conflated, which is worth recording because the bug was invisible
in every unit test and only showed up when the demo seed produced a matrix where
nobody was ever "solid":

- `H` (21 days) is how fast an attempt loses weight **relative to a newer
  attempt**. It governs how quickly a turnaround shows.
- `R` (45 days) is how fast knowledge **fades** when nobody practises.

Sharing one value made a student with a perfect record read as *fragile* three
weeks after the lesson — and three weeks is a perfectly normal gap between a
chapter and its revision.

### Why recency has to exist

This is the subtle part, and it is the reason the model is two factors rather
than one.

`accuracy` is **scale-invariant under uniform time decay**. Every weight shrinks
by the same factor as time passes, and the factor cancels in the ratio. A
student who answered five items perfectly and then never touched the competency
again would read as `accuracy = 1.0` a year later, exactly as on the day.

A "Fading — losing it" band that never fades is not a band. `recency` is what
makes the scale ordered *in time* as well as in correctness.

### Why the constants are what they are

| Constant | Value | Reasoning |
|---|---|---|
| `HALF_LIFE_DAYS` | 21 | Evidence ageing. Roughly the span over which a Swiss Sek I class moves through a chapter. Short enough that a turnaround shows within a few lessons; long enough that one bad Monday does not erase a term. |
| `RECENCY_HALF_LIFE_DAYS` | 45 | Retention. Chosen so a perfect record walks the bands the way their names promise (below). |
| `RECENCY_GRACE_DAYS` | 7 | Practising on Monday must not make the matrix look worse on Friday. Without a grace period the dashboard changes under the teacher between two lessons for no pedagogical reason. |
| `RECENCY_FLOOR` | 0.55 | Stale evidence is stale, not void. A once-mastered competency settles into "fading" and stops there, rather than decaying toward "never seen" — which would be a lie, because we did see it. |
| `MIN_EVIDENCE` | 1.5 | Below roughly one and a half fresh attempts, the band is marked **provisional**. One lucky guess on one MCQ is not mastery. |

---

## 2. The bands

Five ordered bands. **Never colour alone** — every rendering carries the colour,
a text label, and a differing tint density; on paper it also carries a distinct
underline style, because the photocopier is black and white.

| Band | Threshold | Token | FR / DE / EN |
|---|---|---|---|
| Solid — mastered | `score ≥ 0.90` | `--c-mastery-solid` | Acquis / Gefestigt / Solid |
| To review — due soon | `0.75 ≤ score < 0.90` | `--c-mastery-ok` | À revoir / Bald fällig / To review |
| Fragile | `0.60 ≤ score < 0.75` | `--c-mastery-weak` | Fragile / Unsicher / Fragile |
| Fading — losing it | `score < 0.60` | `--c-mastery-fading` | S'efface / Verblasst / Fading |
| Not yet seen | no attempts | `--c-mastery-none` | Pas encore vu / Noch nicht gesehen / Not yet seen |

Thresholds are **inclusive at the bottom** of each band: exactly `0.90` is solid.

**"Not yet seen" is a band, not a zero.** A competency nobody has assessed is
not the same thing as one a student fails, and collapsing the two would send a
child remedial work on material they have never been taught.

---

## 3. Worked examples

Produced by the model at `HALF_LIFE_DAYS=21`, `GRACE=7`, `FLOOR=0.55`:

| History | accuracy | recency | score | band | provisional |
|---|---|---|---|---|---|
| 5 correct today | 1.00 | 1.00 | 1.00 | solid | no |
| 4 of 5 correct today | 0.80 | 1.00 | 0.80 | to review | no |
| 5 wrong today | 0.00 | 1.00 | 0.00 | fading | no |
| 2 wrong 40 d ago, 3 correct yesterday | 0.84 | 1.00 | 0.84 | to review | no |
| 2 correct 40 d ago, 3 wrong yesterday | 0.16 | 1.00 | 0.16 | fading | no |
| 5 correct, 21 d ago | 1.00 | 0.81 | 0.81 | to review | no |
| 5 correct, 60 d ago | 1.00 | 0.55 | 0.55 | fading | **yes** |
| 1 correct today | 1.00 | 1.00 | 1.00 | solid | **yes** |
| nothing | — | — | 0.00 | not yet seen | yes |

### The fade schedule

A perfect record, with no further practice. This is the promise the band names
make, and `test_a_perfect_record_walks_the_bands_the_way_the_names_describe`
pins it down:

| Days since the lesson | score | band |
|---|---|---|
| 0 – 7 | 1.00 | Solid |
| 14 | 0.90 | Solid / To review |
| 21 | 0.81 | To review |
| 28 | 0.72 | Fragile |
| 35 | 0.65 | Fragile |
| 42 | 0.58 | Fading |
| 56 and beyond | 0.55 | Fading |

The last two rows are the ones worth arguing about. A single correct answer
produces a full green cell — and the `provisional` flag is what stops the UI
presenting it as settled. The decay row shows the whole point of the second
factor: a perfect record from two months ago is not evidence of present mastery.

---

## 4. Review prediction

`days_until_review` answers "when will this drop below *to review*", by solving
for the first whole day `d` where `accuracy × recency(last_attempt, now + d) <
0.75`. It is what the `MasteryMeter` caption shows: *62 % · révision dans 2
jours*. It returns `0` when already due, and `None` when the recency floor holds
the score above the threshold indefinitely, or when the competency has never
been assessed.

---

## 5. What feeds the model

Only **confirmed** attempts. The scan pipeline produces detections with a
confidence; the teacher reviews them, corrects anything wrong, and confirms.
Nothing reaches `Attempt` — and therefore nothing reaches this model — until a
human has signed off. Low-confidence detections are surfaced first in the review
UI for exactly this reason.

Items the grader marks *not gradeable* (free text, an ambiguous double mark)
produce **no attempt at all** rather than a zero. A blank answer, by contrast,
*is* an attempt worth zero: the student saw the item and left it, which is
information.

---

## 6. Limits, honestly

- **No guessing correction.** A 4-option MCQ has a 25 % floor from chance alone;
  the model treats a lucky guess as evidence. The `provisional` flag mitigates
  this, and per-item discrimination would fix it properly.
- **One half-life for every competency.** Arithmetic drill and geometric
  reasoning almost certainly decay at different rates.
- **Difficulty is an estimate**, taken from extraction or an author's judgement,
  not calibrated against how the cohort actually performed.
- **No partial credit.** Correct or not; the `score` field on `Attempt` exists so
  a future grader can supply a fraction.
- **Competencies are treated as independent.** Mastery of "add fractions" tells
  the model nothing about "compare fractions", though the curriculum says it
  should.

Every one of these is a deliberate MVP trade, listed again in
[`handover.md`](handover.md).
