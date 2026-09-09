# Sheets Architecture

## Component diagram

```
  api/v1/sheets.py
     │  POST /sheets            POST /sheets/preview        POST /sheets/{id}/render
     ▼                                │                              │
  services/sheet_service.py           │                              ▼
     │  _replace_items                │                        Job(RENDER_SHEET)
     │  _bind_instances               │                              │
     ▼                                │                              ▼  arq worker
  Sheet ─< SheetItem                  │                     sheets/render.py
        ─< SheetInstance ──────────────┴──────────────┐             │
                                                      ▼             │
                        sheets/render.py::build_sheet_data ◀────────┘
                        build_draft_sheet_data (unsaved draft)
                                     │  SheetData(Copy[], items)
                                     ▼
                        sheets/pagination.py::paginate_all
                                     │  Page[] of PlacedItem
                                     ▼
                        sheets/html.py::render_sheet_html ──▶ render_both()
                                     │        (inlines packages/ui CSS,
                                     │         geometry.css.j2 from layout.py)
                                     ▼
                        sheets/render.py::html_to_pdf   (Playwright/Chromium)
                                     │
                    ┌────────────────┼─────────────────┐
                    ▼                ▼                 ▼
                blank.pdf     answer-key.pdf    measure_answer_boxes()
                    │                │                 │
                    └── storage ─────┘                 ▼
                                             _check_box_inside_statement_region
                                                       │
                                             _persist_answer_box_placements
                                                       │
                                              AnswerBoxPlacement rows
```

`layout.py` sits under all of it and is imported by four consumers that must agree:
the markup, the generated CSS, the PDF renderer and — through
`packages/shared/src/layout.generated.ts` — the web preview. The fifth consumer,
`alppy.scan`, imports it directly.

## Data flow

### Input — what the renderer is given

```python
# sheets/html.py
@dataclass(frozen=True)
class Copy:
    student_uid: str          # "7B_15" — printed as text AND as the 32-bit grid
    items: list[Item]         # this copy's own plan; a differentiated copy differs
    group_label: str | None   # for an N-group batch

@dataclass(frozen=True)
class SheetData:
    title: str
    copies: list[Copy]        # ordered by UID — never by database order (I-sheets-10)
    layout_version: str       # stamped onto every page
    kind: SheetKind           # BLANK | ANSWER_KEY | FEEDBACK
```

```python
# sheets/pagination.py — pure, no SQLAlchemy
@dataclass(frozen=True)
class Item:
    type: ExerciseType        # mcq | true_false | open
    statement: str
    options: list[str]
    figure: Figure | None     # a crop of the textbook page (corpus regions)
    answer_box_lines: int     # 0..14; 0 means "worked in the notebook"
    answer_box_fill: AnswerBoxFill
```

### Output

```python
@dataclass(frozen=True)
class PlacedItem:
    item_index: int   # PAGE-LOCAL 0..15. The detector addresses bubbles by this. (I-sheets-06)
    number: int       # the printed number, continuous across pages
    top_mm: float     # where the statement starts
    continuation: bool  # a box carried to the next page prints "SUITE" and the box only

@dataclass(frozen=True)
class MeasuredBox:      # sheets/render.py, read back out of the browser
    student_uid: str
    copy_page: int
    item_index: int
    x_mm: float; y_mm: float; w_mm: float; h_mm: float
```

`MeasuredBox` becomes an `AnswerBoxPlacement` row. That row, not the `SheetItem`, is
what `scanning` crops against (I-sheets-07).

## Component interaction

### `layout.py` — the geometry

Constants only, plus `bubble_centre_mm`, `page_slots`, `uid_cell_centre_mm` and
`as_dict()` for export. It imports nothing from Alppy. That is deliberate: it must be
readable by the detector, by pagination and by the exporter without dragging in the
ORM. Enforces nothing by itself; it is what everything else is measured against
(I-sheets-03).

### `pagination.py` — where a page ends

Two independent limits, and a page ends as soon as **either** is reached:

1. **Bubbles** — `ITEMS_PER_PAGE` (16) rows exist on the fixed answer grid. A
   seventeenth item would have no bubble to fill.
2. **Statement height** — the region is `ITEMS_BOTTOM_MM - ITEMS_TOP_MM` = 148 mm.
   Two long open questions exhaust it long before sixteen bubbles are used.

Height binds in practice. It enforces I-sheets-06 and I-sheets-09.

### `html.py` — one renderer, two documents

`render_both()` produces the blank and the key from one `SheetData`; the key is the
same document with `data-key="true"` on the correct bubble and a badge in the header
(I-sheets-04). It reads `packages/ui/src/design/{tokens,base,print}.css` **from disk
at render time**, so the design system cannot drift from the paper, and raises
`DesignSystemNotFoundError` rather than rendering an unstyled page.

### `render.py` — Chromium, and the two gates

- `_refuse_unapproved` → `ensure_printable` (I-sheets-01). Raises
  `UnapprovedExerciseError` carrying the offending ids.
- `measure_answer_boxes` reads each printed box's rectangle out of the live page,
  `_check_box_inside_statement_region` refuses any that escaped the statement region
  (I-sheets-08), and `_persist_answer_box_placements` writes them (I-sheets-07).
- `BrowserUnavailableError` is a distinct type so a caller can tell "Chromium is not
  installed" apart from "this sheet cannot be rendered".

## Edge cases

- **An item taller than a whole page.** → `ItemTooTallError`, naming the printed
  number of the offending item. Never clipped, never shrunk (I-sheets-09).
- **A box that does not fit the remaining space.** → the statement stays where it is
  and the box is carried to the next page at full height, printed under the item's
  number with `SUITE`. `ANSWER_BOX_MAX_LINES = 14` is exactly the tallest box that
  still fits a page alone (repo log D44).
- **A figure wider than the column.** → shrunk to fit, never enlarged; pagination
  reserves the printed height, not the intrinsic one.
- **A sheet with no items.** → render is refused at the API
  (`test_api_sheets.py::test_render_refuses_an_empty_sheet`).
- **A sheet re-rendered after an edit.** → placements are replaced wholesale; the
  scan job reads the placements that exist, which is why editing after printing is
  the hazard I-sheets-07 names.
- **A sheet printed before answer boxes existed.** → no placements; its open items
  stay `NOT_GRADEABLE` rather than being cropped from a guess.
- **An unsaved draft.** → `build_draft_sheet_data` + `POST /sheets/preview` renders
  the real printed document and persists nothing (repo log D29).
- **A differentiated copy.** → each `Copy` carries its own `items`; the exercise a
  detection answers is resolved through that copy's pagination, never re-derived
  from the sheet's class-wide list.

---

**Companion:** [`README.md`](README.md) §2 for the load-bearing rules.
