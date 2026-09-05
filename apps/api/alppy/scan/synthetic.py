"""Synthetic sheet rendering and degradation, for testing the detector.

This is a *test double for the printer and the camera*, not a second renderer:
it draws exactly the marks the layout module specifies — the four fiducials, the
UID grid, the answer bubbles — and nothing else. That is the point. If the
detector and the layout ever disagree, this harness fails, which is the cheapest
possible place to catch a layout drift.

The degradations model what actually arrives from a classroom: a page fed
crooked into a copier, a phone photo taken at an angle over a desk, a third-
generation photocopy with grey paper and blown-out contrast.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

from alppy.scan.detector import PX_PER_MM
from alppy.sheets import layout as L
from alppy.sheets.uid_code import encode_uid

Image = npt.NDArray[np.uint8]

INK = 0
PAPER = 255


@dataclass(frozen=True, slots=True)
class SyntheticSheet:
    image: Image
    uid: str
    option_counts: list[int]
    marked: list[int | None]


def _mm(v: float) -> int:
    return int(round(v * PX_PER_MM))


def render_page(
    uid: str,
    option_counts: list[int],
    marked: list[int | None],
    *,
    pencil: float = 0.9,
) -> SyntheticSheet:
    """Draw one canonical page.

    ``marked[i]`` is the option the student filled for item ``i``, or None for a
    blank. ``pencil`` is how thoroughly the bubble was filled in, 0..1 — a child
    scribbling lightly is the interesting case for the confidence model.
    """
    if len(option_counts) != len(marked):
        raise ValueError("option_counts and marked must be the same length")

    img: Image = np.full(
        (int(L.PAGE_H_MM * PX_PER_MM), int(L.PAGE_W_MM * PX_PER_MM)), PAPER, dtype=np.uint8
    )

    # --- fiducials: solid squares at the four corners
    half = L.FIDUCIAL_MM / 2.0
    for cx_mm, cy_mm in L.FIDUCIAL_CENTRES_MM.values():
        cv2.rectangle(
            img,
            (_mm(cx_mm - half), _mm(cy_mm - half)),
            (_mm(cx_mm + half), _mm(cy_mm + half)),
            INK,
            thickness=-1,
        )

    # --- UID grid: outlined cells, filled where the bit is 1
    bits = encode_uid(uid)
    for slot in range(L.UID_GRID_CELLS):
        for row in range(L.UID_GRID_ROWS):
            cx, cy = L.uid_cell_centre_mm(slot, row)
            c = L.UID_GRID_CELL_MM / 2.0
            p0 = (_mm(cx - c), _mm(cy - c))
            p1 = (_mm(cx + c), _mm(cy + c))
            bit = bits[slot * L.UID_GRID_ROWS + row]
            cv2.rectangle(img, p0, p1, INK, thickness=-1 if bit else 1)

    # --- answer bubbles: outline always, fill where the student marked
    for item_index, n_options in enumerate(option_counts):
        for oi in range(n_options):
            cx, cy = L.bubble_centre_mm(item_index, oi)
            centre = (_mm(cx), _mm(cy))
            radius = int(round(L.BUBBLE_D_MM / 2.0 * PX_PER_MM))
            cv2.circle(img, centre, radius, INK, thickness=1)
            if marked[item_index] == oi:
                shade = int(PAPER * (1.0 - pencil))
                cv2.circle(img, centre, int(radius * 0.75), shade, thickness=-1)

    return SyntheticSheet(image=img, uid=uid, option_counts=option_counts, marked=marked)


# --------------------------------------------------------------------------
# Degradations — what the classroom does to a sheet on its way back
# --------------------------------------------------------------------------
def rotate(img: Image, degrees: float, *, border: int = PAPER) -> Image:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), degrees, 1.0)
    return cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=border)


def perspective(img: Image, strength: float, *, border: int = PAPER) -> Image:
    """A phone held at an angle over the desk. ``strength`` 0..0.15 is realistic."""
    h, w = img.shape[:2]
    dx, dy = w * strength, h * strength * 0.5
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[dx, dy * 0.4], [w - dx * 0.35, 0], [w - dx * 0.1, h], [dx * 0.5, h - dy]])
    m = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, m, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=border)


def photocopy(img: Image, *, generations: int = 1, paper_grey: int = 246) -> Image:
    """Grey paper, thickened ink, lost mid-tones — a third-generation copy.

    The transfer curve matters more than it looks. An earlier version used a
    steep contrast boost with its black point at 110, which mapped a mid-grey
    pencil mark (~140) almost to paper white and made the whole suite look like
    a detector failure. Real copiers clip the extremes and compress the middle;
    they lose *very* light pencil and keep the rest. Black point 70 / white
    point 215 reproduces that without slandering the detector.
    """
    out = img.astype(np.float32)
    black_point, white_point = 70.0, 215.0
    for _ in range(max(1, generations)):
        out = cv2.GaussianBlur(out, (3, 3), 0)
        out = np.clip((out - black_point) / (white_point - black_point) * 255.0, 0, 255)
    out = out * (paper_grey / 255.0)
    return np.clip(out, 0, 255).astype(np.uint8)


def uneven_light(img: Image, strength: float = 0.35) -> Image:
    """A shadow across one side of the page, the classic phone-photo failure."""
    h, w = img.shape[:2]
    gx = np.linspace(1.0, 1.0 - strength, w, dtype=np.float32)
    gy = np.linspace(1.0, 1.0 - strength * 0.4, h, dtype=np.float32)
    gradient = np.outer(gy, gx)
    return np.clip(img.astype(np.float32) * gradient, 0, 255).astype(np.uint8)


def noise(img: Image, sigma: float = 8.0, *, seed: int = 0) -> Image:
    rng = np.random.default_rng(seed)
    out = img.astype(np.float32) + rng.normal(0, sigma, img.shape).astype(np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)


def jpeg(img: Image, quality: int = 55) -> Image:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:  # pragma: no cover - encoder failure is not a real case
        return img
    decoded = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    return decoded.astype(np.uint8)


def rescale(img: Image, factor: float) -> Image:
    h, w = img.shape[:2]
    interp = cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, (int(w * factor), int(h * factor)), interpolation=interp)


def phone_photo(img: Image, *, seed: int = 0) -> Image:
    """The full realistic pipeline: angle, shadow, sensor noise, JPEG, downscale."""
    out = perspective(img, 0.045)
    out = rotate(out, 1.8)
    out = uneven_light(out, 0.30)
    out = rescale(out, 0.55)
    out = noise(out, 6.0, seed=seed)
    return jpeg(out, 62)


def copier(img: Image, *, seed: int = 0) -> Image:
    """Fed slightly crooked into a photocopier, twice."""
    out = rotate(img, -1.2)
    out = photocopy(out, generations=2)
    out = noise(out, 4.0, seed=seed)
    return rescale(out, 0.7)
