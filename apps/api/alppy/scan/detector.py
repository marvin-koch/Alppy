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
from alppy.sheets.uid_code import TOTAL_BITS, UidCodeError, decode_uid

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

    # The fiducial is 8mm on a 210mm page: ~3.8% of page width. Allow a wide
    # band because we do not yet know the scale or how much margin was cropped.
    page_min = min(h, w)
    area_lo = (page_min * 0.012) ** 2
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
        _x, _y, bw, bh = cv2.boundingRect(approx)
        if bh == 0:
            continue
        aspect = bw / bh
        if not 0.7 <= aspect <= 1.4:
            continue
        # A fiducial is SOLID: its area nearly fills its bounding box. This is
        # what separates it from a bubble outline or a letter like "O".
        extent = area / float(bw * bh)
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
def _fill_ratio(canonical: Image, cx_mm: float, cy_mm: float, d_mm: float) -> float:
    """Fraction of dark pixels inside a disc, measured against the LOCAL paper.

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
        return 0.0

    patch = canonical[y0:y1, x0:x1].astype(np.float32)
    if patch.size == 0:
        return 0.0

    yy, xx = np.ogrid[y0:y1, x0:x1]
    dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
    inside = dist2 <= inner_r**2
    annulus = (dist2 > (r_px * 1.15) ** 2) & (dist2 <= outer_r**2)
    if not inside.any():
        return 0.0

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
    return float((patch[inside] < threshold).mean())


def read_uid_grid(canonical: Image) -> tuple[str | None, float, list[float]]:
    """Read the 32-bit UID grid. Returns ``(uid, confidence, fills)``."""
    fills: list[float] = []
    for slot in range(L.UID_GRID_CELLS):
        for row in range(L.UID_GRID_ROWS):
            cx, cy = L.uid_cell_centre_mm(slot, row)
            fills.append(_fill_ratio(canonical, cx, cy, L.UID_GRID_CELL_MM))

    bits = [1 if f >= 0.5 else 0 for f in fills]
    # Confidence is how far every cell sat from the 0.5 decision boundary: one
    # ambiguous cell is enough to make the whole read untrustworthy.
    margins = [abs(f - 0.5) * 2.0 for f in fills]
    confidence = float(min(margins)) if margins else 0.0

    if len(bits) != TOTAL_BITS:
        return (None, 0.0, fills)
    try:
        return (decode_uid(bits), confidence, fills)
    except UidCodeError:
        return (None, 0.0, fills)


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
        slot = L.BubbleSlot(0, item_index, oi, cx, cy)
        readings.append(BubbleReading(oi, fill, slot.u, slot.v))
        half_u = (L.BUBBLE_D_MM / 2) / L.FRAME_W_MM
        half_v = (L.BUBBLE_D_MM / 2) / L.FRAME_H_MM
        boxes.append(
            {
                "u": slot.u - half_u,
                "v": slot.v - half_v,
                "w": half_u * 2,
                "h": half_v * 2,
                "fill": fill,
            }
        )

    fills = [r.fill for r in readings]
    ordered = sorted(readings, key=lambda r: r.fill, reverse=True)
    best = ordered[0]
    second = ordered[1].fill if len(ordered) > 1 else 0.0
    margin = best.fill - second

    if best.fill < FILL_BLANK:
        # Confidently blank only when the bubble is really empty. A reading just
        # under the threshold is an eraser smudge or a very light mark, and the
        # teacher must be the one to decide — reporting "blank, 100% sure" for a
        # faint pencil mark silently scores a child zero.
        outcome = DetectionOutcome.BLANK
        detected: int | None = None
        confidence = float(max(0.0, min(1.0, 1.0 - best.fill / FILL_BLANK)))
    elif second >= FILL_MARKED and margin < MARGIN_CONFIDENT:
        # Two bubbles both look filled: never guess between them.
        outcome = DetectionOutcome.MULTIPLE
        detected = None
        confidence = float(max(0.0, 1.0 - margin / MARGIN_CONFIDENT) * 0.5)
    elif best.fill < FILL_MARKED:
        # Something is there, but it is faint. Always surface it, whatever the
        # separation from the runner-up looks like.
        detected = best.option_index
        span = FILL_MARKED - FILL_BLANK
        outcome = DetectionOutcome.LOW_CONFIDENCE
        confidence = float(
            max(0.0, min(LOW_CONFIDENCE - 0.05, 0.30 + 0.30 * (best.fill - FILL_BLANK) / span))
        )
    else:
        detected = best.option_index
        # Confidence combines "is it clearly a mark" with "is it clearly THE mark".
        strength = min(1.0, best.fill / (FILL_MARKED * 1.6))
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


def process_page(image: Image, option_counts: list[int]) -> PageResult:
    """The whole per-page pipeline. Never raises: a failure is a result."""
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

    uid, uid_conf, _ = read_uid_grid(reg.canonical)
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
    )
