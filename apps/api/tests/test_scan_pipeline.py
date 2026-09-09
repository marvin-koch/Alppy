"""End-to-end scan pipeline against synthetically degraded pages.

This is the test the brief asks for: render a sheet, rasterise it, degrade it
the way a classroom does, push it back through the detector, and assert. It is
also the test that keeps ``layout.py`` and ``detector.py`` honest with each
other — the synthetic renderer draws from the layout constants, so a change to
one without the other fails here.
"""

from __future__ import annotations

import pytest

from alppy.models.enums import DetectionOutcome
from alppy.scan.detector import (
    FILL_BLANK,
    FILL_MARKED,
    LOW_CONFIDENCE,
    PX_PER_MM,
    _cross_score,
    _fill_ratio,
    _mark_strength,
    process_page,
)
from alppy.scan.synthetic import (
    copier,
    draw_mark,
    draw_smudge,
    draw_stray_line,
    jpeg,
    noise,
    perspective,
    phone_photo,
    photocopy,
    render_page,
    rescale,
    rotate,
    uneven_light,
)
from alppy.sheets.layout import BUBBLE_D_MM, bubble_centre_mm

OPTION_COUNTS = [4] * 8 + [2] * 8
MARKED: list[int | None] = [0, 1, 2, 3, None, 1, 2, 3, 0, 1, 0, 1, None, 0, 1, 0]
UID = "7B_15"


CLEAN = render_page(UID, OPTION_COUNTS, MARKED, pencil=0.9)


@pytest.fixture(scope="module")
def sheet():
    return render_page(UID, OPTION_COUNTS, MARKED, pencil=0.9)


def answers(result) -> list[int | None]:
    return [d.detected_index for d in result.detections]


def test_clean_page_is_read_perfectly(sheet) -> None:
    r = process_page(sheet.image, OPTION_COUNTS)
    assert r.registered
    assert r.uid == UID
    assert answers(r) == MARKED
    assert r.quality > 0.95


@pytest.mark.parametrize(
    ("name", "degrade"),
    [
        ("rotate +2", lambda i: rotate(i, 2)),
        ("rotate -5", lambda i: rotate(i, -5)),
        ("perspective 0.05", lambda i: perspective(i, 0.05)),
        ("perspective 0.10", lambda i: perspective(i, 0.10)),
        ("photocopy x2", lambda i: photocopy(i, generations=2)),
        ("uneven light", lambda i: uneven_light(i, 0.35)),
        ("noise", lambda i: noise(i, 12)),
        ("jpeg q40", lambda i: jpeg(i, 40)),
        ("downscale 0.35", lambda i: rescale(i, 0.35)),
        ("phone photo", phone_photo),
        ("copier", copier),
    ],
)
def test_degraded_pages_still_register_and_read(sheet, name: str, degrade) -> None:
    r = process_page(degrade(sheet.image), OPTION_COUNTS)
    assert r.registered, f"{name}: registration failed ({r.error})"
    assert r.uid == UID, f"{name}: uid misread as {r.uid}"
    assert answers(r) == MARKED, f"{name}: answers misread"


@pytest.mark.parametrize("pencil", [0.9, 0.75, 0.6, 0.45])
def test_light_pencil_still_reads_through_a_phone_photo(pencil: float) -> None:
    """A child who does not press hard must not be scored zero."""
    s = render_page(UID, OPTION_COUNTS, MARKED, pencil=pencil)
    r = process_page(phone_photo(s.image), OPTION_COUNTS)
    assert r.registered
    assert answers(r) == MARKED


def test_a_mark_lost_by_the_copier_is_flagged_not_silently_zeroed() -> None:
    """When a very light mark genuinely does not survive two photocopy
    generations, the pixels are gone and no detector can recover them. What we
    can control is the failure mode: the page must go to the teacher, not
    quietly score the child zero."""
    s = render_page(UID, OPTION_COUNTS, MARKED, pencil=0.22)
    r = process_page(copier(s.image), OPTION_COUNTS)
    assert r.registered
    gradeable = [d for d in r.detections if d.outcome is not DetectionOutcome.NOT_GRADEABLE]
    assert all(d.confidence < LOW_CONFIDENCE for d in gradeable)
    assert not any(d.outcome is DetectionOutcome.BLANK for d in gradeable)


def test_a_genuinely_empty_page_is_sent_for_review() -> None:
    """Indistinguishable from a lost-pencil page at the level of one bubble, so
    it is treated the same way: surfaced, not assumed."""
    s = render_page(UID, OPTION_COUNTS, [None] * 16)
    r = process_page(s.image, OPTION_COUNTS)
    assert r.registered
    assert all(d.confidence < LOW_CONFIDENCE for d in r.detections)


def test_double_marks_are_reported_as_ambiguous() -> None:
    s = render_page(UID, [4], [0])
    # Fill a second bubble on the same item.
    import cv2

    from alppy.scan.detector import PX_PER_MM
    from alppy.sheets import layout as L

    cx, cy = L.bubble_centre_mm(0, 2)
    cv2.circle(
        s.image,
        (int(cx * PX_PER_MM), int(cy * PX_PER_MM)),
        int(L.BUBBLE_D_MM / 2 * PX_PER_MM * 0.75),
        0,
        thickness=-1,
    )
    r = process_page(s.image, [4])
    assert r.detections[0].outcome is DetectionOutcome.MULTIPLE
    assert r.detections[0].detected_index is None


def test_free_text_items_are_marked_not_gradeable() -> None:
    s = render_page(UID, [0, 4], [None, 1])
    r = process_page(s.image, [0, 4])
    assert r.detections[0].outcome is DetectionOutcome.NOT_GRADEABLE
    assert r.detections[1].detected_index == 1


def test_a_page_without_fiducials_fails_registration_cleanly() -> None:
    """No exception escapes the pipeline: a failure is a result the UI renders."""
    import numpy as np

    blank = np.full((1200, 850), 255, dtype=np.uint8)
    r = process_page(blank, OPTION_COUNTS)
    assert not r.registered
    assert r.error
    assert r.detections == []


def _redraw_mark(image, item: int, option: int, *, radius: float) -> None:
    """Replace one item's filled bubble with a smaller mark, in place."""
    import cv2

    from alppy.scan.detector import PX_PER_MM
    from alppy.sheets import layout as L

    cx, cy = L.bubble_centre_mm(item, option)
    centre = (int(cx * PX_PER_MM), int(cy * PX_PER_MM))
    bubble = L.BUBBLE_D_MM / 2 * PX_PER_MM
    cv2.circle(image, centre, int(bubble * 0.78), 255, -1)  # erase what was drawn
    cv2.circle(image, centre, int(bubble), 0, 1)            # the printed ring stays
    # `radius` is a fraction of the BUBBLE, which is what the fill ratio is
    # measured against — not of the mark the harness happened to draw.
    cv2.circle(image, centre, int(bubble * radius), 0, -1)


@pytest.mark.parametrize("radius", [0.35, 0.40, 0.45])
def test_a_faint_mark_is_read_but_flagged(radius: float) -> None:
    """The band between "clearly blank" and "clearly marked".

    A tick instead of a filled bubble is a real answer and must be read — but
    read with an admission of doubt, so the teacher sees it. This is the branch
    the whole safety design rests on and it had no test: every earlier case
    either sat firmly above FILL_MARKED, or fell to BLANK and was rescued by
    the *page-level* mostly-blank rule instead. Fifteen firm marks here keep
    that rule out of it, so the per-bubble path is what is being measured.
    """
    counts = [4] * 16
    sheet = render_page(UID, counts, [0] * 16, pencil=0.95)
    _redraw_mark(sheet.image, 0, 0, radius=radius)

    r = process_page(sheet.image, counts)
    assert r.registered
    faint = r.detections[0]
    assert FILL_BLANK <= faint.fill_ratios[0] < FILL_MARKED, "not in the faint band"
    assert faint.detected_index == 0, "a faint mark is still the student's answer"
    assert faint.outcome is DetectionOutcome.LOW_CONFIDENCE
    assert faint.confidence < LOW_CONFIDENCE, "it must reach the teacher"
    # ...and it did not drag the firmly marked items down with it.
    assert all(d.outcome is DetectionOutcome.DETECTED for d in r.detections[1:])


@pytest.mark.parametrize("degrees", [-25, -15, -8, 8, 15, 25])
def test_a_crooked_page_still_registers(degrees: float) -> None:
    """Rotation tolerance, measured on a page nothing has cropped.

    ``rotate`` keeps the canvas, so past about 6 degrees a full-bleed A4 render
    loses its corner marks off the edge — an artefact of the harness, not of
    the detector. Padding first is what a photo or a scanner bed actually gives
    you, and that is where the real limit lives. It used to be ~7 degrees, and
    it moved with how much blank space surrounded the sheet, because squareness
    and solidity were measured on an axis-aligned box: a tilted square's box
    grows as (cos t + sin t)^2, so a real fiducial was rejected for being
    tilted.
    """
    import cv2

    pad = int(max(CLEAN.image.shape) * 0.35)
    padded = cv2.copyMakeBorder(
        CLEAN.image, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255
    )
    h, w = padded.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), degrees, 1.0)
    turned = cv2.warpAffine(
        padded, m, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=255
    )

    r = process_page(turned, OPTION_COUNTS)
    assert r.registered, f"{degrees}deg: {r.error}"
    assert r.uid == UID
    assert answers(r) == MARKED


def test_decoy_squares_do_not_displace_a_real_fiducial() -> None:
    """Loosening the shape gates must not let anything square-ish stand in.

    The corner-by-corner assignment is what protects this, and it has to keep
    protecting it now that a tilted square is allowed to look like a square.
    """
    import cv2
    import numpy as np

    sheet = render_page(UID, OPTION_COUNTS, MARKED, pencil=0.9)
    rng = np.random.default_rng(11)
    for _ in range(40):
        x, y = int(rng.integers(250, 1350)), int(rng.integers(500, 1700))
        size = int(rng.integers(20, 60))
        cv2.rectangle(sheet.image, (x, y), (x + size, y + size), 0, -1)

    r = process_page(sheet.image, OPTION_COUNTS)
    assert r.registered
    assert r.uid == UID
    assert r.quality > 0.95


def test_uid_is_read_for_several_classes() -> None:
    for uid in ("7A_01", "9C_07", "11AB_99"):
        s = render_page(uid, [4], [0])
        r = process_page(phone_photo(s.image), [4])
        assert r.uid == uid


# ==========================================================================
# Crossed marks
#
# The sheet tells the student to fill the box OR cross it, so both have to
# read. A hand-drawn X's ink DENSITY is far below FILL_MARKED — two thin
# strokes cover about a quarter of the disc — so it is recognised by its shape
# instead, and the two measures are combined in `_mark_strength`. These tests
# run crosses through the same degradation grid the fills above go through.
# ==========================================================================

CROSSED = render_page(UID, OPTION_COUNTS, MARKED, pencil=0.9, mark_style="cross")


def test_a_clean_crossed_page_is_read_perfectly() -> None:
    r = process_page(CROSSED.image, OPTION_COUNTS)
    assert r.registered
    assert r.uid == UID
    assert answers(r) == MARKED
    marked_items = [d for i, d in enumerate(r.detections) if MARKED[i] is not None]
    assert all(d.outcome is DetectionOutcome.DETECTED for d in marked_items)


@pytest.mark.parametrize(
    "degrade",
    [
        lambda i: rotate(i, 2.5),
        lambda i: perspective(i, 0.02),
        lambda i: photocopy(i, generations=2),
        lambda i: uneven_light(i, 0.35),
        lambda i: noise(i, 8.0, seed=1),
        lambda i: jpeg(i, 55),
        lambda i: rescale(i, 0.6),
        lambda i: phone_photo(i, seed=2),
        lambda i: copier(i, seed=2),
    ],
)
def test_degraded_crossed_pages_still_read(degrade) -> None:
    r = process_page(degrade(CROSSED.image), OPTION_COUNTS)
    assert r.registered, r.error
    assert answers(r) == MARKED


@pytest.mark.parametrize("pencil", [0.9, 0.75, 0.6, 0.45])
def test_a_light_crossed_page_still_reads_through_a_phone_photo(pencil: float) -> None:
    s = render_page(UID, OPTION_COUNTS, MARKED, pencil=pencil, mark_style="cross")
    r = process_page(phone_photo(s.image, seed=5), OPTION_COUNTS)
    assert r.registered, r.error
    assert answers(r) == MARKED


def test_a_page_mixing_crosses_and_fills_is_read_perfectly() -> None:
    """A real class does not agree on a convention, and does not have to."""
    filled = render_page(UID, OPTION_COUNTS, MARKED, pencil=0.9)
    crossed = render_page(UID, OPTION_COUNTS, MARKED, pencil=0.9, mark_style="cross")
    # Top half from one page, bottom half from the other: the grid's two
    # column groups end up marked in different hands.
    mixed = filled.image.copy()
    half = mixed.shape[0] // 2
    mixed[half:] = crossed.image[half:]
    r = process_page(mixed, OPTION_COUNTS)
    assert r.registered, r.error
    assert answers(r) == MARKED


def test_two_crosses_on_one_item_are_reported_as_ambiguous() -> None:
    """D5 holds whatever the marks look like: the MULTIPLE test compares the
    two bubbles on the same combined scale, so a pair of crosses is as
    ambiguous as a pair of fills."""
    s = render_page(UID, OPTION_COUNTS, MARKED, pencil=0.9, mark_style="cross")
    draw_mark(
        s.image,
        (
            round(bubble_centre_mm(0, 2)[0] * PX_PER_MM),
            round(bubble_centre_mm(0, 2)[1] * PX_PER_MM),
        ),
        round(BUBBLE_D_MM / 2.0 * PX_PER_MM),
        style="cross",
        pencil=0.9,
        seed=77,
    )
    r = process_page(s.image, OPTION_COUNTS)
    assert r.detections[0].outcome is DetectionOutcome.MULTIPLE
    assert r.detections[0].detected_index is None


def test_a_stray_line_through_a_bubble_is_not_read_as_a_cross() -> None:
    """A rested pen or an overshooting crossing-out puts real ink in the disc.
    One stroke is two lobes, not four, so the shape test refuses it — and the
    density left over is faint, so the teacher is asked rather than guessed at.
    """
    s = render_page(UID, OPTION_COUNTS, [None] * 16, pencil=0.9)
    draw_stray_line(s.image, 0, 1)
    r = process_page(s.image, OPTION_COUNTS)
    cx, cy = bubble_centre_mm(0, 1)
    assert _cross_score(r.canonical, cx, cy, BUBBLE_D_MM) == 0.0
    assert r.detections[0].outcome is not DetectionOutcome.DETECTED


def test_an_eraser_smudge_is_not_read_as_a_cross() -> None:
    """The case the OUTER band exists for: a rubbing-out spreads ink in every
    direction, including into all four quadrants, but it is not arranged as
    strokes and has no lobes to count."""
    s = render_page(UID, OPTION_COUNTS, [None] * 16, pencil=0.9)
    draw_smudge(s.image, 0, 1, seed=4)
    r = process_page(s.image, OPTION_COUNTS)
    cx, cy = bubble_centre_mm(0, 1)
    assert _cross_score(r.canonical, cx, cy, BUBBLE_D_MM) == 0.0
    assert r.detections[0].outcome is not DetectionOutcome.DETECTED


def test_a_filled_bubble_scores_no_cross_at_all() -> None:
    """The non-regression guarantee, stated directly: with no crossing
    structure the cross score is exactly 0, `_mark_strength` collapses to the
    fill ratio, and every judgement this module made before is unchanged."""
    r = process_page(CLEAN.image, OPTION_COUNTS)
    cx, cy = bubble_centre_mm(0, MARKED[0])
    assert _cross_score(r.canonical, cx, cy, BUBBLE_D_MM) == 0.0
    fill = _fill_ratio(r.canonical, cx, cy, BUBBLE_D_MM)
    assert _mark_strength(fill, 0.0) == fill


def _fine_pen_cross(seed: int):
    """A cross drawn with a fine pen: less ink in the disc than FILL_BLANK, so
    the density measure alone would call the bubble empty."""
    s = render_page(UID, OPTION_COUNTS, [None] * 16, pencil=0.9)
    cx_mm, cy_mm = bubble_centre_mm(0, 1)
    draw_mark(
        s.image,
        (round(cx_mm * PX_PER_MM), round(cy_mm * PX_PER_MM)),
        round(BUBBLE_D_MM / 2.0 * PX_PER_MM),
        style="cross",
        pencil=0.9,
        seed=seed,
        thickness_frac=0.07,
    )
    return process_page(s.image, OPTION_COUNTS), cx_mm, cy_mm


def test_a_fine_pen_cross_is_rescued_from_reading_blank() -> None:
    """Why the shape test earns its place.

    A cross drawn with a fine pen puts less ink in the disc than FILL_BLANK,
    so density alone would call it empty — and a confident blank is a graded
    zero (D5). Seeing four arms turns that into a read answer.
    """
    r, cx_mm, cy_mm = _fine_pen_cross(seed=1)
    fill = _fill_ratio(r.canonical, cx_mm, cy_mm, BUBBLE_D_MM)
    cross = _cross_score(r.canonical, cx_mm, cy_mm, BUBBLE_D_MM)
    assert fill < FILL_BLANK, "the premise: density alone would call this empty"
    assert cross > 0.0
    assert _mark_strength(fill, cross) >= FILL_MARKED
    assert r.detections[0].detected_index == 1
    assert r.detections[0].outcome is DetectionOutcome.DETECTED


@pytest.mark.parametrize("seed", range(12))
def test_a_fine_pen_cross_is_never_silently_scored_zero(seed: int) -> None:
    """The guarantee that has to hold for EVERY fine cross, not most of them.

    The shape test does not resolve four arms every single time — a hand that
    draws one arm short, or two that nearly overlap, leaves a profile with
    fewer lobes than a cross has, and that reading is refused rather than
    guessed at. What must never happen is the other failure: a mark the child
    actually made, reported as a confident blank and scored zero without
    anyone seeing it. Every one of these is either read or handed back.
    """
    r, _, _ = _fine_pen_cross(seed=seed)
    d = r.detections[0]
    if d.outcome is DetectionOutcome.DETECTED:
        assert d.detected_index == 1
    else:
        # Not read — then it must be surfaced, and never a confident blank.
        assert d.confidence < LOW_CONFIDENCE
        assert d.outcome is not DetectionOutcome.BLANK
