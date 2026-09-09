# The sheets feature — implementation spec

**Status:** describes what is in `main` as of 2026-09-09, layout version **v1**.
**Audience:** whoever has to extend this, port it, or rebuild it.

A *sheet* is the printed A4 worksheet a teacher hands to a class, plus its
answer key, plus — for a differentiated batch — a per-student feedback page.
It is the product's centre of gravity: the paper is the deliverable, and every
other subsystem (ingest, retrieval, scan, mastery) either feeds it or reads it
back.

This document is the contract. Where it disagrees with the code, the code wins
and this file is stale — but the *invariants* in §2 are load-bearing and a diff
that breaks one is a bug even when every test passes.

Companion documents:

| | |
|---|---|
| [`sheet-layout.md`](sheet-layout.md) | the millimetre geometry, printed from the source module |
| [`decisions-log.md`](decisions-log.md) | D1, D2, D3, D29, D40–D45 are the sheet decisions |
| [`architecture.md`](architecture.md) | Flow 2 (render) and Flow 3 (scan) in context |
| [`privacy.md`](privacy.md) | why a crop never leaves the statement region |

---

## 1 · What the feature does

```
   a textbook chapter ─┐
   an AI proposal ─────┼─▶  the builder  ─▶  Sheet + SheetItem[] + SheetInstance[]
   the teacher's own ──┘    (draft, unsaved)      │
                                                   │  POST /sheets/{id}/render
                                                   ▼
                              headless Chromium over the print markup
                                                   │
                            ┌──────────────────────┼──────────────────────┐
                            ▼                      ▼                      ▼
                        blank.pdf            answer-key.pdf     AnswerBoxPlacement[]
                            │                                            │
                     photocopier, classroom                              │
                            │                                            │
                            ▼                                            │
                     phone photo / scan  ─▶  alppy.scan  ──────────────▶─┘
                                                   │        (crops each box
                                                   ▼         where it printed)
                                        Detection[] ─▶ Attempt[] ─▶ mastery
```

Three properties make the rest of the system possible, and each is paid for
somewhere in this feature:

1. **A printed page is self-describing.** Four fiducials, a checksummed UID
   grid, and bubbles at coordinates fixed by the layout. The detector needs no
   text, no OCR, no per-sheet calibration.
2. **One renderer.** The in-app preview, the PDF, and the geometry the detector
   samples all come from the same module (`alppy.sheets.html`) reading the same
   constants (`alppy.sheets.layout`) and the same design system CSS.
3. **Everything the scanner needs is recorded at print time.** The layout
   version on the sheet, the page count on the instance, the answer-box
   rectangles in their own table. Nothing is recomputed from rows that may have
   changed since the paper left the printer.

---

## 2 · Invariants

These are the rules a reviewer has to enforce by reading. Each names where it
is enforced and what breaks when it is not.

| # | Invariant | Enforced in | Failure if broken |
|---|---|---|---|
| I1 | Changing any number in `layout.py` is a **layout version bump**, never a tweak. | review; `Sheet.layout_version`, `storage_key()` | scans of last term's pile register against the wrong coordinates |
| I2 | One `.print-page` is **one physical page**, never one student's copy. Every page carries its own header and UID. | `_page.html.j2`, `physical_pages()` | a second page belongs to nobody and cannot be graded |
| I3 | Always **two documents** — blank and answer key — from the same `SheetData`. | `render_both()`, `render_sheet_pdfs()` | a teacher cannot correct the pile |
| I4 | The **feedback pages are a third document**, never extra pages inside a copy. | `SheetKind.FEEDBACK`, `render_feedback_pdf()` | `seen[uid] % len(printed_pages)` rotates and grades page 2 against page 1's questions |
| I5 | Every mark the pipeline reads is drawn as a **border, not a background**. | `print.css`, `geometry.css.j2`, `print_background=False` | the teacher prints with backgrounds off and every scan fails to register |
| I6 | `PlacedItem.item_index` is **page-local 0..15** and resets on every page; `PlacedItem.number` is the continuous printed number. | `pagination.paginate()` | a whole class is graded against the wrong questions |
| I7 | An **answer box is cropped where it printed**, from `AnswerBoxPlacement`, never recomputed from `SheetItem`. | `render._persist_answer_box_placements`, `scan_processing._placements_by_uid` | an edit after printing moves what the scanner crops |
| I8 | A **crop never leaves the statement region** (`ITEMS_TOP_MM..ITEMS_BOTTOM_MM`). | `render._check_box_inside_statement_region` | a crop carries the header, i.e. a student code, to a model provider |
| I9 | **No AI-generated exercise reaches paper without `approved_at`.** Checked at the last door, the render path. | `render._refuse_unapproved`, `services.approval` | unreviewed generated content is handed to children |
| I10 | **A written answer is graded on a verdict, never a heuristic**; pending / unreadable / offline all produce no attempt. | `open_answer_grading`, `scan.open_grading` | a missing verdict becomes a zero for a child |
| I11 | **Student-facing text never below `body-l`** (1.125 rem). The textbook crop is exempt: it reproduces the book at 1:1. | `print.css`, D40 | unreadable paper |
| I12 | **No student name reaches a model provider.** Prompts carry the UID. | `alppy/ai/scrub.py` (raises), plus I8 for images | a leak |
| I13 | The sheet is rendered **deterministically**: copies ordered by UID, no clock in the markup, page numbers derived. | `build_sheet_data`, `physical_pages` | two renders of one sheet produce different piles |
| I14 | An item **too tall for any page is refused**, not clipped. | `pagination.ItemTooTallError` | a question with no ending prints, silently |
| I15 | **A blank is never penalised, and an ambiguous mark is never scored at all.** Every grader settles both before the barème is consulted. | `scan.grading` (`score_for` is unreachable from either), D5, D46 | a child loses marks for leaving an item, or for a mark the machine could not read |
| I16 | **`Attempt.score` is the teacher's mark; `Attempt.correct` is the mastery signal.** Mastery reads only the boolean. | `mastery_service.load_attempt_inputs`, `mastery.model.compute_accuracy` | a marking scheme silently rewrites what the model believes a child knows |
| I17 | **A cross and a fill both read as a mark**, and neither a stray stroke nor a smudge does. | `detector._cross_score` / `_mark_strength`, D47 | every crossed answer in a class lands in manual review |

---

## 3 · Module map

### Server (`apps/api/alppy/`)

| Path | Owns | Depends on |
|---|---|---|
| `sheets/layout.py` | **every millimetre**, `LAYOUT_VERSION`, bubble/UID coordinates, answer-box furniture constants | nothing |
| `sheets/uid_code.py` | UID ⇄ 32 checksummed bits ⇄ grid cells | `layout`, `core.uid` |
| `sheets/pagination.py` | `Item`, `Figure`, height estimation, `paginate()`, `PlacedItem`, `Page` | `layout`, `models.enums` — **no SQLAlchemy** |
| `sheets/html.py` | `SheetData`/`Copy`, `physical_pages()`, `geometry_context()`, `render_sheet_html()`, the feedback document | `layout`, `pagination`, `uid_code`, Jinja, the design CSS |
| `sheets/templates/*.j2` | the markup and the generated stylesheet | — |
| `sheets/render.py` | Chromium: HTML→PDF, `measure_answer_boxes()`; rows→`SheetData`; storage; the two/three entry points | `html`, `models`, `storage`, Playwright |
| `services/sheet_service.py` | CRUD, item replacement, instance binding, the adaptive batch | `models`, `schemas` |
| `api/v1/sheets.py` | HTTP surface, the 422s, the render job | `sheet_service`, `sheets.*` via `load_optional` |
| `worker/tasks.py` | `render_sheet`, `generate_adaptive` job bodies | `sheets.render` |

`sheets/*` is deliberately layered so that everything interesting is testable
without a database and without a browser: `layout` is pure constants,
`pagination` is pure functions over frozen dataclasses, `html` is pure string
production, and only `render` touches Chromium, the ORM and the object store.

### Web (`apps/web/src/`)

| Path | Owns |
|---|---|
| `app/[locale]/sheets/page.tsx` | the list: two piles — "to finish" (no PDF) and "ready to print" |
| `app/[locale]/sheets/new/page.tsx` | the builder shell: title-as-heading, two tabs, scope from the sidebar |
| `app/[locale]/sheets/[sheetId]/page.tsx` | the saved sheet: preview frames, render job, downloads, print |
| `components/sheet-builder/useDraftSheet.ts` | the unsaved draft (holds whole `ExerciseOut`s, not ids) |
| `components/sheet-builder/SheetComposer.tsx` | the ordered item list, reordering, per-item box + expected answer |
| `components/sheet-builder/DraftPreview.tsx` | `POST /sheets/preview` → `srcdoc` iframe, debounced, scaled to fit |
| `components/sheet-builder/{ExercisePicker,SectionPicker,ProposeTab,AddExerciseModal}.tsx` | the three ways exercises get onto a sheet |
| `lib/optionLetters.ts` | option glyphs, mirrored from `layout.py` via `@alppy/shared` |
| `packages/shared/src/layout.generated.ts` | **generated** from `layout.py`; CI fails if stale |

---

## 4 · Data model

```
Class ──< Student
  │           │
Sheet ──< SheetItem >── Exercise
  │  └─< SheetInstance >── Student      (one per student, carries the UID)
  │  └─< AnswerBoxPlacement             (written at render time, replaced wholesale)
  └── derived_from_id ──▶ Sheet         (the common sheet this batch answers)
```

### `Sheet`

| Column | Notes |
|---|---|
| `class_id`, `subject_id`, `created_by_id` | ownership is the **class's**, not just the school's (D23) |
| `title`, `language`, `intent` | `language` is the **exercises'** language, not the UI locale |
| `target` | `class` \| `student` \| `group`; `group` is set only by an adaptive batch with >1 group |
| `derived_from_id` | the common sheet whose corrected scan produced this one — what makes a teaching unit a chain |
| `layout_version` | stamped at creation and re-stamped at render; a scan is registered against **this** |
| `default_points_correct`, `default_points_penalty` | the sheet's barème, NOT NULL; what every item falls back to. The penalty is a **magnitude** (D46) |
| `blank_pdf_key`, `answer_key_pdf_key`, `feedback_pdf_key` | storage keys; `NULL`ed when items **or the barème** change |
| `rendered_at` | when the PDF was built — *not* when it was printed (see `SHEET_PRINTED` event) |

### `SheetItem` — the class-level list the teacher reorders

| Column | Notes |
|---|---|
| `position` | unique per sheet (`uq_sheet_item_position`) |
| `statement_override` | the teacher's printed wording; the corpus row keeps its own text and provenance |
| `answer_box_lines` | 0–14, `NULL` = default 5. `CHECK` constraint, widened by migration 0013 |
| `answer_box_fill` | `lined` \| `grid` \| `blank` |
| `expected_answer` | the teacher's answer **for this printing**; dropped by the service on a bubble item |
| `points_correct`, `points_penalty` | this item's own barème, `NULL` = follow the sheet. `CHECK 0–20`. **Not type-gated** — a point value means something on every type (D46) |

Box height, fill and expected answer live here rather than on `Exercise`
because the same exercise wants three lines on a quiz and twelve on a test, and
because a PATCH per keystroke on a shared corpus row from inside an unsaved
draft is the wrong shape (D42, D43).

### `SheetInstance` — the printed artefact

One per student, unique on `(sheet_id, student_id)`. Carries `student_uid`
(denormalised: the paper has it, so the scan path must resolve it without a
join through a possibly-renamed roster), `item_plan` (`[{exercise_id,
variant_id|null, position}]`, resolved at render time), `page_count` (stamped by
`_stamp()`), `group_label` (a printable string, deliberately not a foreign key
— grouping is recomputed from mastery every time), and `feedback_id`.

### `AnswerBoxPlacement` — where a box actually printed

Unique on `(sheet_id, student_uid, copy_page, item_index)` — exactly how a
detection is resolved. Holds `x/y/w/h_mm` of the border box in page
millimetres, plus `box_lines`, `box_fill` and `layout_version`.

Written by delete-then-insert **by sheet** on every render, never upsert by
student: a re-render after a roster change must lose the rows of a child who
left as surely as it gains those of one who arrived.

### Migrations

| | |
|---|---|
| `0001` | `sheet`, `sheet_item`, `sheet_instance` |
| `0006` | `derived_from_id`, `feedback_pdf_key`, `group_label`, `feedback_id` |
| `0009` | `exercise.figure_*` (the textbook crop a sheet prints) |
| `0010` | `answer_box_lines`, `answer_box_fill`, `answer_box_placement` |
| `0011` | 0 lines = "no box" admitted by the check constraint |
| `0012` | `sheet_item.expected_answer` |
| `0013` | box height widened from four presets to any 0–14 |
| `0014` | `sheet.default_points_*` and `sheet_item.points_*` — the teacher's barème |

> Migrations reproduce the models; the unit tests build their schema with
> `create_all()` and **structurally cannot** catch drift. Run
> `scripts/check-schema-drift.py` against a disposable Postgres.

---

## 5 · Geometry and layout versioning

The numbers themselves are in [`sheet-layout.md`](sheet-layout.md) and are
printed from `layout.py`. What matters here is the *contract*.

**One source, three consumers.** `apps/api/alppy/sheets/layout.py` is the only
place a millimetre is typed. It reaches:

- the markup, through `html.geometry_context()` → `geometry.css.j2` (generated
  stylesheet, no design decisions, no colour literals);
- the PDF, because the PDF is that markup in Chromium;
- the detector, which computes bubble centres with `layout.bubble_centre_mm`;
- TypeScript, through `scripts/export-layout.py` →
  `packages/shared/src/layout.generated.ts`, **CI fails if stale**.

**The frame.** The four fiducial *centres* define a 174 × 261 mm registration
frame at origin (18, 18). `BubbleSlot.u/v` normalise any coordinate into it, so
the detector needs nothing from the page but those four squares.

**Why borders, not backgrounds.** Browsers default to not printing background
graphics. A fiducial, a set UID cell or a keyed bubble drawn as a `background`
disappears on the one machine that matters — the teacher's printer.
`geometry.css.j2` therefore fills boxes with a border half the box wide, and
`html_to_pdf` renders with `print_background=False` **on purpose**, so a mistake
here fails in CI rather than in a classroom.

**Margins are passed explicitly.** Chromium's own default print margin is
0.4 in; a silent 10 mm would shift every fiducial. `html_to_pdf` passes
`layout.MARGIN_MM` on all four sides, matching the `@page` rule.

**The two media reconciled.** On screen `.print-page` is the whole sheet with
14 mm padding; in print `@page` supplies the margin and the element covers only
the 182 × 269 mm content box. `.sheet-geometry` spans the whole sheet in both
(`inset: -14mm` in print), so every child positions in raw page millimetres.
This is also what makes `measure_answer_boxes` correct: a rectangle relative to
`.sheet-geometry` *is* a rectangle in page millimetres.

### Bumping to v2

1. Add the new constants **alongside** the old ones; do not edit v1's numbers.
2. Keep `LAYOUT_VERSION` selectable, and teach `detector`/`process_page` to
   dispatch on `Sheet.layout_version` (it already takes `layout_version`).
3. Leave existing sheets rendering and scanning exactly as before — the storage
   key already carries the version (`sheets/{id}/{version}/blank.pdf`).
4. Regenerate `layout.generated.ts`.

Adding a constant that positions nothing a machine reads is **not** a bump:
`ANSWER_BOX_*` was added under v1 for exactly this reason (D42), and so was the
carried-over box (D44) — no fiducial, UID cell or bubble moved.

---

## 6 · The item model and pagination

`pagination.py` is pure: frozen dataclasses in, frozen dataclasses out, no ORM,
no browser, no design system.

### `Item`

The database-free printable exercise: `key` (the exercise id, as a string),
`type`, `statement`, `options`, `answer_index`, `answer_text`, `language`,
`ai_generated`, `open_lines`, `box_fill`, `figure`.

- `option_count` — 2 for `true_false`, `min(len(options), 4)` for `mcq`, **0**
  for `open`. Zero options is exactly what makes an item printable and never
  auto-graded by bubble.
- `option_letters` — `ABCD`, or `VF`/`RF`/`TF` by sheet language. **Positions
  never move; only the glyph does**, which is why the detector needs no
  language.
- `Item.true_false_index(bool)` — the single place `answer_bool` becomes an
  option index (0 = true, 1 = false, in every language).

### Height estimation

Deliberately an over-estimate; it decides *where to break*, never where
anything sits. Every rounding rounds up. Breaking early costs a sheet of paper;
breaking late costs the bottom of a question.

```
BODY_L_MM   = 1.125 rem × 16 px ÷ (96/25.4)     ≈ 4.76 mm
LINE_H_MM   = BODY_L_MM × 1.6                    ≈ 7.62 mm
AVG_CHAR_EM = 0.5      # pessimistic for Nunito: predicts more lines than drawn

REGION_H_MM = ITEMS_BOTTOM_MM − ITEMS_TOP_MM     = 148 mm
USABLE_H_MM = 148 − INSTRUCTIONS_H_MM(10) − REGION_BOTTOM_PAD_MM(4) = 134 mm
```

`REGION_BOTTOM_PAD_MM` is not decoration: it is the slack that absorbs the
estimate's error, so a statement a millimetre over does not touch the grid
caption.

Item height = padding (6) + rule (0.2) + statement-or-figure + options + box
block. The box block is `OPEN_LINES_MARGIN_MM (4) + lines × 8 mm +
BOX_MARGIN_BOTTOM_MM (tick + 0.5)`.

### `paginate()`

A page ends as soon as **either** limit is reached:

1. **bubbles** — `ITEMS_PER_PAGE` = 16 rows exist on the fixed grid;
2. **statement height** — 134 mm, which is the limit that binds in practice
   (roughly ten one-line items).

An empty item list still yields one page: a copy always needs a sheet with a
header and a UID or the student has nothing to hand in.

**When an item does not fit as a whole** (D44):

- if it has a box, and the statement alone fits, and the continuation fits →
  place it **twice**: `part="statement"` (question, no box) on this page, then a
  flush, then `part="box"` on the next (number, "(suite)", the box). Each part
  gets its own page-local `item_index`. The box moves whole, never split — a
  crop cut in two is two crops for the grader. The scan job records a detection
  only against the **box** part.
- otherwise → `ItemTooTallError`, naming the printed number and an excerpt.
  Refused rather than clipped, because the statement region is
  `overflow: hidden` and a clipped statement prints a question with no ending
  and tells nobody.

`allow_overflow=True` restores place-it-anyway for a caller that would rather
show a clipped preview than nothing; `Page.overflowing` then marks the page.

`ANSWER_BOX_MAX_LINES = 14` is derived, not chosen: `continuation_height_mm`
for 14 lines is 133.3 mm of the 134 mm available. `test_sheet_output` fails if
the ceiling and the continuation height ever disagree.

### Figures (a crop of the textbook page)

A `Figure` prints **in place of** the statement — the picture *is* the
statement, as the book set it — with the text kept as `alt` and for the key.
`show_statement=True` additionally prints the teacher's own wording above it.

- Printed at 1:1, **never enlarged**, shrunk only to fit the column or
  `FIGURE_MAX_H_MM` (116 mm).
- `figure_room_mm()` lowers that ceiling by whatever text the item prints above
  the picture, so a figured item always fits a page on its own. It deliberately
  does **not** subtract the box (D44): the crop keeps its size and the box moves
  to the next page instead.
- Too tall is **shrunk, never refused** (D41). The crop is a raster at print
  resolution, so it stays sharp; the preview shows the teacher how small.
- `printed_figure_size_mm()` is the single place the printed size is decided —
  pagination reserves it and the markup writes it as an inline style, so they
  cannot disagree.

---

## 7 · The print document

One standalone HTML file, produced by `html.render_sheet_html(sheet_data,
kind=...)`. The browser preview and the PDF are the *same document*.

### Composition

```
sheet.html.j2
  <style> packages/ui/src/design/tokens.css   ─┐ read from disk at render time,
  <style> packages/ui/src/design/base.css      │ never vendored, never cached
  <style> packages/ui/src/design/print.css    ─┘
  <style> geometry.css.j2                       generated from layout.py
  <body><div class="print-sheet">
    _page.html.j2  ×N        ← one per PHYSICAL page
      fiducials ×4
      .print-header  (title, meta, key badge)
      .print-uid-grid (32 cells)  +  .print-uid (human-readable)
      .sheet-items → _item.html.j2 ×n
      _answer_grid.html.j2   (omitted entirely when the page has no bubble item)
      .print-footer  (folio, uid, layout version)  [+ _legend.html.j2]
```

`design_css_dir()` walks up for `packages/ui/src/design`, or takes
`$ALPPY_DESIGN_CSS_DIR`. Not finding it raises `DesignSystemNotFoundError` and
is **deliberately fatal**: rendering with a fallback stylesheet would silently
move the fiducials, and a sheet whose fiducials moved is a sheet the scan
pipeline reads as a different student's answers.

`data-theme="light"` is set on `<html>`: the sheet is paper, and paper does not
follow the reader's dark-mode preference.

### The two kinds

`SheetKind.BLANK` and `SheetKind.ANSWER_KEY` are the **same markup**. The key
adds, and only adds:

- `data-key="true"` on the correct bubble's mark,
- a `CORRIGÉ` / `LÖSUNG` / `ANSWER KEY` badge in the header,
- the expected answer under a written item (`t.expected`), printed once — on
  the `box` part when the item was carried over.

Every coordinate is byte-identical. `render_both()` returns both, because a
design that produces only the first has not produced a printable sheet.

### Markup contract (data attributes)

These are read by tooling — `measure_answer_boxes`, the e2e tests, the print
CSS — so they are API, not decoration.

| Attribute | On | Meaning |
|---|---|---|
| `data-sheet-kind` | `.print-sheet` | `blank` \| `answer_key` \| `feedback` |
| `data-layout-version` | `.print-sheet` | the version this document was laid out with |
| `data-page` / `data-copy-uid` / `data-copy-page` | `.print-page` | document-wide number (collation only), student UID, the student's own folio |
| `data-fiducial` | `span` | `tl` \| `tr` \| `bl` \| `br` |
| `data-filled` | `.print-uid-cell` | one of the 32 bits |
| `data-item-index` | `.print-item`, `.sheet-grid-row` | **page-local** index — how a detection is addressed |
| `data-number` | `.print-item` | the printed, continuous question number |
| `data-part` | `.print-item` | `whole` \| `statement` \| `box` |
| `data-answer-box="true"` | `.sheet-answer-box` | what `measure_answer_boxes` selects |
| `data-fill` / `data-lines` | `.sheet-answer-box` | what the crop step subtracts |
| `data-key="true"` | `.print-bubble-mark` | answer key only |
| `data-student-facing="true"` | `.sheet-items`, statements, options | the `body-l` floor applies (the instructions inherit it from the section) |
| `data-ai-generated="true"` | `.print-item` | the one place the mandarin accent is allowed |

### The footer is the student's

"Page 1/2" is the folio of *their copy*, never "36/72" of the class pile (D41).
The document-wide number stays in `data-page` for the printer's collation,
which is the only reader that wants it.

### Instructions

`_instructions()` prints only the sentence that applies to what is on **this**
page: the bubble sentence if any item is gradeable, the written-answer sentence
if any is not, both if both. A page of written items alone prints no answer
grid at all and says nothing about bubbles.

### The answer box

```
  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐   ← L-shaped corner ticks,
  ⌐                                             ¬        3 mm arms, OUTSIDE
  │                                             │        the border
  │   guides: SVG pattern, 8 mm lines or 5 mm   │
  │   grid, or nothing                          │
  └                                             ┘
```

- Border 0.35 mm (1 pt), ticks outside it, guides as **inline SVG** — so all of
  it prints with background graphics off (I5).
- Height is decided by pagination and written **inline** (`style="height: …mm"`),
  so the millimetres reserved and the millimetres printed are one number.
- `box_fill = blank` prints border and ticks only.
- `open_lines = 0` prints **no box** — the teacher's "worked in the notebook".
- The furniture is what the crop step removes: border and ticks by geometry,
  guides by luminance inside narrow bands (see §12).

### The feedback document

`render_feedback_html(FeedbackData)` — deliberately **not** a variant of
`SheetData` and deliberately not routed through `physical_pages`/`paginate`.
It carries no fiducials, no UID grid and no answer grid: a page that is never
scanned must not *look* like a page that is, so a stack of feedback pages fed
into the scanner by accident is rejected outright rather than read as blank
answers for the child whose UID is printed on them. See I4.

---

## 8 · Rendering

`sheets/render.py` is the only module that opens a browser, touches the ORM, or
writes to the object store.

### `html_to_pdf(html) -> bytes`

`_printed_page()` is the single place Chromium is opened, so the PDF pass and
the measurement pass see the document identically: `media="print"`,
`color_scheme="light"`, `set_content` (no base URL, no network).

```python
page.pdf(format="A4", print_background=False, prefer_css_page_size=True,
         display_header_footer=False, margin={... layout.MARGIN_MM ...})
```

`BrowserUnavailableError` (environment: Chromium missing) is a **distinct**
type from `SheetRenderError` (data: no students, no items, a bad UID), so a
caller can tell "install the browser" from "this sheet cannot be rendered".
`browser_available()` is a cheap probe for callers and tests that want to
degrade rather than fail.

**Determinism** (I13) means the same sheet renders the same *document* every
time: no clock reaches the markup (dates arrive as an explicit label), copies
are ordered by UID, page numbers are derived. The PDF *bytes* still differ —
Chromium stamps a creation date — so determinism is asserted against the HTML,
which is where all the decisions live.

### `measure_answer_boxes(html) -> list[MeasuredBox]`

Runs the same document in the same print media and asks the browser for each
`[data-answer-box="true"]` element's `getBoundingClientRect()`, expressed
relative to `.sheet-geometry` and divided by `96/25.4`.

Measured rather than computed, because a bubble sits where the layout says and
a box sits under text whose wrapping only the browser knows. Pinning every item
at its estimated top — the alternative — would put uneven gaps on every printed
sheet, including ones with no box (D42).

A document with no box opens no browser at all. Every returned box is checked
against `ITEMS_TOP_MM..ITEMS_BOTTOM_MM` (±0.5 mm) and a box outside it **raises**
— loud, for the same reason the PII gate raises (I8).

### Rows → `SheetData`

| Function | Produces |
|---|---|
| `build_sheet_data(db, sheet, show_legend=, require_instances=)` | the saved sheet: one `Copy` per `SheetInstance` (or per student if none yet), ordered by UID |
| `build_draft_sheet_data(db, …, items=…)` | the unsaved draft: **one** copy, using the first student's UID so the grid is real rather than drawn |
| `build_feedback_data(db, sheet)` | approved, non-discarded notes only; `None` when nobody has one |

`_item_from_exercise()` resolves the precedence in one place:

```
statement : SheetItem.statement_override  →  variant.statement  →  exercise.statement
options   : variant.options               →  exercise.options
answer    : variant.answer_*              →  exercise.answer_*
answer_text (the key / grader reference)  : SheetItem.expected_answer → exercise.answer_text
box lines / fill                          : SheetItem.answer_box_*    → defaults (5, lined)
figure    : only when there is no variant — a rewording and the book's picture contradict each other
```

`_instance_items()` exists because a differentiated instance carries only ids in
its `item_plan`; the teacher's wording, box and expected answer live on the
`SheetItem` and must be looked up by exercise id or they are silently dropped
from the paper.

`_figure_from_exercise()` inlines the crop as a `data:` URI (the renderer has no
base URL and must not fetch from the object store while Chromium waits). A crop
that cannot be read is **logged and dropped** — the item prints its text, so the
teacher gets a sheet with a visible gap rather than no sheet.

### Entry points

| Function | Writes |
|---|---|
| `render_sheet_pdfs(db, sheet_id)` | `blank.pdf`, `answer-key.pdf`, `layout_version`, `rendered_at`, `page_count` per instance, all `AnswerBoxPlacement` rows |
| `render_adaptive_batch(db, sheet_id)` | the same, from `adaptive-batch*.pdf` keys, with the mastery legend, plus `feedback.pdf` |
| `render_feedback_pdf(db, sheet_id)` | `feedback.pdf` alone, or clears the key when nobody has an approved note |

Both PDF entry points call `_refuse_unapproved()` **first** (I9). It is checked
here, in the render path, and not only where the sheet was assembled: a sheet
can be re-rendered long after it was built and an exercise can be un-approved in
between. This is the last door, so it is the one that has to be locked.

Placements are measured from the **blank** document — that is what the students
write on, so its boxes are the ones the scanner will crop.

### Storage

```
sheets/{sheet_id}/{layout_version}/blank.pdf
                                  /answer-key.pdf
                                  /feedback.pdf
                                  /adaptive-batch.pdf
                                  /adaptive-batch-answer-key.pdf
```

The version is in the key so an old scan stays resolvable against the exact
document it was printed from. `store_pdf()` writes through
`alppy.storage.get_storage().put_bytes`; the `$ALPPY_RENDER_DIR` fallback exists
only for a deployment with no object store at all, and a failure to reach the
store is logged, not raised.

---

## 9 · Jobs

Nothing blocks a request handler on Chromium.

| Job | Enqueued by | Body |
|---|---|---|
| `RENDER_SHEET` | `POST /sheets/{id}/render` | `tasks.render_sheet` → `render_sheet_pdfs` |
| `GENERATE_ADAPTIVE` | `POST /adaptive/batch/{id}/render` | `tasks.generate_adaptive` → `render_adaptive_batch` |
| `PROCESS_SCAN` | scan upload | OpenCV only; chains `GRADE_OPEN_ANSWERS` |
| `GRADE_OPEN_ANSWERS` | chained by the worker | one vision call per pending box |

The client polls `GET /jobs/{id}`. The web app re-fetches the **sheet** when the
job reports `succeeded`, because the PDF keys land on the sheet row and without
that refetch the render succeeds, the files exist, and the download buttons
never appear.

---

## 10 · API surface

| Method | Path | Returns | Notes |
|---|---|---|---|
| `POST` | `/sheets/propose` | `SheetProposeResponse` | the one read path that can reach a model provider; per-teacher rate limit |
| `GET` | `/sheets?class_id=` | `SheetOut[]` | newest first, scoped to owned classes |
| `POST` | `/sheets` | `SheetOut` 201 | creates items **and** one instance per student |
| `GET` | `/sheets/{id}` | `SheetOut` | |
| `PATCH` | `/sheets/{id}` | `SheetOut` | replacing items re-plans every instance and **invalidates the render** (`*_pdf_key = NULL`, `rendered_at = NULL`) |
| `POST` | `/sheets/{id}/render` | `JobOut` 202 | paginates first (`_assert_printable`) so a too-tall statement is a 422 now, not a failed job later |
| `POST` | `/sheets/preview` | `text/html` | the unsaved draft; **nothing is written** (D29) |
| `GET` | `/sheets/{id}/preview?kind=` | `text/html` | the same markup the PDF is made from |
| `POST` | `/sheets/{id}/printed` | `SheetOut` | records `SHEET_PRINTED`; the one lifecycle moment nothing in the schema could observe |
| `POST` | `/adaptive/batch` | `SheetOut` 201 | binds N students to N item plans; approval gate at the **first** door too |
| `POST` | `/adaptive/batch/{id}/render` | `JobOut` 202 | one PDF for the whole differentiated class |

**Error shape.** A sheet that cannot be laid out answers **422** with the
renderer's own message ("item 7 needs about 150 mm but a page has only 134 mm…",
"class 7B has no students: nothing to print a UID for"). Both preview endpoints
catch `SheetRenderError | ValueError` for this reason: an iframe would otherwise
render raw error JSON at the teacher.

**`load_optional`** is used for every `alppy.sheets.render` import in the API
layer, so an API deployment without Playwright still starts and reports the
missing feature instead of failing at import.

**Why preview is a POST that stores nothing** (D29): redrawing the page in React
duplicates the geometry `layout.py` owns — the previous hand-rolled attempt put
bubbles inline instead of on the fixed grid, printed no UID grid and hardcoded
A/B/C/D where the sheet prints V/F — and creating a real draft `Sheet` writes a
row plus one `SheetInstance` per student on every edit.

---

## 11 · The builder (web)

### Scope and language

Class and subject come from the **sidebar** (`useScope()`), shown as
"Pour 7B · Mathématiques" under the title (D45). They were once two more selects
on this page, and a sheet built under one scope while the sidebar showed another
was a sheet for the wrong pupils.

The sheet's `language` is `draftLanguage()`: the **majority language of its
exercises**, not the UI locale and not `items[0]` (reordering used to flip a
French sheet to German). `draftHasMixedLanguages()` warns when a sheet mixes
them.

### The draft

`useDraftSheet()` holds whole `ExerciseOut` objects, not ids, and is
deliberately independent of whatever the picker is showing: the picker is a
*viewport* onto a corpus of thousands that refilters constantly, and a selection
living in the visible list would silently drop ticks on a filter change. The e2e
suite asserts exactly this ("ticks survive a filter change").

`toSheetItemIn(item, position)` is the single place a draft item becomes the API
shape, used by both the preview and creation — so the paper previewed is the
paper printed. Box and expected answer are sent **only** for `open` items.

### The composer

- The page budget is the subtitle: item count + `minPages`, a floor computed
  from the 16-row grid only. The **server preview stays the authority**, because
  statement height also decides the count.
- An open item's settings are one summary line until opened (a native
  `<details>`): "Cadre de 5 lignes, lignes · réponse trouvée par le modèle".
  Twelve open panels is what made the composer unreadable.
- Presets 0/3/5/8/12 as shortcuts, plus a custom height clamped to
  `MAX_ANSWER_BOX_LINES` — all read from `SHEET_LAYOUT`, never typed twice.
- Reordering offers arrows (keyboard-reachable, 44 px, works on a phone) **and**
  a drag handle (HTML5 DnD, not a library: the Worker bundle has a 3 MiB
  ceiling, D25).

### The preview

`DraftPreview` posts the draft, debounced 400 ms, keyed on a serialised
signature rather than array identity, and renders the returned document in an
`srcdoc` iframe with `sandbox=""` (the document is ours and runs no script). It
is scaled with a `ResizeObserver` attached through a **ref callback** — an
effect with an empty dependency array ran before the node existed and pinned the
scale forever.

The saved-sheet page uses `src` instead (`GET …/preview`) with
`sandbox="allow-same-origin allow-modals"`, because printing means calling
`print()` on that frame: the preview iframe **is** the print document, served
with the same `print.css` the PDF is made from. `allow-modals` is what lets a
sandboxed frame open the print dialog; without it the button silently does
nothing. If the frame cannot be driven, it falls back to opening the document in
its own tab.

Taking the blank PDF — or printing the blank frame — fires `POST
/sheets/{id}/printed`, fire-and-forget.

---

## 12 · What the scan pipeline consumes

The sheet's obligations do not end at the printer. Three things it records are
read back, and getting any of them wrong misgrades a class.

**1 · The layout version.** A scan is registered against
`Scan.layout_version or Sheet.layout_version`, never against "the current one".

**2 · The pagination.** `scan_processing._copies_by_uid()` re-runs
`build_sheet_data` + `paginate` to get each copy's page list, keyed by UID
because a differentiated batch gives each student a different item list — copy
`7B_03` may have four MCQs where `7B_07` has two true/false items, so "how many
bubbles are on row 3" has a different answer per copy. A photographed page is
mapped with `seen[uid] % len(printed_pages)`.

> This is why I4 exists. Any page the renderer emits *inside* a copy that this
> count does not know about rotates every later page onto the wrong item list —
> silently, with confident detections.

**3 · The answer-box rectangles.** `_placements_by_uid()` reads
`AnswerBoxPlacement` straight off the rows the render job wrote —
`uid → copy_page → item_index → placement` — and never re-derives a box.
`scan/answer_box.py` then:

1. crops at that rectangle in the canonical 8 px/mm registered frame, so a phone
   photo at an angle crops the same box a flatbed does;
2. paints out the border and corner ticks **by geometry** (a band
   `ANSWER_BOX_BORDER_MM + 0.75` in from each edge), and the guides by position
   *and* luminance — only pixels lighter than 45 % of local paper are removed,
   so a pen stroke crossing a guide survives;
3. reports `ink_ratio`; below `BLANK_INK_RATIO` the box is **blank**, and a
   blank needs no model call.

`open_answer_grading.py` then makes one vision call per remaining crop, with
`grade_open_answer.v2`, and settles every row:

- the teacher's `SheetItem.expected_answer` → else `Exercise.answer_text` → else
  `NO_EXPECTED_ANSWER`, in which case the model works the answer out first and
  returns it as `reference`, kept on the detection for the teacher to see. **A
  placeholder string is never substituted** — v1 did, and the model judged
  against the placeholder (D43).
- a failed call, an ungrounded provider, an unreadable answer → `NOT_GRADEABLE`.
  **Nothing stays pending**, and a missing verdict is never a zero (I10).

---

## 13 · i18n

The sheet has almost no chrome by design, so its strings live in
`html._STRINGS` (fr/de/en) rather than in the web catalogues, with
`_BAND_LABELS` for the mastery legend. `strings(language)` falls back to
English, never to nothing.

Two rules that bite here:

- **Exercise content follows the language of the source material**, never the UI
  locale. A German textbook exercise prints in German on a sheet a
  French-speaking teacher built.
- **Option glyphs are per sheet language** (`VF` / `RF` / `TF`) while positions
  never move. `packages/shared` + `lib/optionLetters.ts` mirror this so the web
  preview cannot show A/B where the paper prints V/F.

The builder's own UI strings are in `apps/web/messages/{fr,de,en}.json` under
`builder.*` and `sheets.*`; `pnpm i18n:check` fails on a key missing from any
locale.

---

## 14 · Failure modes

| Condition | Where it surfaces | Behaviour |
|---|---|---|
| A statement taller than 134 mm | `paginate()` | `ItemTooTallError` → 422 naming the item number and an excerpt |
| An open item whose statement + box exceed a page | `paginate()` | split into `statement` + `box` parts across two pages |
| Class with no students | `build_sheet_data` | `SheetRenderError` → 422 ("nothing to print a UID for") |
| Sheet with no items | render endpoint / `build_sheet_data` | 422 |
| A class year outside 1–15, or a malformed UID | `encode_uid`, called by `physical_pages` **before** any page is built | raises up front, not mid print run |
| An unapproved AI exercise | `_refuse_unapproved` at render, `ensure_printable` at batch creation | `SheetRenderError` / 422 with the exercise ids |
| An answer box measured outside the statement region | `_check_box_inside_statement_region` | `SheetRenderError` — the render fails rather than emitting a crop that might carry a code |
| A textbook crop that cannot be read from storage | `_figure_from_exercise` | logged, dropped, the item prints its text |
| Chromium missing | `_printed_page` | `BrowserUnavailableError` with the install command |
| Object storage unreachable | `store_pdf` | logged, falls back to `$ALPPY_RENDER_DIR` |
| The design CSS not found | `design_css_dir` | `DesignSystemNotFoundError` — fatal on purpose |
| A box that cannot be cropped from a scan | `_crop_answer_boxes` | logged, skipped; that item stays `NOT_GRADEABLE` |
| A UID grid misread | `decode_uid` | CRC-8 rejects; the page goes to the teacher for manual assignment |

---

## 15 · Test map

Everything above is asserted somewhere. When changing this feature, these are
the files that should fail first.

| File | Guards |
|---|---|
| `test_layout.py` | the geometry is self-consistent: bubbles inside the frame, never overlapping each other or the fiducials, grid below the statement region, UID cells disjoint, `as_dict()` complete |
| `test_uid_code.py` | round trip, **all 32 single-bit and all 496 double-bit flips rejected**, wrong length, unrepresentable class year |
| `test_sheet_output.py` | too-tall refused and named, headers on every page, `allow_overflow`, statement override reaches the paper, figure sizing and the room left for text, box height/ticks/fill in the markup, the box never shrinks a picture, the continuation prints number + "(suite)" + box only, the key prints the sheet item's answer, written items have no grid row, and **the 14-line ceiling still fits a carried-over page** |
| `test_answer_box_placement.py` | a document with no box is not measured at all; the measured rectangle is the border the paper shows; rendering writes one placement per box per copy |
| `test_answer_box_crop.py` | furniture subtraction, blank detection |
| `test_print_scan_roundtrip.py` | a rendered page registers and gives up its UID; a filled bubble is read at the coordinate the layout promised; **the feedback document carries nothing the scanner registers on** |
| `test_api_sheets.py` | one instance per student, unique positions, PATCH invalidates the render, the expected answer round-trips, any height up to the ceiling |
| `test_open_grading.py`, `test_scan_processing.py` | verdict-only grading, nothing left pending |
| `apps/web/e2e/sheet-builder.spec.ts` | document → chapter drives the list, ticks survive a filter change, paging hits the API, the preview stays closed until asked, a hand-written true/false reaches the sheet, deleting the correct answer clears the key, reordering, an open item's box is sized by the teacher, the chapter names the sheet |
| CI: `export-layout.py` re-run | `layout.generated.ts` is not stale |
| `scripts/check-schema-drift.py` | migrations reproduce the models (needs a disposable Postgres) |

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q -k "sheet or layout or uid or box or roundtrip"
pnpm test:e2e -- sheet-builder
```

---

## 16 · Extension recipes

### Add a new exercise type with bubbles

1. `ExerciseType` + `Item.option_count` / `option_letters`. Positions must not
   move; only glyphs may.
2. If it needs more than 4 options, that is `MAX_OPTIONS` — **a layout version
   bump** (§5).
3. `_row_context` and `_item_context` follow automatically; check
   `Page.option_counts` and `answer_indices` still describe it.
4. `detector.process_page` takes `option_counts`; nothing else in the scan path
   needs to know the type.

### Add a new document kind

1. Extend `SheetKind` and give it its **own** template + `render_*_html`
   function. Do **not** add pages to a copy (I4).
2. If it must never be scanned, print no fiducials, no UID grid, no answer grid
   — and add a case to `test_print_scan_roundtrip.py` asserting the detector
   rejects it.
3. Add a storage key and a `*_pdf_key` column; serialise it in `sheet_out`.

### Change the answer box

- Furniture constants (`ANSWER_BOX_*`) live in `layout.py` because the *crop
  step* needs them a priori, even though the box's position does not.
- If you change the border, ticks or guide pitch, update `EDGE_BAND_MM` /
  `GUIDE_BAND_MM` in `scan/answer_box.py` in the same commit — they are the
  numbers that erase what you just printed.
- If you change `ANSWER_BOX_MAX_LINES`, `test_sheet_output` will tell you
  whether the continuation still fits a page. Do not raise it by hand.

### Add a per-item printed option

The path is fixed and short: `SheetItemIn` (schema, with validation) →
`_replace_items` (drop it for the types it is meaningless on) → `SheetItem`
column + migration → `_item_from_exercise(box_lines=…, …)` → `_instance_items`
lookup by exercise id (**or it is silently dropped from a differentiated
batch**) → `_item_context` → the template → `SheetItemOut` → `toSheetItemIn`
and the composer.

`points_correct` (D46, migration 0014) is the worked example end to end, with
two departures worth copying only when they apply:

- It is **not** dropped for any type. The rule is "drop it where it is
  meaningless", and a point value never is — an `open` item is not auto-graded
  today and will be as soon as a verdict arrives through `register_grader`.
- It has a **sheet-level default** beside the per-item column, resolved by
  `render._points_for` and `scan_service._resolve_policy`. Both test
  `is not None`, never truthiness: a deliberate `0` is an override, and reading
  it as absent hands the item the default back.

Anything printed inside the statement also costs width. `points_correct` takes
`POINTS_LABEL_W_MM` out of `pagination.TEXT_W_MM`, which every wrap estimate
already reads — shrinking that constant makes the estimate larger than the
truth, which is the safe direction (§6).

---

## 17 · Known gaps

Recorded so they are not rediscovered as surprises.

- **Editing a saved sheet in the builder.** `PATCH /sheets/{id}` accepts a new
  item list, but the list screen opens `/sheets/[id]`, which has no editor
  (D45).
- **Vision-grading cost is unbudgeted.** A class of 28 with three written items
  is 84 vision calls per pile. The audit log prices them; nothing caps them.
  Batching several crops of one copy into one call is the obvious next step
  (D42).
- **Sheet PDF keys do not follow the canonical storage key shape.**
  `storage_key()` produces `sheets/{sheet_id}/{version}/{name}`, while the local
  backend's `GET /api/v1/files/{key}` tenant check compares the **second**
  segment against the school id (`<kind>/<school_id>/<entity_id>/<name>`). On S3
  this is invisible — `url_for` returns a presigned URL — but a local-storage
  deployment will 404 on every sheet PDF download. Either the key gains the
  school id or the route learns this shape.
- **No "grade without an answer" for a book exercise that has one.** Clearing
  `expected_answer` falls back to the book's (D43).
- **The answer grid is below the statements, not beside them** (D1). The
  decision most worth revisiting after watching a class use one.
- **Units and phases** — a sheet knows `derived_from_id` but the data model has
  no notion of a teaching unit (D45).
