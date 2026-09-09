# Results — architecture

## Component diagram

```
  GET /classes/{id}/points            GET /sheets/{id}/confidence
          │                                      │
  sheet_service.class_points_totals     scan_service.confidence_by_item
          │                                      │
   ┌──────┴───────┐                       newest reading per
   │              │                       (student, QUESTION)
_earned_by_sheet  _possible_by_student           │
  one SUM for     per copy, from its       count by outcome
  N sheets        own item_plan                  │
          │              │                       │
          └──────┬───────┘                       │
       ClassPointsReport                 list[ItemConfidence]
                 │                               │
        class_points_out                 sheet_confidence_out
                 │                               │
            ClassPointsOut                SheetConfidenceOut
```

### The drill-down

```
  /results                    class · students x sheets, points
      │  cell = one pupil, one sheet
      ▼
  /classes/{c}/students/{s}/sheets/{sheet}
      │  GET /students/{s}/sheets/{sheet}
      ▼
  per question: statement · their answer · expected answer · points
  plus the crop of what they wrote, when there is one
```

The profile's sheet history links here too, because from a pupil's page "this
sheet" means the paper *they* sat, not the class-wide sheet.

## Data flow

**Input.** `Attempt.score` (signed, per item, written by confirmation),
`Sheet.default_points_correct` / `SheetItem.points_correct` (the barème),
`SheetInstance.item_plan` (what each copy actually held), and `Detection.outcome`.

**Output.** Two Pydantic documents, and a `/results` screen that pivots them into
students × sheets.

## Edge cases

| Case | Behaviour | Why |
|---|---|---|
| A student on the roster with no graded sheet | `points_earned: null`, `points_possible > 0` | The paper was still worth something; the pupil simply has no mark |
| A sheet nobody has scanned | `average_ratio: null` | An average of nothing is not 0 % |
| A differentiated batch | Each copy's `possible` comes from its own `item_plan` | Two pupils held different papers |
| An item worth 0 points | Counts toward neither earned nor possible beyond its own 0 | A bonus item that costs nothing |
| A copy photographed twice | Counted once, newest page wins | The same rule confirmation applies to grades |
| A question printed across two pages | Keyed by exercise, not `item_index` | `item_index` is page-local and restarts at 0 |
| A detection with no exercise | Falls back to `(student, folio, item_index)` | A reading with nothing behind it still belongs to one slot |
| A copy nobody has marked | Every item `correct: null`, `points_earned: null`; the total is `null` | "Not graded" is not "scored zero" |
| A blank answer | `given: null` → "Sans réponse", `correct: false`, `0` points | A blank IS a graded zero (D5); the pupil saw the item and left it |
| A written answer | `given` is the transcription; the crop is served beside it | The answer rendered on the site, not only inside the PDF |
| An item with no reference answer | `expected: null` → "no reference answer" | Never a placeholder (I-grading-08) |

## Performance

`_earned_by_sheet` is one grouped query for every sheet of the class rather than
one per sheet — a term is the normal case and this is read on every dashboard
load. `_possible_by_student` walks `sheet.instances` in memory; the relationship
is already loaded by the time the report runs.

## Why the grid is shared and the cell is not

`Matrix` owns the keyboard model, the sticky first column and the contained
horizontal scroll — behaviour, no vocabulary. `MasteryCell` and `PointsCell` are
separate because the five-band ramp is calibrated: monotonic in greyscale,
constant glyph luminance, tuned for a photocopy. It encodes decayed competency
evidence. A score is a different measurement, and colouring it with that ramp
would assert a band the mastery model never computed.
