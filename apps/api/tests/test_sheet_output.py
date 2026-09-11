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
from conftest import printed_body
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise

from alppy.models.enums import ExerciseType
from alppy.sheets.pagination import (
    FIGURE_GAP_MM,
    FIGURE_MAX_H_MM,
    ITEM_PADDING_MM,
    ITEM_RULE_MM,
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
    # A full-page exercise of the book worked in the notebook fits a sheet on
    # its own, at the ceiling.
    tall = Item(key="p", type=ExerciseType.OPEN, statement="Voir la figure.", open_lines=0,
                figure=_figure(165.0, 150.0))
    pages = paginate([tall])
    assert len(pages) == 1 and not pages[0].overflowing

    # Two ordinary exercises of the book worked in the notebook (no box)
    # share a page; give each a box and the boxes need a second page.
    two = [
        Item(key="a", type=ExerciseType.OPEN, statement="a", open_lines=0,
             figure=_figure(165.0, 55.0)),
        Item(key="b", type=ExerciseType.OPEN, statement="b", open_lines=0,
             figure=_figure(165.0, 46.0)),
    ]
    assert len(paginate(two)) == 1
    boxed = [
        Item(key="a", type=ExerciseType.OPEN, statement="a", figure=_figure(165.0, 55.0)),
        Item(key="b", type=ExerciseType.OPEN, statement="b", figure=_figure(165.0, 46.0)),
    ]
    assert len(paginate(boxed)) == 2
    assert all(p.part == "whole" for page in paginate(boxed) for p in page.items)


def test_a_figure_taller_than_the_page_is_shrunk_to_fit_never_refused() -> None:
    """A half-page exercise of the book used to fail the whole sheet with a
    message about one item. It is a raster at print resolution: shrink it to
    the ceiling — and no further for the box, which follows on the next page."""
    huge = Item(key="h", type=ExerciseType.OPEN, statement="NO113 Rectangle coloré",
                figure=_figure(165.0, 300.0))
    width, height, scale = printed_figure_size_mm(huge)
    assert height == pytest.approx(figure_room_mm(huge)) == pytest.approx(FIGURE_MAX_H_MM)
    assert width == pytest.approx(165.0 * scale)
    pages = paginate([huge])
    assert [p.items[0].part for p in pages] == ["statement", "box"]
    assert not any(page.overflowing for page in pages)


def test_the_figure_makes_room_for_the_text_printed_above_it() -> None:
    """A teacher's three-line wording above a full-height crop must not push
    the statement past the page — the picture gives way to the words, which
    are the statement too. It does not give way to the box."""
    long_wording = " ".join(["Mesure chaque côté du rectangle avec la règle"] * 6)
    figure = Figure(
        src="data:image/png;base64,iVBORw0KGgo=", width_mm=165.0, height_mm=150.0,
        show_statement=True,
    )
    item = Item(key="w", type=ExerciseType.OPEN, statement=long_wording, figure=figure)
    assert figure_room_mm(item) < FIGURE_MAX_H_MM
    assert estimate_item_height_mm(item, with_box=False) <= USABLE_H_MM
    assert [p.items[0].part for p in paginate([item])] == ["statement", "box"]

    # An MCQ with a picture pays for its options the same way.
    mcq = Item(key="m", type=ExerciseType.MCQ, statement="Quelle aire ?",
               options=("12 cm²", "24 cm²", "36 cm²", "48 cm²"), figure=_figure(165.0, 150.0))
    plain = Item(key="x", type=ExerciseType.OPEN, statement="x", open_lines=0,
                 figure=_figure(165.0, 150.0))
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
    assert 'data-lines="2"' in html, "the box prints under a picture too"


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


def test_the_box_never_shrinks_the_picture_it_moves_to_the_next_page() -> None:
    """A textbook exercise is the common case for a written answer. The crop
    used to be sized to what the box left, which printed the book's type at a
    size nobody could read under a twelve-line box. The statement is the one
    thing that must be legible: the picture keeps its room, and a box that no
    longer fits under it is carried whole to the next page."""
    from alppy.sheets.pagination import (
        LINE_H_MM,
        box_block_mm,
        continuation_height_mm,
        figure_room_mm,
    )

    boxed = Item(key="f", type=ExerciseType.OPEN, statement="x", open_lines=12,
                 figure=_figure(165.0, 150.0))
    bare = Item(key="f", type=ExerciseType.OPEN, statement="x", open_lines=0,
                figure=_figure(165.0, 150.0))
    assert figure_room_mm(boxed) == figure_room_mm(bare) == pytest.approx(FIGURE_MAX_H_MM)
    assert printed_figure_size_mm(boxed) == printed_figure_size_mm(bare)

    pages = paginate([boxed])
    assert len(pages) == 2
    statement, box = pages[0].items[0], pages[1].items[0]
    assert (statement.part, box.part) == ("statement", "box")
    # Same printed number, each with its own page-local index; the box part
    # is the one a detection is recorded against.
    assert statement.number == box.number == 1
    assert statement.item_index == box.item_index == 0
    assert not statement.prints_box and box.prints_box
    assert statement.height_mm == pytest.approx(estimate_item_height_mm(boxed, with_box=False))
    assert box.height_mm == pytest.approx(continuation_height_mm(boxed))
    assert continuation_height_mm(boxed) == pytest.approx(
        ITEM_PADDING_MM + ITEM_RULE_MM + LINE_H_MM + box_block_mm(boxed)
    )

    # A small box still prints under its picture: nothing moves that fits.
    small = Item(key="f", type=ExerciseType.OPEN, statement="x", open_lines=3,
                 figure=_figure(165.0, 60.0))
    assert [p.items[0].part for p in paginate([small])] == ["whole"]

    # A long text statement with a tall box splits the same way; a statement
    # too tall on its own is still refused, never clipped.
    long_text = Item(key="t", type=ExerciseType.OPEN, statement=" ".join(["mot"] * 150), open_lines=12)
    assert [p.items[0].part for p in paginate([long_text])] == ["statement", "box"]
    with pytest.raises(ItemTooTallError):
        paginate([Item(key="L", type=ExerciseType.OPEN, statement=FORTY_LINES, open_lines=3)])

    # Items after a split item carry on numbering on the continuation's page.
    after = Item(key="n", type=ExerciseType.MCQ, statement="Suivant.", options=("a", "b"))
    eight = Item(key="f", type=ExerciseType.OPEN, statement="x", open_lines=8, figure=_figure(165.0, 150.0))
    pages = paginate([eight, after])
    assert [(p.number, p.part, p.item_index) for p in pages[1].items] == [(1, "box", 0), (2, "whole", 1)]


def test_a_continuation_prints_the_number_the_word_suite_and_the_box_only() -> None:
    from alppy.sheets.html import Copy, SheetData, render_sheet_html

    item = Item(key="f", type=ExerciseType.OPEN, statement="Prends les mesures nécessaires.",
                open_lines=12, answer_text="7/8", figure=_figure(165.0, 150.0))
    data = SheetData(
        title="Aires", class_code="10B", subject="Maths", language="fr",
        copies=(Copy(uid="10B_01", items=(item,)),),
    )
    html = render_sheet_html(data)
    first, second = html.split('data-part="box"')
    assert 'data-part="statement"' in first
    assert 'data-answer-box="true"' not in first, "the box is on the next page"
    assert 'data-answer-box="true"' in second and "(suite)" in second
    assert 'class="sheet-figure"' not in second, "the picture is not printed twice"
    assert html.count("sheet-figure\"") == 1
    assert html.count('data-number="1"') == 2

    key = render_sheet_html(data, kind=__import__("alppy.sheets.html", fromlist=["SheetKind"]).SheetKind.ANSWER_KEY)
    # `printed_body`: the head carries the embedded faces, and base64 contains
    # every short string eventually. What is being asserted is about the page.
    assert printed_body(key).count("7/8") == 1, "the expected answer prints once, beside the box"


def test_the_key_prints_the_sheet_items_answer_over_the_exercises(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The teacher wrote an answer for this printing; the book's own stays in
    the corpus and off this key."""
    from alppy.models.enums import ExerciseType

    login(client, tenant.teacher.email)
    written = make_exercise(db, tenant, statement="Calcule 3/4 + 1/8.", kind=ExerciseType.OPEN, answer_index=None)
    written.answer_text = "0,875"
    db.commit()
    response = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Key test",
            "language": "fr",
            "items": [{"exercise_id": str(written.id), "position": 0, "expected_answer": "7/8"}],
        },
    )
    assert response.status_code == 201, response.text
    sheet_id = response.json()["id"]
    key = client.get(f"/api/v1/sheets/{sheet_id}/preview?kind=answer_key").text
    assert "7/8" in key and "0,875" not in key


def test_written_items_have_no_grid_row_and_a_page_of_them_has_no_grid(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The box under the statement is where a written answer goes; a grid row
    saying "in the box" told the student nothing. Bubble items keep their rows
    at the same page-local index, which is what the detector reads."""
    from alppy.models.enums import ExerciseType

    login(client, tenant.teacher.email)
    written = make_exercise(db, tenant, statement="Explique.", kind=ExerciseType.OPEN, answer_index=None)
    bubbles = make_exercise(db, tenant, statement="1/2 + 1/4 ?")

    def sheet_with(ids: list[str]) -> str:
        response = client.post(
            "/api/v1/sheets",
            json={
                "class_id": str(tenant.school_class.id),
                "subject_id": str(tenant.subject.id),
                "title": "Grid test",
                "language": "fr",
                "items": [{"exercise_id": eid, "position": i} for i, eid in enumerate(ids)],
            },
        )
        assert response.status_code == 201, response.text
        return client.get(f"/api/v1/sheets/{response.json()['id']}/preview").text

    row = '<div class="sheet-grid-row"'
    alone = sheet_with([str(written.id)])
    assert row not in alone and 'class="sheet-grid"' not in alone
    assert "dans le cadre" in alone and "grille de réponses en bas" not in alone

    # One row per copy — the preview prints the whole class, three students here.
    mixed = sheet_with([str(written.id), str(bubbles.id)])
    assert mixed.count(row) == 3
    # The bubble item keeps its page-local index — the detector's key.
    assert 'data-row="1" data-item-index="1"' in mixed
    assert "dans le cadre" in mixed and "grille de réponses en bas" in mixed


def test_the_tallest_allowed_box_still_fits_a_page_when_carried_over() -> None:
    """``layout.ANSWER_BOX_MAX_LINES`` is derived from the continuation height;
    if either constant moves, this is what catches the two disagreeing."""
    from alppy.sheets.layout import ANSWER_BOX_MAX_LINES
    from alppy.sheets.pagination import continuation_height_mm

    tallest = Item(key="t", type=ExerciseType.OPEN, statement="x", open_lines=ANSWER_BOX_MAX_LINES)
    assert continuation_height_mm(tallest) <= USABLE_H_MM
    one_more = Item(key="t", type=ExerciseType.OPEN, statement="x", open_lines=ANSWER_BOX_MAX_LINES + 1)
    assert continuation_height_mm(one_more) > USABLE_H_MM
    with pytest.raises(ItemTooTallError):
        paginate([one_more])


def test_each_statement_prints_what_it_is_worth(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The student needs to know where to spend the hour, so the paper says it.

    Only the reward is printed. The penalty is a scoring rule, and "-0,25"
    beside every question on a child's paper is a different message from
    telling them what the question is worth.
    """
    login(client, tenant.teacher.email)
    cheap = make_exercise(db, tenant, statement="Question facile.")
    dear = make_exercise(db, tenant, statement="Question difficile.")
    response = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Barème test",
            "language": "fr",
            "default_points_correct": 1.0,
            "default_points_penalty": 0.25,
            "items": [
                {"exercise_id": str(cheap.id), "position": 0},
                {"exercise_id": str(dear.id), "position": 1, "points_correct": 3.0},
            ],
        },
    )
    assert response.status_code == 201, response.text
    html = client.get(f"/api/v1/sheets/{response.json()['id']}/preview").text

    # The unit agrees in number. "(1 pts)" is wrong French and wrong English,
    # and it is the kind of thing nobody notices until it is on 24 sheets of
    # paper in front of a class.
    assert "(1 pt)" in html
    assert "(1 pts)" not in html
    assert "(3 pts)" in html
    # The penalty is a scoring rule, not something a student reads per item.
    assert "0,25" not in html and "-0.25" not in html


def test_an_item_worth_nothing_prints_no_label(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """A "(0 pts)" beside a question is a thing to explain to thirty
    teenagers. Silence is not."""
    login(client, tenant.teacher.email)
    warmup = make_exercise(db, tenant, statement="Pour se mettre en route.")
    response = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Zero test",
            "language": "fr",
            "items": [{"exercise_id": str(warmup.id), "position": 0, "points_correct": 0.0}],
        },
    )
    assert response.status_code == 201, response.text
    html = client.get(f"/api/v1/sheets/{response.json()['id']}/preview").text
    assert "pts)" not in html


def test_the_printed_instruction_names_both_ways_of_marking(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The detector reads a cross as readily as a fill, and the paper is the
    only place a student learns that either is allowed."""
    login(client, tenant.teacher.email)
    a = make_exercise(db, tenant, statement="1/2 + 1/4 ?")
    response = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Instruction test",
            "language": "fr",
            "items": [{"exercise_id": str(a.id), "position": 0}],
        },
    )
    assert response.status_code == 201, response.text
    html = client.get(f"/api/v1/sheets/{response.json()['id']}/preview").text
    assert "croise" in html.lower()
