"""What an uploaded image is allowed to be, decided before it is decoded.

Two independent problems, both of which reach a teacher's laptop and neither of
which the upload checks in ``api/deps`` could see (audit 03, B15).

**A photograph carries where it was taken.** A phone stamps EXIF onto every
JPEG: GPS coordinates, the device, the exact second. A pile of scans is
photographed in a classroom, so those coordinates are a school building and, in
a village with one school, a class of identifiable children. That data has no
use anywhere in this product — the pipeline converts to greyscale on the first
line it touches — and it is copied to object storage and kept forever. It is
stripped on the way in.

**A small file is not a small image.** ``cv2.imdecode`` allocates the *decoded*
raster, so a 40 KB PNG declaring 60000×60000 asks for about 10 GB and takes the
worker's container with it. The size cap in ``read_upload`` cannot catch that:
it measures the compressed bytes, and compression is exactly what the attack
uses. The declared dimensions are read from the header — a few hundred bytes,
no raster — and the file is refused before anything allocates.

Both run at the door rather than in the pipeline, because the pipeline is the
worker and the worker is the thing being protected.
"""

from __future__ import annotations

import io
from typing import Final

from alppy.core.logging import get_logger

log = get_logger(__name__)

#: Formats whose metadata we can strip while keeping the pixels bit-for-bit.
#: HEIC is absent on purpose: it is transcoded to greyscale by
#: ``scan_processing._decode_heif`` before anything else sees it, and
#: re-encoding it here would cost quality for no gain. PDFs are not images and
#: are left alone; ``_decode_one`` rasterises them under its own guard.
_STRIPPABLE: Final = frozenset({"image/jpeg", "image/png"})


class ImageTooLargeError(ValueError):
    """The declared dimensions are past what we will decode."""


def guard_and_strip(data: bytes, content_type: str, *, max_pixels: int) -> bytes:
    """Refuse an oversized raster, and return the bytes without their metadata.

    Never raises for a file it simply cannot parse: a decode failure here would
    turn "this photo is unusual" into "this pile cannot be uploaded", and the
    pipeline downstream already reports an unreadable page in a way a teacher
    can act on. It raises only for the one case it is certain about — a header
    that *declares* more pixels than we are willing to allocate.
    """
    if content_type == "application/pdf":
        return data
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - pillow is a declared dependency
        return data

    # Explicit rather than inherited. Pillow's own default is ~89 Mpx and warns
    # at it; we want a number this codebase chose and a refusal, not a warning
    # in a log nobody reads.
    Image.MAX_IMAGE_PIXELS = max_pixels

    try:
        # `open` parses the header and does NOT decode the raster, so `size` is
        # the declared size and costs nothing. This is the whole guard.
        with Image.open(io.BytesIO(data)) as probe:
            width, height = probe.size
            fmt = probe.format
    except Image.DecompressionBombError as exc:
        raise ImageTooLargeError(str(exc)) from exc
    except Exception:
        # Unparseable by Pillow — a HEIC without the plugin registered, a
        # format it does not know. Hand it on untouched; the pipeline decides.
        return data

    if width * height > max_pixels:
        raise ImageTooLargeError(
            f"image declares {width}x{height} pixels, above the {max_pixels} ceiling"
        )

    if content_type not in _STRIPPABLE:
        return data
    return _without_metadata(data, content_type=content_type, fmt=fmt)


def _without_metadata(data: bytes, *, content_type: str, fmt: str | None) -> bytes:
    """Remove metadata without touching a single pixel.

    Done by segment surgery rather than by re-saving through Pillow, and the
    difference is not pedantry. These are the images a bubble detector reads,
    and ``_mark_strength`` compares fill ratios against fixed thresholds. Even
    Pillow's ``quality="keep"`` — which reuses the source's quantisation tables
    — decodes and re-encodes, and a test of this module measured the result:
    pixels moved by ±1. Small, and still a change to the evidence a grade is
    computed from, made silently, on every upload, for the sake of tidiness.

    So the entropy-coded data is copied through byte for byte and only the
    metadata containers are dropped:

    * **JPEG** — the APP1 segments holding Exif and XMP. Markers are walked in
      order; the scan data after SOS is copied whole and never parsed.
    * **PNG** — the ancillary chunks (``eXIf``, ``tEXt``, ``iTXt``, ``zTXt``).
      IHDR, PLTE, IDAT and IEND are untouched, so the raster is identical.

    Anything unexpected returns the original bytes. Keeping a photograph's EXIF
    is a privacy shortfall; dropping the photograph is a child's answers lost.
    """
    try:
        if content_type == "image/jpeg" and fmt == "JPEG":
            return _jpeg_without_metadata(data) or data
        if content_type == "image/png" and fmt == "PNG":
            return _png_without_metadata(data) or data
    except Exception as exc:  # pragma: no cover - defensive
        log.info("upload.metadata_strip_failed", content_type=content_type, error=str(exc))
    return data


#: JPEG application segments that carry metadata rather than image data.
#: APP1 is Exif and XMP; APP13 is Photoshop IRB, which carries IPTC.
_JPEG_METADATA_MARKERS: Final = frozenset({0xE1, 0xED})


def _jpeg_without_metadata(data: bytes) -> bytes | None:
    """Copy every JPEG segment except the metadata ones.

    Returns ``None`` if the file does not look like the JPEG we expect, so the
    caller can pass the original through untouched.
    """
    if not data.startswith(b"\xff\xd8"):
        return None
    out = bytearray(b"\xff\xd8")
    i = 2
    end = len(data)
    while i < end - 1:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        # Standalone markers: no length, no payload.
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            out += data[i : i + 2]
            i += 2
            continue
        if marker == 0xDA:  # start of scan — the rest is entropy-coded data
            out += data[i:]
            return bytes(out)
        if i + 4 > end:
            return None
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if length < 2 or i + 2 + length > end:
            return None
        if marker not in _JPEG_METADATA_MARKERS:
            out += data[i : i + 2 + length]
        i += 2 + length
    return bytes(out)


#: PNG chunks that carry metadata. Ancillary by definition (lower-case first
#: letter), so a decoder that has never heard of them ignores them anyway.
_PNG_METADATA_CHUNKS: Final = frozenset({b"eXIf", b"tEXt", b"iTXt", b"zTXt", b"tIME"})


def _png_without_metadata(data: bytes) -> bytes | None:
    """Copy every PNG chunk except the metadata ones."""
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        return None
    out = bytearray(signature)
    i = len(signature)
    end = len(data)
    while i + 8 <= end:
        length = int.from_bytes(data[i : i + 4], "big")
        tag = data[i + 4 : i + 8]
        nxt = i + 12 + length
        if length < 0 or nxt > end:
            return None
        if tag not in _PNG_METADATA_CHUNKS:
            out += data[i:nxt]
        i = nxt
        if tag == b"IEND":
            break
    return bytes(out)
