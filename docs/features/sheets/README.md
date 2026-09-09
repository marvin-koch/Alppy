# Sheets

**Status:** describes `main` as of 2026-09-09
**Audience:** developers, LLM agents, reviewers
**Layout version:** v1

---

## 1 · What it does

A *sheet* is the printed A4 worksheet a teacher hands to a class, plus its answer
key, plus — for a differentiated batch — a per-student feedback page. It is the
product's centre of gravity: the paper is the deliverable, and every other
subsystem either feeds it or reads it back.

The teacher builds an item list (`SheetItem[]`), the sheet is bound to students
(`SheetInstance[]`, one per child, carrying that child's UID and, for a
differentiated batch, its own item plan), and the render job drives headless
Chromium over print markup to produce two PDFs and one row per measured answer box.

```
   a textbook chapter ─┐
   an AI proposal ─────┼─▶  the builder  ─▶  Sheet + SheetItem[] + SheetInstance[]
   the teacher's own ──┘    (draft, unsaved)      │
                                                  │  POST /sheets/{id}/render
                                                  ▼
                              headless Chromium over the print markup
                                                  │
                            ┌─────────────────────┼──────────────────────┐
                            ▼                     ▼                      ▼
                        blank.pdf           answer-key.pdf     AnswerBoxPlacement[]
                            │                                            │
                     photocopier, classroom                              │
                            │                                            │
                            ▼                                            │
                     phone photo / scan  ─▶  alppy.scan  ──────────────▶─┘
                                                  │        (crops each box
                                                  ▼         where it printed)
                                        Detection[] ─▶ Attempt[] ─▶ mastery
```

### Key properties

1. **A printed page is self-describing.** Four corner fiducials, a checksummed UID
   grid, and bubbles at coordinates fixed by the layout. The detector needs no text,
   no OCR and no per-sheet calibration.
2. **One renderer.** The in-app preview, the PDF and the geometry the detector
   samples all come from `alppy.sheets.html`, reading the same constants
   (`alppy.sheets.layout`) and inlining the same design CSS from `packages/ui` at
   render time. The preview and the PDF cannot drift from each other or from the
   design system.
3. **Everything the scanner needs is recorded at print time.** The layout version on
   the sheet, the page count on the instance, the answer-box rectangles in their own
   table. Nothing is recomputed from rows that may have changed since the paper left
   the printer.

---

## 2 · Invariants (load-bearing)

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-sheets-01 | **No AI-generated exercise reaches paper without `approved_at`.** Checked at the last door, the render path, as well as at build time. | `services/approval.py::ensure_printable`, called from `sheets/render.py::_refuse_unapproved` and `services/sheet_service.py::create_adaptive_sheet` | Unreviewed model output is handed to children | Wrong or nonsensical exercises printed and distributed |
| I-sheets-02 | One `.print-page` is **one physical page**, never one student's copy. Every page carries its own header and its own UID, as text and as the grid. | `sheets/html.py::physical_pages`, `templates/_page.html.j2` | A page with no code belongs to nobody | Second page of a multi-page copy comes back ungradeable |
| I-sheets-03 | Changing **any number** in `layout.py` is a layout version bump, never a tweak. | review; `LAYOUT_VERSION`, `Sheet.layout_version`, `render.storage_key` | The detector reads coordinates derived from that file | Last term's pile registers against the wrong coordinates |
| I-sheets-04 | Always **two documents** — blank and answer key — from the same `SheetData`. | `sheets/html.py::render_both`, `sheets/render.py::render_sheet_pdfs` | The key must describe the paper the class actually sat | Teacher corrects a pile against a stale key |
| I-sheets-05 | Every mark the pipeline reads is drawn as a **border, not a background**. | `packages/ui/src/design/print.css`, `templates/geometry.css.j2`, `html_to_pdf(print_background=False)` | Browsers default to dropping background graphics | Fiducials and bubbles invisible; every scan fails to register |
| I-sheets-06 | `PlacedItem.item_index` is **page-local 0..15** and resets on every page; `PlacedItem.number` is the continuous printed number. | `sheets/pagination.py::paginate` | The detector addresses bubbles by that index and nothing else | A whole class graded against the wrong questions |
| I-sheets-07 | An answer box is cropped **where it printed** — from `AnswerBoxPlacement` — never recomputed from `SheetItem`. | `sheets/render.py::_persist_answer_box_placements`, `services/scan_processing.py::_placements_by_uid` | An edit after printing would move what the scanner crops | Crops drift; one student's answers read against another item |
| I-sheets-08 | A crop **never leaves the statement region** (`ITEMS_TOP_MM..ITEMS_BOTTOM_MM`). | `sheets/render.py::_check_box_inside_statement_region` | Above that line sits the header, which carries the UID | A student identifier reaches a model provider inside an image |
| I-sheets-09 | An item that does not fit is **refused, not clipped**; a box that does not fit **follows on the next page** at its full height. The statement never shrinks. | `sheets/pagination.py::ItemTooTallError`, `continuation_height_mm` | Paper does not scroll, and student-facing text has a floor | A statement runs off the bottom edge, unreadably |
| I-sheets-11 | Every sheet has a **home Theme** (`chapter_id`, NOT NULL). Omitting it means `unfiled`; it is never inferred from the items. | `sheet_service::_resolve_chapter` | `Exercise.chapter_id` is itself a guess, and a guess promoted to a filing is one the teacher never confirmed | A sheet is quietly filed under a chapter its teacher never chose, and the tree says so with confidence |
| I-sheets-10 | The render is **deterministic**: copies ordered by UID, no clock in the markup, page numbers derived. | `sheets/render.py::build_sheet_data`, `_stamp`, `html.physical_pages` | A re-render must reproduce the pile that was printed | Two renders of one sheet produce different papers |

> Note on I-sheets-10: the PDF *bytes* differ between runs — Chromium stamps a
> creation date into the file metadata — so determinism is asserted against the
> HTML, which is where every decision lives.

---

## 3 · Module map

| Path | Owns | Depends on |
|---|---|---|
| `alppy/sheets/layout.py` | **Every millimetre.** `LAYOUT_VERSION`, fiducials, UID grid, bubbles, answer-box furniture, the barème ceiling | nothing |
| `alppy/sheets/uid_code.py` | UID ⇄ 32 checksummed bits ⇄ grid cells | `layout`, `core.uid` |
| `alppy/sheets/pagination.py` | `Item`, `Figure`, height estimation, `paginate()`, `PlacedItem`, `Page`, `ItemTooTallError` | `layout`, `models.enums` — **no SQLAlchemy** |
| `alppy/sheets/html.py` | `SheetData`/`Copy`, `physical_pages()`, `geometry_context()`, `render_sheet_html()`, `render_both()`, the feedback document | `layout`, `pagination`, `uid_code`, Jinja, the design CSS |
| `alppy/sheets/templates/*.j2` | The markup and the generated stylesheet | — |
| `alppy/sheets/render.py` | Chromium, `measure_answer_boxes()`, the approval gate, placement persistence, `render_sheet_pdfs()`, `render_adaptive_batch()`, `render_feedback_pdf()` | `html`, `models`, `storage`, `services.approval` |
| `alppy/services/sheet_service.py` | Build, edit, bind instances, points totals | `models`, `approval`, `class_service` |
| `alppy/api/v1/sheets.py` | The endpoints, including `POST /sheets/preview` for an unsaved draft | `sheet_service`, `render` |
| `packages/shared/src/layout.generated.ts` | The same geometry, for the web preview — generated by `scripts/export-layout.py` | `layout.py` |

---

## 4 · How to extend this feature

1. **Read §2.** These are contracts.
2. **List which invariants your change touches** in the PR description.
3. **Add or adjust a test for each**, in the files named in §6.
4. **Update this document** if you add a rule, and `decisions.md` with why.

### If you touch `layout.py`

Any change to a number is `I-sheets-03`. That means:

- bump `LAYOUT_VERSION`;
- confirm old sheets keep their stored `Sheet.layout_version` and that
  `scan_processing` still refuses to read a page printed under another one;
- re-run `scripts/export-layout.py` so `packages/shared` agrees;
- re-run `apps/api/tests/test_print_scan_roundtrip.py`, which prints and scans.

Adding a *new* constant that moves no existing mark (as the answer-box furniture
did) is not a version bump. Moving one is, always.

### LLM checklist

- [ ] Read §2 — these are not suggestions
- [ ] Which invariants does the change affect?
- [ ] Is there a test for each one, and does its name still describe the behaviour?
- [ ] Does the change recompute anything the render job already measured? (I-sheets-07)
- [ ] Does anything new print below `body-l`, or shrink a statement to fit? (I-sheets-09)
- [ ] Read `decisions.md` for the rule you are about to change

---

## 5 · Privacy & safety

| Data | Where it is stopped | Why |
|---|---|---|
| Student name | Never printed on a sheet; the header carries the UID (`7B_15`) | A crop that caught the header would carry an identifier to a provider |
| Student UID | Never inside an answer-box crop — `_check_box_inside_statement_region` refuses a box outside `ITEMS_TOP_MM..ITEMS_BOTTOM_MM` | Geometry, not text, is what keeps identity out of an image |
| Unapproved AI content | `services/approval.py`, raising `UnapprovedExerciseError` at two doors | A teacher must read generated content before a child does |

The gate **raises rather than filtering**. A sheet quietly missing three of its
twelve items is a worse outcome for a teacher standing at a photocopier than an
error naming exactly which items are waiting for a decision.

---

## 6 · Testing strategy

| Invariant | Proved by |
|---|---|
| I-sheets-01 | `test_adaptive_fixes.py::test_the_render_path_refuses_an_unapproved_item`, `::test_a_batch_cannot_be_built_out_of_unapproved_items` |
| I-sheets-02 | `test_sheet_output.py::test_a_normal_sheet_still_paginates_with_a_header_on_every_page` |
| I-sheets-03 | `test_scan_processing.py::test_a_page_printed_under_another_layout_is_not_read`; `test_layout.py` (whole file) |
| I-sheets-04 | `test_sheet_output.py::test_preview_can_render_the_answer_key`, `test_adaptive_fixes.py::test_the_batch_renderer_produces_both_documents` |
| I-sheets-05 | `test_print_scan_roundtrip.py::test_a_printed_page_registers_and_gives_up_its_student_code` |
| I-sheets-06 | `test_layout.py::test_item_index_bounds_are_enforced`, `test_print_scan_roundtrip.py::test_a_filled_bubble_is_read_at_the_coordinate_the_layout_promised` |
| I-sheets-07 | `test_answer_box_placement.py::test_rendering_a_sheet_records_one_placement_per_box_per_copy`, `test_answer_box_crop.py::test_the_crop_is_cut_from_the_registered_page_even_off_a_phone_photo` |
| I-sheets-08 | `test_answer_box_crop.py::test_the_rectangle_sits_inside_the_statement_region`, `::test_a_box_off_the_page_is_refused` |
| I-sheets-09 | `test_sheet_output.py::test_a_statement_taller_than_the_page_is_refused_not_clipped`, `::test_the_box_never_shrinks_the_picture_it_moves_to_the_next_page`, `::test_the_tallest_allowed_box_still_fits_a_page_when_carried_over` |
| I-sheets-11 | `test_api_sheets.py::test_a_sheet_created_without_a_theme_lands_in_unfiled`, `::test_a_theme_from_another_subject_is_refused`, `::test_a_sheet_can_be_refiled_after_the_fact` |
| I-sheets-10 | `test_sheet_output.py::test_preview_returns_the_real_printed_document` (the preview and the PDF are one document), `test_api_sheets.py::test_patching_a_sheet_replaces_items_and_invalidates_the_render`. Determinism itself is asserted against the HTML, never the PDF bytes |

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_layout.py \
  apps/api/tests/test_sheet_output.py apps/api/tests/test_answer_box_placement.py \
  apps/api/tests/test_print_scan_roundtrip.py apps/api/tests/test_api_sheets.py -q
```

`test_print_scan_roundtrip.py` is the one that matters most: it prints a sheet and
scans the result, so the two halves of `I-sheets-03` are checked against each other
rather than argued about (repo log D37).

---

## Companion documents

- [`architecture.md`](architecture.md) — the render pipeline, the data classes, the edge cases
- [`decisions.md`](decisions.md) — why a fixed grid, why two PDFs, why boxes are measured
- [`../../sheet-layout.md`](../../sheet-layout.md) and [`../../sheets-spec.md`](../../sheets-spec.md) — the geometry in full

**Last updated:** 2026-09-09
