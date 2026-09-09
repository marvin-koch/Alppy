#!/usr/bin/env python3
"""Export the print-sheet geometry from Python to TypeScript.

``apps/api/alppy/sheets/layout.py`` is the single source of truth for every
millimetre used by the print markup, the server-side PDF renderer and the
scan detector (see that module's docstring). This script writes the same
numbers, as ``as_dict()`` returns them, into
``packages/shared/src/layout.generated.ts`` so the web app can position the
print preview identically without hand-transcribing constants — and so a
CI step (see ``.github/workflows/ci.yml``) can catch the day someone changes
a number on one side and forgets the other, by re-running this script and
failing if the generated file changes.

The detector's decision thresholds come along for the ride, from
``alppy.scan.detector``. The review screen has to draw the same line the
pipeline draws — "below this the machine does not trust itself" — and it used
to do that with a `0.65` typed into a React component, three files and one
language away from the constant it was mirroring.

Usage:
    PYTHONPATH=apps/api python scripts/export-layout.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "packages" / "shared" / "src" / "layout.generated.ts"


def _import_layout():
    """Import alppy.sheets.layout, adding apps/api to sys.path if needed so
    this also works when invoked without PYTHONPATH pre-set."""
    try:
        from alppy.sheets import layout
    except ImportError:
        api_src = str(REPO_ROOT / "apps" / "api")
        if api_src not in sys.path:
            sys.path.insert(0, api_src)
        from alppy.sheets import layout
    return layout


def _import_detector():
    try:
        from alppy.scan import detector
    except ImportError:  # pragma: no cover - same path fix as _import_layout
        api_src = str(REPO_ROOT / "apps" / "api")
        if api_src not in sys.path:
            sys.path.insert(0, api_src)
        from alppy.scan import detector
    return detector


def render_ts(
    data: dict[str, object],
    thresholds: dict[str, float],
    *,
    source: str,
    layout_version: str,
) -> str:
    body = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)
    detection = json.dumps(thresholds, indent=2, ensure_ascii=False, sort_keys=False)
    return (
        "// AUTO-GENERATED — DO NOT EDIT.\n"
        f"// Source of truth: {source} (as_dict()).\n"
        "// Regenerate with: PYTHONPATH=apps/api python scripts/export-layout.py\n"
        "// CI fails if this file is stale (see .github/workflows/ci.yml) --\n"
        "// the print markup, the server-side PDF renderer and the scan\n"
        "// detector must agree on these numbers exactly, or a scan taken\n"
        "// against one printed layout silently misreads against another.\n"
        f"// layoutVersion: {layout_version}\n"
        "\n"
        f"export const SHEET_LAYOUT = {body} as const;\n"
        "\n"
        "export type SheetLayout = typeof SHEET_LAYOUT;\n"
        "\n"
        "/** The detector's own decision thresholds, so the review UI can draw\n"
        " *  the same line the pipeline draws rather than a copy of it. */\n"
        f"export const SCAN_THRESHOLDS = {detection} as const;\n"
    )


def main() -> int:
    layout = _import_layout()
    detector = _import_detector()
    data = layout.as_dict()
    thresholds = {
        "lowConfidence": detector.LOW_CONFIDENCE,
        "fillMarked": detector.FILL_MARKED,
        "fillBlank": detector.FILL_BLANK,
        # The cross scale's own pair. Exported for the same reason as the fill
        # pair: the review overlay explains a reading to the teacher, and
        # "0.55" typed into a React component is a constant one language away
        # from the one it mirrors. The shape test's internals (bin count, lobe
        # width) stay in Python — nothing on screen draws a line at them.
        "crossMarked": detector.CROSS_MARKED,
        "crossBlank": detector.CROSS_BLANK,
        "minQuality": detector.MIN_QUALITY,
    }

    ts = render_ts(
        data,
        thresholds,
        source="apps/api/alppy/sheets/layout.py + alppy/scan/detector.py",
        layout_version=layout.LAYOUT_VERSION,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    previous = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else None
    OUTPUT_PATH.write_text(ts)

    changed = previous != ts
    rel = OUTPUT_PATH.relative_to(REPO_ROOT)
    if changed:
        print(f"wrote {rel} ({len(ts)} bytes, {'updated' if previous else 'created'})")
    else:
        print(f"{rel} already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
