"""Print it, rasterise it, scan it back — the loop, end to end, for real.

Everything else in this suite tests one side of the paper. `test_layout` checks
the geometry is self-consistent, `test_sheet_output` checks the HTML carries the
right marks, and `test_scan_pipeline` drives the detector from *synthetic* pages
drawn by `scan/synthetic.py`. None of them ever put the real renderer and the
real detector in the same sentence, so the one thing that actually matters —
**that a page Chromium prints is a page the detector can read** — was never
verified. The handover recorded it as unverified code.

It is verified now, and this is the test that keeps it that way.

What it proves, on a genuinely rendered PDF:

* the four corner fiducials land where `layout.py` says, so the page registers;
* the pre-filled UID grid round-trips through print and raster back to the same
  student code, with its CRC intact;
* a filled bubble on the answer key is read at the coordinate the layout
  promised, for the right item.

Skipped, never failed, when the browser is not installed: the suite has to stay
runnable on a machine with no Chromium, and a red test there would say the code
is broken when what is missing is a binary.
"""

from __future__ import annotations

import numpy as np
import pytest

from alppy.models.enums import ExerciseType, SheetKind
from alppy.sheets.html import Copy, SheetData, physical_pages, render_sheet_html
from alppy.sheets.pagination import Item
from alppy.sheets.render import BrowserUnavailableError, html_to_pdf

pymupdf = pytest.importorskip("pymupdf", reason="rasterising the PDF needs PyMuPDF")

#: 200 dpi is roughly what a phone photograph of an A4 page gives, and well
#: below the 300 dpi a flatbed would. Reading at the low end is the useful test.
RASTER_DPI = 200


def _sheet() -> SheetData:
    items = tuple(
        Item(
            key=f"e{i}",
            type=ExerciseType.MCQ,
            statement=f"Combien font {i} x 7 ?",
            options=("14", "21", "28", "35"),
            answer_index=i % 4,
            language="fr",
        )
        for i in range(1, 4)
    )
    return SheetData(
        title="Controle commun",
        class_code="7B",
        subject="Maths",
        language="fr",
        copies=(Copy(uid="7B_01", items=items),),
    )


def _greyscale_pages(pdf: bytes) -> list[np.ndarray]:
    """Every page of the PDF as an 8-bit greyscale array, as the scanner sees it."""
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    out: list[np.ndarray] = []
    for page in doc:
        pix = page.get_pixmap(dpi=RASTER_DPI)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        rgb = img[:, :, :3]
        out.append(
            (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]).astype(np.uint8)
        )
    return out


def _render(kind: SheetKind) -> bytes:
    try:
        return html_to_pdf(render_sheet_html(_sheet(), kind=kind))
    except BrowserUnavailableError as exc:  # pragma: no cover - environment
        pytest.skip(f"headless Chromium is not available here: {exc}")


def test_a_printed_page_registers_and_gives_up_its_student_code() -> None:
    """Fiducials and the UID grid survive the trip to paper and back.

    A page that does not register is a page nobody can grade, and a UID that
    comes back wrong is worse than one that fails: it files a child's answers
    under another child's name.
    """
    from alppy.scan.detector import process_page

    data = _sheet()
    pages = physical_pages(data)
    images = _greyscale_pages(_render(SheetKind.BLANK))

    assert len(images) == len(pages), "the PDF has a page for every printed page"

    for index, image in enumerate(images):
        result = process_page(image, pages[index].page.option_counts)
        assert result.registered, f"page {index + 1} did not register: {result.error}"
        assert result.uid == "7B_01", f"page {index + 1} read the wrong student code"
        assert result.uid_confidence > 0.9
        # A page printed flat should be flat. Anything more is a geometry bug,
        # not a scanning one: there is no camera in this test to add skew.
        assert abs(result.skew_deg) < 0.5


def test_a_filled_bubble_is_read_at_the_coordinate_the_layout_promised() -> None:
    """The answer key prints its bubbles filled, so it stands in for a perfectly
    completed copy — and every mark must come back on the right item.

    This is the assertion that ties `layout.py`, `print.css`, the renderer and
    the detector together. If any one of them drifts, this fails and the other
    tests do not.
    """
    from alppy.scan.detector import process_page

    data = _sheet()
    pages = physical_pages(data)
    images = _greyscale_pages(_render(SheetKind.ANSWER_KEY))

    read = 0
    for index, image in enumerate(images):
        printed = pages[index].page
        result = process_page(image, printed.option_counts)
        expected = [placed.item.answer_index for placed in printed.items]
        assert result.detections, f"page {index + 1} produced no detections at all"
        for detection in result.detections:
            want = expected[detection.item_index]
            assert detection.detected_index == want, (
                f"page {index + 1} item {detection.item_index}: "
                f"read {detection.detected_index}, printed {want}"
            )
            assert detection.confidence > 0.5
            read += 1

    assert read == sum(len(p.page.items) for p in pages), "not every printed item was read"


def test_the_feedback_document_carries_nothing_the_scanner_registers_on() -> None:
    """The feedback pages are a separate document and must stay unscannable.

    Not a style point: if a stack of feedback pages is fed into the scanner by
    mistake, registering them would file blank answers against the UID printed
    on each one. Refusing to register is the safe outcome, and it is what the
    missing fiducials buy (decisions-log D34).
    """
    from alppy.scan.detector import process_page
    from alppy.sheets.html import FeedbackCopy, FeedbackData, render_feedback_html

    feedback = FeedbackData(
        title="Fractions",
        class_code="7B",
        subject="Maths",
        language="fr",
        copies=(FeedbackCopy(uid="7B_01", notes=("Tu calcules de gauche a droite.",)),),
    )
    try:
        pdf = html_to_pdf(render_feedback_html(feedback))
    except BrowserUnavailableError as exc:  # pragma: no cover - environment
        pytest.skip(f"headless Chromium is not available here: {exc}")

    images = _greyscale_pages(pdf)
    assert len(images) == 1, "one page per student who has a note"

    result = process_page(images[0], [4, 4, 4])
    assert not result.registered, (
        "a feedback page registered as a gradeable one; a mis-fed stack would "
        "score its students zero"
    )
