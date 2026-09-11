"""Scan registration and mark detection.

The pipeline, in order:

1. **Find the four corner fiducials.** Solid squares printed as borders, so they
   survive "do not print background graphics".
2. **Register.** A perspective transform from the four fiducial centres onto the
   canonical page. This removes rotation, skew and the keystone distortion of a
   phone photo in one step, which is why a photo taken at an angle is acceptable
   input.
3. **Read the UID grid.** 32 checksummed bits; no OCR in the happy path.
4. **Detect bubbles** at the coordinates ``alppy.sheets.layout`` computes, and
   report a confidence for each item.

Nothing here reads the words on the page. The detector only needs the geometry,
which is precisely what makes it robust — and what makes the layout and the
detector a single versioned unit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import cv2
import numpy as np
import numpy.typing as npt

from alppy.models.enums import DetectionOutcome
from alppy.sheets import layout as L
from alppy.sheets.uid_code import PageCode, UidCodeError, decode_page_code, decode_uid

Image = npt.NDArray[np.uint8]

PX_PER_MM: Final = 8.0
"""Canonical resolution. 8 px/mm puts a 5 mm bubble at 40 px across, which is
comfortably enough to measure a fill ratio on a 150 dpi photocopy."""

CANONICAL_W: Final = int(L.PAGE_W_MM * PX_PER_MM)
CANONICAL_H: Final = int(L.PAGE_H_MM * PX_PER_MM)

# --- Detection thresholds. Tuned against the synthetic degradation suite.
FILL_MARKED: Final = 0.35
"""Above this fraction of dark pixels, a bubble counts as marked."""

FILL_BLANK: Final = 0.18
"""Below this, definitely blank. Between the two is the uncertain band."""

MARGIN_CONFIDENT: Final = 0.20
"""Gap between the best and second-best bubble needed to be sure which one the
student meant. A small gap means a stray pencil line or an erased answer."""

LOW_CONFIDENCE: Final = 0.65
"""Below this the item is surfaced to the teacher first, before anything else."""

# --- Reading a CROSS as well as a fill -----------------------------------
# The thresholds above measure how MUCH ink is in a bubble. These measure what
# SHAPE it is in, so a student who crosses the box is read as confidently as
# one who fills it. See ``_cross_score``.
CROSS_BINS: Final = 24
"""Angular bins around the bubble, 15 degrees each. Fine enough to separate the
two strokes of a cross (their lobes sit ~90 degrees apart), coarse enough that
one bin still holds enough pixels for its mean to mean anything at 8 px/mm."""

CROSS_LOBES: Final = 4
"""Two crossing strokes cut the rim of the disc in exactly four places. This is
the definition of the shape rather than a tuned value: two lobes is a single
stroke, and three or five is a scribble."""

CROSS_BAND_INNER_FRAC: Final = 0.45
"""The band starts at this fraction of the sampling radius. Inside it lies the
middle, where a cross's own intersection and a rubbed-out answer both leave ink
and neither can be told from the other — so the middle is not counted."""

CROSS_LOBE_FRAC: Final = 0.45
"""A bin belongs to a lobe when it holds at least this fraction of the peak
bin's ink. Empirical: high enough that the gaps between a cross's arms survive
a photocopy, low enough that a light arm is not split in two."""

CROSS_MAX_LOBE_BINS: Final = 8
"""A lobe wider than 120 degrees is a wedge of ink, not the arm of a stroke."""

CROSS_MIN_BAND_INK: Final = 0.06
"""Below this the outer band is empty and there is no shape to read. Keeps the
angular profile from finding lobes in sensor noise."""

CROSS_LOBE_REF: Final = 0.5
"""The ink fraction a bin holds when a full stroke passes through it. The
weakest arm is divided by this to score how complete the cross is. Empirical."""

CROSS_MARKED: Final = 0.55
CROSS_BLANK: Final = 0.20
"""The cross score's own marked/blank pair, in its own 0-1 units.
``_mark_strength`` maps the span between them onto FILL_BLANK..FILL_MARKED so
that one item's bubbles stay comparable however each of them was marked. Both
empirical."""

MIN_QUALITY: Final = 0.55
"""Below this the located frame is not a page, and nothing read from it means
anything.

``register`` will happily fit a homography onto any four dark marks. Erase the
four corner fiducials and it finds four cells of the UID grid instead, warps the
page onto them, and reads bubbles from whatever lands at the resulting
coordinates — nine wrong answers at confidence 1.0 in the case that found this.
The bubble confidences cannot see it: they only measure the ink at the
coordinates they were handed, never whether those were the right coordinates.
``quality`` can, and it separates cleanly — a real page scores >0.99 flat, 0.92
through a phone photo and 0.62 at the steepest perspective that still registers,
while a page fitted onto the wrong marks scores 0.11-0.29.
"""


class RegistrationError(RuntimeError):
    """Raised when the four fiducials cannot be located on a page."""


@dataclass(frozen=True, slots=True)
class Registration:
    canonical: Image
    corners_px: npt.NDArray[np.float32]  # the 4 fiducial centres found, TL TR BR BL
    homography: npt.NDArray[np.float64]
    skew_deg: float
    quality: float  # 0..1, how square and even the located frame was


@dataclass(slots=True)
class BubbleReading:
    option_index: int
    fill: float
    """Raw ink density. Unchanged in meaning, and still what ``fill_ratios``
    reports to the review screen."""
    cross: float
    """Raw shape score, 0 unless a crossing structure was found."""
    mark: float
    """The two combined — the quantity every decision below is made on."""
    u: float
    v: float


@dataclass(slots=True)
class ItemDetection:
    item_index: int
    detected_index: int | None
    outcome: DetectionOutcome
    confidence: float
    fill_ratios: list[float] = field(default_factory=list)
    bubble_boxes: list[dict[str, float]] = field(default_factory=list)


@dataclass(slots=True)
class PageResult:
    registered: bool
    uid: str | None
    uid_confidence: float
    detections: list[ItemDetection]
    skew_deg: float
    quality: float
    error: str | None = None
    page_code: PageCode | None = None
    """What layout v2 read out of the grid, or None for a v1 page.

    The pipeline uses it to stop guessing: which page of the copy this is comes
    from the paper rather than from upload order (B5), and the nonce says which
    sheet and which render it was printed from."""
    canonical: Image | None = None
    """The deskewed page, in canonical coordinates.

    The review overlay draws boxes at the coordinates the detector sampled. Laid
    over the *original* upload those boxes are wrong twice over -- the page is
    still rotated, and the frame is inset from the paper -- so the image the
    teacher checks against must be this one, not what came off the camera.
    """


# --------------------------------------------------------------------------
# 1 · fiducials
# --------------------------------------------------------------------------
def _to_gray(image: Image) -> Image:
    if image.ndim == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def _binarise(gray: Image) -> Image:
    """Adaptive threshold: a phone photo is lit unevenly, so a global threshold
    loses one corner of the page."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    return cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 51, 15
    )


def _order_corners(pts: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    """Order four points as TL, TR, BR, BL — robust to any input order."""
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
        dtype=np.float32,
    )


def find_fiducials(image: Image) -> npt.NDArray[np.float32]:
    """Locate the four solid corner squares. Returns centres ordered TL TR BR BL."""
    gray = _to_gray(image)
    binary = _binarise(gray)
    h, w = binary.shape[:2]

    # The fiducial is 8mm on a 210mm page: ~3.8% of page width. The band is wide
    # because we do not yet know the scale or how much margin was cropped — and
    # it is derived from the whole image, so a photo with desk visible around
    # the sheet makes every threshold larger than the page warrants. Keep the
    # floor generous for that reason; squareness and solidity below are what
    # actually identify a fiducial, and they do not care about the framing.
    page_min = min(h, w)
    area_lo = (page_min * 0.006) ** 2
    area_hi = (page_min * 0.12) ** 2

    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[float, tuple[float, float]]] = []

    for c in contours:
        area = cv2.contourArea(c)
        if not area_lo <= area <= area_hi:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.04 * peri, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue

        # Squareness and solidity are measured on the contour's OWN rectangle,
        # not on an axis-aligned one. A square photographed at an angle is still
        # a square, but its axis-aligned box grows as (cos t + sin t)^2, so an
        # axis-aligned extent falls away as the page rotates and crosses 0.72 at
        # about 10 degrees — the detector was rejecting real fiducials for the
        # crime of being tilted. minAreaRect is rotation-invariant, which is
        # what "is this shape a solid square" was always supposed to mean.
        (_cx, _cy), (rw, rh), _angle = cv2.minAreaRect(approx)
        if rw <= 0 or rh <= 0:
            continue
        # A square photographed from an angle is a genuine rectangle: at the
        # steepest keystone this pipeline registers (perspective s=0.22, about
        # a 14 degree tilt) the far marks compress by roughly 1.4x. The old
        # 0.7-1.4 band was measured on an axis-aligned box, where rotation and
        # keystone partly cancelled; on the true rectangle it has to admit the
        # distortion the rest of the pipeline is built to survive. Solidity
        # below is the discriminating test, not this one.
        aspect = rw / rh
        if not 0.55 <= aspect <= 1.8:
            continue
        # A fiducial is SOLID: its area nearly fills its own rectangle. This is
        # what separates it from a bubble outline or a letter like "O".
        extent = area / float(rw * rh)
        if extent < 0.72:
            continue
        m = cv2.moments(approx)
        if m["m00"] == 0:
            continue
        candidates.append((area, (m["m10"] / m["m00"], m["m01"] / m["m00"])))

    if len(candidates) < 4:
        raise RegistrationError(
            f"found {len(candidates)} fiducial candidates, need 4"
        )

    # Keep the candidate closest to each image corner. Working per-corner rather
    # than by size means a dark blob in the middle of the page cannot displace a
    # real fiducial.
    corners_of_image = [(0.0, 0.0), (float(w), 0.0), (float(w), float(h)), (0.0, float(h))]
    chosen: list[tuple[float, float]] = []
    remaining = list(candidates)
    for cx, cy in corners_of_image:
        if not remaining:
            raise RegistrationError("ran out of fiducial candidates while assigning corners")
        best = min(remaining, key=lambda it: (it[1][0] - cx) ** 2 + (it[1][1] - cy) ** 2)
        chosen.append(best[1])
        remaining.remove(best)

    pts = np.array(chosen, dtype=np.float32)
    if len({(round(x), round(y)) for x, y in chosen}) < 4:
        raise RegistrationError("fiducial candidates collapsed onto the same point")
    return _order_corners(pts)


# --------------------------------------------------------------------------
# 2 · registration
# --------------------------------------------------------------------------
def _canonical_fiducial_targets() -> npt.NDArray[np.float32]:
    c = L.FIDUCIAL_CENTRES_MM
    return np.array(
        [
            [c["tl"][0] * PX_PER_MM, c["tl"][1] * PX_PER_MM],
            [c["tr"][0] * PX_PER_MM, c["tr"][1] * PX_PER_MM],
            [c["br"][0] * PX_PER_MM, c["br"][1] * PX_PER_MM],
            [c["bl"][0] * PX_PER_MM, c["bl"][1] * PX_PER_MM],
        ],
        dtype=np.float32,
    )


def register(image: Image) -> Registration:
    """Warp a photographed or scanned page onto the canonical A4 grid."""
    corners = find_fiducials(image)
    targets = _canonical_fiducial_targets()
    homography = cv2.getPerspectiveTransform(corners, targets)
    gray = _to_gray(image)
    canonical = cv2.warpPerspective(
        gray, homography, (CANONICAL_W, CANONICAL_H), flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=255,
    )

    # Skew: the angle of the top edge between the two upper fiducials.
    dx = float(corners[1][0] - corners[0][0])
    dy = float(corners[1][1] - corners[0][1])
    skew = float(np.degrees(np.arctan2(dy, dx)))

    # Quality: how close the located quadrilateral is to the expected aspect.
    top = float(np.linalg.norm(corners[1] - corners[0]))
    bottom = float(np.linalg.norm(corners[2] - corners[3]))
    left = float(np.linalg.norm(corners[3] - corners[0]))
    right = float(np.linalg.norm(corners[2] - corners[1]))
    if min(top, bottom, left, right) <= 0:
        raise RegistrationError("degenerate fiducial quadrilateral")
    side_balance = min(top, bottom) / max(top, bottom) * min(left, right) / max(left, right)
    expected_aspect = L.FRAME_W_MM / L.FRAME_H_MM
    got_aspect = ((top + bottom) / 2) / ((left + right) / 2)
    aspect_score = min(expected_aspect, got_aspect) / max(expected_aspect, got_aspect)
    quality = float(max(0.0, min(1.0, side_balance * aspect_score)))

    return Registration(
        canonical=canonical,
        corners_px=corners,
        homography=homography,
        skew_deg=skew,
        quality=quality,
    )


# --------------------------------------------------------------------------
# 3 · sampling
# --------------------------------------------------------------------------
@dataclass(slots=True)
class _InkSample:
    """One bubble's ink, as both measures below agree to see it.

    Extracted so ``_cross_score`` cannot invent a second definition of what
    counts as ink. The local-annulus threshold (D6) is the load-bearing part;
    a shape measure built on a different threshold would disagree with the
    density measure about whether there is anything there at all.
    """

    ink: npt.NDArray[np.bool_]
    """Patch-shaped: True where the pixel is darker than the local paper."""
    inside: npt.NDArray[np.bool_]
    """Patch-shaped: True inside the 80%-diameter sampling disc."""
    cx_px: float
    """Bubble centre, patch-local."""
    cy_px: float
    inner_r: float
    """Radius of the sampling disc, in pixels."""


def _sample_ink(
    canonical: Image, cx_mm: float, cy_mm: float, d_mm: float
) -> _InkSample | None:
    """The ink inside one bubble, measured against the LOCAL paper.

    Two details here are load-bearing, and both were found by the synthetic
    degradation suite rather than by reasoning:

    * We sample at 80% of the diameter. The bubble's own 0.6 pt printed ring is
      ink too, and counting it would give every blank bubble a nonzero floor
      that drifts with print quality.

    * The threshold is derived from an annulus around this specific bubble, not
      from the page. A global threshold reads a light pencil mark (~70%
      reflectance) as paper and silently scores the child zero, while a
      photocopy's grey paper pushes a global threshold the other way. The local
      annulus tracks both. We take a high percentile of it rather than the mean
      so that a stray line clipping the annulus does not drag the estimate down.

    ``None`` when the bubble sits outside the page or the patch is unusable —
    every caller treats that as "no reading", not as "blank".
    """
    r_px = (d_mm * PX_PER_MM) / 2.0
    inner_r = r_px * 0.8
    outer_r = r_px * 1.6
    cx = cx_mm * PX_PER_MM
    cy = cy_mm * PX_PER_MM

    x0, x1 = int(cx - outer_r), int(cx + outer_r) + 1
    y0, y1 = int(cy - outer_r), int(cy + outer_r) + 1
    h, w = canonical.shape[:2]
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None

    patch = canonical[y0:y1, x0:x1].astype(np.float32)
    if patch.size == 0:
        return None

    yy, xx = np.ogrid[y0:y1, x0:x1]
    dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
    inside = dist2 <= inner_r**2
    annulus = (dist2 > (r_px * 1.15) ** 2) & (dist2 <= outer_r**2)
    if not inside.any():
        return None

    # Local paper level. Fall back to the page's 90th percentile if this bubble
    # sits too close to an edge for a usable annulus.
    if annulus.sum() >= 12:
        paper = float(np.percentile(patch[annulus], 75))
    else:
        paper = float(np.percentile(canonical, 90))
    paper = max(paper, 40.0)

    # A pencil mark reflects roughly 60-75% of what the paper does. Anything
    # below 82% of local paper is treated as deliberate ink.
    threshold = paper * 0.82
    return _InkSample(
        ink=patch < threshold,
        # Already patch-shaped: `dist2` broadcast the two ogrid axes together,
        # so this is the full (h, w) mask, not a row/column vector.
        inside=inside,
        cx_px=cx - x0,
        cy_px=cy - y0,
        inner_r=inner_r,
    )


def _fill_ratio(canonical: Image, cx_mm: float, cy_mm: float, d_mm: float) -> float:
    """Fraction of dark pixels inside the sampling disc. See ``_sample_ink``."""
    sample = _sample_ink(canonical, cx_mm, cy_mm, d_mm)
    if sample is None:
        return 0.0
    return float(sample.ink[sample.inside].mean())


def _cross_score(canonical: Image, cx_mm: float, cy_mm: float, d_mm: float) -> float:
    """How much this bubble looks like a CROSS, 0 when it does not look like one.

    Why this exists: a hand-drawn X's ink DENSITY is naturally far below
    ``FILL_MARKED``. Two ~0.5 mm strokes across a 5 mm bubble cover roughly a
    quarter of the sampled disc, where a filled bubble covers most of it. Tuned
    on density alone, every crossed answer in a class would land in the
    uncertain band and be handed back to the teacher — the pipeline working
    perfectly and being useless. So a cross is recognised by its SHAPE instead,
    and the two measures are combined in ``_mark_strength``.

    The shape test is an angular profile. Bin the ink in the OUTER band of the
    disc by its angle around the centre, and count how many separate lobes the
    profile has:

        filled disc   every bin lit          -> one lobe the whole way round
        stray line    two lobes, 180 apart   -> a single stroke
        cross         FOUR lobes             -> two strokes crossing
        smudge        no coherent lobes      -> nothing to count

    Two crossing strokes produce four lobes at ANY rotation, so this needs no
    angle threshold and does not care whether the student's X is upright or
    leaning. The outer band is what excludes the middle, where a cross's own
    intersection and a rubbed-out smudge both put ink and neither is
    distinguishable from the other.

    Gated, not graded: anything failing the structural tests returns exactly
    0.0, which is what lets ``_mark_strength`` collapse to the fill ratio for
    every bubble that is not crossed, and leaves the existing behaviour of this
    module bit-for-bit unchanged on every mark that was ever tested before.
    """
    sample = _sample_ink(canonical, cx_mm, cy_mm, d_mm)
    if sample is None:
        return 0.0

    h, w = sample.ink.shape
    yy, xx = np.mgrid[0:h, 0:w]
    dx = xx - sample.cx_px
    dy = yy - sample.cy_px
    dist = np.sqrt(dx * dx + dy * dy)
    band = sample.inside & (dist >= sample.inner_r * CROSS_BAND_INNER_FRAC)
    if not band.any():
        return 0.0

    band_ink = float(sample.ink[band].mean())
    if band_ink < CROSS_MIN_BAND_INK:
        # Nothing in the outer band. An empty bubble, or a mark so faint the
        # density measure is the honest one to use.
        return 0.0

    # Angle of every band pixel, in bins around the circle.
    angles = np.degrees(np.arctan2(dy, dx)) % 360.0
    bin_index = (angles / (360.0 / CROSS_BINS)).astype(np.int32) % CROSS_BINS
    profile = np.zeros(CROSS_BINS, dtype=np.float64)
    for b in range(CROSS_BINS):
        cell = band & (bin_index == b)
        profile[b] = float(sample.ink[cell].mean()) if cell.any() else 0.0

    peak = float(profile.max())
    if peak <= 0.0:
        return 0.0

    lit = profile >= peak * CROSS_LOBE_FRAC
    if lit.all():
        # Ink all the way round: a filled bubble, or a blot. Either way the
        # density measure already describes it correctly.
        return 0.0

    # Contiguous runs of lit bins, counted around the circle rather than across
    # the array: a lobe straddling 0 degrees is one lobe, not two.
    runs: list[list[int]] = []
    start = 0
    while lit[start - 1] and start < CROSS_BINS:
        start += 1  # begin at a gap so no run is split at the seam
    current: list[int] = []
    for offset in range(CROSS_BINS):
        b = (start + offset) % CROSS_BINS
        if lit[b]:
            current.append(b)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)

    if len(runs) != CROSS_LOBES:
        # Two lobes is one stroke; three or five is a scribble. Only four is
        # two strokes crossing, and we never guess at the others.
        return 0.0
    if any(len(run) > CROSS_MAX_LOBE_BINS for run in runs):
        # A lobe wider than a stroke: a wedge of ink, not an arm.
        return 0.0

    # The weakest arm decides. An X is only an X if all four arms are there,
    # so a strong pair plus two faint smudges must not score as a whole one.
    weakest = min(float(profile[run].mean()) for run in runs)
    return float(min(1.0, weakest / CROSS_LOBE_REF))


def _mark_strength(fill: float, cross: float) -> float:
    """One number for "is this bubble marked", from the two measures.

    ``max``, not a blend. ``_cross_score`` is gated: it is either 0 or a shape
    it has already confirmed, and once confirmed there is nothing a low density
    can usefully add — a thin X SHOULD have low density. Blending would drag a
    real cross back under the threshold, which is the whole problem being
    solved.

    It also buys a guarantee worth having: for every bubble with no crossing
    structure, ``cross`` is 0 and this returns ``fill`` exactly, so every mark
    the degradation suite ever tested is classified precisely as before.

    The cross score is mapped into the fill scale first, so ``detect_item``
    keeps comparing against ``FILL_MARKED``/``FILL_BLANK`` and the MULTIPLE
    test keeps working when the two marks on an item are a cross and a fill.
    """
    if cross <= CROSS_BLANK:
        return fill

    # Piecewise linear through three anchors, so the two scales agree at every
    # point that has a name:
    #
    #   CROSS_BLANK   -> FILL_BLANK        the floor of the uncertain band
    #   CROSS_MARKED  -> FILL_MARKED       the threshold itself
    #   1.0 (perfect) -> FILL_MARKED * 1.6 where `strength` saturates
    #
    # The top anchor matters: mapping a perfect cross to exactly FILL_MARKED
    # would clear the threshold by nothing at all, and the confidence formula
    # below would then report an unmistakable X as barely-a-mark.
    if cross <= CROSS_MARKED:
        span = (cross - CROSS_BLANK) / (CROSS_MARKED - CROSS_BLANK)
        mapped = FILL_BLANK + span * (FILL_MARKED - FILL_BLANK)
    else:
        span = (cross - CROSS_MARKED) / (1.0 - CROSS_MARKED)
        mapped = FILL_MARKED + min(1.0, span) * (FILL_MARKED * 1.6 - FILL_MARKED)
    return max(fill, mapped)


def read_uid_grid(
    canonical: Image, *, layout_version: str | None = None
) -> tuple[str | None, float, list[float], PageCode | None]:
    """Read the UID grid for one layout version.

    Returns ``(uid, confidence, fills, page_code)``. ``page_code`` is populated
    only from v2, which encodes the page rather than only the pupil (B4) — the
    school year, which page of the copy this is, the canton, and the nonce
    identifying the sheet and render the paper came from.

    **The geometry comes from the version the page was PRINTED with**, not from
    the constants as they stand today. That is the whole point of versioning
    them: reading a v1 page against v2's grid would sample twelve columns where
    eight were printed and decode something plausible out of white paper.
    """
    grid = L.uid_grid(layout_version)
    fills: list[float] = []
    for slot in range(grid.cells):
        for row in range(grid.rows):
            cx, cy = grid.cell_centre_mm(slot, row)
            fills.append(_fill_ratio(canonical, cx, cy, grid.cell_mm))

    bits = [1 if f >= 0.5 else 0 for f in fills]
    # Confidence is how far every cell sat from the 0.5 decision boundary: one
    # ambiguous cell is enough to make the whole read untrustworthy.
    margins = [abs(f - 0.5) * 2.0 for f in fills]
    confidence = float(min(margins)) if margins else 0.0

    if len(bits) != grid.total_bits:  # pragma: no cover - sizes come from `grid`
        return (None, 0.0, fills, None)

    version = layout_version or L.LAYOUT_VERSION
    try:
        if version == "v1":
            return (decode_uid(bits), confidence, fills, None)
        code = decode_page_code(bits)
    except UidCodeError:
        return (None, 0.0, fills, None)
    return (code.uid, confidence, fills, code)


def detect_item(canonical: Image, item_index: int, option_count: int) -> ItemDetection:
    """Read one item's bubbles and decide what the student marked."""
    if option_count <= 0:
        return ItemDetection(
            item_index=item_index,
            detected_index=None,
            outcome=DetectionOutcome.NOT_GRADEABLE,
            confidence=1.0,
        )

    readings: list[BubbleReading] = []
    boxes: list[dict[str, float]] = []
    for oi in range(option_count):
        cx, cy = L.bubble_centre_mm(item_index, oi)
        fill = _fill_ratio(canonical, cx, cy, L.BUBBLE_D_MM)
        cross = _cross_score(canonical, cx, cy, L.BUBBLE_D_MM)
        mark = _mark_strength(fill, cross)
        slot = L.BubbleSlot(0, item_index, oi, cx, cy)
        readings.append(BubbleReading(oi, fill, cross, mark, slot.u, slot.v))
        half_u = (L.BUBBLE_D_MM / 2) / L.FRAME_W_MM
        half_v = (L.BUBBLE_D_MM / 2) / L.FRAME_H_MM
        boxes.append(
            {
                "u": slot.u - half_u,
                "v": slot.v - half_v,
                "w": half_u * 2,
                "h": half_v * 2,
                "fill": fill,
                # Additive, and JSONB either side, so no migration: the review
                # overlay can say WHY a bubble was read, not just that it was.
                "cross": cross,
                "mark": mark,
            }
        )

    # `fill_ratios` keeps reporting raw DENSITY: it is the audit trail, and a
    # teacher looking at why a bubble was read wants what was measured, not a
    # combined figure. Every decision below is made on `.mark`.
    fills = [r.fill for r in readings]
    ordered = sorted(readings, key=lambda r: r.mark, reverse=True)
    best = ordered[0]
    second = ordered[1].mark if len(ordered) > 1 else 0.0
    margin = best.mark - second

    if best.mark < FILL_BLANK:
        # Confidently blank only when the bubble is really empty. A reading just
        # under the threshold is an eraser smudge or a very light mark, and the
        # teacher must be the one to decide — reporting "blank, 100% sure" for a
        # faint pencil mark silently scores a child zero.
        outcome = DetectionOutcome.BLANK
        detected: int | None = None
        confidence = float(max(0.0, min(1.0, 1.0 - best.mark / FILL_BLANK)))
    elif second >= FILL_MARKED:
        # Two bubbles are both filled. Never guess between them, and note that
        # the margin plays no part in this test: it used to, and a runner-up at
        # 0.66 -- nearly twice FILL_MARKED, unmistakably a mark -- cleared the
        # margin and was silently dropped, reporting a single answer at
        # confidence 1.0. A student who fills B and half-fills C is asking the
        # teacher a question (D5); the size of the second mark does not make it
        # less of a question.
        outcome = DetectionOutcome.MULTIPLE
        detected = None
        confidence = float(max(0.0, 1.0 - margin / MARGIN_CONFIDENT) * 0.5)
    elif best.mark < FILL_MARKED:
        # Something is there, but it is faint. Always surface it, whatever the
        # separation from the runner-up looks like.
        detected = best.option_index
        span = FILL_MARKED - FILL_BLANK
        outcome = DetectionOutcome.LOW_CONFIDENCE
        confidence = float(
            max(0.0, min(LOW_CONFIDENCE - 0.05, 0.30 + 0.30 * (best.mark - FILL_BLANK) / span))
        )
    else:
        detected = best.option_index
        # Confidence combines "is it clearly a mark" with "is it clearly THE mark".
        strength = min(1.0, best.mark / (FILL_MARKED * 1.6))
        separation = min(1.0, margin / MARGIN_CONFIDENT)
        confidence = float(max(0.0, min(1.0, 0.45 * strength + 0.55 * separation)))
        outcome = (
            DetectionOutcome.DETECTED
            if confidence >= LOW_CONFIDENCE
            else DetectionOutcome.LOW_CONFIDENCE
        )

    return ItemDetection(
        item_index=item_index,
        detected_index=detected,
        outcome=outcome,
        confidence=confidence,
        fill_ratios=fills,
        bubble_boxes=boxes,
    )


MOSTLY_BLANK_RATIO: Final = 0.6
"""Above this share of blank gradeable items, distrust the blanks."""


def _flag_suspicious_blanks(detections: list[ItemDetection]) -> None:
    """Downgrade confidence when a page reads as almost entirely blank.

    A student who leaves three quarters of a sheet empty is possible. A scan
    that lost a light pencil across the whole page looks identical at the level
    of a single bubble, and is far more common. We cannot tell the two apart
    from one item, but we can tell them apart from the page: so when most of a
    page reads blank we stop claiming certainty about any individual blank and
    send them all to the teacher, rather than silently scoring a child zero.
    """
    gradeable = [d for d in detections if d.outcome is not DetectionOutcome.NOT_GRADEABLE]
    if len(gradeable) < 4:
        return
    blanks = [d for d in gradeable if d.outcome is DetectionOutcome.BLANK]
    if len(blanks) / len(gradeable) < MOSTLY_BLANK_RATIO:
        return
    for d in blanks:
        d.outcome = DetectionOutcome.LOW_CONFIDENCE
        d.confidence = min(d.confidence, 0.35)


def process_page(
    image: Image,
    option_counts: list[int],
    *,
    layout_version: str = L.LAYOUT_VERSION,
) -> PageResult:
    """The whole per-page pipeline. Never raises: a failure is a result.

    ``layout_version`` is the version the page was *printed* with, carried on
    the sheet. Every coordinate below comes from ``alppy.sheets.layout`` as it
    exists today, so reading a page printed under a different version would not
    fail -- it would silently sample the wrong places and return plausible
    answers. Until versioned geometry exists there is exactly one honest
    response to a mismatch, and it is to refuse.
    """
    # A layout we have geometry for is readable, whether or not it is the one
    # we currently print (B4). This used to refuse anything but the current
    # version — the only honest answer while every coordinate came from the
    # constants as they stand today, and the reason a version bump would have
    # made every already-printed sheet unreadable. What must still be refused
    # is a version this build knows nothing about: sampling it would read
    # plausible answers out of the wrong parts of the paper.
    if layout_version not in L.UID_GRIDS:
        return PageResult(
            registered=False,
            uid=None,
            uid_confidence=0.0,
            detections=[],
            skew_deg=0.0,
            quality=0.0,
            error=(
                f"sheet was printed with layout {layout_version}, "
                f"which this detector has no geometry for"
            ),
        )

    try:
        reg = register(image)
    except RegistrationError as exc:
        return PageResult(
            registered=False,
            uid=None,
            uid_confidence=0.0,
            detections=[],
            skew_deg=0.0,
            quality=0.0,
            error=str(exc),
        )

    if reg.quality < MIN_QUALITY:
        # Four marks were found and they are not a page. See MIN_QUALITY.
        return PageResult(
            registered=False,
            uid=None,
            uid_confidence=0.0,
            detections=[],
            skew_deg=reg.skew_deg,
            quality=reg.quality,
            canonical=reg.canonical,
            error=(
                f"registration quality {reg.quality:.2f} is below {MIN_QUALITY:.2f}: "
                "the four marks found do not form a page"
            ),
        )

    uid, uid_conf, _fills, page_code = read_uid_grid(
        reg.canonical, layout_version=layout_version
    )
    detections = [
        detect_item(reg.canonical, i, n) for i, n in enumerate(option_counts)
    ]
    _flag_suspicious_blanks(detections)
    return PageResult(
        registered=True,
        uid=uid,
        uid_confidence=uid_conf,
        detections=detections,
        skew_deg=reg.skew_deg,
        quality=reg.quality,
        canonical=reg.canonical,
        page_code=page_code,
    )
