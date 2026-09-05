#!/usr/bin/env python3
"""Generate packages/ui/src/icons/set.tsx from the shipped brand pictograms.

The 48 pictograms in docs/design/alppy-brand-assets/brand/icons are the
authority (CLAUDE.md). This script transcribes their geometry into React
components rather than anyone redrawing them by eye, so a change to the brand
library is a re-run of this script and not a design exercise.

Re-run with:  python packages/ui/scripts/generate-icons.py
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "docs/design/alppy-brand-assets/brand/icons"
OUT = ROOT / "packages/ui/src/icons/set.tsx"

SVG_NS = "{http://www.w3.org/2000/svg}"

# Attributes the shared <Icon> wrapper already sets on the <svg>. Repeating them
# on every child would be noise; anything else (a solid fill on a dot, a
# dasharray) is carried through verbatim.
INHERITED = {
    "fill": "none",
    "stroke": "currentColor",
    "stroke-width": "2.2",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
}


def camel(attr: str) -> str:
    head, *rest = attr.split("-")
    return head + "".join(p.capitalize() for p in rest)


def component_name(stem: str) -> str:
    return "Icon" + "".join(p.capitalize() for p in re.split(r"[-_]", stem))


def render(el: ET.Element, indent: int = 6) -> list[str]:
    tag = el.tag.replace(SVG_NS, "")
    attrs = {
        k: v for k, v in el.attrib.items() if INHERITED.get(k) != v
    }
    pad = " " * indent
    props = "".join(f' {camel(k)}="{v}"' for k, v in attrs.items())
    children = list(el)

    if tag == "g" and not attrs and children:
        # A grouping <g> that only restated the inherited defaults: drop it and
        # lift its children, so the emitted component stays flat.
        out: list[str] = []
        for child in children:
            out.extend(render(child, indent))
        return out

    if not children:
        return [f"{pad}<{tag}{props} />"]

    out = [f"{pad}<{tag}{props}>"]
    for child in children:
        out.extend(render(child, indent + 2))
    out.append(f"{pad}</{tag}>")
    return out


def main() -> None:
    files = sorted(SRC.glob("*.svg"))
    if not files:
        raise SystemExit(f"no pictograms found in {SRC}")

    lines = [
        "/* AUTO-GENERATED — DO NOT EDIT BY HAND.",
        " *",
        " * Source of truth: docs/design/alppy-brand-assets/brand/icons/ (the shipped",
        " * brand library). Regenerate with:",
        " *",
        " *     python packages/ui/scripts/generate-icons.py",
        " *",
        " * 24px grid, 20x20 safe area, stroke 2.2 (never 2, never 3), round caps and",
        " * joins, currentColor only. Solid fills are reserved for dots and pips: a",
        " * pictogram stays a line drawing. Below 16px, use a label instead.",
        " */",
        "",
        "import { createIcon } from './Icon';",
        "",
    ]

    names: list[str] = []
    for path in files:
        tree = ET.parse(path)
        root = tree.getroot()
        body: list[str] = []
        for child in list(root):
            body.extend(render(child))
        name = component_name(path.stem)
        names.append(name)
        lines.append(f"export const {name} = createIcon(")
        lines.append(f"  '{name}',")
        lines.append("  <>")
        lines.extend(body)
        lines.append("  </>,")
        lines.append(");")
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(names)} pictograms")
    print(", ".join(names))


if __name__ == "__main__":
    main()
