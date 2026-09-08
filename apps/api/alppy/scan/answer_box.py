"""Cutting a written-answer box out of a registered page.

The bubbles are read by geometry alone; a box is *cut* by geometry alone and
then handed to a model that reads handwriting. Everything here is what happens
between the registered page and that hand-over, and none of it is a judgement
about the answer:

1. **Crop** at the rectangle the renderer measured for this copy and page
   (``AnswerBoxPlacement``), in the canonical 8 px/mm frame the detector
   produces — so a phone photo taken at an angle crops the same box a flatbed
   scan does.
2. **Remove the furniture Alppy printed.** The border and the corner ticks sit
   at the crop's own edges, so a thin band along each edge is painted white.
   The guides (lines every 8 mm, or the 5 mm grid) sit at known offsets from
   the top-left corner, so thin bands at those offsets are painted white too —
   but only where the pixel is lighter than heavy ink, so a pen stroke crossing
   a guide survives. A light pencil stroke crossing a guide loses a millimetre
   there; the model is told which guides the box carried, and the prompt says
   to ignore them.
3. **Say whether anything was written at all.** A box with no ink is a blank,
   and a blank does not need a model call to say so.

Nothing here reads a word, and nothing here is a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

from alppy.models.enums import AnswerBoxFill
from alppy.scan.detector import PX_PER_MM
from alppy.sheets import layout as L

Image = npt.NDArray[np.uint8]

PAPER: Final = 255

EDGE_BAND_MM: Final = L.ANSWER_BOX_BORDER_MM + 0.75
"""How far in from the crop's edge the printed border can sit once registration
error is allowed for. Everything in this band is the box's own line, or a
corner tick that leaked inward, never the student's answer."""

GUIDE_BAND_MM: Final = 0.6
"""Half-width of the band painted out around each printed guide line."""

GUIDE_INK_FRACTION: Final = 0.45
"""Inside a guide band, a pixel darker than this fraction of the local paper
level is pen and is kept; anything lighter is the guide (or a pencil stroke
we cannot tell from it) and is painted out."""

BLANK_INK_RATIO: Final = 0.0015
"""Below this share of dark pixels the box is empty. Tuned so a single short
word in pencil is well above it, and a stray dot from the copier below."""

INK_FRACTION: Final = 0.6
"""A pixel darker than this fraction of the local paper level is ink of some
kind — pen, pencil, or a guide that escaped the bands. Used only to measure
how much was written, never to decide what."""


@dataclass(frozen=True, slots=True)
class BoxRect:
    """A rectangle in page millimetres, as ``AnswerBoxPlacement`` stores it."""

    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float


@dataclass(frozen=True, slots=True)
class BoxCrop:
    image: Image
    """Greyscale, furniture removed, the student's ink on white."""
    ink_ratio: float
    """Share of pixels that are ink, after the furniture is gone."""

    @property
    def blank(self) -> bool:
        return self.ink_ratio < BLANK_INK_RATIO

    @property
    def blank_confidence(self) -> float:
        """How sure the blank verdict is: 1 for a spotless box, falling to 0 at
        the threshold, so a box with *something* in it goes to the teacher."""
        return float(max(0.0, min(1.0, 1.0 - self.ink_ratio / BLANK_INK_RATIO)))


def _px(mm: float) -> int:
    return round(mm * PX_PER_MM)


def _paper_level(crop: Image) -> float:
    """The brightness of paper in this crop: a high percentile, so the answer
    itself cannot drag it down, floored so a black scan does not make every
    pixel count as paper."""
    return max(float(np.percentile(crop, 90)), 40.0)


def crop_answer_box(canonical: Image, rect: BoxRect, *, fill: AnswerBoxFill) -> BoxCrop:
    """The inside of one answer box, with Alppy's own ink removed."""
    h, w = canonical.shape[:2]
    x0, y0 = max(0, _px(rect.x_mm)), max(0, _px(rect.y_mm))
    x1, y1 = min(w, _px(rect.x_mm + rect.w_mm)), min(h, _px(rect.y_mm + rect.h_mm))
    if x1 - x0 < 4 or y1 - y0 < 4:
        raise ValueError(f"answer box {rect} falls outside the page")
    crop: Image = canonical[y0:y1, x0:x1].copy()
    paper = _paper_level(crop)

    _paint_edges(crop)
    _paint_guides(crop, fill=fill, paper=paper)

    ink = crop < paper * INK_FRACTION
    return BoxCrop(image=crop, ink_ratio=float(ink.mean()))


def _paint_edges(crop: Image) -> None:
    band = _px(EDGE_BAND_MM)
    crop[:band, :] = PAPER
    crop[-band:, :] = PAPER
    crop[:, :band] = PAPER
    crop[:, -band:] = PAPER


def _paint_guides(crop: Image, *, fill: AnswerBoxFill, paper: float) -> None:
    """Paint out the printed guides where they are, keeping pen that crosses
    them. The pattern is anchored at the box's top-left corner, which is the
    crop's corner less the border: line ``k`` sits ``k`` pitches down."""
    if fill is AnswerBoxFill.BLANK:
        return
    pitch_mm = L.ANSWER_BOX_LINE_PITCH_MM if fill is AnswerBoxFill.LINED else L.ANSWER_BOX_GRID_MM
    half = _px(GUIDE_BAND_MM)
    keep_dark = paper * GUIDE_INK_FRACTION
    h, w = crop.shape[:2]
    origin = _px(L.ANSWER_BOX_BORDER_MM)

    def paint(sl: tuple[slice, slice]) -> None:
        region = crop[sl]
        region[region > keep_dark] = PAPER

    for k in range(1, int(h / (pitch_mm * PX_PER_MM)) + 2):
        y = origin + _px(k * pitch_mm)
        if y - half >= h:
            break
        paint((slice(max(0, y - half), min(h, y + half + 1)), slice(0, w)))
    if fill is AnswerBoxFill.GRID:
        for k in range(1, int(w / (pitch_mm * PX_PER_MM)) + 2):
            x = origin + _px(k * pitch_mm)
            if x - half >= w:
                break
            paint((slice(0, h), slice(max(0, x - half), min(w, x + half + 1))))


def encode_png(image: Image) -> bytes:
    import cv2

    ok, buf = cv2.imencode(".png", image)
    if not ok:  # pragma: no cover - cv2 encodes any 8-bit array
        raise ValueError("could not encode the crop")
    return buf.tobytes()


__all__ = ["BoxCrop", "BoxRect", "crop_answer_box", "encode_png"]
