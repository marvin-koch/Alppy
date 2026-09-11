"""Print markup for a sheet — one standalone HTML document, both kinds of it.

`render_sheet_html` produces the exact document the browser print preview shows
and the exact document headless Chromium turns into a PDF. There is one renderer,
not two, and it inlines ``packages/ui/src/design/{fonts,tokens,base,print}.css``
by *reading those files at render time*. Nothing about the design system is
copied into this package, so the preview and the PDF cannot drift from it.

``fonts.css`` is generated (``scripts/embed-fonts.mjs``) and carries the four
faces as data: URIs, because a standalone document that only *names* its
families leaves every renderer to pick its own — and a statement that wraps
differently is an answer box measured at a row the scan job will not crop.

Three rules from DESIGN.md §9 are structural here, not stylistic:

* **One ``.print-page`` is one physical page**, never "one student's copy". A copy
  that overflows becomes several pages, and each of them carries its own header
  and its own UID — as text and as the pre-filled 32-bit grid. A second page with
  no header and no code belongs to nobody, and comes back from the classroom
  impossible to grade.
* **Always two documents**: the blank sheet and the answer key. The key is the
  same document with ``data-key="true"`` on the correct bubble, and a badge in the
  header so a teacher can tell them apart at arm's length.
* **Free text gets a box, never a bubble.** An ``open`` item prints a delimited
  answer box under its statement and claims no row on the answer grid. The box
  is what the scan job crops for the vision grader; its printed position is
  measured at render time, not computed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from alppy.models.enums import BAND_ORDER, ExerciseType, SheetKind
from alppy.sheets import layout as L
from alppy.sheets.pagination import (
    BOX_INSET_MM,
    BOX_MARGIN_BOTTOM_MM,
    OPEN_LINES_MARGIN_MM,
    Item,
    Page,
    box_height_mm,
    paginate,
    printed_figure_size_mm,
)
from alppy.sheets.uid_code import (
    PageCode,
    bits_to_cells,
    encode_page_code,
    encode_uid,
)

TEMPLATE_DIR: Final = Path(__file__).resolve().parent / "templates"
# `fonts` first: the faces have to be declared before anything asks for them,
# and its absence is fatal rather than a fallback (see DesignSystemNotFoundError
# below). A sheet typeset in whatever the renderer happened to have is a sheet
# whose answer boxes were measured against a different text flow.
DESIGN_CSS_SHEETS: Final = ("fonts", "tokens", "base", "print")
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
    # --- what layout v2 prints into the grid beyond the pupil (B4) ----------
    # All three are ignored under v1, whose grid has no room for them. They are
    # plain values rather than model objects because this module takes no
    # SQLAlchemy and no clock — `build_sheet_data` resolves them.
    nonce: int = 0
    """Identifies (sheet, render generation). `uid_code.sheet_nonce` derives it,
    and the scan pipeline derives it again to check the paper against the pile
    it was uploaded into."""
    school_year_slot: int = 0
    canton: int = 31  # uid_code.CANTON_UNSET


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
        "instructions_bubbles": (
            "Remplis ou croise une seule case par ligne dans la grille de réponses "
            "en bas de page."
        ),
        "instructions_written": "Pour une réponse écrite, écris dans le cadre.",
        "answers": "Grille de réponses",
        "expected": "Réponse attendue :",
        "points_unit": "pts",
        "points_unit_one": "pt",
        "page": "Page",
        "layout": "mise en page",
        "ai": "IA",
        "continued": "suite",
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
        "instructions_bubbles": (
            "Fülle oder kreuze pro Zeile genau ein Feld im Antwortraster unten auf "
            "der Seite an."
        ),
        "instructions_written": "Eine schriftliche Antwort schreibst du in den Kasten.",
        "answers": "Antwortraster",
        "expected": "Erwartete Antwort:",
        "points_unit": "Pkt.",
        "points_unit_one": "Pkt.",
        "page": "Seite",
        "layout": "Layout",
        "ai": "KI",
        "continued": "Fortsetzung",
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
        "instructions_bubbles": (
            "Fill in or cross exactly one box per row in the answer grid at the foot "
            "of the page."
        ),
        "instructions_written": "Write a written answer inside its box.",
        "answers": "Answer grid",
        "expected": "Expected answer:",
        "points_unit": "pts",
        "points_unit_one": "pt",
        "page": "Page",
        "layout": "layout",
        "ai": "AI",
        "continued": "continued",
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
    # From settings, not `os.environ` (audit 03, B25).
    from alppy.core.config import get_settings

    override = get_settings().design_css_dir
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


def geometry_context(version: str | None = None) -> dict[str, Any]:
    """Every millimetre the generated stylesheet needs, derived — never typed
    twice — from ``alppy.sheets.layout``.

    Takes a layout version since B4: the UID grid's size and position differ
    between v1 and v2, and a stylesheet built from the current constants would
    lay a v1 sheet out with v2's grid."""
    grid = L.uid_grid(version)
    uid_pitch = grid.pitch_mm
    uid_grid_w = grid.width_mm
    uid_grid_h = grid.height_mm
    uid_x, uid_y = grid.origin_mm
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
        "version": version or L.LAYOUT_VERSION,
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
        "uid_cell": grid.cell_mm,
        "uid_gap": _fmt(grid.gap_mm),
        "uid_rows": grid.rows,
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
        "open_pitch": _fmt(L.ANSWER_BOX_LINE_PITCH_MM),
        "open_margin": _fmt(OPEN_LINES_MARGIN_MM),
        "box_margin_bottom": _fmt(BOX_MARGIN_BOTTOM_MM),
        "box_inset": _fmt(BOX_INSET_MM),
        "box_border": _fmt(L.ANSWER_BOX_BORDER_MM),
        "box_tick": _fmt(L.ANSWER_BOX_TICK_MM),
        # The guide patterns are SVG, so they print with backgrounds off; SVG
        # user units are CSS px, hence the conversion here and nowhere else.
        "box_line_px": _fmt(L.ANSWER_BOX_LINE_PITCH_MM * 96.0 / 25.4),
        "box_grid_px": _fmt(L.ANSWER_BOX_GRID_MM * 96.0 / 25.4),
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


def render_geometry_css(version: str | None = None) -> str:
    """The generated stylesheet for one layout version.

    Public so a test can assert it matches ``layout.py`` without going anywhere
    near a browser. Version-aware since B4: the UID grid's size and position
    differ between v1 and v2, so a sheet must be laid out with the geometry it
    declares rather than with whatever is current."""
    env = _html_env().overlay(autoescape=False)
    return env.get_template("geometry.css.j2").render(g=geometry_context(version))


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


def _points_label(points: float, strings: dict[str, str]) -> str:
    """"(2 pts)", "(1 pt)", or "" when the item is worth nothing.

    Formatted here rather than in the template so the conventions live in one
    place: a whole number prints whole (2, not 2.0), anything else keeps one
    decimal — as fine as a barème ever gets — and the unit agrees in number,
    which French and English need and German does not ("Pkt." either way).

    An item worth 0 prints no label at all. A "(0 pts)" beside a question is a
    thing to explain to thirty teenagers; silence is not."""
    if points <= 0:
        return ""
    value = int(points) if float(points).is_integer() else round(points, 1)
    unit = strings["points_unit_one"] if value == 1 else strings["points_unit"]
    return f"({value} {unit})"


def _item_context(placed: Any, *, letters: str, strings: dict[str, str]) -> dict[str, Any]:
    item = placed.item
    options: list[dict[str, str]] = []
    if item.type is ExerciseType.MCQ or item.options:
        options = [
            {"letter": letters[i] if i < len(letters) else "", "text": text}
            for i, text in enumerate(item.options)
        ]
    figure: dict[str, Any] | None = None
    if item.figure is not None:
        width_mm, height_mm, _ = printed_figure_size_mm(item)
        figure = {
            "src": item.figure.src,
            "alt": item.figure.alt or item.statement,
            # The printed size is decided here, once, and written as an
            # inline width: pagination reserved exactly this many millimetres.
            "width_mm": _fmt(width_mm),
            "height_mm": _fmt(height_mm),
            "show_statement": item.figure.show_statement,
        }
    return {
        "item_index": placed.item_index,
        "number": placed.number,
        "part": placed.part,
        "type": item.type.value,
        "statement": item.statement,
        "ai_generated": item.ai_generated,
        "options": options,
        "is_open": item.type is ExerciseType.OPEN,
        "open_lines": max(0, item.open_lines) if placed.prints_box else 0,
        "box_fill": item.box_fill.value,
        # The height is decided once, here, and written inline: pagination
        # reserved exactly this many millimetres.
        "box_height_mm": _fmt(box_height_mm(item) or 0.0),
        "answer_text": item.answer_text,
        "points_label": _points_label(item.points_correct, strings),
        "figure": figure,
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
    # v1 prints the pupil; v2 prints the page (B4). `copy_page` is 1-based and
    # is exactly what `PageCode.page_in_copy` means, so B5's "which page is
    # this?" stops being something the scan pipeline has to infer.
    if sheet.layout_version == "v1":
        bits = encode_uid(physical.copy.uid)
    else:
        bits = encode_page_code(
            PageCode(
                uid=physical.copy.uid,
                school_year=sheet.school_year_slot,
                page_in_copy=physical.copy_page,
                canton=sheet.canton,
                nonce=sheet.nonce,
            )
        )
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
        "uid_cells": bits_to_cells(bits, version=sheet.layout_version),
        # NB: not "items" — Jinja would resolve page.items to dict.items.
        "statements": [
            _item_context(
                placed,
                letters=placed.item.option_letters,
                strings=strings(sheet.language),
            )
            for placed in physical.page.items
        ],
        # The grid lists bubble items only. A written answer has its box under
        # the statement; a grid row saying "in the box" told the student
        # nothing and, on a page of written items alone, printed an empty grid
        # with a heading. The detector never reads the grid markup — it reads
        # bubble positions from `layout.py` by page-local item index, which is
        # unchanged — so an open item's row can simply not print.
        "rows": [
            _row_context(placed, is_key=is_key)
            for placed in physical.page.items
            if placed.item.is_gradeable
        ],
        "instructions": _instructions(physical, strings(sheet.language)),
    }


def _instructions(physical: PhysicalPage, t: dict[str, str]) -> str:
    """Only the sentence that applies to what this page prints."""
    kinds = {placed.item.is_gradeable for placed in physical.page.items}
    parts = []
    if True in kinds:
        parts.append(t["instructions_bubbles"])
    if False in kinds:
        parts.append(t["instructions_written"])
    return " ".join(parts)


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
            "fonts": Markup(css["fonts"]),
            "tokens": Markup(css["tokens"]),
            "base": Markup(css["base"]),
            "print": Markup(css["print"]),
            "geometry": Markup(render_geometry_css(sheet_data.layout_version)),
        },
        # The answer-box guide patterns are inline SVG and need the pitch in
        # user units; everything else positional stays in the generated CSS.
        "g": geometry_context(sheet_data.layout_version),
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


def _without_group_number(label: str) -> str:
    """"Série 3 · Fractions" -> "Fractions", for the page a pupil is handed.

    The two halves of the label disclose very different things, and only on
    paper does the difference matter. The competency is informative: a pupil
    reading "Fractions" learns what their sheet is about, which is the point of
    printing it. The NUMBER is relative-ranking information and nothing else —
    where a large group was split by how badly, "Série 3" against a neighbour's
    "Série 1" says who is further behind, to anyone who can see both desks.

    So the number goes from the student-facing feedback page and stays
    everywhere the teacher reads it: the screen, and the sheet header where it
    is how a teacher tells one pile of copies from another while handing them
    out.

    Split on the separator this module wrote itself (`_group_label`), and
    returns the label unchanged when it does not find one — a label from before
    this existed, or a group with no competency to name, is still correct as it
    stands.
    """
    _, separator, rest = label.partition(" · ")
    return rest.strip() if separator and rest.strip() else label


def _feedback_page_context(copy: FeedbackCopy, data: FeedbackData, *, number: int, count: int
                           ) -> dict[str, Any]:
    t = strings(data.language)
    meta_parts = [data.class_code, data.subject]
    if data.source_title:
        meta_parts.append(data.source_title)
    if data.date_label:
        meta_parts.append(data.date_label)
    if copy.group_label:
        meta_parts.append(_without_group_number(copy.group_label))
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
            "fonts": Markup(css["fonts"]),
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
