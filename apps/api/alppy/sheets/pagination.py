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

from alppy.models.enums import ExerciseType
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

OPEN_LINE_PITCH_MM: float = 8.0
DEFAULT_OPEN_LINES: int = 4
OPEN_LINES_MARGIN_MM: float = 2.0

MCQ_LETTERS: str = L.OptionLetters.MCQ.value


# --------------------------------------------------------------------------
# The item
# --------------------------------------------------------------------------
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


def estimate_item_height_mm(item: Item) -> float:
    """Millimetres of statement region this item will occupy.

    Deliberately an over-estimate. See ``AVG_CHAR_EM``."""
    height = ITEM_PADDING_MM + ITEM_RULE_MM
    height += wrapped_lines(item.statement, TEXT_W_MM) * LINE_H_MM

    if item.options:
        option_w = TEXT_W_MM - OPTION_INDENT_MM - OPTION_LETTER_W_MM
        height += OPTIONS_GAP_MM
        for option in item.options:
            height += wrapped_lines(option, option_w) * LINE_H_MM

    if item.type is ExerciseType.OPEN:
        height += OPEN_LINES_MARGIN_MM + max(0, item.open_lines) * OPEN_LINE_PITCH_MM

    return height


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


def paginate(
    items: list[Item] | tuple[Item, ...],
    *,
    items_per_page: int = L.ITEMS_PER_PAGE,
    usable_height_mm: float = USABLE_H_MM,
) -> list[Page]:
    """Split an ordered item list into physical pages.

    A copy always occupies at least one page: an empty item list still needs a
    sheet carrying a header and a UID, or the student has nothing to hand in.
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
        height = estimate_item_height_mm(item)
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
