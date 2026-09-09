# Sheet layout v1

> Geometry only. The feature around it — data model, pagination, rendering,
> the API, the builder and what the scan pipeline reads back — is specified in
> [`sheets-spec.md`](sheets-spec.md).

The printed A4 sheet is the deliverable, not a rendering of a screen. Three
components must agree on its geometry exactly:

1. the print markup and `packages/ui/src/design/print.css`,
2. the server-side PDF renderer (headless Chromium over that same markup),
3. the scan detector, which registers a photographed page against the corner
   marks and then looks for bubbles at computed coordinates.

They agree because they all read one file:
[`apps/api/alppy/sheets/layout.py`](../apps/api/alppy/sheets/layout.py). The
TypeScript side is **generated** from it (`scripts/export-layout.py` →
`packages/shared/src/layout.generated.ts`) and CI fails if the generated file
drifts.

Every number below is printed from the source module, so this document cannot
go stale silently.

---

## The page

| | mm |
|---|---|
| Page | 210 × 297 (A4 portrait) |
| Margin | 14 |
| Fiducial square | 8 × 8 |

```
   0                                                              210
   +--------------------------------------------------------------+  0
   |                                                              |
   |   ##                                                    ##   |   <- fiducials, 8mm
   |   ##   Title / class / date        UID text + UID grid  ##   |      centres at
   |                                                              |      (18, 18)
   |   ------------------------------------------------------     |      and mirrored
   |                                                              |
   |   1.  statement .....................................        |   <- items region
   |   2.  statement .....................................        |      y 48 -> 196
   |   3.  statement .....................................        |      (148mm)
   |                                                              |
   |   ------------------------------------------------------     |
   |                                                              |
   |    1  O O O O            9  O O O O                          |   <- answer grid
   |    2  O O O O           10  O O O O                          |      FIXED position
   |    ...                  ...                                  |      y from 202
   |    8  O O O O           16  O O O O                          |      8 rows x 2 groups
   |                                                              |
   |   ##                                                    ##   |
   +--------------------------------------------------------------+  297
```

## The registration frame

The four fiducial **centres** define the frame. Every other coordinate is
expressed as a fraction of it, which is why the detector needs nothing from the
page but those four marks — not a single word of text.

| | mm |
|---|---|
| Frame origin | (18, 18) |
| Frame size | 174 × 261 |

### Why the fiducials are borders, not filled boxes

They are printed as CSS `border`, never as `background`. Browsers default to
**not printing background graphics**, so a fiducial drawn as a background
silently disappears on the one machine that matters — the teacher's printer —
and every scan then fails to register. A border survives that setting.

## The answer grid — and why it is not beside the questions

The grid sits at a **fixed** position: 8 rows × 2
column groups = **16 items per physical page**.

| | mm |
|---|---|
| Grid origin | (24, 206) |
| Row pitch | 8.5 |
| Column-group pitch | 88 |
| Item-number column | 14 wide |
| Bubble diameter / pitch | 5.0 / 8 |
| Max options per item | 4 |

Statement height varies with the text. A grid at a fixed position does not. That
is the whole argument: the detector can compute every bubble centre from the
four corners alone, with no layout analysis, no text parsing and no per-sheet
calibration.

The cost is real and worth stating: the student reads the statement above and
marks below, as on any optical mark sheet, rather than answering beside each
question. That trade is recorded as **D1** in
[`decisions-log.md`](decisions-log.md) and is the decision most worth revisiting
after watching a class actually use one.

Items of type `open` claim **no** bubbles: they print a delimited answer box
under the statement instead, and are graded from a verdict rather than from a
mark — see [`sheets-spec.md`](sheets-spec.md) §7 and §12.

## The UID grid

The student code is printed twice: as human-readable text (`7B_15`) and as a
8 × 4 grid of filled and empty cells
= **32 bits**, at
(120, 30), cells
4.0mm with a 1.0mm gap.

The grid is what the pipeline reads, which is why the happy path needs **no
OCR** — OCR on a phone photo of a photocopy is exactly where these systems fail.

24 bits carry the payload (class year, one or two class letters, student number)
and 8 carry a CRC-8. The checksum is the point:

> **Every single-bit and every double-bit misread is rejected**, rather than
> decoding to a different, real student.

A failed decode asks the teacher to assign the page, which is recoverable. A
wrong decode files a child's answers under someone else's name, which is not.
`tests/test_uid_code.py` asserts this exhaustively over all 32 single-bit and all
496 double-bit flips.

## Versioning

`Sheet.layout_version` records the version a sheet was printed with, and a scan
is always registered against **its own sheet's** version. So:

> Changing any number in `layout.py` is a **layout version bump**, never a tweak.

To add `v2`: add the new constants alongside the old ones, keep `v1` intact,
teach the detector to dispatch on `Sheet.layout_version`, and leave existing
sheets rendering and scanning exactly as before. Sheets printed last term must
keep working after the change — a teacher's filing cabinet is the real
compatibility constraint.

