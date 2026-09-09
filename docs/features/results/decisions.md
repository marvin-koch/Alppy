# Results Decisions Log

D-numbers follow the repo-wide [`docs/decisions-log.md`](../../decisions-log.md).

---

## D49 · Points and mastery are two screens, not two columns of one

**Date:** M4 · **Affected invariants:** I-results-03

**Background.** Both are "how is this pupil doing". The temptation is one grid.

**Considered alternatives**
- A) *Add a points column to the mastery matrix.* Rejected: the matrix is
  students × competencies and points are per *sheet*. The two do not share an axis.
- B) *Colour points with the mastery bands.* Rejected, and this is the important
  one. The band ramp is calibrated — monotonic in greyscale, constant glyph
  luminance, built to survive a photocopier. It means "decayed evidence about a
  competency". Painting 71 % amber asserts a band nobody computed, from one
  morning's paper.
- C) **A separate `/results` screen sharing the grid shell only.** Chosen.

**Consequence.** `Matrix` was extracted from `MasteryMatrix` so the keyboard model
and the sticky column are written once. `MasteryMatrix`'s public props are
unchanged, so the class page needed no edit.

---

## D50 · Absent is null all the way down

**Date:** M4 · **Affected invariants:** I-results-01

**Background.** A dashboard has to show a pupil who has not been marked yet.

**Chosen.** `null` in the SQL, `null` on the wire, `null` in the TS type, an em
dash in the cell. `aggregatePoints` sums `possible` over the *graded* entries only,
so an unmarked sheet cannot enlarge the denominator and drag a ratio down.

**Rejected.** Coalescing to 0 anywhere. It reads as a failure the pupil never had,
and it is the same mistake as scoring an unreadable answer zero (D5, I-grading-02)
one altitude up.

---

## D52 · The breakdown renders answers, not indices

**Date:** M4 · **Affected invariants:** I-results-06

**Background.** A detection stores `detected_index: 2`. A teacher handing back a
paper needs "C. 3/4".

**Chosen.** `_readable_choice` turns an index into the letter and the option text,
using the same `OptionLetters` / `tf_letters` the sheet printed with — so the screen
says exactly what the paper says, in the sheet's language, including V/F versus R/F.

**Rejected.** Sending the index and formatting in React. The letter set is a *print
geometry* fact (`layout.py`) and the language is the sheet's, not the interface's;
resolving it on the client would mean duplicating both and eventually disagreeing
with the paper.

---

## D53 · "Not graded" is a third state on every item, not the absence of a mark

**Date:** M4 · **Affected invariants:** I-results-05

**Background.** An item can be right, wrong, or never graded — a copy not yet
scanned, an ambiguous mark the teacher has not settled, a written answer with no
verdict.

**Chosen.** `correct: null` and `points_earned: null` travel all the way to a badge
that says "non noté" and a dash where the points would be. Three states in the type,
three in the UI.

**Rejected.** `correct: false` for the ungraded. It is the same mistake as scoring an
unreadable answer zero (D5, I-grading-02) and it would be shown to the pupil whose
paper it is.
