"""The written-answer box: measured where it printed, and found there again.

`test_print_scan_roundtrip` proves a bubble is read at the coordinate the
layout promised. A box has no promised coordinate — it sits under text the
browser wraps — so the promise is made the other way round: the renderer
measures where the box landed and the scanner crops there. These tests hold
both ends of that: the measured rectangle is the border the paper shows, and
the rows written for a sheet are keyed the way a scan will look them up.

Skipped, never failed, without Chromium.
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, make_exercise

from alppy.models import AnswerBoxPlacement, Sheet, SheetInstance, SheetItem
from alppy.models.enums import AnswerBoxFill, ExerciseType, SheetKind, SheetTarget
from alppy.scan.detector import PX_PER_MM, register
from alppy.sheets import layout as L
from alppy.sheets import render
from alppy.sheets.html import Copy, SheetData, physical_pages, render_sheet_html
from alppy.sheets.pagination import Item

pymupdf = pytest.importorskip("pymupdf", reason="rasterising the PDF needs PyMuPDF")

RASTER_DPI = 200


def _sheet() -> SheetData:
    items = (
        Item(key="e1", type=ExerciseType.MCQ, statement="Combien font 3 x 7 ?",
             options=("14", "21", "28", "35"), answer_index=1, language="fr"),
        Item(key="e2", type=ExerciseType.OPEN, statement="Explique ta démarche en une phrase.",
             language="fr", open_lines=5, box_fill=AnswerBoxFill.LINED),
        Item(key="e3", type=ExerciseType.OPEN, statement="Dessine.", language="fr",
             open_lines=3, box_fill=AnswerBoxFill.GRID),
    )
    return SheetData(
        title="Contrôle", class_code="7B", subject="Maths", language="fr",
        copies=(Copy(uid="7B_01", items=items),),
    )


def _skip_without_browser() -> None:
    if not render.browser_available():
        pytest.skip("headless Chromium is not available here")


def _greyscale_pages(pdf: bytes) -> list[np.ndarray]:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    out: list[np.ndarray] = []
    for page in doc:
        pix = page.get_pixmap(dpi=RASTER_DPI, colorspace=pymupdf.csGRAY)
        out.append(np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy())
    return out


def test_a_document_without_a_box_is_not_measured_at_all() -> None:
    html = "<html><body><section class='print-page'></section></body></html>"
    assert render.measure_answer_boxes(html) == []


def test_the_measured_rectangle_is_the_border_the_paper_shows() -> None:
    """Render, measure, print, rasterise, register — and the box's border is
    dark exactly along the measured rectangle, and the inside is paper."""
    _skip_without_browser()
    data = _sheet()
    html = render_sheet_html(data, kind=SheetKind.BLANK)

    boxes = render.measure_answer_boxes(html)
    # The grid box does not fit under the first two items, so it opens page 2
    # as that page's first item — and the measurement says so.
    assert [(b.page_number, b.item_index) for b in boxes] == [(1, 1), (2, 0)]
    for box, lines in zip(boxes, (5, 3), strict=True):
        assert box.h_mm == pytest.approx(lines * L.ANSWER_BOX_LINE_PITCH_MM, abs=0.3)
        assert box.w_mm > 150 and L.ITEMS_TOP_MM < box.y_mm < L.ITEMS_BOTTOM_MM

    images = _greyscale_pages(render.html_to_pdf(html))
    assert len(images) == 2
    canonicals = [register(image).canonical for image in images]

    def strip(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
        return canonical[
            round(y0 * PX_PER_MM):round(y1 * PX_PER_MM),
            round(x0 * PX_PER_MM):round(x1 * PX_PER_MM),
        ]

    for box in boxes:
        canonical = canonicals[box.page_number - 1]
        x0, y0, x1, y1 = box.x_mm, box.y_mm, box.x_mm + box.w_mm, box.y_mm + box.h_mm
        # The border itself, a 1 mm band centred on each edge, carries ink.
        for band in (
            strip(x0 + 5, y0 - 0.5, x1 - 5, y0 + 0.5),
            strip(x0 + 5, y1 - 0.5, x1 - 5, y1 + 0.5),
            strip(x0 - 0.5, y0 + 5, x0 + 0.5, y1 - 5),
            strip(x1 - 0.5, y0 + 5, x1 + 0.5, y1 - 5),
        ):
            assert (band < 128).mean() > 0.15, "the border is not where it was measured"
        # Two millimetres further out, only paper — the measurement is tight.
        for band in (
            strip(x0 + 8, y0 - 3.0, x1 - 8, y0 - 2.0),
            strip(x0 + 8, y1 + 2.0, x1 - 8, y1 + 3.0),
        ):
            assert (band < 128).mean() < 0.02, "ink outside the measured rectangle"
        # Inside, the guides are light: never mistaken for pen.
        inner = strip(x0 + 6, y0 + 6, x1 - 6, y1 - 6)
        assert (inner < 100).mean() < 0.01


def test_rendering_a_sheet_records_one_placement_per_box_per_copy(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keyed the way the scanner looks them up: UID, page of the copy, item
    index. Re-rendering replaces the rows rather than adding to them."""
    _skip_without_browser()
    mcq = make_exercise(db, tenant, statement="Combien font 3 x 7 ?")
    free = make_exercise(db, tenant, statement="Explique.", kind=ExerciseType.OPEN, answer_index=None)
    sheet = Sheet(
        id=uuid.uuid4(), school_id=tenant.school.id, class_id=tenant.school_class.id,
        subject_id=tenant.subject.id, chapter_id=tenant.unfiled_chapter_id,
        created_by_id=tenant.teacher.id, title="Contrôle",
        target=SheetTarget.CLASS, language="fr", layout_version="v1",
    )
    db.add(sheet)
    db.flush()
    for position, exercise in enumerate((mcq, free), start=1):
        db.add(SheetItem(
            id=uuid.uuid4(), school_id=tenant.school.id, sheet_id=sheet.id,
            exercise_id=exercise.id, position=position,
            answer_box_lines=8 if exercise is free else None,
            answer_box_fill=AnswerBoxFill.GRID if exercise is free else None,
        ))
    for student in tenant.students:
        db.add(SheetInstance(
            id=uuid.uuid4(), school_id=tenant.school.id, sheet_id=sheet.id,
            student_id=student.id, student_uid=student.uid, item_plan=[],
        ))
    db.commit()
    db.refresh(sheet)
    monkeypatch.setattr(render, "store_pdf", lambda payload, key: key)

    render.render_sheet_pdfs(db, sheet_id=sheet.id)
    db.commit()

    rows = db.query(AnswerBoxPlacement).filter_by(sheet_id=sheet.id).all()
    assert len(rows) == len(tenant.students)
    assert {r.student_uid for r in rows} == {s.uid for s in tenant.students}
    for row in rows:
        assert (row.copy_page, row.item_index) == (1, 1)
        assert row.exercise_id == free.id
        assert (row.box_lines, row.box_fill) == (8, AnswerBoxFill.GRID)
        assert row.h_mm == pytest.approx(8 * L.ANSWER_BOX_LINE_PITCH_MM, abs=0.3)
        assert row.layout_version == "v1"
    # Every copy of a class sheet is the same paper, so the box is at the
    # same place on each.
    assert len({(r.x_mm, r.y_mm, r.w_mm, r.h_mm) for r in rows}) == 1
    pages = physical_pages(render.build_sheet_data(db, sheet))
    assert all(p.copy_pages == 1 for p in pages)

    render.render_sheet_pdfs(db, sheet_id=sheet.id)
    db.commit()
    assert db.query(AnswerBoxPlacement).filter_by(sheet_id=sheet.id).count() == len(tenant.students)
