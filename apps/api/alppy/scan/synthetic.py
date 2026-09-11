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
from alppy.sheets.uid_code import CANTON_UNSET, PageCode, encode_page_code, encode_uid

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
    return round(v * PX_PER_MM)


def draw_mark(
    img: Image,
    centre: tuple[int, int],
    radius: int,
    *,
    style: str = "fill",
    pencil: float = 0.9,
    seed: int = 0,
    thickness_frac: float = 0.18,
) -> None:
    """The student's own mark inside one bubble.

    ``fill`` is the original: a solid disc at 75% of the radius, which is what
    the detector's density thresholds were tuned against.

    ``cross`` is a hand-drawn X — two strokes near the diagonals, each one
    wobbled by a few degrees and stopping short of the ring by a random margin,
    because nobody draws a clean X in a 5 mm circle. The imperfection is the
    point: a geometrically perfect cross would test the detector against a
    shape it will never actually be handed.
    """
    shade = int(PAPER * (1.0 - pencil))
    if style == "fill":
        cv2.circle(img, centre, int(radius * 0.75), shade, thickness=-1)
        return
    if style != "cross":
        raise ValueError(f"unknown mark style {style!r}")

    rng = np.random.default_rng(seed)
    # `thickness_frac` defaults to ~0.45 mm at 8 px/mm: a ballpoint.
    # Deliberately thin — a fatter stroke covers enough of the disc for the
    # density measure to catch it alone, and the shape test this harness
    # exists to exercise would never run. Tests that want a finer pen (the
    # case density genuinely cannot read) pass a smaller fraction.
    thickness = max(1, round(radius * thickness_frac))
    cx, cy = centre
    for base in (45.0, 135.0):
        angle = np.radians(base + float(rng.uniform(-12.0, 12.0)))
        dx, dy = np.cos(angle), np.sin(angle)
        # Each arm reaches most of the way out, by its own amount.
        r0 = radius * float(rng.uniform(0.72, 0.95))
        r1 = radius * float(rng.uniform(0.72, 0.95))
        # ...from a start point a little off the exact centre.
        ox = float(rng.uniform(-0.12, 0.12)) * radius
        oy = float(rng.uniform(-0.12, 0.12)) * radius
        cv2.line(
            img,
            (round(cx + ox - dx * r0), round(cy + oy - dy * r0)),
            (round(cx + ox + dx * r1), round(cy + oy + dy * r1)),
            shade,
            thickness=thickness,
            lineType=cv2.LINE_AA,
        )


def draw_stray_line(
    img: Image,
    item_index: int,
    option_index: int,
    *,
    angle_deg: float = 40.0,
    pencil: float = 0.75,
) -> None:
    """One stroke straight through a bubble the student did not choose.

    A rested pen, a ruled line, a crossing-out that overshot. It puts real ink
    inside the disc, so the density measure sees something; only the shape test
    can tell it is one stroke and not two."""
    cx, cy = L.bubble_centre_mm(item_index, option_index)
    centre = (_mm(cx), _mm(cy))
    radius = round(L.BUBBLE_D_MM / 2.0 * PX_PER_MM)
    angle = np.radians(angle_deg)
    dx, dy = np.cos(angle), np.sin(angle)
    reach = radius * 1.4
    cv2.line(
        img,
        (round(centre[0] - dx * reach), round(centre[1] - dy * reach)),
        (round(centre[0] + dx * reach), round(centre[1] + dy * reach)),
        int(PAPER * (1.0 - pencil)),
        thickness=max(1, round(radius * 0.28)),
        lineType=cv2.LINE_AA,
    )


def draw_smudge(
    img: Image, item_index: int, option_index: int, *, pencil: float = 0.35, seed: int = 0
) -> None:
    """An erased answer: grey, spread out, with no straight edge anywhere.

    The case that justifies looking at the outer band rather than the whole
    disc — a vigorous rubbing-out can spread ink in every direction, and only
    "is it arranged as strokes" separates it from a real mark."""
    cx, cy = L.bubble_centre_mm(item_index, option_index)
    centre = (_mm(cx), _mm(cy))
    radius = round(L.BUBBLE_D_MM / 2.0 * PX_PER_MM)
    rng = np.random.default_rng(seed)
    shade = int(PAPER * (1.0 - pencil))
    for _ in range(9):
        ox = float(rng.uniform(-0.75, 0.75)) * radius
        oy = float(rng.uniform(-0.75, 0.75)) * radius
        cv2.circle(
            img,
            (round(centre[0] + ox), round(centre[1] + oy)),
            max(1, round(radius * 0.22)),
            shade,
            thickness=-1,
        )


def _default_page_code(uid: str) -> PageCode:
    """The non-identity half of a v2 grid, for a test that only cares about the
    pupil. Page 1, no canton, and a nonce that is recognisably a fixture."""
    return PageCode(
        uid=uid, school_year=0, page_in_copy=1, canton=CANTON_UNSET, nonce=0
    )


def render_page(
    uid: str,
    option_counts: list[int],
    marked: list[int | None],
    *,
    pencil: float = 0.9,
    mark_style: str = "fill",
    seed: int = 0,
    layout_version: str | None = None,
    page_code: PageCode | None = None,
) -> SyntheticSheet:
    """Draw one canonical page.

    ``marked[i]`` is the option the student filled for item ``i``, or None for a
    blank. ``pencil`` is how thoroughly the bubble was filled in, 0..1 — a child
    scribbling lightly is the interesting case for the confidence model.

    ``layout_version`` selects the UID grid geometry (B4). Under v2 the grid
    encodes the whole page rather than only the pupil, so ``page_code`` carries
    the rest; passing only a ``uid`` fills the other fields with a fixed,
    obviously-synthetic default, which is what most tests want.
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
    version = layout_version or L.LAYOUT_VERSION
    grid = L.uid_grid(version)
    if version == "v1":
        bits = encode_uid(uid)
    else:
        bits = encode_page_code(page_code or _default_page_code(uid))
    for slot in range(grid.cells):
        for row in range(grid.rows):
            cx, cy = grid.cell_centre_mm(slot, row)
            c = grid.cell_mm / 2.0
            p0 = (_mm(cx - c), _mm(cy - c))
            p1 = (_mm(cx + c), _mm(cy + c))
            bit = bits[slot * grid.rows + row]
            cv2.rectangle(img, p0, p1, INK, thickness=-1 if bit else 1)

    # --- answer bubbles: outline always, fill where the student marked
    for item_index, n_options in enumerate(option_counts):
        for oi in range(n_options):
            cx, cy = L.bubble_centre_mm(item_index, oi)
            centre = (_mm(cx), _mm(cy))
            radius = round(L.BUBBLE_D_MM / 2.0 * PX_PER_MM)
            cv2.circle(img, centre, radius, INK, thickness=1)
            if marked[item_index] == oi:
                draw_mark(
                    img,
                    centre,
                    radius,
                    style=mark_style,
                    pencil=pencil,
                    # Per bubble, so a page of crosses is a page of different
                    # crosses rather than the same one stamped sixteen times.
                    seed=seed * 1000 + item_index * 10 + oi,
                )

    return SyntheticSheet(image=img, uid=uid, option_counts=option_counts, marked=marked)


# --------------------------------------------------------------------------
# Written-answer boxes — the furniture the renderer prints, and a student's ink
# --------------------------------------------------------------------------
def draw_answer_box(
    img: Image, x_mm: float, y_mm: float, w_mm: float, h_mm: float, *, fill: str = "lined"
) -> None:
    """Exactly what the print markup draws: the border, the four corner ticks
    crossing it from outside, and the guides — lines every 8 mm or the 5 mm
    grid — in the light grey the paper gets for ``--c-ink-300``."""
    x0, y0, x1, y1 = _mm(x_mm), _mm(y_mm), _mm(x_mm + w_mm), _mm(y_mm + h_mm)
    border = max(1, _mm(L.ANSWER_BOX_BORDER_MM))
    guide_grey = 170
    if fill == "lined":
        pitch = L.ANSWER_BOX_LINE_PITCH_MM
        for k in range(1, int(h_mm / pitch) + 1):
            y = y0 + _mm(k * pitch)
            if y < y1:
                cv2.line(img, (x0, y), (x1, y), guide_grey, 1)
    elif fill == "grid":
        pitch = L.ANSWER_BOX_GRID_MM
        for k in range(1, int(h_mm / pitch) + 1):
            y = y0 + _mm(k * pitch)
            if y < y1:
                cv2.line(img, (x0, y), (x1, y), guide_grey, 1)
        for k in range(1, int(w_mm / pitch) + 1):
            x = x0 + _mm(k * pitch)
            if x < x1:
                cv2.line(img, (x, y0), (x, y1), guide_grey, 1)
    cv2.rectangle(img, (x0, y0), (x1, y1), INK, thickness=border)
    tick = _mm(L.ANSWER_BOX_TICK_MM)
    for cx, cy, sx, sy in ((x0, y0, -1, -1), (x1, y0, 1, -1), (x0, y1, -1, 1), (x1, y1, 1, 1)):
        cv2.line(img, (cx, cy), (cx + sx * tick, cy), INK, border)
        cv2.line(img, (cx, cy), (cx, cy + sy * tick), INK, border)


def scribble(
    img: Image, x_mm: float, y_mm: float, w_mm: float, h_mm: float, *, seed: int = 0,
    shade: int = INK, strokes: int = 6,
) -> None:
    """A student's writing: a few thick wavy strokes across the box, well
    inside it. Not letters — the detector never reads them — but enough ink,
    in the right place, for the crop to be plainly not blank."""
    rng = np.random.default_rng(seed)
    x0, y0 = _mm(x_mm + 6), _mm(y_mm + 5)
    x1, y1 = _mm(x_mm + w_mm - 6), _mm(y_mm + h_mm - 5)
    if x1 <= x0 or y1 <= y0:
        return
    for _ in range(strokes):
        y = int(rng.integers(y0, y1))
        xs = np.linspace(x0, x1, 40)
        ys = y + (np.sin(xs / 25.0) * 12).astype(int)
        pts = np.stack([xs.astype(int), ys], axis=1).reshape(-1, 1, 2)
        cv2.polylines(img, [pts], False, shade, thickness=max(2, _mm(0.8)))


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
