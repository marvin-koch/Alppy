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

LAYOUT_VERSION: Final = "v2"

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
class UnknownLayoutError(ValueError):
    """A page printed under a layout this build has no geometry for."""


#: The UID grid, **per layout version**, because a printed page keeps the
#: geometry it was printed with forever (B4).
#:
#: Before this, the detector read every page against the constants as they
#: existed *today* and refused outright when `Sheet.layout_version` did not
#: match — which was the only honest answer available, and it meant the first
#: version bump would make every already-printed sheet unreadable. A pile
#: photographed in March from a sheet printed in January is the ordinary case,
#: not an edge one, so the geometry has to be selectable rather than current.
@dataclass(frozen=True, slots=True)
class UidGrid:
    """Where the machine-readable UID cells sit, and how many bits they carry."""

    origin_mm: tuple[float, float]
    cell_mm: float
    gap_mm: float
    cells: int
    rows: int
    payload_bits: int
    checksum_bits: int

    @property
    def pitch_mm(self) -> float:
        return self.cell_mm + self.gap_mm

    @property
    def total_bits(self) -> int:
        return self.cells * self.rows

    @property
    def width_mm(self) -> float:
        return self.cells * self.cell_mm + (self.cells - 1) * self.gap_mm

    @property
    def height_mm(self) -> float:
        return self.rows * self.cell_mm + (self.rows - 1) * self.gap_mm

    def cell_centre_mm(self, slot: int, row: int) -> tuple[float, float]:
        ox, oy = self.origin_mm
        return (
            ox + slot * self.pitch_mm + self.cell_mm / 2.0,
            oy + row * self.pitch_mm + self.cell_mm / 2.0,
        )


UID_GRIDS: Final[dict[str, UidGrid]] = {
    # 8 x 4 = 32 bits: 24 payload + CRC-8. Frozen forever — every sheet printed
    # before v2 is read against exactly this.
    "v1": UidGrid(
        origin_mm=(120.0, 30.0),
        cell_mm=4.0,
        gap_mm=1.0,
        cells=8,
        rows=4,
        payload_bits=24,
        checksum_bits=8,
    ),
    # 12 x 6 = 72 bits: 57 payload (+1 spare) + CRC-16.
    #
    # **Wider, and moved UP rather than down.** Six rows at the v1 origin would
    # span y 30..60 and print over the first exercise: `ITEMS_TOP_MM` is 48.
    # Pushing the items region down instead was the obvious alternative and is
    # the wrong one — `ANSWER_BOX_MAX_LINES` is calibrated to the millimetre
    # against that region ("14 lines is 133.3 mm of the 134 mm a page has"), so
    # moving it silently costs a teacher the tallest box they can ask for.
    #
    # At y=18 the grid ends at 47, one millimetre clear of the items. It
    # overlaps the fiducial band vertically (14..22) and that is harmless: the
    # fiducials sit at x 14..22 and 188..196, and this grid spans x 120..179.
    # CRC-16 rather than CRC-8 because the payload more than doubled, and an
    # 8-bit checksum over 57 bits on a creased photocopy is no longer the
    # "fails rather than resolves to a different real student" guarantee that
    # makes the whole scheme safe.
    "v2": UidGrid(
        origin_mm=(120.0, 18.0),
        cell_mm=4.0,
        gap_mm=1.0,
        cells=12,
        rows=6,
        payload_bits=56,
        checksum_bits=16,
    ),
}


def uid_grid(version: str | None = None) -> UidGrid:
    """The grid for one layout version. Raises for a version we cannot read."""
    key = version or LAYOUT_VERSION
    try:
        return UID_GRIDS[key]
    except KeyError:
        raise UnknownLayoutError(f"no geometry for layout {key!r}") from None


# The bare `UID_GRID_*` constants are deliberately gone. They held v1's numbers
# under a name that read as "the current grid", which is a trap with two live
# layouts: `as_dict()` exported them beside `layoutVersion: "v2"` and the web
# print preview would have drawn an 8x4 grid at y=30 while the server printed
# 12x6 at y=18 — the exact drift `scripts/export-layout.py` exists to catch,
# walking straight past it because both sides agreed on a stale number.
# Ask `uid_grid(version)` instead, and say which version you mean.

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
# The tallest box a teacher may ask for, in lines. Any height from 1 to this
# is allowed — the presets are shortcuts, not the only choices. The ceiling is
# the tallest box that still fits the statement region alone when carried to
# the next page (``pagination.continuation_height_mm``): 14 lines is 133.3 mm
# of the 134 mm a page has for statements; 15 would not fit any page.
ANSWER_BOX_MAX_LINES: Final = 14
ANSWER_BOX_NO_BOX: Final = 0  # the teacher's "worked in the notebook"
ANSWER_BOX_DEFAULT_LINES: Final = 5

# --- Grading policy ------------------------------------------------------
# The teacher's barème: what a correct answer is worth, and what a wrong one
# costs. Not print geometry — nothing here moves a fiducial or a bubble, so
# this is not a layout version bump. It lives here anyway because the printed
# points label is a *pagination* concern: `pagination.POINTS_LABEL_W_MM` has
# to reserve room for the widest label a teacher can ask for, and that width
# is decided by this ceiling.
#
# The penalty is stored as a MAGNITUDE, never as a negative number. The sign
# is applied in exactly one place (`scan.grading.score_for`), so a teacher who
# types 0.25 and a teacher who types -0.25 cannot mean two different things.
MAX_ITEM_POINTS: Final = 20.0
DEFAULT_POINTS_CORRECT: Final = 1.0
DEFAULT_POINTS_PENALTY: Final = 0.0


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


def uid_cell_centre_mm(
    slot: int, row: int, *, version: str | None = None
) -> tuple[float, float]:
    """Centre of one cell of the pre-filled UID grid, for one layout version."""
    return uid_grid(version).cell_centre_mm(slot, row)


def _grid_dict(grid: UidGrid) -> dict[str, object]:
    return {
        "originMm": list(grid.origin_mm),
        "cellMm": grid.cell_mm,
        "gapMm": grid.gap_mm,
        "cells": grid.cells,
        "rows": grid.rows,
        "payloadBits": grid.payload_bits,
        "checksumBits": grid.checksum_bits,
    }


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
        # The grid for the CURRENT layout, so the web preview positions what
        # the server actually prints...
        "uidGrid": _grid_dict(uid_grid(LAYOUT_VERSION)),
        # ...and every grid we can still read, because a preview of an
        # already-printed v1 sheet has to be drawn as v1 (B4).
        "uidGrids": {name: _grid_dict(grid) for name, grid in UID_GRIDS.items()},
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
            "maxLines": ANSWER_BOX_MAX_LINES,
        },
        "grading": {
            "defaultPointsCorrect": DEFAULT_POINTS_CORRECT,
            "defaultPointsPenalty": DEFAULT_POINTS_PENALTY,
            "maxItemPoints": MAX_ITEM_POINTS,
        },
    }
