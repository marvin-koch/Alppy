"""The region detector against the real thing: *Mathématiques 10e* (MER).

Every other ingest test works on a handful of invented pages. This one reads
the 228-page book the feature was built for, because the questions that matter
— does it find every exercise, does it cut at the right place, does a
two-page exercise come back whole — cannot be answered by a fixture that was
written to pass.

The file is 47 MB and lives in ``docs/books/``; it is not committed to CI's
checkout, so the module skips rather than fails when it is absent. The detector
runs once per session: fifteen seconds is fine once, not fine twelve times.
"""

from __future__ import annotations

import io
from itertools import pairwise
from pathlib import Path

import pytest

from alppy.ingest.regions import (
    ExerciseRegion,
    detect_exercise_regions,
    read_outline,
    render_region,
)
from alppy.ingest.sections import sections_from_outline

BOOK = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "books"
    / "10e_LE_PDF-Web_signets_2026-06-30.pdf"
)

pytestmark = pytest.mark.skipif(not BOOK.exists(), reason="the real textbook is not checked in")
pytest.importorskip("pymupdf", reason="the region detector needs PyMuPDF")

EXERCISES_IN_BOOK = 504
"""Counted by hand from the book's own index: every coded header from RS1 to
GM133, minus the codes that are skipped in print. If this number moves, the
detector changed, and somebody has to open the book and say which is right."""

DOMAINS = ("RS", "NO", "FA", "ES", "GM")
"""Recherche et stratégies, Nombres et opérations, Fonctions et algèbre,
Espace, Grandeurs et mesures — the five domains of the PER, which is also
how the book codes its exercises."""

CONTINUED = {
    "NO109": (50, 51),
    "NO113": (51, 52),
    "NO234": (74, 75),
    "FA57": (94, 95, 96),
    "ES4": (146, 147),
    "ES8": (148, 149),
    "ES64": (165, 166),
    "ES82": (172, 173),
    "GM32": (188, 189),
}
"""Every ``SUITE ▶`` in the book, and the pages the exercise spans. FA57 is the
one that runs over three pages."""


@pytest.fixture(scope="module")
def data() -> bytes:
    return BOOK.read_bytes()


@pytest.fixture(scope="module")
def regions(data: bytes) -> list[ExerciseRegion]:
    return detect_exercise_regions(data)


@pytest.fixture(scope="module")
def by_label(regions: list[ExerciseRegion]) -> dict[str, ExerciseRegion]:
    return {r.label: r for r in regions}


# --------------------------------------------------------------------------
# 1 · Every exercise, each exactly once
# --------------------------------------------------------------------------
def test_every_coded_exercise_is_found_once(regions: list[ExerciseRegion]) -> None:
    labels = [r.label for r in regions]
    assert len(labels) == EXERCISES_IN_BOOK
    assert len(set(labels)) == len(labels), "a label found twice is a region cut in two"


def test_the_how_to_use_this_book_page_is_not_mistaken_for_exercises(
    regions: list[ExerciseRegion],
) -> None:
    """Pages 4-5 show miniature pages with tiny coded headers as an example.
    They are thumbnails, not exercises, and are set at 2-5 pt."""
    assert all(r.page >= 9 for r in regions)


def test_labels_are_the_books_own_codes(regions: list[ExerciseRegion]) -> None:
    for region in regions:
        assert region.label.startswith(DOMAINS), region.label
        assert region.title, f"{region.label} has no title"


def test_regions_are_in_reading_order(regions: list[ExerciseRegion]) -> None:
    pages = [r.page for r in regions]
    assert pages == sorted(pages)


# --------------------------------------------------------------------------
# 2 · The cut is in the right place
# --------------------------------------------------------------------------
def test_a_region_starts_at_its_header_and_stops_before_the_next(
    by_label: dict[str, ExerciseRegion],
) -> None:
    """Page 41 carries NO64, NO65 and NO68 with a cross-reference between the
    last two. Each must hold its own body and nothing of its neighbour's."""
    no64, no65, no68 = by_label["NO64"], by_label["NO65"], by_label["NO68"]
    assert (no64.page, no65.page, no68.page) == (41, 41, 41)
    assert no64.parts[0].y1 <= no65.parts[0].y0
    assert no65.parts[0].y1 <= no68.parts[0].y0

    assert no64.title == "Les quatre multiplications"
    assert "Aide-toi de ces quatre égalités" in no64.text
    assert "(+ 1000)" in no64.text, "the last sub-item h) is at the bottom of the region"
    assert "Trouve la règle" not in no64.text, "that sentence opens NO65"

    assert "Fichier" not in no65.text, "the workbook pointer belongs to no exercise"
    assert "(– 7) · (+ 6)" in no65.text.replace(" ", " ").replace("  ", " ")


def test_the_header_line_is_not_repeated_in_the_text(regions: list[ExerciseRegion]) -> None:
    for region in regions:
        assert not region.text.startswith(region.label), region.label


def test_regions_are_column_wide_and_never_a_sliver(regions: list[ExerciseRegion]) -> None:
    """The book's text column is 165 mm; a region narrower than 150 mm has lost
    its right-hand figure, and one under 15 mm tall is a header with no body."""
    for region in regions:
        assert 150 <= region.width_mm <= 190, (region.label, region.width_mm)
        assert region.height_mm >= 15, (region.label, region.height_mm)


def test_a_figure_only_exercise_keeps_its_drawing(by_label: dict[str, ExerciseRegion]) -> None:
    """GM26 "Smile !" is one sentence and a large drawn face. The text layer
    knows nothing of the face; the region must still be tall enough to hold
    it, or the student gets a question about a picture that is not there."""
    smile = by_label["GM26"]
    assert smile.page == 186
    assert smile.height_mm > 90, smile.height_mm
    assert "aire de la surface blanche" in smile.text


# --------------------------------------------------------------------------
# 3 · SUITE ▶ — an exercise that runs over the page comes back whole
# --------------------------------------------------------------------------
def test_every_suite_mark_stitches_the_next_page_on(
    by_label: dict[str, ExerciseRegion],
) -> None:
    for label, pages in CONTINUED.items():
        region = by_label[label]
        assert region.continues, label
        assert tuple(p.page for p in region.parts) == pages, label
    assert sum(1 for r in by_label.values() if r.continues) == len(CONTINUED)


def test_a_continued_exercise_carries_both_halves_of_its_text(
    by_label: dict[str, ExerciseRegion],
) -> None:
    """NO113 "Rectangle coloré": the coloured rectangle on page 51, the
    fractions i) to n) on page 52."""
    region = by_label["NO113"]
    assert "L’unité d’aire est le rectangle extérieur." in region.text
    assert "Applique cette règle aux calculs suivants" in region.text
    assert "SUITE" not in region.text


def test_the_page_after_a_continuation_starts_its_own_exercises_cleanly(
    by_label: dict[str, ExerciseRegion],
) -> None:
    """Page 52 opens with the tail of NO113; NO114 below it must not include it."""
    no114 = by_label["NO114"]
    assert no114.page == 52
    assert "Applique cette règle" not in no114.text
    assert "Voici deux procédés pour additionner" in no114.text


# --------------------------------------------------------------------------
# 4 · The crop is a real picture of the exercise
# --------------------------------------------------------------------------
def test_a_crop_renders_at_the_regions_physical_size(
    data: bytes, by_label: dict[str, ExerciseRegion]
) -> None:
    from PIL import Image

    region = by_label["NO64"]
    image = render_region(data, region)
    decoded = Image.open(io.BytesIO(image.png))
    assert decoded.size == (image.width_px, image.height_px)
    assert abs(image.width_mm - region.width_mm) < 0.5
    assert abs(image.height_mm - region.height_mm) < 0.5
    # Not a blank rectangle: the page's red header and black body are in it.
    greys = decoded.convert("L").getextrema()
    assert greys[0] < 80 and greys[1] > 240


def test_a_continued_crop_is_one_image_of_both_pages(
    data: bytes, by_label: dict[str, ExerciseRegion]
) -> None:
    region = by_label["NO113"]
    image = render_region(data, region)
    assert abs(image.height_mm - region.height_mm) < 1.0
    assert image.height_mm > 120, "two pages' worth, stacked"


# --------------------------------------------------------------------------
# 5 · The outline is the book's own table of contents
# --------------------------------------------------------------------------
def test_the_outline_yields_the_books_chapters(data: bytes) -> None:
    entries = [(e.level, e.title, e.page) for e in read_outline(data)]
    sections = sections_from_outline(entries, first_page=1, last_page=228)
    titles = [s.title for s in sections]
    assert "NO – Nombres relatifs" in titles
    relatifs = next(s for s in sections if s.title == "NO – Nombres relatifs")
    assert (relatifs.page_from, relatifs.page_to, relatifs.label) == (35, 48, "NO")
    # Gapless, in order, and starting at the front matter.
    assert sections[0].page_from == 1
    for before, after in pairwise(sections):
        assert after.page_from == before.page_to + 1
    assert sections[-1].page_to == 228


def test_every_exercise_lands_in_a_chapter_of_its_own_domain(
    data: bytes, regions: list[ExerciseRegion]
) -> None:
    """The book codes exercises by domain and chapters by domain; an NO
    exercise in an FA chapter means either the outline or a region is wrong."""
    entries = [(e.level, e.title, e.page) for e in read_outline(data)]
    sections = sections_from_outline(entries, first_page=1, last_page=228)
    for region in regions:
        section = next(s for s in sections if s.page_from <= region.page <= s.page_to)
        assert section.label is not None, (region.label, section.title)
        assert region.label.startswith(section.label), (region.label, section.title)
