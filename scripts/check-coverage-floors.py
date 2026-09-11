#!/usr/bin/env python
"""Per-module coverage floors — a ratchet, not an average.

``--cov-fail-under=85`` is one number over the whole package, and one number
hides its own distribution. The audit measured it: `worker/tasks.py` at 69 %,
`db/tenancy.py` at 77 %, `api/v1/adaptive.py` at 77 % — each meaningfully
weaker than the codebase average, each invisible behind a green 85, and each a
module where the untested part is the part that matters. `tenancy.py` is the
**only** writer of the row-level-security GUC; a gap there is a gap in the
thing standing between two schools' rosters.

Why floors rather than one higher global number: raising the global figure
would demand work everywhere, including in modules where the uncovered lines
are genuinely uninteresting, and the usual response to that is assertion-free
tests that move the number without moving the risk. A floor per module says
what is expected *of that module*, and says it where a reviewer can argue with
it.

Why a script rather than configuration: `coverage.py` has no per-module
``fail_under``. This reads the XML the test run already writes, so it adds no
second measurement that could disagree with the first.

**How to change a floor.** Upward, freely — that is the ratchet working, and
the message below tells you when a module has earned a higher one. Downward
only with a reason in the commit message: a floor that drops silently is the
global average's problem again, one module at a time.

Usage
-----
    python scripts/check-coverage-floors.py coverage.xml
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

#: module path -> the percentage it must not fall below.
#:
#: Deliberately a little under each module's measured figure, so ordinary churn
#: does not fail the build; the point is to catch a *regression*, not to pin a
#: number. Only modules with a reason to be listed are listed — a floor on
#: everything is the global average wearing a different hat.
FLOORS: dict[str, float] = {
    # The only writer of `app.current_school_id`. An untested branch here is an
    # untested branch in the tenant boundary itself (D84).
    "alppy/db/tenancy.py": 75.0,
    # Every long-running job goes through it: scan processing, rendering,
    # grading, adaptive generation. It sat at 18 % for months.
    "alppy/worker/tasks.py": 65.0,
    # The batched-generation and in-flight-dedup paths, which are where a
    # provider hiccup turns into a whole class's work being lost.
    "alppy/api/v1/adaptive.py": 75.0,
    # Print geometry is the single source of truth the detector reads back.
    "alppy/sheets/layout.py": 85.0,
    # The PII gate. It raises rather than redacting, and the raising path is
    # the one that must never regress. Measured at 85.4%, so the floor is 80 —
    # the first draft said 90 because that felt like the right number for a
    # privacy gate, which is how a floor becomes a target nobody can hold.
    "alppy/ai/scrub.py": 80.0,
    # Mastery is the number a teacher acts on.
    "alppy/mastery/model.py": 90.0,
}


def main(path: Path) -> int:
    if not path.exists():
        print(f"✗ {path} does not exist — run the suite with --cov-report=xml first")
        return 2

    root = ET.parse(path).getroot()
    measured: dict[str, float] = {}
    for cls in root.iter("class"):
        filename = cls.get("filename")
        rate = cls.get("line-rate")
        if filename and rate is not None:
            measured[filename] = float(rate) * 100.0

    def coverage_of(module: str) -> float | None:
        """Match on a path SUFFIX.

        `coverage.xml` records paths relative to wherever the run was started —
        `apps/api/alppy/db/tenancy.py` from the repo root, `alppy/db/tenancy.py`
        from `apps/api`. Keying on the full string makes the floors silently
        unfindable when someone changes directory, and "unfindable" is the one
        answer this script must never treat as "fine".
        """
        for filename, rate in measured.items():
            if filename == module or filename.endswith("/" + module):
                return rate
        return None

    failures: list[str] = []
    earned: list[str] = []
    missing: list[str] = []

    for module, floor in sorted(FLOORS.items()):
        actual = coverage_of(module)
        if actual is None:
            # A module that vanished from the report is not a pass. It has been
            # renamed, moved, or excluded from measurement, and a floor nobody
            # is checking is worse than no floor.
            missing.append(module)
            continue
        if actual < floor:
            failures.append(f"  {module}: {actual:.1f}% is below its floor of {floor:.0f}%")
        elif actual >= floor + 10:
            earned.append(f"  {module}: {actual:.1f}% — floor is {floor:.0f}%, raise it")

    for module in missing:
        failures.append(
            f"  {module}: not in the coverage report at all. Renamed, moved, or no "
            f"longer measured — update FLOORS rather than leaving it unchecked."
        )

    if failures:
        print("coverage floors: failed\n")
        print("\n".join(failures))
        print(
            "\nThese are per-module floors, not the global 85%. A module can drag "
            "well below the average without moving it, which is how worker/tasks.py "
            "sat at 18% for months. Raise the coverage, or lower the floor in "
            "scripts/check-coverage-floors.py with a reason in the commit message."
        )
        return 1

    print(f"coverage floors: ok — {len(FLOORS)} modules above their floor")
    if earned:
        # Not a failure: a ratchet that fails when you do well teaches people to
        # stop doing well. But it should say so.
        print("\nComfortably clear, and the floor could be raised:\n")
        print("\n".join(earned))
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "coverage.xml")
    raise SystemExit(main(target))
