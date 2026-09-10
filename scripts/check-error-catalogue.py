#!/usr/bin/env python3
"""Fail when the API can emit an error code the client cannot name.

`A failure crosses to the client as a code; the client owns the sentence` —
CLAUDE.md. That contract only holds if the client HAS a sentence for every code
the API can raise. Twelve of twenty-three had none, so those failures reached
a teacher as whatever `apiErrorMessage` falls back to: a generic sentence, on a
screen that is regularly projected onto a classroom wall.

Nothing could have caught that, because the two halves live in different
languages and neither imports the other. This is the join, run in CI.

The codes come from two places, both read mechanically rather than listed by
hand — a list by hand is the thing that drifted in the first place:

  * `alppy/api/errors.py`'s constructors and its status -> code map, which are
    the codes every handler gets for free.
  * every `code="..."` keyword at a raise site anywhere under `alppy/`, which
    is how a handler asks for a named one.

Usage:
    python scripts/check-error-catalogue.py
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api" / "alppy"
MESSAGES = REPO_ROOT / "apps" / "web" / "messages"
LOCALES = ("fr", "de", "en")

#: Codes the CLIENT raises for itself, which the API cannot emit and must not
#: be expected to. `network_error` is the fetch never reaching us; `fallback`
#: is what `apiErrorMessage` says when a code is genuinely unknown — the safety
#: net this check exists to keep empty.
CLIENT_ONLY = {"network_error", "fallback"}


def api_codes() -> set[str]:
    """Every code the API can put in an error envelope."""
    errors_py = (API_ROOT / "api" / "errors.py").read_text()

    # The constructors: `ApiError(<status>, "<code>", ...)`.
    found = set(re.findall(r'ApiError\(\s*[^,]+,\s*["\']([a-z][a-z0-9_]*)["\']', errors_py))
    # The status -> code map used by the bare-HTTPException handler.
    tree = ast.parse(errors_py)
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, int)
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    found.add(value.value)
    # The handlers' own codes, including the one the status map falls back to
    # — `_STATUS_CODES.get(status, "http_error")` is a real emittable code and
    # is not a call argument, so it needs its own shape.
    found |= set(re.findall(r'error_body\(\s*["\']([a-z][a-z0-9_]*)["\']', errors_py))
    found |= set(re.findall(r'\.get\([^,()]+,\s*["\']([a-z][a-z0-9_]*)["\']\s*\)', errors_py))

    # And every named code asked for at a raise site.
    for path in sorted(API_ROOT.rglob("*.py")):
        # Group 2 is the code; group 1 is only the quote character, matched so
        # the closing quote has to be the same one.
        found |= {
            match[1]
            for match in re.findall(r'code=(["\'])([a-z][a-z0-9_]*)\1', path.read_text())
        }
    return {c for c in found if c}


def catalogue(locale: str) -> set[str]:
    data = json.loads((MESSAGES / f"{locale}.json").read_text())
    return set(data.get("errors", {}).get("code", {}))


def main() -> int:
    emitted = api_codes()
    failures: list[str] = []

    for locale in LOCALES:
        keys = catalogue(locale)
        missing = sorted(emitted - keys)
        if missing:
            failures.append(
                f"{locale}.json has no sentence for {len(missing)} code(s) the API can emit: "
                + ", ".join(missing)
            )
        # A key for a code nothing can raise is dead weight that reads as
        # coverage. Client-only codes are declared above and exempt.
        stale = sorted(keys - emitted - CLIENT_ONLY)
        if stale:
            failures.append(
                f"{locale}.json names {len(stale)} code(s) the API cannot emit: " + ", ".join(stale)
            )

    reference = catalogue(LOCALES[0])
    for locale in LOCALES[1:]:
        keys = catalogue(locale)
        if keys != reference:
            failures.append(
                f"{locale}.json and {LOCALES[0]}.json disagree — "
                f"only in {LOCALES[0]}: {sorted(reference - keys)}; "
                f"only in {locale}: {sorted(keys - reference)}"
            )

    if failures:
        for line in failures:
            print(f"error: {line}", file=sys.stderr)
        return 1

    print(f"error catalogue: {len(emitted)} codes, in sync across {', '.join(LOCALES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
