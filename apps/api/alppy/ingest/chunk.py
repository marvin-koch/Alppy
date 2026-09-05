"""Exercise-aware chunking with page provenance.

Why this is not a fixed-width splitter
--------------------------------------
A chunk that cuts an exercise in half poisons the two things it feeds:

* **Retrieval.** Half a statement embeds as a fragment. "Calcule l'aire d'un
  triangle rectangle dont les cathètes mesurent" and "6 cm et 8 cm." are two
  vectors, neither of which is close to a teacher's query about areas, where the
  whole sentence would have been.
* **Extraction.** The `extract_exercises` prompt is explicitly told not to
  invent. Handed half an exercise it correctly refuses, and the exercise is
  lost from both halves — a silent 100 % loss on that item, not a degradation.

So the chunker treats the start of a numbered exercise as a preferred break
point. It never breaks *into* one when it can break *before* one instead.

Sizes
-----
Target 500-800 characters. The floor keeps a chunk large enough to carry an
exercise plus the instruction line above it; the ceiling keeps it comfortably
under the 512-token truncation limit of `intfloat/multilingual-e5-large`
(docs/adr/0001-embeddings-provider.md) — 800 characters of French or German
prose is roughly 200-280 tokens, so even with the model's ``passage: `` prefix
there is ample headroom.

Chunks never span a page. Page provenance is the whole point of the feature and
a chunk covering pages 12-13 can only report one of them honestly.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from alppy.ingest.extract import PageText

TARGET_CHARS = 650
"""What we aim for. Chunks flush at an exercise boundary once past MIN_CHARS."""

MIN_CHARS = 500
"""Below this a chunk keeps accumulating even across an exercise boundary."""

MAX_CHARS = 800
"""Hard ceiling. A single block longer than this is split on sentence ends."""

OVERLAP_CHARS = 120
"""Tail of the previous chunk repeated at the head of the next, so a sentence
straddling a forced break is still retrievable whole from one side. Skipped
when the next chunk starts at an exercise boundary: there the break is
deliberate and clean, and repeating the previous exercise's tail would only
blur what the chunk is about."""

MERGE_TAIL_CHARS = 120
"""A trailing scrap shorter than this is merged back into the previous chunk of
the same page rather than left as a chunk that says nothing."""


# ``12.`` ``12)`` ``12]`` ``N° 7`` ``Exercice 4`` ``Aufgabe 12`` ``Übung 3``
_EXERCISE_START_RE = re.compile(
    r"""^\s{0,3}(?:
          \d{1,3}\s*[.)\]]\s+\S            # 12. Calcule ...   (needs content after)
        | [nN]°\s*\d{1,3}
        | (?:Exercice|Exercise|Exercices|Übung|Uebung|Übungen|Aufgabe|Aufgaben
           |Ex|Aufg|Nr|Nr\.)\s*\.?\s*\d{1,3}\b
    )""",
    re.VERBOSE,
)

# A heading such as "Exercices" / "Aufgaben" with no number also starts a block:
# it is the top of an exercise run, which is exactly where we want to break.
_EXERCISE_HEADING_RE = re.compile(
    r"^\s{0,3}(?:Exercices?|Exercises?|Übungen?|Uebungen?|Aufgaben?|Problèmes?)\s*:?\s*$",
    re.IGNORECASE,
)

_SENTENCE_END_RE = re.compile(r"(?<=[.!?:;])\s+")


def is_exercise_start(line: str) -> bool:
    """True if this line opens a numbered exercise or an exercise run.

    Sub-items (``a)``, ``b.``) deliberately do not match: they belong to the
    exercise above them and breaking there would split the very thing we are
    protecting.
    """
    return bool(_EXERCISE_START_RE.match(line) or _EXERCISE_HEADING_RE.match(line))


@dataclass(frozen=True, slots=True)
class Chunk:
    """A unit of retrieval. ``position`` is unique and monotonic per document."""

    text: str
    page: int
    position: int
    starts_exercise: bool = False

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass(frozen=True, slots=True)
class _Block:
    """A paragraph or a single exercise: the atom the packer moves around."""

    text: str
    starts_exercise: bool


def split_blocks(page_text: str) -> list[_Block]:
    """Split one page into paragraph/exercise blocks.

    A block ends at a blank line or immediately before a line that opens an
    exercise. That second rule is what makes the chunker exercise-aware: by the
    time the packer runs, an exercise is already an indivisible object.
    """
    blocks: list[_Block] = []
    current: list[str] = []
    current_is_exercise = False

    def flush() -> None:
        nonlocal current, current_is_exercise
        text = "\n".join(current).strip()
        if text:
            blocks.append(_Block(text=text, starts_exercise=current_is_exercise))
        current = []
        current_is_exercise = False

    for line in page_text.split("\n"):
        if not line.strip():
            flush()
            continue
        if is_exercise_start(line):
            flush()
            current_is_exercise = True
        current.append(line)
    flush()
    return blocks


def _split_oversized(text: str, *, limit: int = MAX_CHARS) -> list[str]:
    """Split a single over-long block on sentence ends, never mid-sentence.

    Only reached by a wall of prose with no blank lines — a dense theory page.
    If even one sentence exceeds the limit it is emitted whole rather than
    chopped: an over-long chunk embeds worse, a chopped sentence embeds wrong.
    """
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    buffer = ""
    for sentence in _SENTENCE_END_RE.split(text):
        if not sentence:
            continue
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence
        if buffer and len(candidate) > limit:
            pieces.append(buffer)
            buffer = sentence
        else:
            buffer = candidate
    if buffer:
        pieces.append(buffer)
    return pieces


def _overlap_tail(text: str, *, size: int = OVERLAP_CHARS) -> str:
    """The last ``size`` characters, snapped forward to a word boundary."""
    if size <= 0 or len(text) <= size:
        return text
    tail = text[-size:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else tail


def chunk_pages(
    pages: Sequence[PageText],
    *,
    target_chars: int = TARGET_CHARS,
    min_chars: int = MIN_CHARS,
    max_chars: int = MAX_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
) -> list[Chunk]:
    """Chunk a whole document, preserving page and ordering.

    ``position`` runs across the document rather than restarting per page, so
    ``(source_id, position)`` is a stable natural key — which is what makes
    re-ingesting the same file idempotent instead of duplicating.
    """
    chunks: list[Chunk] = []
    position = 0

    for page in pages:
        for text, starts_exercise in _pack_page(
            split_blocks(page.text),
            target_chars=target_chars,
            min_chars=min_chars,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        ):
            chunks.append(
                Chunk(
                    text=text,
                    page=page.page,
                    position=position,
                    starts_exercise=starts_exercise,
                )
            )
            position += 1
    return chunks


def _pack_page(
    blocks: Iterable[_Block],
    *,
    target_chars: int,
    min_chars: int,
    max_chars: int,
    overlap_chars: int,
) -> list[tuple[str, bool]]:
    """Greedy packer with two break rules, in priority order.

    1. **Exercise boundary** — once the buffer is past ``min_chars``, a block
       that opens an exercise flushes first. This is the rule the whole module
       exists for.
    2. **Ceiling** — a block that would push the buffer past ``max_chars``
       flushes first, whatever it is. Without it a page of unnumbered prose
       would grow one unbounded chunk.
    """
    out: list[tuple[str, bool]] = []
    buffer = ""
    buffer_starts_exercise = False
    pending_overlap = ""

    def flush() -> None:
        nonlocal buffer, buffer_starts_exercise, pending_overlap
        text = buffer.strip()
        if text:
            out.append((text, buffer_starts_exercise))
            pending_overlap = _overlap_tail(text, size=overlap_chars)
        buffer = ""
        buffer_starts_exercise = False

    for block in blocks:
        for i, piece in enumerate(_split_oversized(block.text, limit=max_chars)):
            opens_exercise = block.starts_exercise and i == 0
            if buffer and opens_exercise and len(buffer) >= min_chars:
                flush()
            elif buffer and len(buffer) + len(piece) + 2 > max_chars:
                flush()

            if not buffer:
                # Carry overlap only into a chunk that does not open an
                # exercise: a clean exercise start deserves a clean chunk.
                if pending_overlap and not opens_exercise:
                    buffer = pending_overlap
                buffer_starts_exercise = opens_exercise
                pending_overlap = ""

            buffer = f"{buffer}\n\n{piece}".strip() if buffer else piece

            if len(buffer) >= max(target_chars, max_chars):
                flush()

    flush()
    return _merge_scraps(out)


def _merge_scraps(pieces: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    """Fold a too-short trailing fragment back into its predecessor."""
    merged: list[tuple[str, bool]] = []
    for text, starts_exercise in pieces:
        if (
            merged
            and len(text) < MERGE_TAIL_CHARS
            and not starts_exercise
            and len(merged[-1][0]) + len(text) + 2 <= MAX_CHARS + MERGE_TAIL_CHARS
        ):
            prev_text, prev_flag = merged[-1]
            merged[-1] = (f"{prev_text}\n\n{text}", prev_flag)
            continue
        merged.append((text, starts_exercise))
    return merged
