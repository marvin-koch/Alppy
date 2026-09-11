# Testing the paper loop on real hardware

Run once per release. Half an hour, one person, one class set.

## Why this exists

The product's whole value proposition is paper, and **no automated test touches
any**. `test_print_scan_roundtrip.py` rasterises a rendered PDF and feeds the
pixels to the detector, which is genuinely good and is the reason the geometry
cannot drift — but a rasteriser is not a printer, and a synthetic degradation is
not a phone camera held at an angle over a desk by someone who has twenty-seven
more to do.

Nothing anywhere recorded which printer, scanner or phone the loop had ever
been tried on, or when. That is the gap this closes, and it is not one a test
can close: the failures it catches are toner density, a photocopier that scales
to 98 %, a laminated desk that throws a highlight across the UID, and a phone
that sharpens aggressively enough to turn a pencil stroke into two.

## What you need

- The target printer. Name it in the log below — "a laser printer" is not a
  record anyone can act on.
- A photocopier, if the school uses one. Most do: the teacher prints one and
  copies twenty-seven.
- A phone. The one a teacher would use, not the newest one in the room.
- A class set's worth of paper. Ten copies is enough to be honest about.

## The procedure

1. **Print.** Build a sheet with at least one MCQ, one true/false and one
   written-answer box. Print **three** copies directly.
2. **Photocopy.** Take one of the three and copy it twice — so one of your
   copies is a copy of a copy. This is the ordinary case in a school, not an
   edge case, and it is where toner density actually bites.
3. **Fill them in**, deliberately unevenly:
   - two in pencil, lightly — the pupil who does not press;
   - two in blue pen;
   - one with **crosses** rather than filled bubbles. `_cross_score` exists for
     this and is recognised by shape rather than by ink;
   - one with a bubble filled and then scribbled out, and the intended one
     filled beside it;
   - one with the written answer running outside its box;
   - one left entirely blank. **A blank must never come back as a zero** — it
     is skipped, and this is the item to check first when reading the results.
4. **Photograph.** Hold the phone at roughly the angle a person standing over a
   desk holds it — not square on. Under classroom light: overhead fluorescents,
   not a window. One photo per copy.
5. **Upload** all of them as one pile.
6. **Read the review screen** and record the numbers below.

## What to write down

Copy this into `docs/print-scan-runs/YYYY-MM-DD.md` and fill it in. The archive
is the point: one run is an anecdote, four runs across two printers is a
finding.

```
date:
release / commit:
printer:            (make, model, toner age if known)
photocopier:        (make, model — or "none")
phone:              (make, model, OS version)
lighting:           (overhead fluorescent / daylight / mixed)

copies uploaded:            __
pages that registered:      __  /  __
UIDs read correctly:        __  /  __
  - misread as another pupil:   __      <- the one that matters most
  - not read at all:            __

per-item accuracy:          __  /  __
  - blanks graded as wrong:     __      <- must be 0
  - crosses missed:             __
  - scribbled-out bubble taken as the answer: __
  - written answer transcribed correctly:  __ / __

items the teacher had to fix by hand:  __
time from upload to a confirmable pile: __ min

anything the screen said that a teacher would not understand:
```

**`misread as another pupil` and `blanks graded as wrong` are the two that stop
a release.** Everything else on this list is a quality signal; those two are a
child getting someone else's marks, and a child being marked wrong for an item
they skipped.

## Afterwards

Archive the filled-in run under `docs/print-scan-runs/`. When a run finds a
recognition failure, the crop is also a candidate for the golden set
(`apps/api/tests/golden/README.md`) — with the same caution about whose
handwriting it is, and the same answer: an adult volunteer rewriting the same
answer carries no consent question, and a real pupil's crop does.
