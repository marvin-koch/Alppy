// AUTO-GENERATED — DO NOT EDIT.
// Source of truth: apps/api/alppy/sheets/layout.py + alppy/scan/detector.py (as_dict()).
// Regenerate with: PYTHONPATH=apps/api python scripts/export-layout.py
// CI fails if this file is stale (see .github/workflows/ci.yml) --
// the print markup, the server-side PDF renderer and the scan
// detector must agree on these numbers exactly, or a scan taken
// against one printed layout silently misreads against another.
// layoutVersion: v1

export const SHEET_LAYOUT = {
  "layoutVersion": "v1",
  "pageWMm": 210.0,
  "pageHMm": 297.0,
  "marginMm": 14.0,
  "fiducialMm": 8.0,
  "fiducialCentresMm": {
    "tl": [
      18.0,
      18.0
    ],
    "tr": [
      192.0,
      18.0
    ],
    "bl": [
      18.0,
      279.0
    ],
    "br": [
      192.0,
      279.0
    ]
  },
  "frame": {
    "x0Mm": 18.0,
    "y0Mm": 18.0,
    "wMm": 174.0,
    "hMm": 261.0
  },
  "headerTopMm": 26.0,
  "itemsTopMm": 48.0,
  "itemsBottomMm": 196.0,
  "uidGrid": {
    "originMm": [
      120.0,
      30.0
    ],
    "cellMm": 4.0,
    "gapMm": 1.0,
    "cells": 8,
    "rows": 4
  },
  "grid": {
    "topMm": 202.0,
    "originMm": [
      24.0,
      206.0
    ],
    "rows": 8,
    "groups": 2,
    "groupPitchMm": 88.0,
    "rowPitchMm": 8.5,
    "numberWMm": 14.0,
    "bubblePitchMm": 8.0,
    "bubbleDMm": 5.0,
    "maxOptions": 4
  },
  "itemsPerPage": 16,
  "answerBox": {
    "linePitchMm": 8.0,
    "gridMm": 5.0,
    "borderMm": 0.35,
    "tickMm": 3.0,
    "linePresets": [
      3,
      5,
      8,
      12
    ],
    "defaultLines": 5,
    "maxLines": 14
  },
  "grading": {
    "defaultPointsCorrect": 1.0,
    "defaultPointsPenalty": 0.0,
    "maxItemPoints": 20.0
  }
} as const;

export type SheetLayout = typeof SHEET_LAYOUT;

/** The detector's own decision thresholds, so the review UI can draw
 *  the same line the pipeline draws rather than a copy of it. */
export const SCAN_THRESHOLDS = {
  "lowConfidence": 0.65,
  "fillMarked": 0.35,
  "fillBlank": 0.18,
  "crossMarked": 0.55,
  "crossBlank": 0.2,
  "minQuality": 0.55
} as const;
