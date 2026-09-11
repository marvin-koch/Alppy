"""What an upload is allowed to be, before anything decodes it (audit 03, B15).

Two independent guards, tested against real bytes rather than mocks: a PNG that
really does declare 60000x60000, and a JPEG that really does carry EXIF GPS.
"""

from __future__ import annotations

import io
import struct
import zlib

import pytest

from alppy.media import ImageTooLargeError, guard_and_strip

MAX_PIXELS = 50_000_000


def _png_declaring(width: int, height: int) -> bytes:
    """A structurally valid PNG header claiming an arbitrary size.

    Hand-built rather than rendered, which is the entire point: the file is a
    few hundred bytes and the raster it declares is tens of gigabytes. Any
    guard that measures the upload's byte count sees nothing wrong here.
    """
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 16))
        + chunk(b"IEND", b"")
    )


def test_a_decompression_bomb_is_refused_before_it_is_decoded() -> None:
    """40 KB of file, ten gigabytes of raster.

    `cv2.imdecode` allocates the decoded image, so this is the worker's
    container going down — and `read_upload`'s size cap cannot see it, because
    compression is exactly what the attack uses.
    """
    bomb = _png_declaring(60_000, 60_000)
    assert len(bomb) < 1024, "the file itself must be tiny, or it proves nothing"
    with pytest.raises(ImageTooLargeError):
        guard_and_strip(bomb, "image/png", max_pixels=MAX_PIXELS)


def test_an_ordinary_photograph_is_not_refused() -> None:
    """The boundary. A guard that refuses everything is not a guard."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("L", (2480, 3508), color=255).save(buf, format="PNG")  # A4 at 300dpi
    out = guard_and_strip(buf.getvalue(), "image/png", max_pixels=MAX_PIXELS)
    assert out, "a normal scan must survive the guard"


def test_a_photographs_gps_never_reaches_storage() -> None:
    """A pile is photographed in a classroom, so its EXIF GPS is a school.

    In a village with one school that is a class of identifiable children,
    copied to object storage and kept forever, for data this product never
    reads — the pipeline greyscales the image on the first line it touches.
    """
    from PIL import Image
    from PIL.ExifTags import Base

    buf = io.BytesIO()
    image = Image.new("RGB", (64, 64), color=(200, 200, 200))
    exif = image.getexif()
    exif[Base.Make.value] = "TestPhone"
    exif[Base.DateTimeOriginal.value] = "2026:09:10 08:15:00"
    image.save(buf, format="JPEG", exif=exif)
    original = buf.getvalue()

    # The fixture has to actually carry the metadata, or the assertion below
    # passes for the wrong reason.
    with Image.open(io.BytesIO(original)) as before:
        assert dict(before.getexif()), "fixture carries no EXIF"

    cleaned = guard_and_strip(original, "image/jpeg", max_pixels=MAX_PIXELS)
    with Image.open(io.BytesIO(cleaned)) as after:
        assert not dict(after.getexif()), "EXIF survived the upload"


def test_stripping_keeps_the_pixels_a_detector_will_read() -> None:
    """The bubbles matter more than the tidiness.

    These are the images a bubble detector reads, and a re-compression artefact
    on the edge of a filled circle is a mark it may read differently. JPEG is
    re-wrapped with `quality="keep"`, which reuses the source's own quantisation
    tables, so the decoded raster is unchanged rather than merely similar.
    """
    import numpy as np
    from PIL import Image

    buf = io.BytesIO()
    rng = np.random.default_rng(0)
    pixels = rng.integers(0, 255, size=(64, 64), dtype=np.uint8)
    Image.fromarray(pixels, mode="L").save(buf, format="JPEG", quality=88)
    original = buf.getvalue()

    cleaned = guard_and_strip(original, "image/jpeg", max_pixels=MAX_PIXELS)
    with Image.open(io.BytesIO(original)) as a, Image.open(io.BytesIO(cleaned)) as b:
        assert np.array_equal(np.asarray(a.convert("L")), np.asarray(b.convert("L")))


def test_an_unparseable_file_is_passed_through_not_rejected() -> None:
    """A guard must not become a new way to lose a child's answers.

    "Pillow cannot read this" is not "this is dangerous" — a HEIC without the
    plugin registered lands here routinely. The pipeline downstream reports an
    unreadable page in a way a teacher can act on; this must not pre-empt it.
    """
    junk = b"not really an image at all"
    assert guard_and_strip(junk, "image/png", max_pixels=MAX_PIXELS) == junk


def test_a_pdf_is_left_alone_here() -> None:
    """PDFs are guarded where they are rasterised, not where they are read."""
    pdf = b"%PDF-1.7\n% a stub"
    assert guard_and_strip(pdf, "application/pdf", max_pixels=MAX_PIXELS) == pdf
