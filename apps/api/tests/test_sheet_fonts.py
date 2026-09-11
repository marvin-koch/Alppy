"""The printed document carries its own type, or it is not the same paper.

`tokens.css` names four families. Until `fonts.css` existed, nothing outside
the Next bundle loaded any of them, so the PDF, the preview iframe and a
browser print of that preview each typeset the statements in a different
fallback. That is not only an identity failure: `measure_answer_boxes` records
where each answer box landed *in the renderer that measured it*, and the scan
job crops at those millimetres. A statement that wraps to four lines in DejaVu
and three in SF Pro moves its box by one line pitch — enough to crop the wrong
pixels, not enough for `_check_box_inside_statement_region` to raise. Nothing
would have failed; the written answers would just have come back wrong.

So this file is the same trick as `theme-script.test.ts`: it reads the family
names out of `tokens.css` rather than repeating them, and asserts the rendered
document declares a face for each. A family added to the tokens and not to the
generator fails here rather than in a classroom.
"""

from __future__ import annotations

import re

import pytest

from alppy.models.enums import ExerciseType, SheetKind
from alppy.sheets.html import (
    Copy,
    SheetData,
    design_css_dir,
    read_design_css,
    render_sheet_html,
)
from alppy.sheets.pagination import Item


def _families() -> set[str]:
    """Every family `--font-*` names, quoted exactly as the tokens declare it.

    Only the first name of each stack: the rest are the system fallbacks the
    stack degrades to, and those are the browser's to find.
    """
    tokens = (design_css_dir() / "tokens.css").read_text(encoding="utf-8")
    families: set[str] = set()
    for line in tokens.splitlines():
        match = re.match(r"\s*--font-(display|sans|mono|hand)\s*:\s*(.+?);", line)
        if not match:
            continue
        first = match.group(2).split(",")[0].strip()
        # `--font-display: var(--font-display)` is the Tailwind @theme re-export
        # at the bottom of the file, not a declaration.
        if first.startswith("var("):
            continue
        families.add(first)
    return families


def _sheet_html(kind: SheetKind = SheetKind.BLANK) -> str:
    item = Item(
        key="a",
        type=ExerciseType.OPEN,
        statement="Explique ta démarche.",
        open_lines=3,
    )
    data = SheetData(
        title="Fractions",
        class_code="10B",
        subject="Maths",
        language="fr",
        copies=(Copy(uid="10B_01", items=(item,)),),
    )
    return render_sheet_html(data, kind=kind)


def test_tokens_still_name_four_families() -> None:
    """A guard on the guard: if this drops to three, the loop below would pass
    while silently checking less."""
    assert len(_families()) == 4, _families()


@pytest.mark.parametrize("kind", [SheetKind.BLANK, SheetKind.ANSWER_KEY])
def test_every_named_family_is_declared_in_the_printed_document(kind: SheetKind) -> None:
    html = _sheet_html(kind)
    faces = re.findall(r"@font-face\s*\{(.+?)\}", html, flags=re.DOTALL)
    declared = {
        match.group(1).strip()
        for face in faces
        if (match := re.search(r"font-family\s*:\s*([^;]+);", face))
    }
    missing = _families() - declared
    assert not missing, f"{kind.value}: no @font-face for {sorted(missing)}"


def test_the_faces_travel_with_the_document_rather_than_being_fetched() -> None:
    """A `url(./files/…)` would resolve against the API host — which serves no
    such path — and fail silently back to the fallback this file exists to
    prevent. The whole point is a document that needs nothing."""
    html = _sheet_html()
    faces = re.findall(r"@font-face\s*\{(.+?)\}", html, flags=re.DOTALL)
    assert faces, "the document declares no faces at all"
    for face in faces:
        # `[^;]+` would stop at the semicolon inside `data:font/woff2;base64`,
        # so match the whole declaration rather than one value.
        assert "src: url(data:font/woff2;base64," in face, face[:160]
        assert "url(./" not in face and "url(http" not in face, face[:160]


def test_a_missing_fonts_stylesheet_is_fatal_rather_than_a_fallback() -> None:
    """`fonts.css` is in `DESIGN_CSS_SHEETS`, so it is subject to the same rule
    as print.css: a renderer that cannot find the design system refuses to draw
    rather than drawing something else. Rendering a sheet in a fallback face is
    exactly the silent failure this module is about."""
    assert "fonts" in read_design_css()
    from alppy.sheets.html import DESIGN_CSS_SHEETS

    assert DESIGN_CSS_SHEETS[0] == "fonts"


def test_the_feedback_document_carries_the_faces_too() -> None:
    """It is student-facing paper as well, and it inlines the same base.css."""
    from alppy.sheets.html import FeedbackCopy, FeedbackData, render_feedback_html

    data = FeedbackData(
        title="Fractions",
        class_code="10B",
        subject="Maths",
        language="fr",
        copies=(FeedbackCopy(uid="10B_01", notes=("Revois les fractions.",)),),
    )
    html = render_feedback_html(data)
    assert "@font-face" in html
    assert "url(data:font/woff2;base64," in html
