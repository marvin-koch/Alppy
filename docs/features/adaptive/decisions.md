# Adaptive Decisions Log

D-numbers follow the repo-wide [`docs/decisions-log.md`](../../decisions-log.md).

---

## Retrieval first, generation for the remainder

**Date:** M5 · **Affected invariant:** I-adaptive-01

A textbook exercise is *already* pedagogically vetted, printed in the language the
class works in, tied to a page the teacher can open, and free. A generated one is none
of those until a teacher reads it.

So generation is the **fallback**, not the default: it fills the remainder of a sheet
the corpus could not fill, and every generated item arrives `approved_at = None` in
its own `generated` list, so the UI can mark it with the accent colour (I-design-01)
and the teacher can read each one.

---

## The approval gate lives in its own module

**Date:** M5 · **Affected invariants:** I-adaptive-04, I-adaptive-05

**Background.** `ExerciseOrigin.AI_GENERATED` + `approved_at IS NULL` is the one state
that must never be printed. `CLAUDE.md` states it as a rule a reviewer enforces by
reading — so it is enforced in code instead.

**Chosen.** `services/approval.py`, depending on nothing but the model, called at
*every* door into the print path. The routers load adaptive planning through
`deps.load_optional`; the gate must never be optional, and an `ImportError` must never
be able to turn the rule off.

**And it raises rather than filtering.** A sheet quietly missing three of its twelve
items is a worse outcome for a teacher standing at a photocopier than an error that
says exactly which items are waiting for a decision.

---

## D32 · `SOLID` is a stretch target, because skipping it inverted the ZPD

**Date:** 2026-09 · **Affected invariant:** I-adaptive-02

**Background.** `TARGET_BANDS` excluded `MasteryBand.SOLID` on a defensible argument:
re-drilling a mastered competency spends a student's attention on what they already
have. The argument is right about re-drilling and **wrong about the student it
actually described**. With no gap in any band, `pick_gaps` returned empty,
`_plan_for_student` took its `diagnostic` branch, and a child who had mastered
everything assessed was handed `FALLBACK_DIFFICULTY = 2` — *easier* work than they
could already do. The precise opposite of the zone of proximal development.

**Chosen.** `SOLID` is targeted at lowest priority, and `target_difficulty` pushes it
one level **above** the working level rather than at it — the only direction in which
the clamp at 5 was ever reachable. `MAX_STRETCH_COMPETENCIES = 1` keeps stretch from
crowding out real gap work, with one deliberate exception: a student whose
competencies are *all* solid has no gap work to protect, so the cap lifts.

**Tradeoff**
- ✅ The strongest child in the room gets the hardest sheet, not the easiest
- ✅ One stretch item does not displace four real gaps
- ❌ A fourth branch in targeting, and a band that is both "fine" and "targetable"

**Two existing tests failed on this change and both were right to** — they pinned the
old contract. They were re-encoded rather than loosened.

**It also nearly shipped a crash.** `_BAND_WORDS` had no `SOLID` entry, so
`_gap_reason` would have raised `KeyError` the first time a stretch item was retrieved.
Rather than adding a word, stretch got its own phrase: "cible une compétence acquise"
reads as a mistake, and French `OK` already holds "acquise".

**Revisit if** a teacher reports sheets that feel too easy for a strong class — the
next lever is an item quota rather than a competency cap.

---

## D33 · N groups is a partition above a function that already worked

**Date:** 2026-09 · **Affected invariant:** I-adaptive-10

**Considered alternatives**
- A) *A second planner for groups.* Rejected: two planners to keep in step, and the
  per-student and whole-class paths would drift apart.
- B) **`cluster_students` placed above the existing `_plan_for_group`, called once per
  cluster.** Chosen — `_plan_for_group` was always parameterised over an arbitrary
  `Sequence[Student]` and never assumed "the whole class".

**The rule, as a teacher must be able to defend it:** students with the same principal
gap go together; if that gives more groups than you asked for, the smallest merge, and
if fewer, the largest splits by severity.

**No group entity is persisted.** The partition is recomputed from mastery every time,
because a stored group would be stale the moment the next scan lands — and nothing
downstream (mastery, attempts, scans) needs to know a copy belonged to one. What
survives is `SheetInstance.group_label`, a printed string, and
`Sheet.target = SheetTarget.GROUP`, which had sat unused in the enum since migration
0001.

**The teacher can move a student between groups** before exporting. That override lives
in the review screen's state and travels with the batch; a move takes the receiving
group's **items** as well as its label — a sheet headed "Groupe 3" holding group 1's
exercises is the one outcome a move must never produce.

**Revisit if** teachers want to name groups or carry them across a unit. That is the
point at which a `StudentGroup` row starts paying for itself.

---

## The language of a generated exercise follows the material

**Date:** M5, corrected 2026-09 · **Affected invariant:** I-adaptive-06

`source_language` reads the language off the corpus the class actually works from; the
teacher's locale is a last resort for a subject with no indexed exercises at all.

Getting this wrong is not merely a wrong label. `Exercise.language` chooses the printed
true/false glyphs (V/F · R/F · T/F), and the detector reads bubbles **by position** —
so a mislabelled item prints the wrong letters next to the right holes, and the student
marks "V" for what the grader scores as "false".

---

## D63 · The sheet the teacher just corrected outranks the term's average

**Date:** 2026-09 · **Affected invariant:** targeting (`gaps_for_student`)

`source_sheet_id` was already on the request and did nothing but record lineage and
fetch feedback notes. Targeting read `MasterySnapshot` — every attempt a child has ever
had, decayed by recency and weighted by difficulty.

That is the right input for "what does this child need next term" and the wrong one for
what a teacher actually does on a Tuesday: correct today's sheet and ask for the
follow-up to answer *it*.

**Chosen.** `sheet_performance` reads that sheet's attempts and rolls them up per
competency **through the same `mastery.model`** — `compute_mastery`, `band_for` — so a
band means the same thing here as everywhere else. When the sheet says something about a
child, it wins. When it says nothing (absent, or the pile was never confirmed), mastery
is the fallback; when neither says anything it is the diagnostic branch, and it is
*reported* as such rather than looking like a child with no gaps.

**The fallback is not a second opinion.** Snapshots derive from the same `Attempt` rows,
unfiltered by sheet. The two can disagree about the same child, and falling back only
when the sheet is silent keeps that from becoming an argument the model has to settle.

**Three things the summary refuses to paper over**, because each is a way it could lie:

- Attribution is many-to-many, so a roll-up does **not** partition — eight items can
  give fourteen (competency, outcome) pairs. It says "3 of the 4 items touching X", never
  "X: 75% of the sheet".
- The attempt join is an **inner** join on `exercise_competency`. A child who got five of
  eight wrong, all on untagged items, would produce an empty summary and read as fine.
  `unattributed` counts them.
- Evidence is often partial: attempts exist only after a scan is confirmed, and
  low-confidence, blank and ungraded items never become attempts. `answered` and
  `printed` are both reported, and `evidence_partial` reaches the screen.

**Revisit if** teachers ask to target a unit rather than a sheet. The query already takes
a filter; what it would need is a way to name the set.

---

## D64 · A model may revise the partition; it may not be trusted with it

**Date:** 2026-09 · **Affected invariants:** I-adaptive-10, I-adaptive-11

**Background.** D33 chose a deterministic rule because a teacher has to be able to state
it to a parent. A model can see things that rule cannot — two children failing the same
competency for visibly different reasons — but it can also return a partition that drops
a child, and unlike a bad exercise nobody reads a partition before it takes effect.

**Chosen.** Opt-in per request (`llm_grouping`, default false), with the deterministic
partition used **twice**: as the seed sent in the prompt, so the model revises a
defensible answer rather than inventing one, and as the fallback. The answer is validated
against the roster — every student exactly once, the requested number of groups, none
empty — and anything short of a real partition returns the seed. Not repaired: a
partition that seats a child twice is not "nearly right", it is a different question
answered, and the rule is standing right there.

`adaptive_cluster` joins `TRANSCRIPTION_PURPOSES`, so the offline provider returns the
empty shape and CI takes the deterministic path — which is both honest and *correct*,
rather than a degraded stand-in.

**The prompt sees row ids** — S1, S2 — and never a UID or a name. It does not need to
know who anyone is to say who belongs with whom.

**Tradeoff**
- ✅ D33's rule survives as the default, the seed and the fallback
- ✅ No path where a model failure produces a worse partition than no model at all
- ❌ A second grouping path to keep in step, and a model call a teacher pays for

**Revisit if** the accepted partitions turn out to be reliably better than the seed. That
is the point at which the default could move — with evidence, not before.

---

## D65 · Batching buys latency, and buys back the isolation it costs

**Date:** 2026-09 · **Affected invariants:** I-adaptive-09, I-adaptive-12

Generation was one call per student or per group. A class of twenty-four in per-student
mode was twenty-four sequential provider calls, each repeating the same system block and
the same style examples.

**Chosen.** A collector: each planner does its own retrieval, computes its own shortfall,
and registers an *ask* plus a closure that finishes its plan. One pass then fills them
all, eight plans to a call. The same move D33 made for grouping — a phase placed above a
planner that already worked.

**What it actually saves, stated honestly.** Groups are partitioned by principal gap, so
each plan carries its own competencies, difficulty, count and style examples; only the
system block and the shared rules dedupe. Realistically 25–35% of *input* tokens and
**zero** output tokens, and output costs roughly 5× input. The real win is latency and
round-trips, not cost. It was measured before it was built, and it is written down here
so nobody re-derives the wrong expectation from the diff.

**The isolation it costs, and how it is bought back.** One call for eight plans makes
I-adaptive-09 untrue by construction. Two failure classes, handled differently:

- *Per plan* — its entry is missing, or every item in it was rejected. That plan alone
  comes up short and is reported. This is I-adaptive-08's per-item rule, one level up.
- *Whole call* — provider error, unparsable, truncated. The chunk is **retried once,
  split into single-plan calls**, so a persistent fault degrades to exactly the behaviour
  that shipped before batching rather than to a class-wide blank.

**And it fixed a live bug on the way.** `seen` was rebuilt per call, so two groups in one
proposal could each be handed the identical statement — the teacher reads it twice and
cannot tell which sheet it belongs to. The set is now shared across the run.

**`test_one_students_failure_does_not_cost_the_rest_of_the_batch` had to be re-encoded.**
It pinned the invariant to a *shape* — one call per student — rather than to the
invariant. It now scripts a failed batch and a failing single-plan retry, which is the
same claim one layer down. Re-encoded, not loosened, as D32's tests were.

---

## D66 · Proposing is a job, and the proposal is not the job's result

**Date:** 2026-09 · **Affected invariant:** I-adaptive-13

`POST /adaptive/propose` ran targeting, retrieval and every generation call inside the
request handler. CLAUDE.md forbids exactly that, and the codebase already argued the case
against itself: `generate_feedback`'s docstring says a class of twenty model calls in a
handler "is a timeout with a half-written batch behind it". Propose was doing the same
thing and only escaped notice because it predates the rule being written down.

**Chosen.** `JobKind.PROPOSE_ADAPTIVE` — a new value, not a reuse of
`GENERATE_ADAPTIVE`, which despite its name only *renders* an approved batch and which
`TASK_NAMES` maps to exactly one worker function.

**The proposal goes in its own row, not in `Job.result`.** A class of twenty-four with
eight items each — full statements, options, provenance — is close to a megabyte, and the
review screen polls the job every 900 ms while it runs. A status row has to stay cheap to
ask about. `GET /adaptive/proposal/{job_id}` reads it; `AdaptiveProposal` cascades from
the job, because it is the shape of one screen and means nothing once that run is gone.

**Two things the move would have broken quietly:**

- `propose_adaptive` called `db.commit()`. The task owns the transaction boundary
  ("a pipeline function must not commit or close `db` itself"), so the commit is now the
  caller's choice and the worker passes `commit=False`.
- The rate limit used to throttle the request that made the calls. Enqueueing is cheap,
  so it would have stopped covering anything: a teacher could queue twenty proposals a
  minute and the worker would fan out. The limit stays on the handler, and an in-flight
  check returns the running job rather than starting a second — a double-click used to
  cost one token and would have cost a second set of unapproved exercises.

---

## When policy changes

```json
{
  "change": "auto-approve generated items whose confidence is high",
  "reason": "the teacher approves everything anyway",
  "date": "YYYY-MM-DD",
  "decision": "rejected — violates I-adaptive-03 and I-adaptive-04",
  "rationale": "approved_at is the boundary between 'a model suggested this' and
                'a teacher stands behind this'. There is no confidence score that
                can cross it on the teacher's behalf."
}
```
