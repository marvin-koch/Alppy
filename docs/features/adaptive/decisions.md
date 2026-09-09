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
