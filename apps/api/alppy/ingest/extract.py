"""Text extraction from an uploaded PDF, with page provenance.

Two things matter here and nothing else does:

1. **Page numbers survive.** A teacher auditing a proposal opens the book at a
   page. If extraction loses the page, provenance is a lie, so text is never
   concatenated across page boundaries in this module.
2. **A scanned book is detected, not silently accepted.** Swiss school
   textbooks are frequently scans with no text layer. ``pypdf`` returns ``""``
   for those without raising, which would sail through the pipeline and produce
   a `Source` with zero chunks and a green tick. ``ExtractedDocument.has_text``
   is what stops that; the pipeline turns it into a `Source.error` the teacher
   can read.

Language detection is a stopword frequency count. It is not a language model
and does not need to be: the question is only "fr, de or en?", the texts are
hundreds of words long, and the three stopword sets are near-disjoint. A
dependency such as ``langdetect`` or ``fasttext`` would add tens of megabytes to
buy accuracy on a decision that a 60-word lookup table already gets right.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from alppy.core.logging import get_logger

log = get_logger(__name__)

# --------------------------------------------------------------------------
# Thresholds for "this PDF has no usable text layer"
# --------------------------------------------------------------------------
MIN_DOC_CHARS = 120
"""A document with less text than this is treated as having no text layer.
A real textbook page carries 1'000-3'000 characters; a scanned one carries a
handful of stray glyphs from the OCR-less PDF producer, if any."""

MIN_CHARS_PER_PAGE = 40
"""Average characters per page below which we also call it a scan. Catches the
case of a 200-page scan with one text-bearing colophon page."""

WORD_RE = re.compile(r"[\wÀ-ÿ']+", re.UNICODE)


class PdfExtractionError(RuntimeError):
    """The file could not be opened as a PDF at all."""


@dataclass(frozen=True, slots=True)
class PageText:
    """One page of a PDF. ``page`` is 1-based, as printed in the book."""

    page: int
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text.strip())


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    pages: tuple[PageText, ...]
    page_count: int
    language: str | None
    extractor: str

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    @property
    def char_count(self) -> int:
        return sum(p.char_count for p in self.pages)

    @property
    def has_text(self) -> bool:
        """False for a scanned book. The pipeline records this on the Source."""
        if self.page_count == 0:
            return False
        if self.char_count < MIN_DOC_CHARS:
            return False
        return self.char_count / self.page_count >= MIN_CHARS_PER_PAGE


# --------------------------------------------------------------------------
# Language detection
# --------------------------------------------------------------------------
# Chosen for frequency and for being near-disjoint between the three languages.
# "in" is genuinely shared by de and en, so it sits in both lists rather than
# being dropped: a shared token adds the same amount to both scores and cannot
# decide the outcome on its own.
STOPWORDS: dict[str, frozenset[str]] = {
    "fr": frozenset(
        ["le", "la", "les", "de", "des", "du", "un", "une", "et", "est", "sont", "dans", "pour", "que", "qui", "sur", "avec", "au", "aux", "ne", "pas", "plus", "ou", "par", "ce", "cette", "son", "sa", "ses", "nous", "vous", "ils", "elles", "a", "en", "il", "elle", "calcule", "quelle", "quel", "combien", "exercice", "réponse", "fraction", "nombre"]
    ),
    "de": frozenset(
        ["der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "und", "ist", "sind", "nicht", "mit", "für", "auf", "zu", "von", "im", "in", "am", "als", "auch", "oder", "aber", "sich", "wird", "werden", "bei", "nach", "berechne", "welche", "welcher", "wie", "viel", "aufgabe", "antwort", "bruch", "zahl"]
    ),
    "en": frozenset(
        ["the", "of", "and", "is", "are", "to", "in", "for", "with", "that", "on", "this", "be", "as", "by", "an", "it", "from", "at", "or", "not", "have", "has", "which", "what", "how", "many", "calculate", "exercise", "answer", "fraction", "number"]
    ),
}

MIN_LANGUAGE_TOKENS = 12
"""Below this many words we decline to guess; the caller keeps ``None``."""


def detect_language(text: str) -> str | None:
    """Return "fr", "de", "en" — or None when there is too little to judge.

    Returns the language whose stopword set covers the largest share of the
    tokens. Ties (which need identical coverage, so effectively only the
    all-zero case) return None rather than a coin flip: an unknown language is
    a better thing to store than a wrong one, because `Exercise.language` is
    what the printer and the grader trust.
    """
    tokens = [t.lower() for t in WORD_RE.findall(text)]
    if len(tokens) < MIN_LANGUAGE_TOKENS:
        return None
    counts = Counter(tokens)
    total = sum(counts.values())
    scores = {
        lang: sum(n for token, n in counts.items() if token in words) / total
        for lang, words in STOPWORDS.items()
    }
    best = max(scores, key=lambda k: scores[k])
    if scores[best] <= 0.0:
        return None
    runners = sorted(scores.values(), reverse=True)
    if len(runners) > 1 and runners[0] == runners[1]:
        return None
    return best


# --------------------------------------------------------------------------
# PDF text extraction
# --------------------------------------------------------------------------
def _extract_with_pdfplumber(data: bytes) -> list[PageText] | None:
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - declared in pyproject
        return None
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return [
                PageText(page=i + 1, text=_normalise(page.extract_text() or ""))
                for i, page in enumerate(pdf.pages)
            ]
    except Exception as exc:
        log.info("ingest.pdfplumber.failed", error=type(exc).__name__)
        return None


def _extract_with_pypdf(data: bytes) -> list[PageText]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - declared in pyproject
        raise PdfExtractionError("pypdf is not installed") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = reader.pages
    except Exception as exc:
        raise PdfExtractionError(f"could not open PDF: {type(exc).__name__}") from exc
    out: list[PageText] = []
    for i, page in enumerate(pages):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        out.append(PageText(page=i + 1, text=_normalise(raw)))
    return out


_WS_RUN = re.compile(r"[ \t ]+")
_BLANK_RUN = re.compile(r"\n{3,}")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")


def _normalise(raw: str) -> str:
    """Tidy extractor output without changing wording.

    Joins words broken across a line by a hyphen (extremely common in a
    justified textbook column and it wrecks both embedding and extraction),
    collapses runs of spaces, and caps blank-line runs at one — the chunker
    reads blank lines as block separators, so their *presence* is signal but
    their *count* is not.
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = "\n".join(_WS_RUN.sub(" ", line).rstrip() for line in text.split("\n"))
    return _BLANK_RUN.sub("\n\n", text).strip()


def extract_pdf(data: bytes) -> ExtractedDocument:
    """Extract text page by page.

    ``pdfplumber`` first: it reconstructs columns and reading order far better
    on textbook layouts, which is exactly where a naive extractor interleaves
    two columns and turns every exercise into nonsense. ``pypdf`` is the
    fallback for files pdfplumber chokes on — between them almost everything
    with a text layer opens.
    """
    if not data:
        raise PdfExtractionError("empty file")

    pages = _extract_with_pdfplumber(data)
    extractor = "pdfplumber"
    if pages is None or not any(p.text.strip() for p in pages):
        fallback = _extract_with_pypdf(data)
        if pages is None or sum(p.char_count for p in fallback) > sum(
            p.char_count for p in pages
        ):
            pages, extractor = fallback, "pypdf"

    document = ExtractedDocument(
        pages=tuple(pages),
        page_count=len(pages),
        language=None,
        extractor=extractor,
    )
    language = detect_language(document.text) if document.has_text else None
    return ExtractedDocument(
        pages=document.pages,
        page_count=document.page_count,
        language=language,
        extractor=extractor,
    )


def document_from_pages(pages: Sequence[PageText], *, extractor: str = "given") -> ExtractedDocument:
    """Build a document from already-extracted pages.

    Used by tests and by any future non-PDF source (a paste, an .odt export)
    so the chunk/embed/extract half of the pipeline never learns about PDFs.
    """
    ordered = tuple(pages)
    doc = ExtractedDocument(
        pages=ordered, page_count=len(ordered), language=None, extractor=extractor
    )
    return ExtractedDocument(
        pages=ordered,
        page_count=len(ordered),
        language=detect_language(doc.text) if doc.has_text else None,
        extractor=extractor,
    )
