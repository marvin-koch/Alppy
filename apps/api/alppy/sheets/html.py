"""Print markup for a sheet — one standalone HTML document, both kinds of it.

`render_sheet_html` produces the exact document the browser print preview shows
and the exact document headless Chromium turns into a PDF. There is one renderer,
not two, and it inlines ``packages/ui/src/design/{tokens,base,print}.css`` by
*reading those files at render time*. Nothing about the design system is copied
into this package, so the preview and the PDF cannot drift from it.

Three rules from DESIGN.md §9 are structural here, not stylistic:

* **One ``.print-page`` is one physical page**, never "one student's copy". A copy
  that overflows becomes several pages, and each of them carries its own header
  and its own UID — as text and as the pre-filled 32-bit grid. A second page with
  no header and no code belongs to nobody, and comes back from the classroom
  impossible to grade.
* **Always two documents**: the blank sheet and the answer key. The key is the
  same document with ``data-key="true"`` on the correct bubble, and a badge in the
  header so a teacher can tell them apart at arm's length.
* **Free text is printed, never auto-graded.** An ``open`` item gets a ruled answer
  space and no bubbles at all, so it claims no row on the answer grid.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from alppy.models.enums import BAND_ORDER, ExerciseType, SheetKind
from alppy.sheets import layout as L
from alppy.sheets.pagination import Item, Page, paginate
from alppy.sheets.uid_code import bits_to_cells, encode_uid

TEMPLATE_DIR: Final = Path(__file__).resolve().parent / "templates"
DESIGN_CSS_SHEETS: Final = ("tokens", "base", "print")
DESIGN_CSS_ENV_VAR: Final = "ALPPY_DESIGN_CSS_DIR"
DESIGN_CSS_RELATIVE: Final = Path("packages/ui/src/design")


class DesignSystemNotFoundError(RuntimeError):
    """Raised when the shared print CSS cannot be located.

    Deliberately fatal. Rendering a sheet with a fallback stylesheet would
    silently move the fiducials, and a sheet whose fiducials moved is a sheet
    the scan pipeline reads as a different student's answers."""


# --------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Copy:
    """One student's copy: a UID and that student's own ordered items.

    In a differentiated batch every copy has a different item list, which is why
    a class export is not N photocopies of one page."""

    uid: str
    items: tuple[Item, ...]
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SheetData:
    """Everything the templates need. No SQLAlchemy, no database, no clock."""

    title: str
    class_code: str
    subject: str
    language: str
    copies: tuple[Copy, ...]
    date_label: str | None = None
    show_legend: bool = False
    layout_version: str = L.LAYOUT_VERSION


@dataclass(frozen=True, slots=True)
class PhysicalPage:
    """A page of the finished document, with the copy it belongs to.

    ``page.option_counts`` and ``page.answer_indices`` are page-local and are
    exactly what ``detector.process_page`` and ``synthetic.render_page`` take —
    which is how the round-trip test drives the detector from the same
    pagination the renderer used."""

    copy: Copy
    page: Page
    copy_page: int
    copy_pages: int
    number: int
    count: int


# --------------------------------------------------------------------------
# Strings. Small enough to live here; the sheet has almost no chrome by design.
# --------------------------------------------------------------------------
_STRINGS: Final[dict[str, dict[str, str]]] = {
    "fr": {
        "code": "Code élève",
        "instructions": (
            "Remplis une seule bulle par ligne dans la grille de réponses en bas de page."
        ),
        "answers": "Grille de réponses",
        "written": "réponse écrite",
        "expected": "Réponse attendue :",
        "page": "Page",
        "layout": "mise en page",
        "ai": "IA",
        "legend": "Légende des paliers",
        "key_badge": "CORRIGÉ",
        "key_suffix": "corrigé",
        "feedback_title": "Ce que tu peux revoir",
        "feedback_suffix": "retour personnalisé",
        "feedback_intro": (
            "Voici ce qui revient dans tes réponses. Chaque point renvoie à un exercice "
            "de ta nouvelle fiche."
        ),
        "feedback_ai": "Écrit par l'IA, relu par ton enseignant",
        "feedback_keep": "À garder — cette page n'est pas à rendre",
    },
    "de": {
        "code": "Schülercode",
        "instructions": (
            "Fülle pro Zeile genau ein Feld im Antwortraster unten auf der Seite aus."
        ),
        "answers": "Antwortraster",
        "written": "schriftliche Antwort",
        "expected": "Erwartete Antwort:",
        "page": "Seite",
        "layout": "Layout",
        "ai": "KI",
        "legend": "Legende der Stufen",
        "key_badge": "LÖSUNG",
        "key_suffix": "Lösung",
        "feedback_title": "Was du üben kannst",
        "feedback_suffix": "persönliche Rückmeldung",
        "feedback_intro": (
            "Das kommt in deinen Antworten immer wieder vor. Jeder Punkt gehört zu einer "
            "Aufgabe auf deinem neuen Blatt."
        ),
        "feedback_ai": "Von der KI geschrieben, von deiner Lehrperson geprüft",
        "feedback_keep": "Behalten — dieses Blatt wird nicht abgegeben",
    },
    "en": {
        "code": "Student code",
        "instructions": (
            "Fill in exactly one bubble per row in the answer grid at the foot of the page."
        ),
        "answers": "Answer grid",
        "written": "written answer",
        "expected": "Expected answer:",
        "page": "Page",
        "layout": "layout",
        "ai": "AI",
        "legend": "Mastery legend",
        "key_badge": "ANSWER KEY",
        "key_suffix": "answer key",
        "feedback_title": "What to look at again",
        "feedback_suffix": "personal feedback",
        "feedback_intro": (
            "Here is what keeps coming up in your answers. Each point matches an exercise "
            "on your new sheet."
        ),
        "feedback_ai": "Written by AI, checked by your teacher",
        "feedback_keep": "Keep this — it is not handed in",
    },
}

_BAND_LABELS: Final[dict[str, dict[str, str]]] = {
    "fr": {
        "solid": "solide",
        "ok": "acquis",
        "weak": "fragile",
        "fading": "à revoir",
        "none": "sans donnée",
    },
    "de": {
        "solid": "sicher",
        "ok": "erreicht",
        "weak": "unsicher",
        "fading": "auffrischen",
        "none": "keine Daten",
    },
    "en": {
        "solid": "solid",
        "ok": "ok",
        "weak": "weak",
        "fading": "fading",
        "none": "no data",
    },
}


def strings(language: str) -> dict[str, str]:
    """Sheet chrome for a locale. Falls back to English, never to nothing."""
    return _STRINGS.get(language, _STRINGS["en"])


def band_legend(language: str) -> list[dict[str, str]]:
    """The five mastery bands, in order. Colour comes from the token, the
    distinct underline from ``print.css``; the legend shows both because the
    photocopier only reproduces one of them."""
    labels = _BAND_LABELS.get(language, _BAND_LABELS["en"])
    return [{"key": band.value, "label": labels[band.value]} for band in BAND_ORDER]


# --------------------------------------------------------------------------
# The shared design system, read from disk on every render
# --------------------------------------------------------------------------
def design_css_dir() -> Path:
    """Locate ``packages/ui/src/design``.

    ``ALPPY_DESIGN_CSS_DIR`` wins, so a container image that ships the CSS
    somewhere else needs no code change. Otherwise we walk up from this file
    looking for the monorepo root."""
    override = os.environ.get(DESIGN_CSS_ENV_VAR)
    if override:
        candidate = Path(override).expanduser().resolve()
        if (candidate / "print.css").is_file():
            return candidate
        raise DesignSystemNotFoundError(
            f"{DESIGN_CSS_ENV_VAR}={override!r} does not contain print.css"
        )

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / DESIGN_CSS_RELATIVE
        if (candidate / "print.css").is_file():
            return candidate
    raise DesignSystemNotFoundError(
        f"could not find {DESIGN_CSS_RELATIVE}/print.css above {here}; "
        f"set {DESIGN_CSS_ENV_VAR}"
    )


def read_design_css() -> dict[str, str]:
    """Read tokens/base/print at render time — never cached, never vendored."""
    directory = design_css_dir()
    out: dict[str, str] = {}
    for name in DESIGN_CSS_SHEETS:
        path = directory / f"{name}.css"
        if not path.is_file():
            raise DesignSystemNotFoundError(f"missing design stylesheet: {path}")
        out[name] = path.read_text(encoding="utf-8")
    return out


# --------------------------------------------------------------------------
# Geometry, straight out of layout.py
# --------------------------------------------------------------------------
def _fmt(value: float) -> str:
    """CSS-friendly number: 24 rather than 24.0, 214.5 rather than 214.49999."""
    rounded = round(value, 3)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:g}"


def geometry_context() -> dict[str, Any]:
    """Every millimetre the generated stylesheet needs, derived — never typed
    twice — from ``alppy.sheets.layout``."""
    uid_pitch = L.UID_GRID_CELL_MM + L.UID_GRID_GAP_MM
    uid_grid_w = L.UID_GRID_CELLS * L.UID_GRID_CELL_MM + (L.UID_GRID_CELLS - 1) * L.UID_GRID_GAP_MM
    uid_grid_h = L.UID_GRID_ROWS * L.UID_GRID_CELL_MM + (L.UID_GRID_ROWS - 1) * L.UID_GRID_GAP_MM
    uid_x, uid_y = L.UID_GRID_ORIGIN_MM
    grid_x, grid_y = L.GRID_ORIGIN_MM

    # The header rule must stop before the UID grid, or it would run straight
    # through the cells the detector samples.
    header_w = uid_x - L.MARGIN_MM - 2.0
    uid_text_x = uid_x + uid_grid_w + 3.0
    uid_text_w = L.PAGE_W_MM - L.MARGIN_MM - uid_text_x

    grid_bottom = grid_y + (L.GRID_ROWS - 1) * L.GRID_ROW_PITCH_MM + L.BUBBLE_D_MM
    # Keep the footer clear of the two bottom fiducials, horizontally as well as
    # vertically: they sit in the outer 8mm of the margin at each side.
    footer_x = L.MARGIN_MM + L.FIDUCIAL_MM + 4.0

    return {
        "version": L.LAYOUT_VERSION,
        "page_w": _fmt(L.PAGE_W_MM),
        "page_h": _fmt(L.PAGE_H_MM),
        "margin": _fmt(L.MARGIN_MM),
        "content_h": _fmt(L.PAGE_H_MM - 2 * L.MARGIN_MM),
        "col_w": _fmt(L.PAGE_W_MM - 2 * L.MARGIN_MM),
        "header_top": _fmt(L.HEADER_TOP_MM),
        "header_h": _fmt(L.HEADER_H_MM),
        "header_w": _fmt(header_w),
        "uid_x": _fmt(uid_x),
        "uid_y": _fmt(uid_y),
        "uid_cell": L.UID_GRID_CELL_MM,
        "uid_gap": _fmt(L.UID_GRID_GAP_MM),
        "uid_rows": L.UID_GRID_ROWS,
        "uid_pitch": _fmt(uid_pitch),
        "uid_grid_h": _fmt(uid_grid_h),
        "uid_text_x": _fmt(uid_text_x),
        "uid_text_w": _fmt(uid_text_w),
        "items_top": _fmt(L.ITEMS_TOP_MM),
        "items_h": _fmt(L.ITEMS_BOTTOM_MM - L.ITEMS_TOP_MM),
        # The feedback document has no answer grid to stay clear of, so its
        # region runs from the same top down to the footer. Derived here rather
        # than in layout.py on purpose: it positions prose no machine reads, so
        # it is not part of the geometry contract the detector is versioned
        # against and changing it is not a layout version bump.
        "feedback_h": _fmt(L.PAGE_H_MM - L.MARGIN_MM - 10.0 - L.ITEMS_TOP_MM),
        "caption_top": _fmt(L.ITEMS_BOTTOM_MM + 0.5),
        "grid_x": _fmt(grid_x),
        "grid_y": _fmt(grid_y),
        "group_lefts": [
            _fmt(grid_x + g * L.GRID_GROUP_PITCH_MM) for g in range(L.GRID_GROUPS)
        ],
        "row_tops": [
            _fmt(grid_y + r * L.GRID_ROW_PITCH_MM) for r in range(L.GRID_ROWS)
        ],
        "option_lefts": [
            _fmt(L.GRID_NUMBER_W_MM + o * L.BUBBLE_PITCH_MM) for o in range(L.MAX_OPTIONS)
        ],
        "row_w": _fmt(L.GRID_NUMBER_W_MM + L.MAX_OPTIONS * L.BUBBLE_PITCH_MM),
        "number_w": _fmt(L.GRID_NUMBER_W_MM),
        # Stop the row number short of the annulus the detector samples around
        # the first bubble (1.6 x radius = 4mm from its centre).
        "number_text_w": _fmt(L.GRID_NUMBER_W_MM - 3.0),
        "bubble_d": L.BUBBLE_D_MM,
        "bubble_pitch": _fmt(L.BUBBLE_PITCH_MM),
        "max_options": L.MAX_OPTIONS,
        # The letter lives in the slack between two rows; it must not reach down
        # into the previous row's bubble.
        "letter_line": _fmt(min(3.2, L.GRID_ROW_PITCH_MM - L.BUBBLE_D_MM - 0.3)),
        "option_indent": 8,
        "option_letter_w": 6,
        "open_pitch": 8,
        "open_margin": 2,
        "footer_x": _fmt(footer_x),
        "footer_w": _fmt(L.PAGE_W_MM - 2 * footer_x),
        "footer_top": _fmt(grid_bottom + 2.5),
        "groups": L.GRID_GROUPS,
        "rows": L.GRID_ROWS,
    }


# --------------------------------------------------------------------------
# Jinja
# --------------------------------------------------------------------------
def _html_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )


def render_geometry_css() -> str:
    """The generated stylesheet. Public so a test can assert it matches
    ``layout.py`` without going anywhere near a browser."""
    env = _html_env().overlay(autoescape=False)
    return env.get_template("geometry.css.j2").render(g=geometry_context())


# --------------------------------------------------------------------------
# Pagination -> pages of the finished document
# --------------------------------------------------------------------------
def physical_pages(sheet_data: SheetData) -> list[PhysicalPage]:
    """Every physical page of the document, in printing order.

    Each copy is paginated on its own — a copy never shares a page with another
    student — and the pages are then numbered continuously across the document."""
    if not sheet_data.copies:
        raise ValueError("a sheet needs at least one copy: a page belongs to a student")

    collected: list[tuple[Copy, Page, int, int]] = []
    for copy in sheet_data.copies:
        encode_uid(copy.uid)  # fail here, not in the middle of a print run
        pages = paginate(list(copy.items))
        for i, page in enumerate(pages):
            collected.append((copy, page, i + 1, len(pages)))

    total = len(collected)
    return [
        PhysicalPage(
            copy=copy,
            page=page,
            copy_page=copy_page,
            copy_pages=copy_pages,
            number=n + 1,
            count=total,
        )
        for n, (copy, page, copy_page, copy_pages) in enumerate(collected)
    ]


def _item_context(placed: Any, *, letters: str) -> dict[str, Any]:
    item = placed.item
    options: list[dict[str, str]] = []
    if item.type is ExerciseType.MCQ or item.options:
        options = [
            {"letter": letters[i] if i < len(letters) else "", "text": text}
            for i, text in enumerate(item.options)
        ]
    return {
        "item_index": placed.item_index,
        "number": placed.number,
        "type": item.type.value,
        "statement": item.statement,
        "ai_generated": item.ai_generated,
        "options": options,
        "is_open": item.type is ExerciseType.OPEN,
        "open_lines": max(0, item.open_lines),
        "answer_text": item.answer_text,
    }


def _row_context(placed: Any, *, is_key: bool) -> dict[str, Any]:
    item = placed.item
    letters = item.option_letters
    bubbles = [
        {
            "index": oi,
            "letter": letters[oi] if oi < len(letters) else "",
            "key": is_key and item.answer_index == oi,
        }
        for oi in range(item.option_count)
    ]
    return {
        "group": placed.group,
        "row": placed.row,
        "item_index": placed.item_index,
        "number": placed.number,
        "option_count": item.option_count,
        "gradeable": item.is_gradeable,
        "bubbles": bubbles,
    }


def _page_context(physical: PhysicalPage, sheet: SheetData, *, is_key: bool) -> dict[str, Any]:
    bits = encode_uid(physical.copy.uid)
    meta_parts = [sheet.class_code, sheet.subject]
    if sheet.date_label:
        meta_parts.append(sheet.date_label)
    if physical.copy.note:
        meta_parts.append(physical.copy.note)

    return {
        "number": physical.number,
        "count": physical.count,
        "copy_uid": physical.copy.uid,
        "copy_page": physical.copy_page,
        "copy_pages": physical.copy_pages,
        "title": sheet.title,
        "meta": " · ".join(p for p in meta_parts if p),
        "uid_cells": bits_to_cells(bits),
        # NB: not "items" — Jinja would resolve page.items to dict.items.
        "statements": [
            _item_context(placed, letters=placed.item.option_letters)
            for placed in physical.page.items
        ],
        "rows": [_row_context(placed, is_key=is_key) for placed in physical.page.items],
    }


# --------------------------------------------------------------------------
# The public entry point
# --------------------------------------------------------------------------
def render_sheet_html(sheet_data: SheetData, *, kind: str | SheetKind = SheetKind.BLANK) -> str:
    """Render one complete, standalone print document.

    ``kind`` selects which of the two documents this is. They are the same
    markup: the key adds ``data-key="true"`` to the correct bubble, a header
    badge and, for free-text items, the expected answer — everything else,
    including every coordinate, is byte-identical."""
    sheet_kind = SheetKind(kind)
    is_key = sheet_kind is SheetKind.ANSWER_KEY
    t = strings(sheet_data.language)

    pages = physical_pages(sheet_data)
    doc_title = sheet_data.title if not is_key else f"{sheet_data.title} — {t['key_suffix']}"

    css = read_design_css()
    context = {
        "lang": sheet_data.language,
        "kind": sheet_kind.value,
        "is_key": is_key,
        "doc_title": doc_title,
        "layout_version": sheet_data.layout_version,
        "t": t,
        "show_legend": sheet_data.show_legend,
        "bands": band_legend(sheet_data.language) if sheet_data.show_legend else [],
        "css": {
            "tokens": Markup(css["tokens"]),
            "base": Markup(css["base"]),
            "print": Markup(css["print"]),
            "geometry": Markup(render_geometry_css()),
        },
        "pages": [_page_context(p, sheet_data, is_key=is_key) for p in pages],
    }
    return _html_env().get_template("sheet.html.j2").render(**context)


def render_both(sheet_data: SheetData) -> tuple[str, str]:
    """The blank sheet and the answer key. Always both — a design that produces
    only the first has not produced a printable sheet."""
    return (
        render_sheet_html(sheet_data, kind=SheetKind.BLANK),
        render_sheet_html(sheet_data, kind=SheetKind.ANSWER_KEY),
    )


__all__ = [
    "Copy",
    "DesignSystemNotFoundError",
    "PhysicalPage",
    "SheetData",
    "band_legend",
    "design_css_dir",
    "geometry_context",
    "physical_pages",
    "read_design_css",
    "render_both",
    "render_geometry_css",
    "render_sheet_html",
    "strings",
]


# --------------------------------------------------------------------------
# The feedback document — separate on purpose
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class FeedbackCopy:
    """One student's feedback page."""

    uid: str
    notes: tuple[str, ...]
    group_label: str | None = None


@dataclass(frozen=True, slots=True)
class FeedbackData:
    """Everything the feedback templates need. No SQLAlchemy, no clock.

    Deliberately NOT a variant of `SheetData`, and deliberately not routed
    through `physical_pages`/`paginate`. The scan detector recomputes a copy's
    page count from its *items* (`scan_processing._copies_by_uid`) and maps a
    photographed page with ``seen[uid] % len(printed_pages)``. Any page the
    renderer emits inside a copy that this count does not know about shifts
    that modulo and grades a page against the wrong questions — silently, with
    confident detections. Keeping feedback in its own document means the two
    can never disagree, whatever is approved or discarded afterwards.
    """

    title: str
    class_code: str
    subject: str
    language: str
    copies: tuple[FeedbackCopy, ...]
    date_label: str | None = None
    source_title: str | None = None


def _feedback_page_context(copy: FeedbackCopy, data: FeedbackData, *, number: int, count: int
                           ) -> dict[str, Any]:
    t = strings(data.language)
    meta_parts = [data.class_code, data.subject]
    if data.source_title:
        meta_parts.append(data.source_title)
    if data.date_label:
        meta_parts.append(data.date_label)
    if copy.group_label:
        meta_parts.append(copy.group_label)
    return {
        "copy_uid": copy.uid,
        "title": t["feedback_title"],
        "meta": " · ".join(p for p in meta_parts if p),
        "notes": list(copy.notes),
        "number": number,
        "count": count,
    }


def render_feedback_html(data: FeedbackData) -> str:
    """One standalone document holding every student's feedback page.

    Carries no fiducials, no UID grid and no answer grid. A page that is never
    scanned must not *look* like a page that is: the four corner squares are
    what the detector registers on, and a stack of feedback pages fed into the
    scanner by accident should be rejected outright rather than read as blank
    answers for the child whose UID is printed on them.
    """
    if not data.copies:
        raise ValueError("a feedback document needs at least one copy")
    t = strings(data.language)
    css = read_design_css()
    total = len(data.copies)
    context = {
        "lang": data.language,
        "kind": SheetKind.FEEDBACK.value,
        "doc_title": f"{data.title} — {t['feedback_suffix']}",
        "t": t,
        "css": {
            "tokens": Markup(css["tokens"]),
            "base": Markup(css["base"]),
            "print": Markup(css["print"]),
            "geometry": Markup(render_geometry_css()),
        },
        "pages": [
            _feedback_page_context(copy, data, number=i + 1, count=total)
            for i, copy in enumerate(data.copies)
        ],
    }
    return _html_env().get_template("feedback.html.j2").render(**context)
