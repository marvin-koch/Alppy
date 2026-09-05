#!/usr/bin/env python3
"""Generate packages/ui/src/illustrations/set.tsx from the shipped brand library.

The seven illustrations in docs/design/alppy-brand-assets/brand/illustrations
are the authority (CLAUDE.md). Their literal colours are mapped back onto design
tokens on the way through, so the drawings still respond to the theme — the
brand files are flat exports and cannot.

Re-run with:  python packages/ui/scripts/generate-illustrations.py
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "docs/design/alppy-brand-assets/brand/illustrations"
OUT = ROOT / "packages/ui/src/illustrations/set.tsx"
SVG_NS = "{http://www.w3.org/2000/svg}"

# Exactly three colours, per the brand manual. Anything outside this map is a
# drift in the source asset and should fail loudly rather than be silently
# hard-coded into the component.
TOKENS = {
    "#ECE7FF": "var(--c-primary-100)",
    "#5B3FF0": "var(--c-primary-500)",
    "#FF8A3D": "var(--c-accent-500)",
    "#FFFFFF": "var(--c-surface)",
    "none": "none",
}


def camel(attr: str) -> str:
    head, *rest = attr.split("-")
    return head + "".join(p.capitalize() for p in rest)


def component_name(stem: str) -> str:
    return "Illo" + "".join(p.capitalize() for p in re.split(r"[-_]", stem))


def map_colour(value: str, where: str) -> str:
    key = value.strip()
    if key.lower() in {"none", "currentcolor"}:
        return key
    token = TOKENS.get(key.upper())
    if token is None:
        raise SystemExit(
            f"{where}: colour {key} is not one of the three brand colours — "
            "the asset has drifted from the manual"
        )
    return token


def render(el: ET.Element, indent: int, where: str) -> list[str]:
    tag = el.tag.replace(SVG_NS, "")
    pad = " " * indent
    parts = []
    for k, v in el.attrib.items():
        if k in {"fill", "stroke"}:
            v = map_colour(v, where)
        if k == "data-decorative":
            continue  # applied once on the root by the wrapper
        parts.append(f' {camel(k)}="{v}"')
    props = "".join(parts)
    children = [c for c in el if c.tag.replace(SVG_NS, "") != "title"]

    if tag == "g" and not props and children:
        out: list[str] = []
        for child in children:
            out.extend(render(child, indent, where))
        return out
    if not children:
        return [f"{pad}<{tag}{props} />"]
    out = [f"{pad}<{tag}{props}>"]
    for child in children:
        out.extend(render(child, indent + 2, where))
    out.append(f"{pad}</{tag}>")
    return out


def main() -> None:
    files = sorted(SRC.glob("*.svg"))
    if not files:
        raise SystemExit(f"no illustrations found in {SRC}")

    lines = [
        "/* AUTO-GENERATED — DO NOT EDIT BY HAND.",
        " *",
        " * Source: docs/design/alppy-brand-assets/brand/illustrations/",
        " * Regenerate: python packages/ui/scripts/generate-illustrations.py",
        " *",
        " * 120px, flat, exactly three colours: primary-100 fill, primary-500 stroke,",
        " * accent-500 for the single point of attention. The flat hexes in the brand",
        " * export are mapped back onto tokens here so the drawings follow the theme.",
        " *",
        " * Every one is decorative: `data-decorative` means calm mode removes it, and",
        " * `aria-hidden` means a screen reader never announces it. No mascot — that is",
        " * a deliberate decision, not an omission.",
        " */",
        "",
        "import { Illustration } from './Illustration';",
        "import type { IllustrationProps } from './Illustration';",
        "",
    ]

    names = []
    for path in files:
        root = ET.parse(path).getroot()
        body: list[str] = []
        for child in root:
            body.extend(render(child, 6, path.name))
        name = component_name(path.stem)
        names.append(name)
        lines += [
            f"export function {name}(props: IllustrationProps) {{",
            "  return (",
            "    <Illustration {...props}>",
            *body,
            "    </Illustration>",
            "  );",
            "}",
            "",
        ]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(names)} illustrations: {', '.join(names)}")


if __name__ == "__main__":
    main()
