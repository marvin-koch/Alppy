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
from alppy.scan.detector import FILL_BLANK, FILL_MARKED, LOW_CONFIDENCE, process_page
from alppy.scan.synthetic import (
    copier,
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
