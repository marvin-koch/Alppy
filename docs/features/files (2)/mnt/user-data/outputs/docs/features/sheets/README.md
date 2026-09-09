# Sheets Feature

**Status:** describes `main` as of 2026-09-09  
**Audience:** developers, LLM agents, reviewers  
**Layout version:** v1

---

## 1 · What it does

A *sheet* is the printed A4 worksheet a teacher hands to a class, plus its answer key, plus — for a differentiated batch — a per-student feedback page. It is the product's centre of gravity: the paper is the deliverable, and every other subsystem (ingest, retrieval, scan, mastery) either feeds it or reads it back.

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

### Key Properties

1. **A printed page is self-describing.** Four fiducials, a checksummed UID grid, and bubbles at coordinates fixed by the layout. The detector needs no text, no OCR, no per-sheet calibration.

2. **One renderer.** The in-app preview, the PDF, and the geometry the detector samples all come from the same module (`alppy.sheets.html`) reading the same constants (`alppy.sheets.layout`) and the same design system CSS.

3. **Everything the scanner needs is recorded at print time.** The layout version on the sheet, the page count on the instance, the answer-box rectangles in their own table. Nothing is recomputed from rows that may have changed since the paper left the printer.

---

## 2 · Invariants (Load-Bearing)

These are rules a reviewer has to enforce by reading. Each names where it is enforced and what breaks when it is not.

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-sheets-01 | **No AI-generated exercise reaches paper without `approved_at`.** Checked at the last door, the render path. | `render._refuse_unapproved()` | Unreviewed AI content is handed to children | Safety: incorrect/nonsense exercises on paper |
| I-sheets-02 | One `.print-page` is **one physical page**, never one student's copy. Every page carries its own header and UID. | `_page.html.j2`, `physical_pages()` | A second page belongs to nobody and cannot be graded | Second page of multi-page sheets is orphaned, ungraded |
| I-sheets-03 | Changing any number in `layout.py` is a **layout version bump**, never a tweak. | review; `Sheet.layout_version`, `storage_key()` | Scans of last term's pile register against the wrong coordinates | Old scans misalign; students' old work becomes ungraded |
| I-sheets-04 | Always **two documents** — blank and answer key — from the same `SheetData`. | `render_both()`, `render_sheet_pdfs()` | Teacher cannot correct the pile with matching answer key | Teacher prints blank but answer key is stale; grading is wrong |
| I-sheets-05 | Every mark the pipeline reads is drawn as a **border, not a background**. | `print.css`, `geometry.css.j2`, `print_background=False` | Teacher prints with backgrounds off and every scan fails to register | Printed marks invisible to detector; all sheets fail scanning |
| I-sheets-06 | `PlacedItem.item_index` is **page-local 0..15** and resets on every page; `PlacedItem.number` is the continuous printed number. | `pagination.paginate()` | A whole class is graded against the wrong questions | Questions renumber on page break; grading is off-by-N |
| I-sheets-07 | An **answer box is cropped where it printed**, from `AnswerBoxPlacement`, never recomputed from `SheetItem`. | `render._persist_answer_box_placements()`, `scan_processing._placements_by_uid()` | An edit after printing moves what the scanner crops | Cropped answer box drifts; question answers are swapped |
| I-sheets-08 | A **crop never leaves the statement region** (`ITEMS_TOP_MM..ITEMS_BOTTOM_MM`). | `render._check_box_inside_statement_region()` | A crop carries the header, i.e. a student code, to a model provider | Privacy leak: student ID sent to LLM |
| I-sheets-09 | **Student-facing text never below `body-l`** (1.125 rem). The textbook crop is exempt: it reproduces the book at 1:1. | `print.css`, decision D40 | Unreadable paper | Students cannot read questions; learning lost |
| I-sheets-10 | The sheet is rendered **deterministically**: copies ordered by UID, no clock in the markup, page numbers derived. | `build_sheet_data()`, `physical_pages()` | Two renders of one sheet produce different piles | Audit trail breaks; re-renders don't match originals |

---

## 3 · Module map

Which files own what?

| Path | Owns | Depends on |
|---|---|---|
| `alppy/sheets/layout.py` | **Every millimetre**, `LAYOUT_VERSION`, bubble/UID coordinates, answer-box furniture constants | nothing |
| `alppy/sheets/uid_code.py` | UID ⇄ 32 checksummed bits ⇄ grid cells | `layout`, `core.uid` |
| `alppy/sheets/pagination.py` | `Item`, `Figure`, height estimation, `paginate()`, `PlacedItem`, `Page` | `layout`, `models.enums` — **no SQLAlchemy** |
| `alppy/sheets/html.py` | `SheetData`/`Copy`, `physical_pages()`, `geometry_context()`, `render_sheet_html()`, the feedback document | `layout`, `pagination`, `uid_code`, Jinja, the design CSS |
| `alppy/sheets/render.py` | `render_sheet_pdf()`, approval gate (I-sheets-01), box placement persistence (I-sheets-07) | `html`, `models` |
| `alppy/sheets/templates/*.j2` | The markup and the generated stylesheet | — |
| `tests/sheets/test_invariants.py` | Tests for all invariants I-sheets-01 through I-sheets-10 | all above |

---

## 4 · How to extend this feature

When adding to the sheets subsystem:

1. **Read §2 invariants** — these are load-bearing rules
2. **List which invariants your change touches**
3. **Add a test** for each invariant affected
4. **Update this document** if you add new rules

### Example: Adding a new question type

```python
# ❌ BEFORE: You want to add a "drag-and-drop" question type

# ✅ AFTER: Check invariants first
# This change touches:
# - I-sheets-02: Must ensure each item fits on one page
# - I-sheets-05: Mark must be a border, not background
# - I-sheets-08: Coordinate crop check needed if images involved

# Add test:
def test_I_sheets_02_draganddrop_fits_page():
    """I-sheets-02: Drag-and-drop questions must fit on one page."""
    ...

def test_I_sheets_05_draganddrop_borders_only():
    """I-sheets-05: Drag-and-drop marks are borders, never backgrounds."""
    ...
```

### LLM Checklist

- [ ] Read §2 (Invariants) — these are not suggestions
- [ ] Which invariants does your change affect?
- [ ] Have you added a test for each affected invariant?
- [ ] Code comments cite invariants (e.g., # I-sheets-01)
- [ ] Reviewed `docs/features/sheets/decisions.md` (why each rule exists)

---

## 5 · Privacy & Safety

| Data | Scrubbing point | Why |
|---|---|---|
| Student name | Never in rendered sheet | Could identify student if cropped image reaches model |
| Student ID (UID) | Never leaves ITEMS_TOP_MM..ITEMS_BOTTOM_MM region (I-sheets-08) | UID in crop = PII leak to model providers |
| Teacher notes | Never on student copy | Privacy of teacher assessment |

**Gate:** Code raises if privacy violated

```python
# I-sheets-08: Crop never leaves statement region
assert box.top >= ITEMS_TOP_MM  # Header is above this
assert box.bottom <= ITEMS_BOTTOM_MM  # Footer is below this
```

---

## 6 · Testing Strategy

Every invariant gets at least one test in `tests/sheets/test_invariants.py`:

```python
def test_I_sheets_01_unapproved_rejected():
    """I-sheets-01: Unapproved AI content never reaches paper."""
    sheet = create_sheet(approved_at=None)
    with pytest.raises(PermissionError, match="I-sheets-01"):
        render_sheet_pdf(sheet)

def test_I_sheets_02_one_page_one_physical():
    """I-sheets-02: One .print-page = one physical page."""
    sheet = create_sheet(items=[...])
    pages = physical_pages(sheet)
    assert len(pages) == expected_count
    for page in pages:
        assert page.has_header()
        assert page.has_uid_grid()

def test_I_sheets_03_layout_version_bump():
    """I-sheets-03: Changing layout.py bumps version."""
    original_version = LAYOUT_VERSION
    # [Simulate coordinate change]
    new_version = LAYOUT_VERSION
    assert new_version > original_version

def test_I_sheets_04_two_pdfs_from_one_sheetdata():
    """I-sheets-04: Render produces blank + answer key."""
    blank, answer_key = render_both(sheet)
    assert blank is not None
    assert answer_key is not None

def test_I_sheets_05_marks_are_borders():
    """I-sheets-05: All marks drawn as borders, not backgrounds."""
    with patch('print.css') as mock_css:
        # Check: print_background=False
        assert "print_background=False" in render_sheet_html(sheet)

def test_I_sheets_06_item_index_resets_per_page():
    """I-sheets-06: item_index is page-local 0..15."""
    pages = physical_pages(sheet)
    for page in pages:
        indices = [item.item_index for item in page.items]
        assert indices == list(range(len(indices)))

def test_I_sheets_07_boxes_from_placements():
    """I-sheets-07: Answer boxes cropped from placement table."""
    placements = persist_answer_box_placements(sheet)
    assert len(placements) > 0
    for placement in placements:
        # Not recomputed from item
        assert placement.from_database

def test_I_sheets_08_crop_in_statement_region():
    """I-sheets-08: Crop never leaves statement region."""
    boxes = extract_answer_boxes(sheet)
    for box in boxes:
        assert box.top >= ITEMS_TOP_MM
        assert box.bottom <= ITEMS_BOTTOM_MM

def test_I_sheets_09_text_readable():
    """I-sheets-09: Student-facing text >= body-l (1.125rem)."""
    html = render_sheet_html(sheet)
    # Parse and check font sizes
    assert min_font_size_rem >= 1.125

def test_I_sheets_10_deterministic():
    """I-sheets-10: Render twice, get identical PDF."""
    sheet_id = "test_sheet_123"
    pdf1 = render_sheet_pdf(sheet_id)
    pdf2 = render_sheet_pdf(sheet_id)
    assert pdf1 == pdf2  # Byte-identical
```

Run all:
```bash
pytest tests/sheets/test_invariants.py -v
```

---

## Companion Documents

- `docs/features/sheets/architecture.md` — Flow diagrams, component interaction
- `docs/features/sheets/decisions.md` — D1–D5: why layout versions, why two PDFs, etc.

---

**When was this last updated?** 2026-09-09
