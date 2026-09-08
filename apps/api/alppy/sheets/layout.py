"""Sheet layout geometry — the single source of truth for layout version v1.

Three consumers must agree exactly on these numbers:

1. the print markup (``WorksheetPrintSheet`` + ``packages/ui/src/design/print.css``),
2. the server-side PDF renderer (headless Chromium over that same markup),
3. the scan detector (``alppy.scan``), which registers a photographed page against
   the four corner fiducials and then looks for bubbles at these coordinates.

Because the detector reads coordinates *derived from this file*, changing any
number here is a layout version bump, never a tweak. Sheets store the version
they were printed with (``Sheet.layout_version``) so old scans keep working.

All distances are millimetres from the top-left corner of the physical A4 page.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

LAYOUT_VERSION: Final = "v1"

# --- The page ------------------------------------------------------------
PAGE_W_MM: Final = 210.0
PAGE_H_MM: Final = 297.0
MARGIN_MM: Final = 14.0

# --- Corner fiducials ----------------------------------------------------
# Solid squares printed as *borders* so they survive the browser's default
# "no background graphics" setting. Their centres define the registration
# frame; every other coordinate is expressed relative to that frame, so the
# detector needs nothing from the page but these four marks.
FIDUCIAL_MM: Final = 8.0
_F: Final = FIDUCIAL_MM / 2.0

FIDUCIAL_CENTRES_MM: Final[dict[str, tuple[float, float]]] = {
    "tl": (MARGIN_MM + _F, MARGIN_MM + _F),
    "tr": (PAGE_W_MM - MARGIN_MM - _F, MARGIN_MM + _F),
    "bl": (MARGIN_MM + _F, PAGE_H_MM - MARGIN_MM - _F),
    "br": (PAGE_W_MM - MARGIN_MM - _F, PAGE_H_MM - MARGIN_MM - _F),
}

FRAME_X0_MM: Final = FIDUCIAL_CENTRES_MM["tl"][0]
FRAME_Y0_MM: Final = FIDUCIAL_CENTRES_MM["tl"][1]
FRAME_W_MM: Final = FIDUCIAL_CENTRES_MM["tr"][0] - FRAME_X0_MM
FRAME_H_MM: Final = FIDUCIAL_CENTRES_MM["bl"][1] - FRAME_Y0_MM

# --- Header and UID ------------------------------------------------------
HEADER_TOP_MM: Final = 26.0
HEADER_H_MM: Final = 18.0

# The UID is printed twice: as human-readable text, and as a pre-filled digit
# grid the detector reads directly. That is why the happy path needs no OCR.
UID_GRID_ORIGIN_MM: Final = (120.0, 30.0)
UID_GRID_CELL_MM: Final = 4.0
UID_GRID_GAP_MM: Final = 1.0
UID_GRID_CELLS: Final = 8  # "7B_15" padded; one column per character slot
UID_GRID_ROWS: Final = 4  # 4 bits per slot -> 16 symbols, enough for 0-9 A-Z subset

# --- Item statements -----------------------------------------------------
ITEMS_TOP_MM: Final = 48.0
ITEMS_BOTTOM_MM: Final = 196.0

# --- The fixed answer grid ----------------------------------------------
# Deliberately NOT inline with the statements. Statement height varies with the
# text; a grid at a fixed position does not. This is what makes detection
# robust: the detector can find every bubble from the fiducials alone, without
# understanding a single word on the page.
#
# Two column groups of 8 rows = 16 items per physical page.
GRID_TOP_MM: Final = 202.0
GRID_ORIGIN_MM: Final = (24.0, 206.0)
GRID_ROWS: Final = 8
GRID_GROUPS: Final = 2
GRID_GROUP_PITCH_MM: Final = 88.0
GRID_ROW_PITCH_MM: Final = 8.5
GRID_NUMBER_W_MM: Final = 14.0
BUBBLE_PITCH_MM: Final = 8.0
BUBBLE_D_MM: Final = 5.0
MAX_OPTIONS: Final = 4

ITEMS_PER_PAGE: Final = GRID_ROWS * GRID_GROUPS

# --- Written-answer boxes -----------------------------------------------
# An `open` item prints a delimited box under its statement. Unlike a bubble,
# the box's POSITION is not fixed here: it sits under text whose height the
# browser decides, so the renderer measures it and records the rectangle per
# printed copy (``AnswerBoxPlacement``). What the crop step must know a priori
# is the furniture it removes — the border, the corner ticks, the guide pitch —
# and that is what lives here. Adding these did not move a fiducial or a
# bubble, so it is not a layout version bump; a placement carries the version
# it was printed under all the same.
ANSWER_BOX_LINE_PITCH_MM: Final = 8.0  # one guide line per written line
ANSWER_BOX_GRID_MM: Final = 5.0  # the square of a Swiss maths notebook
ANSWER_BOX_BORDER_MM: Final = 0.35  # 1 pt
ANSWER_BOX_TICK_MM: Final = 3.0  # arm of the L-shaped corner tick, outside the box
ANSWER_BOX_LINE_PRESETS: Final[tuple[int, ...]] = (3, 5, 8, 12)
ANSWER_BOX_DEFAULT_LINES: Final = 5


class OptionLetters(StrEnum):
    """Printed glyphs. Positions never change — only the glyph does."""

    MCQ = "ABCD"
    TF_FR = "VF"  # Vrai / Faux
    TF_DE = "RF"  # Richtig / Falsch
    TF_EN = "TF"  # True / False


def tf_letters(locale: str) -> str:
    return {"fr": OptionLetters.TF_FR, "de": OptionLetters.TF_DE}.get(
        locale, OptionLetters.TF_EN
    ).value


@dataclass(frozen=True, slots=True)
class BubbleSlot:
    """One machine-readable bubble on one physical page."""

    page_index: int
    item_index: int  # 0-based index of the item *on this page*
    option_index: int  # 0-based; 0..1 for true/false, 0..3 for MCQ
    cx_mm: float
    cy_mm: float

    @property
    def u(self) -> float:
        """X within the fiducial frame, normalised to [0, 1]."""
        return (self.cx_mm - FRAME_X0_MM) / FRAME_W_MM

    @property
    def v(self) -> float:
        """Y within the fiducial frame, normalised to [0, 1]."""
        return (self.cy_mm - FRAME_Y0_MM) / FRAME_H_MM


def bubble_centre_mm(item_index: int, option_index: int) -> tuple[float, float]:
    """Centre of the bubble for item ``item_index`` on a page, option ``option_index``.

    ``item_index`` is 0-based *within the page*: items 0-7 fill the left column
    group top to bottom, items 8-15 the right group.
    """
    if not 0 <= item_index < ITEMS_PER_PAGE:
        raise ValueError(f"item_index {item_index} outside 0..{ITEMS_PER_PAGE - 1}")
    if not 0 <= option_index < MAX_OPTIONS:
        raise ValueError(f"option_index {option_index} outside 0..{MAX_OPTIONS - 1}")

    group, row = divmod(item_index, GRID_ROWS)
    ox, oy = GRID_ORIGIN_MM
    cx = (
        ox
        + group * GRID_GROUP_PITCH_MM
        + GRID_NUMBER_W_MM
        + option_index * BUBBLE_PITCH_MM
        + BUBBLE_D_MM / 2.0
    )
    cy = oy + row * GRID_ROW_PITCH_MM + BUBBLE_D_MM / 2.0
    return (cx, cy)


def page_slots(page_index: int, option_counts: list[int]) -> list[BubbleSlot]:
    """Every bubble the detector should inspect on one physical page.

    ``option_counts[i]`` is how many options item ``i`` on this page actually has
    (2 for true/false, up to 4 for MCQ). Items with 0 options — free-text — get
    no bubbles: they are printed and never auto-graded.
    """
    slots: list[BubbleSlot] = []
    for item_index, n_options in enumerate(option_counts):
        for option_index in range(n_options):
            cx, cy = bubble_centre_mm(item_index, option_index)
            slots.append(
                BubbleSlot(
                    page_index=page_index,
                    item_index=item_index,
                    option_index=option_index,
                    cx_mm=cx,
                    cy_mm=cy,
                )
            )
    return slots


def uid_cell_centre_mm(slot: int, row: int) -> tuple[float, float]:
    """Centre of one cell of the pre-filled UID grid."""
    ox, oy = UID_GRID_ORIGIN_MM
    pitch = UID_GRID_CELL_MM + UID_GRID_GAP_MM
    return (
        ox + slot * pitch + UID_GRID_CELL_MM / 2.0,
        oy + row * pitch + UID_GRID_CELL_MM / 2.0,
    )


def as_dict() -> dict[str, object]:
    """Serialisable form, exported to TypeScript so the web print preview and the
    detector cannot drift. See ``scripts/export-layout.py``."""
    return {
        "layoutVersion": LAYOUT_VERSION,
        "pageWMm": PAGE_W_MM,
        "pageHMm": PAGE_H_MM,
        "marginMm": MARGIN_MM,
        "fiducialMm": FIDUCIAL_MM,
        "fiducialCentresMm": {k: list(v) for k, v in FIDUCIAL_CENTRES_MM.items()},
        "frame": {
            "x0Mm": FRAME_X0_MM,
            "y0Mm": FRAME_Y0_MM,
            "wMm": FRAME_W_MM,
            "hMm": FRAME_H_MM,
        },
        "headerTopMm": HEADER_TOP_MM,
        "itemsTopMm": ITEMS_TOP_MM,
        "itemsBottomMm": ITEMS_BOTTOM_MM,
        "uidGrid": {
            "originMm": list(UID_GRID_ORIGIN_MM),
            "cellMm": UID_GRID_CELL_MM,
            "gapMm": UID_GRID_GAP_MM,
            "cells": UID_GRID_CELLS,
            "rows": UID_GRID_ROWS,
        },
        "grid": {
            "topMm": GRID_TOP_MM,
            "originMm": list(GRID_ORIGIN_MM),
            "rows": GRID_ROWS,
            "groups": GRID_GROUPS,
            "groupPitchMm": GRID_GROUP_PITCH_MM,
            "rowPitchMm": GRID_ROW_PITCH_MM,
            "numberWMm": GRID_NUMBER_W_MM,
            "bubblePitchMm": BUBBLE_PITCH_MM,
            "bubbleDMm": BUBBLE_D_MM,
            "maxOptions": MAX_OPTIONS,
        },
        "itemsPerPage": ITEMS_PER_PAGE,
        "answerBox": {
            "linePitchMm": ANSWER_BOX_LINE_PITCH_MM,
            "gridMm": ANSWER_BOX_GRID_MM,
            "borderMm": ANSWER_BOX_BORDER_MM,
            "tickMm": ANSWER_BOX_TICK_MM,
            "linePresets": list(ANSWER_BOX_LINE_PRESETS),
            "defaultLines": ANSWER_BOX_DEFAULT_LINES,
        },
    }
