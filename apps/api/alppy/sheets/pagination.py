"""Splitting an ordered item list into *physical pages*.

Two independent limits decide where a page ends, and a page ends as soon as
**either** is reached:

1. **Bubbles.** ``layout.ITEMS_PER_PAGE`` (16) answer rows fit the fixed answer
   grid. A seventeenth item on a page would have no bubble to fill.
2. **Statement height.** The statement region is only
   ``ITEMS_BOTTOM_MM - ITEMS_TOP_MM`` = 148 mm tall. Two long open questions
   fill it long before sixteen bubbles are used up.

The height limit is the one that binds in practice: an item costs at least
``3 mm + 3 mm`` of padding plus one ``body-l`` line (7.62 mm), so roughly ten
one-line items fit. That is intentional — the alternative is a statement that
runs off the bottom of the paper, and paper does not scroll.

Everything here is a pure function over small frozen dataclasses, never over
SQLAlchemy rows, so pagination can be tested without a database, without a
browser and without the design system.

The part that must be exactly right is ``PlacedItem.item_index``: the *page-local*
0..15 index. The scan detector addresses bubbles by that index and by nothing
else — it never reads a word on the page — so if this mapping drifts, a whole
class is graded against the wrong questions. It resets to 0 on every physical
page; the *printed* number (``PlacedItem.number``) keeps counting across pages
so a student reads "12." next to statement 12 and next to grid row 12.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from alppy.models.enums import AnswerBoxFill, ExerciseType
from alppy.sheets import layout as L

# --------------------------------------------------------------------------
# Typography, mirrored from packages/ui/src/design/tokens.css
# --------------------------------------------------------------------------
# These are *estimates* used to decide where to break. They do not position
# anything: the renderer lays the text out with the real CSS. They only have to
# be conservative enough that the statement region never overflows, which is why
# every rounding below rounds up.

CSS_PX_PER_MM: float = 96.0 / 25.4
ROOT_FONT_PX: float = 16.0

BODY_L_REM: float = 1.125  # --text-body-l, the student-facing floor
BODY_L_LINE: float = 1.6  # --lh-body-l

BODY_L_MM: float = BODY_L_REM * ROOT_FONT_PX / CSS_PX_PER_MM  # ~4.76 mm
LINE_H_MM: float = BODY_L_MM * BODY_L_LINE  # ~7.62 mm

AVG_CHAR_EM: float = 0.5
"""Mean advance width of a lowercase glyph as a fraction of the font size.

0.5 em is a deliberately pessimistic figure for Nunito. Underestimating the
characters that fit on a line means we predict *more* lines than the browser
draws, so we break early rather than late. Breaking early costs a sheet of
paper; breaking late costs the bottom of a question."""

# --------------------------------------------------------------------------
# The statement region, straight out of layout.py
# --------------------------------------------------------------------------
REGION_TOP_MM: float = L.ITEMS_TOP_MM
REGION_BOTTOM_MM: float = L.ITEMS_BOTTOM_MM
REGION_H_MM: float = REGION_BOTTOM_MM - REGION_TOP_MM

INSTRUCTIONS_H_MM: float = 10.0
"""Every page repeats the "fill one bubble per row" line at ``body-l``. It is
part of the region, so pagination pays for it on every page."""

REGION_BOTTOM_PAD_MM: float = 4.0
"""White space kept between the last statement and the answer grid caption.

Not decoration: the estimate below is approximate, and this is the slack that
absorbs the approximation. Without it, a statement whose real height is a
millimetre over the estimate touches the grid caption."""

USABLE_H_MM: float = REGION_H_MM - INSTRUCTIONS_H_MM - REGION_BOTTOM_PAD_MM

COLUMN_W_MM: float = L.PAGE_W_MM - 2 * L.MARGIN_MM
NUMBER_GUTTER_MM: float = 10.0
TEXT_W_MM: float = COLUMN_W_MM - NUMBER_GUTTER_MM

OPTION_INDENT_MM: float = 8.0
OPTION_LETTER_W_MM: float = 6.0

ITEM_PADDING_MM: float = 6.0  # .print-item { padding: 3mm 0 }
ITEM_RULE_MM: float = 0.2  # its 0.5pt bottom rule
OPTIONS_GAP_MM: float = 1.0

OPEN_LINE_PITCH_MM: float = L.ANSWER_BOX_LINE_PITCH_MM
DEFAULT_OPEN_LINES: int = L.ANSWER_BOX_DEFAULT_LINES
OPEN_LINES_MARGIN_MM: float = 4.0
"""Above the box: room for the corner ticks, which reach ``ANSWER_BOX_TICK_MM``
outside it, plus a hair so they never touch the statement's descenders."""
BOX_MARGIN_BOTTOM_MM: float = L.ANSWER_BOX_TICK_MM + 0.5
BOX_INSET_MM: float = L.ANSWER_BOX_TICK_MM
"""Horizontal inset of the box inside the column, so the ticks stay inside it."""
BOX_W_MM: float = COLUMN_W_MM - 2 * BOX_INSET_MM

FIGURE_GAP_MM: float = 1.0  # .sheet-figure { margin-top: 1mm }
FIGURE_MAX_H_MM: float = 116.0
"""The tallest a figure may print. A crop of the book is reproduced at its own
size — the student reads the book's own type — and shrunk only to fit the
column or this ceiling. The ceiling is the statement region less the item's
own furniture (padding, the number line, the gap, the rules' margin), so a
full-page exercise of the book still fits alone on one sheet.

It is a ceiling, not the box: ``figure_room_mm`` lowers it by whatever text
the item prints above the picture — a teacher's own wording, MCQ options — so
an item with a figure *always* fits a page on its own. A crop taller than the
room is shrunk further, never refused: the sheet used to raise
``ItemTooTallError`` below a 0.65 scale, which meant a half-page exercise of
the book could be imported, ticked and previewed, and then failed the whole
sheet with a message about one item. The crop is a raster at print
resolution, so it stays sharp when small; a teacher who finds it too small on
paper can see that in the preview, which is what the preview is for."""

# An answer box under a picture: none. A textbook exercise is worked in the
# notebook, as the book intends, and a token box under a twelve-part exercise
# costs the millimetres that keep a second exercise off the page. A teacher
# who wants answer space on the sheet adds an item of their own.
# ``html._item_context`` mirrors this by giving a figured item
# ``open_lines = 0``, and the template draws no box for it.

MCQ_LETTERS: str = L.OptionLetters.MCQ.value


# --------------------------------------------------------------------------
# The item
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Figure:
    """A crop of the textbook page, printed in place of the statement.

    ``src`` is what the ``<img>`` gets — a ``data:`` URI, because the PDF
    renderer loads the document from a string with no base URL and must not
    reach the network. ``width_mm``/``height_mm`` is the physical size at 1:1,
    the size the crop was cut at; the sheet never enlarges it."""

    src: str
    width_mm: float
    height_mm: float
    alt: str = ""
    show_statement: bool = False
    """Print the statement text above the picture as well. Set when the teacher
    has written their own wording for the item: their words must reach the
    paper, and the picture still carries the figure."""

    def printed_size_mm(
        self, *, max_width_mm: float = TEXT_W_MM, max_height_mm: float = FIGURE_MAX_H_MM
    ) -> tuple[float, float, float]:
        """``(width, height, scale)`` as it will print. Never scaled up."""
        scale = min(1.0, max_width_mm / self.width_mm, max_height_mm / self.height_mm)
        return self.width_mm * scale, self.height_mm * scale, scale



@dataclass(frozen=True, slots=True)
class Item:
    """One printable exercise, detached from the database.

    ``answer_index`` is the 0-based option the key marks. For ``true_false`` the
    convention is fixed by ``layout.tf_letters``: index 0 is the *true* glyph
    (V / R / T) and index 1 the *false* one. ``Item.true_false_index`` exists so that
    conversion happens in exactly one place.
    """

    key: str
    type: ExerciseType
    statement: str
    options: tuple[str, ...] = ()
    answer_index: int | None = None
    answer_text: str | None = None
    language: str = "fr"
    ai_generated: bool = False
    open_lines: int = DEFAULT_OPEN_LINES
    """Height of the written-answer box, in ``OPEN_LINE_PITCH_MM`` lines. One
    of ``layout.ANSWER_BOX_LINE_PRESETS`` when the teacher chose; 0 prints no
    box at all."""
    box_fill: AnswerBoxFill = AnswerBoxFill.LINED
    figure: Figure | None = None
    """When set, the sheet prints the picture and not the statement text: the
    picture *is* the statement, exactly as the book set it. The text stays as
    the image's alt and for the answer key."""

    @property
    def option_count(self) -> int:
        """How many bubbles this item claims on the answer grid.

        Mirrors ``models.Exercise.option_count`` exactly: free text claims none,
        which is what makes it printable and never auto-graded."""
        if self.type is ExerciseType.TRUE_FALSE:
            return 2
        if self.type is ExerciseType.MCQ:
            return min(len(self.options), L.MAX_OPTIONS)
        return 0

    @property
    def is_gradeable(self) -> bool:
        return self.option_count > 0

    @property
    def option_letters(self) -> str:
        """The glyphs printed next to the bubbles. Positions never move; only
        the glyphs do, which is why the detector needs no language."""
        if self.type is ExerciseType.TRUE_FALSE:
            return L.tf_letters(self.language)
        if self.type is ExerciseType.MCQ:
            return MCQ_LETTERS[: self.option_count]
        return ""

    @staticmethod
    def true_false_index(answer: bool | None) -> int | None:
        """The one place ``answer_bool`` becomes an option index."""
        if answer is None:
            return None
        return 0 if answer else 1


# --------------------------------------------------------------------------
# Height estimation
# --------------------------------------------------------------------------
def wrapped_lines(text: str, width_mm: float, *, font_mm: float = BODY_L_MM) -> int:
    """How many lines ``text`` needs in a ``width_mm`` column. Always >= 1."""
    per_line = max(1, int(width_mm / (font_mm * AVG_CHAR_EM)))
    total = 0
    for paragraph in (text or "").split("\n"):
        total += max(1, ceil(len(paragraph) / per_line))
    return max(1, total)


def _text_above_figure_mm(item: Item) -> float:
    """Millimetres of text an item prints *above* its picture: the number line,
    or the teacher's wording when that is printed instead."""
    if item.figure is not None and item.figure.show_statement:
        return wrapped_lines(item.statement, TEXT_W_MM) * LINE_H_MM
    return LINE_H_MM


def _options_height_mm(item: Item) -> float:
    if not item.options:
        return 0.0
    option_w = TEXT_W_MM - OPTION_INDENT_MM - OPTION_LETTER_W_MM
    return OPTIONS_GAP_MM + sum(wrapped_lines(o, option_w) * LINE_H_MM for o in item.options)


def figure_room_mm(item: Item) -> float:
    """The tallest this item's picture may print, in millimetres.

    ``FIGURE_MAX_H_MM`` less whatever else the item puts on the page, so the
    whole item — text, picture and options — fits the statement region alone.
    Never below a millimetre: a degenerate item still prints *something*."""
    room = USABLE_H_MM - ITEM_PADDING_MM - ITEM_RULE_MM - FIGURE_GAP_MM
    room -= _text_above_figure_mm(item) + _options_height_mm(item)
    return max(1.0, min(FIGURE_MAX_H_MM, room))


def printed_figure_size_mm(item: Item) -> tuple[float, float, float]:
    """``(width, height, scale)`` of the item's picture as it prints.

    The one place that decides the printed size: pagination reserves it and
    the markup writes it as an inline style, so they cannot disagree."""
    if item.figure is None:
        raise ValueError("item has no figure")
    return item.figure.printed_size_mm(max_height_mm=figure_room_mm(item))


def estimate_item_height_mm(item: Item) -> float:
    """Millimetres of statement region this item will occupy.

    Deliberately an over-estimate. See ``AVG_CHAR_EM``."""
    height = ITEM_PADDING_MM + ITEM_RULE_MM
    if item.figure is not None:
        _, figure_h, _ = printed_figure_size_mm(item)
        # The number sits on its own line above the picture, unless the
        # teacher's wording is printed there instead.
        height += _text_above_figure_mm(item)
        height += FIGURE_GAP_MM + figure_h
    else:
        height += wrapped_lines(item.statement, TEXT_W_MM) * LINE_H_MM

    height += _options_height_mm(item)

    box = box_height_mm(item)
    if box is not None:
        height += OPEN_LINES_MARGIN_MM + box + BOX_MARGIN_BOTTOM_MM

    return height


def box_height_mm(item: Item) -> float | None:
    """The printed height of this item's written-answer box, or ``None`` when
    it prints none: a bubble item, a figured item, or zero lines."""
    if item.type is not ExerciseType.OPEN or item.figure is not None:
        return None
    if item.open_lines <= 0:
        return None
    return item.open_lines * OPEN_LINE_PITCH_MM


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PlacedItem:
    """An item pinned to a position on a physical page."""

    item: Item
    page_index: int
    item_index: int
    """PAGE-LOCAL, 0..ITEMS_PER_PAGE-1. The detector addresses bubbles by this."""
    number: int
    """1-based number printed next to the statement AND next to the grid row.
    Continuous across pages, so it is not the same thing as ``item_index``."""
    height_mm: float

    @property
    def group(self) -> int:
        """Left (0) or right (1) column group of the answer grid."""
        return self.item_index // L.GRID_ROWS

    @property
    def row(self) -> int:
        return self.item_index % L.GRID_ROWS

    @property
    def bubble_centres_mm(self) -> list[tuple[float, float]]:
        return [
            L.bubble_centre_mm(self.item_index, oi)
            for oi in range(self.item.option_count)
        ]


@dataclass(frozen=True, slots=True)
class Page:
    """One physical sheet of paper.

    Not "one student's copy": a copy that overflows becomes several of these,
    and every one of them carries its own header and its own UID."""

    index: int
    items: tuple[PlacedItem, ...]

    @property
    def option_counts(self) -> list[int]:
        """Exactly what ``detector.process_page`` wants as its second argument."""
        return [p.item.option_count for p in self.items]

    @property
    def answer_indices(self) -> list[int | None]:
        """The key for this page, page-local. ``synthetic.render_page`` takes
        this as its ``marked`` argument."""
        return [p.item.answer_index if p.item.is_gradeable else None for p in self.items]

    @property
    def used_height_mm(self) -> float:
        return sum(p.height_mm for p in self.items)

    @property
    def overflowing(self) -> bool:
        """True when a single item is taller than the whole statement region.

        We place it anyway — alone on its page — because refusing to paginate
        would leave the teacher with no sheet at all. The renderer clips it and
        this flag is how a caller can warn."""
        return len(self.items) == 1 and self.used_height_mm > USABLE_H_MM


class ItemTooTallError(ValueError):
    """One item cannot fit on any page, whatever we do with the others.

    Raised rather than placed-and-clipped. The statement region has
    ``overflow: hidden`` so the answer grid can never be pushed off its
    coordinates, which meant an over-long statement was silently cut
    mid-sentence and printed that way — the student got a question with no
    ending and no ruled space, and nothing told the teacher. Failing here gives
    them a message naming the item instead.
    """

    def __init__(self, *, number: int, height_mm: float, limit_mm: float, statement: str) -> None:
        self.number = number
        self.height_mm = height_mm
        self.limit_mm = limit_mm
        excerpt = " ".join(statement.split())[:60]
        super().__init__(
            f"item {number} needs about {height_mm:.0f} mm but a page has only "
            f"{limit_mm:.0f} mm for statements: shorten or split it "
            f"(\u201c{excerpt}\u2026\u201d)"
        )


def paginate(
    items: list[Item] | tuple[Item, ...],
    *,
    items_per_page: int = L.ITEMS_PER_PAGE,
    usable_height_mm: float = USABLE_H_MM,
    allow_overflow: bool = False,
) -> list[Page]:
    """Split an ordered item list into physical pages.

    A copy always occupies at least one page: an empty item list still needs a
    sheet carrying a header and a UID, or the student has nothing to hand in.

    An item taller than the whole statement region raises
    :class:`ItemTooTallError`. ``allow_overflow=True`` restores the old
    place-it-anyway behaviour for callers that would rather show a clipped
    preview than nothing; ``Page.overflowing`` then marks the page.
    """
    if items_per_page < 1:
        raise ValueError("items_per_page must be at least 1")
    if items_per_page > L.ITEMS_PER_PAGE:
        raise ValueError(
            f"items_per_page {items_per_page} exceeds the {L.ITEMS_PER_PAGE} bubble "
            f"rows the fixed answer grid of layout {L.LAYOUT_VERSION} provides"
        )

    pages: list[Page] = []
    current: list[PlacedItem] = []
    used = 0.0
    number = 0

    def flush() -> None:
        nonlocal current, used
        pages.append(Page(index=len(pages), items=tuple(current)))
        current = []
        used = 0.0

    for item in items:
        # A figured item is sized by ``figure_room_mm`` to fit a page on its
        # own, so only a text item can be too tall here.
        height = estimate_item_height_mm(item)
        if height > usable_height_mm and not allow_overflow:
            raise ItemTooTallError(
                number=number + 1,
                height_mm=height,
                limit_mm=usable_height_mm,
                statement=item.statement,
            )
        bubbles_full = len(current) >= items_per_page
        too_tall = bool(current) and used + height > usable_height_mm
        if bubbles_full or too_tall:
            flush()

        # Not enumerate(): the counter advances per *placed* item, and a page
        # flush above can restart the loop body without consuming a number.
        number += 1  # noqa: SIM113
        current.append(
            PlacedItem(
                item=item,
                page_index=len(pages),
                item_index=len(current),
                number=number,
                height_mm=height,
            )
        )
        used += height

    flush()
    return pages


def paginate_all(copies: dict[str, list[Item]]) -> dict[str, list[Page]]:
    """Paginate several students' copies at once, in a stable order.

    Used by the adaptive batch, where every student has a different item list
    and the resulting PDF must still be one ``.print-page`` per physical page."""
    return {uid: paginate(items) for uid, items in sorted(copies.items())}
