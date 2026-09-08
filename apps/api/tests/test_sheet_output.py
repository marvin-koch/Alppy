"""What comes out of the sheet path: the preview, and the refusal to clip.

Both of these shipped broken.

``GET /sheets/{id}/preview`` answered 500 on every request — it called
``render_sheet_html(db, sheet_id=...)``, a signature that does not exist — so
the web app rendered its own approximation of the sheet instead, one without an
answer grid or a UID grid.

Pagination placed an over-long statement on its own page and let
``.sheet-items { overflow: hidden }`` cut it. The student got a question that
stopped mid-sentence with nowhere to write, and nothing told the teacher.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise

from alppy.models.enums import ExerciseType
from alppy.sheets.pagination import (
    FIGURE_GAP_MM,
    FIGURE_MAX_H_MM,
    OPEN_LINES_MARGIN_MM,
    TEXT_W_MM,
    USABLE_H_MM,
    Figure,
    Item,
    ItemTooTallError,
    estimate_item_height_mm,
    figure_room_mm,
    paginate,
    printed_figure_size_mm,
)

FORTY_LINES = "\n".join(f"Ligne {i + 1} de cet énoncé délibérément très long." for i in range(40))


# --------------------------------------------------------------------------
# Nothing is ever silently cut
# --------------------------------------------------------------------------
def test_a_statement_taller_than_the_page_is_refused_not_clipped() -> None:
    item = Item(key="L", type=ExerciseType.OPEN, statement=FORTY_LINES)
    assert estimate_item_height_mm(item) > USABLE_H_MM

    with pytest.raises(ItemTooTallError) as caught:
        paginate([item])

    # The message has to name the item and say what to do about it.
    assert "item 1" in str(caught.value)
    assert "shorten" in str(caught.value)


def test_the_offending_item_is_named_by_its_printed_number() -> None:
    short = Item(key="a", type=ExerciseType.TRUE_FALSE, statement="Vrai ou faux : 2 + 2 = 4.")
    tall = Item(key="b", type=ExerciseType.OPEN, statement=FORTY_LINES)
    with pytest.raises(ItemTooTallError) as caught:
        paginate([short, short, tall])
    assert caught.value.number == 3


def test_a_normal_sheet_still_paginates_with_a_header_on_every_page() -> None:
    items = [
        Item(
            key=str(i),
            type=ExerciseType.MCQ,
            statement=f"Question {i + 1} : calcule {i + 1} × 7.",
            options=("a", "b", "c", "d"),
            answer_index=i % 4,
        )
        for i in range(40)
    ]
    pages = paginate(items)
    assert sum(len(p.items) for p in pages) == 40
    # Page-local indices restart; printed numbers do not. The detector depends
    # on exactly this.
    assert [p.items[0].item_index for p in pages] == [0] * len(pages)
    assert [pi.number for page in pages for pi in page.items] == list(range(1, 41))


def test_allow_overflow_is_still_available_for_a_caller_that_wants_it() -> None:
    pages = paginate([Item(key="L", type=ExerciseType.OPEN, statement=FORTY_LINES)],
                     allow_overflow=True)
    assert len(pages) == 1
    assert pages[0].overflowing is True


# --------------------------------------------------------------------------
# The preview is the document, not a lookalike
# --------------------------------------------------------------------------
def test_preview_returns_the_real_printed_document(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    login(client, tenant.teacher.email)
    sheet_id = _make_sheet(client, tenant, db)

    response = client.get(f"/api/v1/sheets/{sheet_id}/preview")
    assert response.status_code == 200, response.text
    html = response.text

    # The two machine-readable elements the scan pipeline depends on, and the
    # fixed answer grid the web app's hand-rolled preview left out entirely.
    assert "print-uid-grid" in html
    assert "sheet-grid-row" in html
    assert 'data-fiducial="tl"' in html
    assert 'data-layout-version="v1"' in html


def test_preview_can_render_the_answer_key(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    login(client, tenant.teacher.email)
    sheet_id = _make_sheet(client, tenant, db)
    blank = client.get(f"/api/v1/sheets/{sheet_id}/preview").text
    key = client.get(f"/api/v1/sheets/{sheet_id}/preview?kind=answer_key").text
    assert 'data-key="true"' not in blank
    assert 'data-key="true"' in key


def _make_sheet(client: TestClient, tenant: Tenant, db: Session) -> str:
    a = make_exercise(db, tenant, statement="Calcule 3/4 + 1/6.")
    b = make_exercise(db, tenant, statement="Vrai ou faux : 2 + 2 = 5.")
    response = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Preview test",
            "language": "fr",
            "items": [
                {"exercise_id": str(a.id), "position": 0},
                {"exercise_id": str(b.id), "position": 1},
            ],
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


# --------------------------------------------------------------------------
# The rendered PDF has to be where the download URL says it is
# --------------------------------------------------------------------------
def test_store_pdf_writes_through_object_storage(storage, monkeypatch) -> None:
    """``store_pdf`` probed for a module-level ``storage.put_object``, which has
    never existed — the interface is ``get_storage().put_bytes``. The probe
    always failed, so every rendered PDF went to the worker's local disk while
    the database advertised an object-storage key: the job reported success and
    the teacher's download 404'd."""
    from alppy import storage as storage_mod
    from alppy.sheets.render import store_pdf

    monkeypatch.setattr(storage_mod, "get_storage", lambda: storage)
    key = store_pdf(b"%PDF-1.7 fake", "sheets/abc/v1/blank.pdf")

    assert key == "sheets/abc/v1/blank.pdf"
    assert storage.exists(key), "the bytes must be where the download URL points"
    assert storage.get_bytes(key) == b"%PDF-1.7 fake"


# --------------------------------------------------------------------------
# The teacher's edit has to survive onto the paper
# --------------------------------------------------------------------------
def test_a_statement_override_reaches_the_printed_page(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Every class sheet binds an `item_plan` per student, and the plan carries
    exercise ids only. The renderer rebuilt each copy from the plan and never
    looked at `SheetItem.statement_override`, so a teacher's edit was stored,
    shown in the builder, and silently dropped from the paper."""
    from alppy.models import Sheet
    from alppy.sheets.render import build_sheet_data

    login(client, tenant.teacher.email)
    a = make_exercise(db, tenant, statement="Original du manuel.")
    response = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Override test",
            "language": "fr",
            "items": [
                {
                    "exercise_id": str(a.id),
                    "position": 0,
                    "statement_override": "Réécrit par le prof.",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text

    sheet = db.get(Sheet, uuid.UUID(response.json()["id"]))
    assert sheet is not None
    assert sheet.instances and sheet.instances[0].item_plan, "the plan path is the one that broke"

    data = build_sheet_data(db, sheet)
    for copy in data.copies:
        assert copy.items[0].statement == "Réécrit par le prof."

    # And the source exercise is untouched — an edit is a printed wording, not
    # a rewrite of the textbook.
    db.refresh(a)
    assert a.statement == "Original du manuel."


# --------------------------------------------------------------------------
# A picture of the exercise, at the book's own size
# --------------------------------------------------------------------------
def _figure(width_mm: float, height_mm: float) -> Figure:
    return Figure(src="data:image/png;base64,iVBORw0KGgo=", width_mm=width_mm, height_mm=height_mm)


def test_a_figure_prints_at_its_own_size_when_it_fits() -> None:
    figure = _figure(150.0, 60.0)
    width, height, scale = figure.printed_size_mm()
    assert (width, height, scale) == (150.0, 60.0, 1.0)


def test_a_figure_wider_than_the_column_is_shrunk_to_fit_and_never_enlarged() -> None:
    wide = _figure(TEXT_W_MM * 2, 40.0)
    width, height, scale = wide.printed_size_mm()
    assert width == pytest.approx(TEXT_W_MM)
    assert height == pytest.approx(20.0) and scale == pytest.approx(0.5)

    tiny = _figure(40.0, 10.0)
    assert tiny.printed_size_mm()[2] == 1.0


def test_pagination_reserves_the_figures_printed_height() -> None:
    text_only = Item(key="t", type=ExerciseType.OPEN, statement="Calcule.", open_lines=0)
    with_figure = Item(
        key="f", type=ExerciseType.OPEN, statement="Calcule.", open_lines=0, figure=_figure(150.0, 60.0)
    )
    # The picture and its gap are added; neither item draws an answer box, so
    # neither pays its margins.
    assert estimate_item_height_mm(with_figure) - estimate_item_height_mm(text_only) == pytest.approx(
        60.0 + FIGURE_GAP_MM
    )
    # A full-page exercise of the book, shrunk to the ceiling, still fits a
    # sheet on its own.
    tall = Item(key="p", type=ExerciseType.OPEN, statement="Voir la figure.",
                figure=_figure(165.0, 150.0))
    pages = paginate([tall])
    assert len(pages) == 1 and not pages[0].overflowing

    # Two ordinary exercises of the book share a page: the ruled lines an open
    # text item gets are not added under a picture.
    two = [
        Item(key="a", type=ExerciseType.OPEN, statement="a", figure=_figure(165.0, 55.0)),
        Item(key="b", type=ExerciseType.OPEN, statement="b", figure=_figure(165.0, 46.0)),
    ]
    assert len(paginate(two)) == 1


def test_a_figure_taller_than_the_page_is_shrunk_to_fit_never_refused() -> None:
    """A half-page exercise of the book used to fail the whole sheet with a
    message about one item. It is a raster at print resolution: shrink it."""
    huge = Item(key="h", type=ExerciseType.OPEN, statement="NO113 Rectangle coloré",
                figure=_figure(165.0, 300.0))
    pages = paginate([huge])
    assert len(pages) == 1 and not pages[0].overflowing
    width, height, scale = printed_figure_size_mm(huge)
    assert height == pytest.approx(figure_room_mm(huge))
    assert height <= FIGURE_MAX_H_MM
    assert width == pytest.approx(165.0 * scale)


def test_the_figure_makes_room_for_the_text_printed_above_it() -> None:
    """A teacher's three-line wording above a full-height crop must not push
    the item past the page — the picture gives way, and the item still fits."""
    long_wording = " ".join(["Mesure chaque côté du rectangle avec la règle"] * 6)
    figure = Figure(
        src="data:image/png;base64,iVBORw0KGgo=", width_mm=165.0, height_mm=150.0,
        show_statement=True,
    )
    item = Item(key="w", type=ExerciseType.OPEN, statement=long_wording, figure=figure)
    assert figure_room_mm(item) < FIGURE_MAX_H_MM
    assert estimate_item_height_mm(item) <= USABLE_H_MM
    assert len(paginate([item])) == 1

    # An MCQ with a picture pays for its options the same way.
    mcq = Item(key="m", type=ExerciseType.MCQ, statement="Quelle aire ?",
               options=("12 cm²", "24 cm²", "36 cm²", "48 cm²"), figure=_figure(165.0, 150.0))
    plain = Item(key="x", type=ExerciseType.OPEN, statement="x", figure=_figure(165.0, 150.0))
    assert figure_room_mm(mcq) < figure_room_mm(plain)
    assert len(paginate([mcq])) == 1


def test_the_markup_sizes_the_picture_to_what_pagination_reserved() -> None:
    from alppy.sheets.html import Copy, SheetData, render_sheet_html

    item = Item(key="f", type=ExerciseType.OPEN, statement="Prends les mesures nécessaires.",
                open_lines=2, figure=_figure(200.0, 100.0))
    data = SheetData(
        title="Aires", class_code="10B", subject="Maths", language="fr",
        copies=(Copy(uid="10B_01", items=(item,)),),
    )
    html = render_sheet_html(data)
    width, height, _ = printed_figure_size_mm(item)
    assert f'style="width: {width:g}mm; height: {height:g}mm"' in html
    assert 'alt="Prends les mesures nécessaires."' in html
    # The statement is the alt, not a paragraph: printed once, as the picture.
    assert html.count("Prends les mesures nécessaires.") == 1
    assert 'class="sheet-answer-box"' not in html, "no answer box under a picture"


# --------------------------------------------------------------------------
# The written-answer box
# --------------------------------------------------------------------------
def _open(lines: int, fill: str = "lined") -> Item:
    from alppy.models.enums import AnswerBoxFill

    return Item(
        key="o", type=ExerciseType.OPEN, statement="Explique.",
        open_lines=lines, box_fill=AnswerBoxFill(fill),
    )


def test_pagination_reserves_the_box_and_its_tick_room() -> None:
    from alppy.sheets.pagination import BOX_MARGIN_BOTTOM_MM, OPEN_LINE_PITCH_MM, box_height_mm

    none = _open(0)
    five = _open(5)
    assert box_height_mm(none) is None
    assert box_height_mm(five) == pytest.approx(5 * OPEN_LINE_PITCH_MM)
    assert estimate_item_height_mm(five) - estimate_item_height_mm(none) == pytest.approx(
        OPEN_LINES_MARGIN_MM + 5 * OPEN_LINE_PITCH_MM + BOX_MARGIN_BOTTOM_MM
    )


def test_the_box_prints_its_height_inline_with_four_ticks_and_the_chosen_fill() -> None:
    """The height pagination reserved is the height the paper gets, and the
    furniture the crop step removes — border, ticks — is markup, not
    background, so it survives printing with backgrounds off."""
    from alppy.sheets.html import Copy, SheetData, render_sheet_html

    def html_for(item: Item) -> str:
        data = SheetData(
            title="t", class_code="7B", subject="Maths", language="fr",
            copies=(Copy(uid="7B_01", items=(item,)),),
        )
        return render_sheet_html(data)

    lined = html_for(_open(5))
    assert 'class="sheet-answer-box" data-answer-box="true" data-fill="lined" data-lines="5"' in lined
    assert 'style="height: 40mm"' in lined
    assert lined.count('class="sheet-answer-box-tick"') == 4
    assert "<pattern" in lined and 'class="sheet-answer-box-guide"' in lined
    assert "sheet-rule" not in lined

    grid = html_for(_open(3, "grid"))
    assert 'data-fill="grid"' in grid and 'style="height: 24mm"' in grid

    blank = html_for(_open(8, "blank"))
    assert 'data-fill="blank"' in blank and "<pattern" not in blank

    assert 'class="sheet-answer-box"' not in html_for(_open(0))
