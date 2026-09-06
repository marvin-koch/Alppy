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
    USABLE_H_MM,
    Item,
    ItemTooTallError,
    estimate_item_height_mm,
    paginate,
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
