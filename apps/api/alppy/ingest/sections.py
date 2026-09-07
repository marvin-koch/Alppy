"""The document's own table of contents, read off its pages.

Why this exists as a separate axis from ``Chapter``
---------------------------------------------------
``Chapter`` is the teacher's grouping, tied to curriculum competencies, and an
exercise reaches one only by inference: ``pipeline._chapter_for`` picks the
chapter whose competencies overlap the model's tags, and returns ``None`` when
there are no tags. Three things must hold for that to land — the teacher created
chapters, the chapters carry competency codes, the extraction tagged the item —
so on a real textbook a large minority of rows stay untagged. ``_chapter_for``
says so itself: *"an untagged exercise is invisible to the builder's chapter
filter — which is the only way a teacher finds it."*

A section is a fact about the file: "4 · Les fractions, p. 112-131". It needs no
setup and it is how a teacher navigates a 400-page book. So it is the builder's
primary filter, and the competency axis is the secondary one.

What counts as a heading
------------------------
Deliberately conservative. A false heading fragments the outline into noise,
which is worse than a coarse one: a teacher can scroll twenty pages inside a
correct chapter, but cannot find anything in ninety spurious ones. So a line is
a heading only if it is *short*, *alone on its line*, and either carries an
explicit chapter word ("Chapitre 4", "Kapitel 7", "Unit 3") or is a bare number
followed by a title-cased phrase. Running heads — the book's own title repeated
at the top of every page — are detected by repetition and dropped.

Every page belongs to exactly one section. Pages before the first heading become
a leading section (a preface, a contents table) rather than being dropped, so no
exercise can end up with a null section and disappear from the filter.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from alppy.ingest.extract import PageText

MAX_HEADING_CHARS = 90
"""A heading is a label, not a sentence. Longer lines are body text that merely
happens to start with a number — ``12. Calcule l'aire du triangle rectangle
dont les cathètes mesurent 6 cm et 8 cm`` is an exercise, not a chapter."""

MIN_SECTION_PAGES = 1

RUNNING_HEAD_MIN_PAGES = 4
"""A line repeated at the top of at least this many pages is the book's running
head, not a heading. Below it, a genuine short chapter could be mistaken for
one — a 3-page chapter whose title is echoed on each of its pages is real."""

RUNNING_HEAD_MIN_RATIO = 0.25
"""...and it must also appear on at least this share of the pages. Together the
two rules mean a repeated line is only dismissed when it repeats *across the
document*, not merely within one long chapter."""

# "Chapitre 4", "Chapitre 4 — Les fractions", "Kapitel 7:", "Unit 3", "Thème 2"
_LABELLED_RE = re.compile(
    r"""^\s{0,4}
      (?:Chapitre|Chapter|Kapitel|Unité|Unite|Unit|Einheit|Thème|Theme|Thema|Module|Modul|Partie|Teil)
      \s*\.?\s*
      (?P<label>\d{1,2}|[IVXLC]{1,6})
      \s*(?:[.:—–\-]\s*)?
      (?P<title>.{0,80})$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# "4 Les fractions" / "4. Les fractions" / "4 — Les fractions" on its own line.
# The title must start with a letter and carry at least one more word-ish run,
# so "12. Calcule" (an exercise) needs the length guard below to be rejected —
# which is why callers must apply MAX_HEADING_CHARS as well.
_NUMBERED_RE = re.compile(
    r"""^\s{0,4}
      (?P<label>\d{1,2})
      \s*(?:[.:—–\-)]\s*|\s+)
      (?P<title>[^\W\d_][^\n]{2,79})$
    """,
    re.VERBOSE,
)

# A heading never ends in sentence punctuation and never contains these: they
# mark running prose or an exercise instruction.
_NOT_HEADING_RE = re.compile(r"[.!?;]\s*$|[=<>]|\.\.\.|…")

# Verbs that open an instruction. "4. Calcule le périmètre" is an exercise even
# though it matches the numbered shape.
_IMPERATIVE_RE = re.compile(
    r"""^(?:
        Calcule|Calculez|Trouve|Trouvez|Détermine|Determine|Déterminez|Explique|Expliquez
      | Range|Rangez|Écris|Ecris|Écrivez|Simplifie|Simplifiez|Résous|Resous|Résolvez
      | Complète|Complete|Complétez|Compare|Comparez|Justifie|Justifiez|Coche|Cochez
      | Berechne|Bestimme|Erkläre|Erklaere|Vereinfache|Löse|Loese|Vergleiche|Ordne|Schreibe
      | Calculate|Find|Determine|Explain|Simplify|Solve|Compare|Order|Write|Complete
    )\b""",
    re.VERBOSE | re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Section:
    """One chapter of the document. Page numbers are 1-based and inclusive."""

    title: str
    label: str | None
    page_from: int
    page_to: int
    position: int

    @property
    def page_count(self) -> int:
        return self.page_to - self.page_from + 1


@dataclass(frozen=True, slots=True)
class _Heading:
    page: int
    title: str
    label: str | None


def _normalise(line: str) -> str:
    """Fold case and accents so a running head is recognised across pages."""
    folded = unicodedata.normalize("NFKD", line.strip().casefold())
    return "".join(c for c in folded if not unicodedata.combining(c))


def _candidate_heading(line: str) -> _Heading | None:
    """The heading this line declares, or ``None``. Page is filled by caller."""
    stripped = line.strip()
    if not stripped or len(stripped) > MAX_HEADING_CHARS:
        return None
    if _NOT_HEADING_RE.search(stripped):
        return None

    labelled = _LABELLED_RE.match(stripped)
    if labelled:
        title = labelled.group("title").strip(" .:—–-")
        label = labelled.group("label")
        # "Chapitre 4" with nothing after it is still a heading; name it by its
        # label rather than inventing a title.
        return _Heading(page=0, title=title or f"{label}", label=label)

    numbered = _NUMBERED_RE.match(stripped)
    if numbered:
        title = numbered.group("title").strip(" .:—–-")
        if not title or _IMPERATIVE_RE.match(title):
            return None
        # A heading is a noun phrase, not a run of prose. Four words is the
        # ceiling a real chapter title needs ("Le théorème de Pythagore").
        if len(title.split()) > 8:
            return None
        return _Heading(page=0, title=title, label=numbered.group("label"))

    return None


def _running_heads(pages: Sequence[PageText]) -> set[str]:
    """Lines repeated near the top of many pages: the book's own furniture."""
    if len(pages) < RUNNING_HEAD_MIN_PAGES:
        return set()
    counts: Counter[str] = Counter()
    for page in pages:
        # Only the first few lines: a running head sits at the top of the page.
        for line in page.text.split("\n")[:3]:
            key = _normalise(line)
            if key:
                counts[key] += 1
    threshold = max(RUNNING_HEAD_MIN_PAGES, int(len(pages) * RUNNING_HEAD_MIN_RATIO))
    return {key for key, n in counts.items() if n >= threshold}


def find_headings(pages: Sequence[PageText]) -> list[_Heading]:
    """Every heading in the document, in page order, at most one per page.

    One per page on purpose: a page carrying two chapter openings is far more
    likely to be a contents table than two three-line chapters, and taking the
    first keeps the outline monotonic.
    """
    furniture = _running_heads(pages)
    found: list[_Heading] = []
    for page in pages:
        for line in page.text.split("\n"):
            if _normalise(line) in furniture:
                continue
            heading = _candidate_heading(line)
            if heading is not None:
                found.append(_Heading(page=page.page, title=heading.title, label=heading.label))
                break
    return found


def detect_sections(pages: Iterable[PageText]) -> list[Section]:
    """Split the document into contiguous, gapless sections.

    Every page lands in exactly one section. If nothing looks like a heading —
    a worksheet, a book whose titles are images — the whole document is one
    section named for its page range, which is still a usable filter and, more
    importantly, still leaves every exercise reachable.
    """
    ordered = sorted(pages, key=lambda p: p.page)
    if not ordered:
        return []

    first_page, last_page = ordered[0].page, ordered[-1].page
    headings = find_headings(ordered)

    # Drop headings that would create a section shorter than the floor, keeping
    # the first of each run: a contents page listing every chapter would
    # otherwise produce a dozen one-page sections that hold no exercises.
    kept: list[_Heading] = []
    for heading in headings:
        if kept and heading.page - kept[-1].page < MIN_SECTION_PAGES:
            continue
        kept.append(heading)

    if not kept:
        return [
            Section(
                title=f"p. {first_page}–{last_page}",
                label=None,
                page_from=first_page,
                page_to=last_page,
                position=0,
            )
        ]

    sections: list[Section] = []
    # Pages before the first heading are a real part of the book. Naming them
    # honestly beats attaching them to chapter 1, which would misreport the
    # page range a teacher checks against the paper on their desk.
    if kept[0].page > first_page:
        sections.append(
            Section(
                title=f"p. {first_page}–{kept[0].page - 1}",
                label=None,
                page_from=first_page,
                page_to=kept[0].page - 1,
                position=0,
            )
        )

    for index, heading in enumerate(kept):
        page_to = kept[index + 1].page - 1 if index + 1 < len(kept) else last_page
        sections.append(
            Section(
                title=heading.title,
                label=heading.label,
                page_from=heading.page,
                page_to=max(page_to, heading.page),
                position=len(sections),
            )
        )
    return sections
