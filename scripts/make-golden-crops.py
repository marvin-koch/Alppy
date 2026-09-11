#!/usr/bin/env python
"""Render the seed crops for the golden set.

Run once to produce `apps/api/tests/golden/crops/*.png` from the manifest. The
images are committed, so this does not run in CI and nothing depends on the
fonts below being present — it exists so the seed corpus is reproducible and so
the next person can see exactly how synthetic it is.

**These are not handwriting.** They are a handwriting-shaped font, which is
regular in every way a child's hand is not: even baseline, even pressure, no
overshoot, no correction, no letter joined differently the second time. They
exercise the harness end to end. They do not measure recognition, and the
manifest's `provenance` field says so on every sample. See the README for what
replacing them looks like.

The one sample where the font is arguably fine is the prompt injection: what
makes it an injection is the content, not the penmanship.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parents[1] / "apps" / "api" / "tests" / "golden"
CROPS = HERE / "crops"

#: macOS ships these; any handwriting-ish TTF will do. A missing font is a
#: failure rather than a silent fallback to the default bitmap face, which would
#: produce crops that look nothing like the committed ones.
FONTS = [
    "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
    "/System/Library/Fonts/Supplemental/Chalkduster.ttf",
]

#: The answer box as printed: `layout.py`'s box is 160 mm x 22 mm at 200 dpi.
WIDTH, HEIGHT = 1260, 173


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def render(text: str, out: Path, *, seed: int, blank: bool = False) -> None:
    """One crop, with Alppy's own ink already removed — as the scan job hands it over.

    White ground rather than the printed rule: `answer_box.py` removes the
    product's own lines before the crop is sent, so a sample with the rule still
    in it would be testing an image the model never receives.
    """
    rng = random.Random(seed)
    image = Image.new("L", (WIDTH, HEIGHT), color=250)
    if blank:
        image.save(out)
        return

    draw = ImageDraw.Draw(image)
    # Fit the text to the box rather than trusting a size. The injection sample
    # is a whole sentence and the first pass cropped it mid-word, which would
    # have made the corpus measure the renderer instead of the model.
    size = rng.randint(52, 64)
    font = _font(FONTS[seed % len(FONTS)], size)
    while size > 16 and draw.textlength(text, font=font) > WIDTH - 120 - 3 * len(text):
        size -= 2
        font = _font(FONTS[seed % len(FONTS)], size)

    # A little wobble, so every sample is not pixel-identical apart from its
    # glyphs. Not a substitute for a real hand; enough that a run cannot pass by
    # matching one exact bitmap.
    x = rng.randint(40, 90)
    y = rng.randint(30, 55)
    for char in text:
        draw.text((x, y + rng.randint(-4, 4)), char, fill=rng.randint(20, 70), font=font)
        x += draw.textlength(char, font=font) + rng.randint(-1, 3)
    image.save(out)


def main() -> int:
    manifest = json.loads((HERE / "manifest.json").read_text())
    CROPS.mkdir(parents=True, exist_ok=True)
    for sample in manifest["samples"]:
        target = CROPS / sample["crop"]
        render(
            sample["expected_transcription"] or "",
            target,
            seed=sample["seed"],
            blank=sample["expected_verdict"] == "blank",
        )
        print(f"  {target.relative_to(HERE.parents[3])}")
    print(f"\n{len(manifest['samples'])} crops rendered. They are SYNTHETIC — see the README.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
