"""Extraction and exercise-aware chunking.

The claim these tests defend is a product claim, not an arithmetic one: a chunk
must never contain half an exercise, because a half exercise is invisible to
retrieval and refused by extraction — a silent total loss of that item rather
than a degradation. Everything else here (page provenance, sizes, language,
the scanned-book path) exists to keep that claim honest end to end.
"""

from __future__ import annotations

import io

import pytest

from alppy.ingest.chunk import (
    MAX_CHARS,
    MERGE_TAIL_CHARS,
    Chunk,
    chunk_pages,
    is_exercise_start,
    split_blocks,
)
from alppy.ingest.extract import (
    MIN_LANGUAGE_TOKENS,
    ExtractedDocument,
    PageText,
    PdfExtractionError,
    detect_language,
    document_from_pages,
    extract_pdf,
)

# --------------------------------------------------------------------------
# A minimal PDF writer, so the extractor is tested against real PDF bytes
# rather than against a mock of itself.
# --------------------------------------------------------------------------
def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_pdf(pages: list[list[str]]) -> bytes:
    """Build a single-font PDF with the given lines on each page."""
    objects: list[bytes] = []
    n_pages = len(pages)
    font_obj = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for i, lines in enumerate(pages):
        content_obj = 4 + 2 * i
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_obj} 0 R >> >> "
                f"/Contents {content_obj} 0 R >>"
            ).encode()
        )
        body = "BT /F1 11 Tf 40 800 Td 14 TL\n"
        for line in lines:
            body += f"({_escape(line)}) Tj T*\n"
        body += "ET"
        raw = body.encode("latin-1", "replace")
        objects.append(
            b"<< /Length " + str(len(raw)).encode() + b" >>\nstream\n" + raw + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def make_blank_pdf(pages: int = 3) -> bytes:
    """A PDF with pages but no text layer — i.e. what a scanned book looks like."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(595, 842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Fixtures: a page that looks like a real textbook page
# --------------------------------------------------------------------------
FR_EXERCISES = [
    "1. Calcule 2/3 + 1/4 et donne le resultat sous forme irreductible.",
    "2. Simplifie la fraction 18/24 puis compare-la avec 3/4.",
    "3. Range dans l ordre croissant : 5/8, 0,6, 2/3 et 7/10.",
    "4. Un rectangle mesure 3/4 de metre sur 2/5 de metre. Quelle est son aire ?",
    "5. Ecris 0,375 sous forme de fraction irreductible et justifie.",
]

FR_PROSE = (
    "Une fraction represente une part d une unite partagee en parts egales. "
    "Le numerateur indique le nombre de parts prises et le denominateur le "
    "nombre total de parts. Deux fractions sont equivalentes lorsqu on peut "
    "passer de l une a l autre en multipliant ou en divisant le numerateur et "
    "le denominateur par un meme nombre non nul."
)


def textbook_page(page: int = 12) -> PageText:
    lines = [FR_PROSE, "", "Exercices", ""]
    for exercise in FR_EXERCISES:
        lines += [exercise, "a) premiere partie", "b) deuxieme partie", ""]
    return PageText(page=page, text="\n".join(lines))


# --------------------------------------------------------------------------
# is_exercise_start
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "line",
    [
        "1. Calcule 2/3 + 1/4.",
        "12) Simplifie la fraction.",
        " 7] Trouve x.",
        "N° 4 Resoudre l equation",
        "Exercice 12",
        "Aufgabe 7",
        "Übung 3",
        "Exercices",
        "Aufgaben",
    ],
)
def test_exercise_starts_are_recognised(line: str) -> None:
    assert is_exercise_start(line)


@pytest.mark.parametrize(
    "line",
    [
        "a) premiere partie",
        "b. deuxieme partie",
        "Le numerateur indique le nombre de parts.",
        "2020 fut une annee difficile.",  # a bare number is not an exercise
        "1.5 cm",  # a decimal is not an exercise number
        "",
    ],
)
def test_sub_items_and_prose_do_not_start_an_exercise(line: str) -> None:
    """Breaking at ``a)`` would split the exercise it belongs to — the exact
    failure the exercise-aware chunker exists to prevent."""
    assert not is_exercise_start(line)


def test_split_blocks_makes_each_exercise_its_own_block() -> None:
    blocks = split_blocks(textbook_page().text)
    exercise_blocks = [b for b in blocks if b.starts_exercise]
    # five numbered exercises plus the "Exercices" heading
    assert len(exercise_blocks) == len(FR_EXERCISES) + 1
    for block, statement in zip(exercise_blocks[1:], FR_EXERCISES, strict=True):
        assert block.text.startswith(statement)
        assert "a) premiere partie" in block.text  # sub-items stayed attached


# --------------------------------------------------------------------------
# chunk_pages — the central claim
# --------------------------------------------------------------------------
def test_no_exercise_is_split_across_chunks() -> None:
    chunks = chunk_pages([textbook_page()])
    for statement in FR_EXERCISES:
        holders = [c for c in chunks if statement in c.text]
        assert holders, f"exercise was lost entirely: {statement!r}"


def test_a_chunk_never_holds_only_the_head_of_an_exercise() -> None:
    """The invariant, stated exactly: if a chunk contains the beginning of an
    exercise it contains all of it. A chunk may hold several whole exercises —
    that is fine — but never a truncated one."""
    chunks = chunk_pages([textbook_page()])
    for statement in FR_EXERCISES:
        head = statement[:30]
        for chunk in chunks:
            if head in chunk.text:
                assert statement in chunk.text, (
                    f"chunk at position {chunk.position} holds only the head of {statement!r}"
                )


def test_chunk_boundaries_land_on_exercise_starts() -> None:
    """Once a chunk is big enough to flush, the break is taken at an exercise
    start rather than wherever the character budget ran out."""
    page = PageText(page=7, text="\n\n".join(FR_EXERCISES * 4))
    chunks = chunk_pages([page])
    assert len(chunks) > 1
    assert all(c.starts_exercise for c in chunks), [c.starts_exercise for c in chunks]
    for chunk in chunks:
        assert is_exercise_start(chunk.text.splitlines()[0])


def test_page_provenance_survives_and_chunks_never_span_pages() -> None:
    pages = [textbook_page(11), textbook_page(12), textbook_page(13)]
    chunks = chunk_pages(pages)
    assert {c.page for c in chunks} == {11, 12, 13}
    # A chunk carries exactly one page, so provenance can never be a guess.
    for page in (11, 12, 13):
        on_page = [c for c in chunks if c.page == page]
        assert on_page
        assert sum(len(c.text) for c in on_page) > 0


def test_positions_are_unique_and_monotonic_across_the_document() -> None:
    chunks = chunk_pages([textbook_page(1), textbook_page(2)])
    positions = [c.position for c in chunks]
    assert positions == sorted(positions)
    assert len(set(positions)) == len(positions)
    assert positions[0] == 0


def test_chunk_sizes_stay_within_the_embedding_budget() -> None:
    chunks = chunk_pages([textbook_page()])
    oversized = [c for c in chunks if c.char_count > MAX_CHARS + MERGE_TAIL_CHARS]
    assert not oversized, [c.char_count for c in oversized]


def test_long_prose_is_split_on_sentence_ends_not_mid_sentence() -> None:
    prose = " ".join([FR_PROSE] * 6)
    chunks = chunk_pages([PageText(page=3, text=prose)])
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.char_count <= MAX_CHARS + MERGE_TAIL_CHARS
        # No chunk ends mid-word.
        assert not chunk.text.endswith(("l", "d")) or chunk.text.endswith(".")


def test_overlap_is_carried_into_a_continuation_chunk_but_not_into_an_exercise() -> None:
    prose_chunks = chunk_pages([PageText(page=1, text=" ".join([FR_PROSE] * 6))])
    tail = prose_chunks[0].text[-40:].split(" ", 1)[-1]
    assert tail in prose_chunks[1].text, "continuation chunk lost its overlap"

    exercise_chunks = [c for c in chunk_pages([textbook_page()]) if c.starts_exercise]
    for chunk in exercise_chunks:
        assert is_exercise_start(chunk.text.splitlines()[0]), (
            "an exercise chunk must start at the exercise, not at borrowed overlap"
        )


def test_empty_pages_produce_no_chunks() -> None:
    assert chunk_pages([PageText(page=1, text="   \n\n  ")]) == []


def test_chunk_is_hashable_and_reports_its_size() -> None:
    chunk = Chunk(text="abc", page=1, position=0)
    assert chunk.char_count == 3
    assert {chunk}  # frozen dataclass: usable in a set


# --------------------------------------------------------------------------
# Language detection
# --------------------------------------------------------------------------
def test_detects_french_german_and_english() -> None:
    assert detect_language(FR_PROSE) == "fr"
    assert (
        detect_language(
            "Ein Bruch ist ein Teil einer Einheit, die in gleiche Teile geteilt wird. "
            "Der Zähler gibt an, wie viele Teile genommen werden, und der Nenner "
            "gibt an, in wie viele Teile das Ganze geteilt ist."
        )
        == "de"
    )
    assert (
        detect_language(
            "A fraction is a part of a unit that has been divided into equal parts. "
            "The numerator is the number of parts taken and the denominator is the "
            "total number of parts that the whole has been divided into."
        )
        == "en"
    )


def test_declines_to_guess_on_too_little_text() -> None:
    assert detect_language("2/3 + 1/4") is None
    assert detect_language(" ".join(["x"] * (MIN_LANGUAGE_TOKENS - 1))) is None


def test_declines_to_guess_when_no_stopword_matches() -> None:
    assert detect_language(" ".join(["xyzzy"] * 40)) is None


# --------------------------------------------------------------------------
# PDF extraction
# --------------------------------------------------------------------------
def test_extracts_text_with_page_numbers() -> None:
    document = extract_pdf(make_pdf([["Page une", *FR_EXERCISES], ["Page deux", FR_PROSE]]))
    assert document.page_count == 2
    assert [p.page for p in document.pages] == [1, 2]
    assert "Page une" in document.pages[0].text
    assert "Page deux" in document.pages[1].text
    assert document.has_text
    assert document.language == "fr"


def test_a_scanned_book_is_reported_not_silently_empty() -> None:
    """A PDF with pages and no text layer must be detectable as such — the
    pipeline turns this into a `Source.error` the teacher can act on."""
    document = extract_pdf(make_blank_pdf(4))
    assert document.page_count == 4
    assert not document.has_text
    assert document.language is None
    assert document.char_count == 0


def test_an_unreadable_file_raises() -> None:
    with pytest.raises(PdfExtractionError):
        extract_pdf(b"")
    with pytest.raises(PdfExtractionError):
        extract_pdf(b"this is not a pdf at all, not even close")


def test_hyphenated_line_breaks_are_rejoined() -> None:
    document = extract_pdf(make_pdf([["Le denomi-", "nateur indique le nombre de parts."]]))
    assert "denominateur" in document.pages[0].text


def test_document_from_pages_detects_language_and_text_presence() -> None:
    document = document_from_pages([PageText(page=1, text=FR_PROSE)])
    assert isinstance(document, ExtractedDocument)
    assert document.language == "fr"
    assert document.has_text
    assert not document_from_pages([PageText(page=1, text="")]).has_text
