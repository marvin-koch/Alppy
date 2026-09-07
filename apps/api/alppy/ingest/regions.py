"""Exercise regions, read off the page geometry rather than the prose.

Why this exists next to the model-based extraction
--------------------------------------------------
A real textbook is not a wall of text. In the Romandy maths books (MER,
``Mathématiques 9e-11e``) an exercise is a header line — a code such as
``NO64`` and a title, set bold in the domain's colour — followed by a body that
is, more often than not, a figure, a table, a column of fractions or a photo of a
newspaper clipping. Handing that body to a language model as extracted text
loses exactly the part the student is meant to look at, and a transcription of
``3n²/n`` has no way of being "precise".

So this module does the one thing a model cannot: it finds where each exercise
*is* on the page and cuts it out as an image. The rule is typographic, not
lexical — a header is a **bold, coloured, body-sized line opening with a short
code** at the left edge of the column — and the region runs from that header to
the next header, to the book's own cross-reference line (``Fichier : …``), to a
section title, or to the end of the page's content, whichever comes first. An
exercise that carries on over the page is stitched back together from both
pages: the book marks that with a ``SUITE ▶`` line, and the continuation is the
body text sitting above the next page's first header.

What comes out is deterministic. The same file produces the same regions, the
same crops and the same text every time, with no model in the loop. A book that
does not use coded headers yields no regions at all, and the pipeline falls
back to the chunk-and-transcribe path.

Everything here is a pure function over bytes; it reaches no database and no
network. Rendering needs PyMuPDF, which the scan pipeline already depends on.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from alppy.core.logging import get_logger

log = get_logger(__name__)

PT_PER_MM = 72.0 / 25.4

FIGURE_DPI = 200
"""Raster resolution of a crop. 200 dpi keeps 10 pt body text crisp through a
photocopier and puts a typical 165 × 60 mm exercise at about 1300 × 470 px —
roughly 60-120 kB as PNG, so a whole book fits comfortably in object storage."""

# A header opens with a short code: 1-3 capitals then 1-3 digits ("NO64",
# "GM110", "RS7"), a run of spaces, then a title starting with a real glyph.
_HEADER_RE = re.compile(r"^(?P<label>[A-Z]{1,3}\d{1,3})\s+(?P<title>\S.*)$")

HEADER_MIN_PT = 9.0
HEADER_MAX_PT = 13.0
"""Body-sized. The same code set at 5 pt is a thumbnail on the book's "how to
use this book" page; at 19 pt it would be a chapter title, which the MER books
set without a code anyway."""

FONT_FLAG_BOLD = 16
"""PyMuPDF's span flag for a bold face."""

FURNITURE_TOP_PT = 45.0
"""Running head and page number live above this line. Nothing up there belongs
to an exercise."""

FOOT_MARGIN_PT = 20.0

_GREY_MAX_SPREAD = 8
"""A colour whose RGB channels are within this of each other is black or grey —
body text, running heads — not a domain colour."""

_HEADER_PAD_PT = 3.0
_BODY_PAD_PT = 4.0
_SIDE_PAD_PT = 3.0
_LABEL_TAB_PT = 16.0
"""The tinted tab the book prints to the left of every code. Part of the
exercise's visual identity, so the crop keeps it."""

_TITLE_MIN_PT = 14.0
"""A line set this large is a section title, and a section title ends the
exercise above it."""

_CROSSREF_RE = re.compile(r"^\s*(?:Fichier|Livre|Aide-mémoire)\s*:", re.IGNORECASE)
"""The book's pointer to the companion workbook. Sits between exercises and
belongs to neither."""

_CONTINUES_RE = re.compile(r"^\s*SUITE\b", re.IGNORECASE)

_RUN_HEADING_RE = re.compile(
    r"^\s*(?:Pour réactiver|Pour consolider|Encore quelques|Problèmes\s*$)", re.IGNORECASE
)
"""Sub-headings the book sets between runs of exercises. Coloured but not a
title size, so they need naming."""


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RegionPart:
    """One rectangle on one page. ``page`` is 1-based; the rect is in PDF points."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width_pt(self) -> float:
        return self.x1 - self.x0

    @property
    def height_pt(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True, slots=True)
class ExerciseRegion:
    """One exercise as the page lays it out.

    ``parts`` is almost always one rectangle. It is two when the book printed
    ``SUITE ▶`` and carried the body over to the next page; the crop then
    stacks both rectangles, and ``page`` is where the header is."""

    label: str
    title: str
    parts: tuple[RegionPart, ...]
    text: str
    """The region's own text in reading order, header line excluded. This is
    the statement the builder searches and the sheet prints as alt text."""

    @property
    def page(self) -> int:
        return self.parts[0].page

    @property
    def continues(self) -> bool:
        return len(self.parts) > 1

    @property
    def width_mm(self) -> float:
        return max(p.width_pt for p in self.parts) / PT_PER_MM

    @property
    def height_mm(self) -> float:
        return sum(p.height_pt for p in self.parts) / PT_PER_MM


@dataclass(frozen=True, slots=True)
class RegionImage:
    png: bytes
    width_px: int
    height_px: int
    width_mm: float
    height_mm: float


@dataclass(frozen=True, slots=True)
class OutlineEntry:
    """One bookmark of the PDF: nesting level (1 = top), title, 1-based page."""

    level: int
    title: str
    page: int


# --------------------------------------------------------------------------
# Page reading
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Line:
    rect: Any  # pymupdf.Rect
    text: str
    font: str
    size: float
    color: int
    flags: int

    @property
    def is_bold(self) -> bool:
        return bool(self.flags & FONT_FLAG_BOLD) or self.font.lower().endswith(("bold", "-bd", "bd"))

    @property
    def is_coloured(self) -> bool:
        r, g, b = (self.color >> 16) & 0xFF, (self.color >> 8) & 0xFF, self.color & 0xFF
        return max(r, g, b) - min(r, g, b) > _GREY_MAX_SPREAD

    @property
    def header(self) -> re.Match[str] | None:
        if not (self.is_bold and self.is_coloured and HEADER_MIN_PT <= self.size <= HEADER_MAX_PT):
            return None
        return _HEADER_RE.match(self.text)

    @property
    def is_stopper(self) -> bool:
        """Ends the exercise above it without belonging to the one below.

        The ``SUITE ▶`` mark counts: it says the exercise goes on, and the crop
        shows that by going on, not by printing the mark."""
        if self.size >= _TITLE_MIN_PT:
            return True
        if _CROSSREF_RE.match(self.text) or self.is_continuation_mark:
            return True
        return self.is_coloured and bool(_RUN_HEADING_RE.match(self.text))

    @property
    def is_continuation_mark(self) -> bool:
        return self.is_bold and bool(_CONTINUES_RE.match(self.text))


@dataclass(slots=True)
class _PageView:
    page: Any  # pymupdf.Page
    number: int
    lines: list[_Line]
    drawings: list[Any]  # pymupdf.Rect

    @property
    def width(self) -> float:
        return float(self.page.rect.width)

    @property
    def height(self) -> float:
        return float(self.page.rect.height)

    @property
    def headers(self) -> list[_Line]:
        return sorted((ln for ln in self.lines if ln.header), key=lambda ln: ln.rect.y0)

    @property
    def continues(self) -> bool:
        return any(ln.is_continuation_mark for ln in self.lines)


def _read_page(page: Any, number: int) -> _PageView:
    import pymupdf

    lines: list[_Line] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            spans = line.get("spans") or []
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            first = spans[0]
            rect = pymupdf.Rect(line["bbox"])  # type: ignore[no-untyped-call]  # pymupdf ships no stubs
            if rect.y1 <= FURNITURE_TOP_PT:
                continue
            lines.append(
                _Line(
                    rect=rect,
                    text=text,
                    font=str(first.get("font", "")),
                    size=float(first.get("size", 0.0)),
                    color=int(first.get("color", 0)),
                    flags=int(first.get("flags", 0)),
                )
            )

    width = float(page.rect.width)
    drawings: list[Any] = []
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        # Full-width rules are page furniture (the bar under the running
        # head, the section-title bars); anything narrower is content.
        if rect.y1 <= FURNITURE_TOP_PT or rect.width >= width - 30:
            continue
        drawings.append(rect)
    for image in page.get_images(full=True):
        try:
            for rect in page.get_image_rects(image[0]):
                if rect.y1 > FURNITURE_TOP_PT:
                    drawings.append(rect)
        except Exception:  # pragma: no cover - a malformed image entry
            continue
    return _PageView(page=page, number=number, lines=lines, drawings=drawings)


# --------------------------------------------------------------------------
# Region geometry
# --------------------------------------------------------------------------
def _content_bounds(view: _PageView, y0: float, y1: float, *, header: _Line | None) -> Any | None:
    """Union of everything drawn between ``y0`` and ``y1``, stoppers excluded."""
    union = None
    for ln in view.lines:
        if ln.is_stopper and ln is not header:
            continue
        if ln.rect.y0 >= y0 - 1 and ln.rect.y1 <= y1 + 1:
            union = ln.rect if union is None else union | ln.rect
    for rect in view.drawings:
        if rect.y0 >= y0 - 1 and rect.y1 <= y1 + 1:
            union = rect if union is None else union | rect
    return union


def _region_end(view: _PageView, header: _Line | None, next_header: _Line | None) -> float:
    """Where the exercise below ``header`` stops, before trimming to content.

    ``header`` is ``None`` for a continuation tail, which starts at the top of
    the page; a stopper anywhere above the next header still ends it."""
    end = next_header.rect.y0 - _HEADER_PAD_PT if next_header else view.height - FOOT_MARGIN_PT
    start = header.rect.y1 + 2 if header is not None else FURNITURE_TOP_PT
    for ln in view.lines:
        if ln.is_stopper and start < ln.rect.y0 < end:
            end = ln.rect.y0 - 2
    return end


def _part(view: _PageView, y0: float, y1: float, *, header: _Line | None, left: float) -> RegionPart | None:
    import pymupdf

    bounds = _content_bounds(view, y0, y1, header=header)
    if bounds is None:
        return None
    x0 = max(0.0, min(left, bounds.x0 - _SIDE_PAD_PT))
    x1 = min(view.width, max(bounds.x1 + _SIDE_PAD_PT, view.width - FOOT_MARGIN_PT))
    rect = pymupdf.Rect(x0, y0, x1, min(y1, bounds.y1 + _BODY_PAD_PT))  # type: ignore[no-untyped-call]  # no stubs
    if rect.is_empty or rect.height < 4:
        return None
    return RegionPart(page=view.number, x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1)


def _text_in(view: _PageView, part: RegionPart, *, skip_header: bool) -> str:
    import pymupdf

    clip = pymupdf.Rect(part.x0, part.y0, part.x1, part.y1)  # type: ignore[no-untyped-call]  # no stubs
    raw = str(view.page.get_text("text", clip=clip, sort=True))
    lines = [ln.rstrip() for ln in raw.split("\n")]
    if skip_header:
        # The first non-empty line is the header we already parsed.
        for i, ln in enumerate(lines):
            if ln.strip():
                if _HEADER_RE.match(ln.strip()):
                    lines = lines[i + 1 :]
                break
    kept = [ln for ln in lines if ln.strip() and not _CONTINUES_RE.match(ln)]
    return _tidy("\n".join(kept))


_WS_RUN = re.compile(r"[ \t    ]+")


def _tidy(text: str) -> str:
    return "\n".join(_WS_RUN.sub(" ", ln).strip() for ln in text.split("\n")).strip()


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def _open(data: bytes) -> Any:
    import pymupdf

    return pymupdf.open(stream=io.BytesIO(data), filetype="pdf")  # type: ignore[no-untyped-call]  # no stubs


def detect_exercise_regions(data: bytes) -> list[ExerciseRegion]:
    """Every coded exercise in the document, in page order.

    Returns ``[]`` for a document that does not set its exercises with coded
    headers; the caller then has nothing to crop and uses the text path.
    """
    doc = _open(data)
    regions: list[ExerciseRegion] = []
    pending: ExerciseRegion | None = None
    """The last region of the previous page, if that page said ``SUITE``."""

    for index in range(len(doc)):
        view = _read_page(doc[index], index + 1)
        headers = view.headers
        left_edge = min((h.rect.x0 for h in headers), default=0.0) - _LABEL_TAB_PT

        # A continuation: body text above this page's first header belongs to
        # the exercise the previous page could not finish.
        if pending is not None:
            top = FURNITURE_TOP_PT
            bottom = _region_end(view, None, headers[0] if headers else None)
            tail = _part(view, top, bottom, header=None, left=pending.parts[-1].x0)
            if tail is not None:
                tail_text = _text_in(view, tail, skip_header=False)
                pending = ExerciseRegion(
                    label=pending.label,
                    title=pending.title,
                    parts=(*pending.parts, tail),
                    text=f"{pending.text}\n{tail_text}".strip(),
                )
            # A page with no header of its own that says SUITE again is the
            # middle of a three-page exercise: keep carrying it.
            if not headers and view.continues:
                continue
            regions.append(pending)
            pending = None

        for i, header in enumerate(headers):
            match = header.header
            if match is None:  # pragma: no cover - `headers` is filtered on it
                continue
            nxt = headers[i + 1] if i + 1 < len(headers) else None
            y0 = header.rect.y0 - _HEADER_PAD_PT
            y1 = _region_end(view, header, nxt)
            part = _part(view, y0, y1, header=header, left=left_edge)
            if part is None:
                continue
            region = ExerciseRegion(
                label=match.group("label"),
                title=_tidy(match.group("title")),
                parts=(part,),
                text=_text_in(view, part, skip_header=True),
            )
            if nxt is None and view.continues:
                pending = region
            else:
                regions.append(region)

    if pending is not None:
        regions.append(pending)
    log.info("ingest.regions", pages=len(doc), regions=len(regions))
    return regions


def _render(doc: Any, region: ExerciseRegion, *, dpi: int) -> RegionImage:
    import pymupdf
    from PIL import Image

    strips: list[Image.Image] = []
    for part in region.parts:
        clip = pymupdf.Rect(part.x0, part.y0, part.x1, part.y1)  # type: ignore[no-untyped-call]  # no stubs
        pix = doc[part.page - 1].get_pixmap(clip=clip, dpi=dpi, alpha=False)
        strips.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))

    if len(strips) == 1:
        image = strips[0]
    else:
        # A continued exercise: the two rectangles stacked, on white.
        image = Image.new(
            "RGB", (max(s.width for s in strips), sum(s.height for s in strips)), "white"
        )
        y = 0
        for strip in strips:
            image.paste(strip, (0, y))
            y += strip.height

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return RegionImage(
        png=buffer.getvalue(),
        width_px=image.width,
        height_px=image.height,
        width_mm=image.width / dpi * 25.4,
        height_mm=image.height / dpi * 25.4,
    )


def render_region(data: bytes, region: ExerciseRegion, *, dpi: int = FIGURE_DPI) -> RegionImage:
    """Rasterise one region to a PNG. Parts on different pages are stacked."""
    return _render(_open(data), region, dpi=dpi)


def iter_region_images(
    data: bytes, regions: Sequence[ExerciseRegion], *, dpi: int = FIGURE_DPI
) -> Iterator[tuple[ExerciseRegion, RegionImage]]:
    """Render many regions from one open document — opening a 50 MB file
    once per exercise is the difference between seconds and minutes."""
    doc = _open(data)
    for region in regions:
        yield region, _render(doc, region, dpi=dpi)


def read_outline(data: bytes) -> list[OutlineEntry]:
    """The PDF's own bookmarks, or ``[]`` when the file has none."""
    try:
        doc = _open(data)
        toc = doc.get_toc(simple=True)
    except Exception as exc:
        log.info("ingest.outline.unreadable", error=type(exc).__name__)
        return []
    entries: list[OutlineEntry] = []
    for level, title, page in toc:
        if not isinstance(page, int) or page < 1:
            continue
        entries.append(OutlineEntry(level=int(level), title=str(title).strip(), page=page))
    return entries


__all__ = [
    "FIGURE_DPI",
    "ExerciseRegion",
    "OutlineEntry",
    "RegionImage",
    "RegionPart",
    "detect_exercise_regions",
    "iter_region_images",
    "read_outline",
    "render_region",
]
