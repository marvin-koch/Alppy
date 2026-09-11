"""The machine-readable UID grid printed on every sheet.

The UID is printed twice: as human-readable text (``7B_15``) and as a small
pre-filled grid of black and white cells. The grid is what the scan pipeline
reads, which is why the happy path needs no OCR at all — OCR on a phone photo
of a photocopy is exactly where these systems usually fail.

Layout v1 uses 8 columns x 4 rows = 32 bits, filled column-major:

    bit index = column * 4 + row

    bits  0..3    class year          1..15   (Swiss Sek I is 7..11)
    bits  4..8    first class letter  0..25   (A=0)
    bits  9..13   second class letter 0..25, or 26 for "absent"
    bits 14..20   student number      1..99
    bits 21..23   reserved, always 0
    bits 24..31   checksum of bits 0..23

The checksum is the point: a single misread cell on a creased photocopy makes
the decode *fail* rather than silently resolve to a different, real student.
Failing sends the page to the teacher for manual assignment, which is
recoverable. Guessing is not.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Final

from alppy.core.uid import InvalidUidError, format_uid, parse_uid
from alppy.sheets.layout import UID_GRIDS, uid_grid

#: **v1's** grid, named explicitly rather than taken from "the current
#: layout". These three used to be derived from the module-level `UID_GRID_*`
#: constants, which were v1's values — so they were right by accident, and the
#: accident would have ended the moment anyone made those constants track the
#: current version. `encode_uid`/`decode_uid` are the v1 codec and nothing else;
#: v2's sizes come from `uid_grid("v2")` at each use.
_V1: Final = uid_grid("v1")
TOTAL_BITS: Final = _V1.total_bits  # 32
PAYLOAD_BITS: Final = _V1.payload_bits  # 24
CHECKSUM_BITS: Final = _V1.checksum_bits  # 8

_LETTER_ABSENT: Final = 26
_CHECKSUM_POLY: Final = 0x07  # CRC-8-ATM; small, cheap, catches every 1-2 bit error


class UidCodeError(ValueError):
    """Raised when a grid cannot be decoded into a valid UID."""


def _crc8(bits: list[int]) -> int:
    """CRC-8 over the payload bits, MSB first."""
    crc = 0x00
    for i in range(0, len(bits), 8):
        byte = 0
        for b in bits[i : i + 8]:
            byte = (byte << 1) | (b & 1)
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ _CHECKSUM_POLY) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def _int_to_bits(value: int, width: int) -> list[int]:
    return [(value >> (width - 1 - i)) & 1 for i in range(width)]


def _bits_to_int(bits: list[int]) -> int:
    out = 0
    for b in bits:
        out = (out << 1) | (b & 1)
    return out


def encode_uid(uid: str) -> list[int]:
    """UID string -> 32 bits, in grid order (column-major)."""
    parsed = parse_uid(uid)
    code = parsed.class_code
    year_part = "".join(c for c in code if c.isdigit())
    letters = "".join(c for c in code if c.isalpha())

    year = int(year_part)
    if not 1 <= year <= 15:
        raise UidCodeError(f"class year {year} outside 1..15, not representable in layout v1")
    if not 1 <= len(letters) <= 2:
        raise UidCodeError(f"class code {code!r} must carry one or two letters")

    l1 = ord(letters[0]) - ord("A")
    l2 = ord(letters[1]) - ord("A") if len(letters) == 2 else _LETTER_ABSENT

    payload = (
        _int_to_bits(year, 4)
        + _int_to_bits(l1, 5)
        + _int_to_bits(l2, 5)
        + _int_to_bits(parsed.number, 7)
        + [0, 0, 0]
    )
    assert len(payload) == PAYLOAD_BITS
    return payload + _int_to_bits(_crc8(payload), CHECKSUM_BITS)


def decode_uid(bits: list[int]) -> str:
    """32 bits -> UID string. Raises ``UidCodeError`` on any inconsistency."""
    if len(bits) != TOTAL_BITS:
        raise UidCodeError(f"expected {TOTAL_BITS} bits, got {len(bits)}")

    payload = [b & 1 for b in bits[:PAYLOAD_BITS]]
    checksum = _bits_to_int([b & 1 for b in bits[PAYLOAD_BITS:]])
    if _crc8(payload) != checksum:
        raise UidCodeError("checksum mismatch — grid misread")

    year = _bits_to_int(payload[0:4])
    l1 = _bits_to_int(payload[4:9])
    l2 = _bits_to_int(payload[9:14])
    number = _bits_to_int(payload[14:21])

    if not 1 <= year <= 15:
        raise UidCodeError(f"decoded class year {year} out of range")
    if l1 > 25:
        raise UidCodeError(f"decoded class letter {l1} out of range")

    code = f"{year}{chr(ord('A') + l1)}"
    if l2 != _LETTER_ABSENT:
        if l2 > 25:
            raise UidCodeError(f"decoded second class letter {l2} out of range")
        code += chr(ord("A") + l2)

    try:
        return format_uid(code, number)
    except InvalidUidError as exc:
        raise UidCodeError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class GridCell:
    slot: int  # column
    row: int
    filled: bool


def _version_for_bits(count: int, version: str | None) -> str:
    """Which layout a run of bits belongs to, when the caller did not say.

    Inferred from the length rather than defaulting to the current version, and
    that is a correctness fix rather than a convenience: `encode_uid` is
    inherently v1, so pairing it with a cell helper that quietly assumed "the
    newest layout" produced 32 bits in and 72 out the day v2 shipped. Length is
    unambiguous — the grids differ in size — and a caller that knows better can
    still say so.
    """
    if version is not None:
        return version
    for name, grid in UID_GRIDS.items():
        if grid.total_bits == count:
            return name
    raise UidCodeError(f"{count} bits match no known layout grid")


def bits_to_cells(bits: list[int], *, version: str | None = None) -> list[GridCell]:
    """Grid order is column-major: bit index = column * rows + row.

    Column-major in **both** versions, deliberately: the ordering is the one
    thing a wider grid must not change, or a v1 page read against v2's row
    count would decode to a different, real pupil rather than failing.
    """
    rows = uid_grid(_version_for_bits(len(bits), version)).rows
    return [
        GridCell(slot=i // rows, row=i % rows, filled=bool(b))
        for i, b in enumerate(bits)
    ]


def cells_to_bits(cells: list[GridCell], *, version: str | None = None) -> list[int]:
    grid = uid_grid(_version_for_bits(len(cells), version))
    bits = [0] * grid.total_bits
    for c in cells:
        bits[c.slot * grid.rows + c.row] = 1 if c.filled else 0
    return bits


# ---------------------------------------------------------------------------
# Layout v2: the page says which paper it is, not just whose
# ---------------------------------------------------------------------------
_CRC16_POLY: Final = 0x1021  # CRC-16-CCITT

#: Canton codes are 0..25; 31 means "this school has not declared one".
CANTON_UNSET: Final = 31

#: Field widths, in the order they are packed. The total is exactly the grid's
#: payload, and a test asserts that rather than trusting this comment.
_V2_FIELDS: Final[tuple[tuple[str, int], ...]] = (
    ("year", 4),
    ("letter1", 5),
    ("letter2", 5),
    ("number", 7),
    ("school_year", 3),
    ("page_in_copy", 4),
    ("canton", 5),
    ("nonce", 23),
)


@dataclass(frozen=True, slots=True)
class PageCode:
    """Everything layout v2 prints into the grid — a page, not just a pupil.

    v1 encoded only the pupil, which is why three separate faults were possible
    at once (audit 03): a UID resolved across school years (B3), which page of
    a copy a photo showed was inferred from upload order (B5), and a page from
    a *different sheet* carrying the same pupil's UID was read against whatever
    answer key the pile was attached to. The paper now says all of it.
    """

    uid: str
    #: The school year, rolling mod 8. Not an id — three bits cannot hold one —
    #: but enough that a copy from a neighbouring year fails the cross-check
    #: rather than resolving to a different real pupil (defence in depth for B3).
    school_year: int
    #: 1-based, as the page footer prints it. B5's real fix: the page says which
    #: page it is instead of the pipeline counting uploads.
    page_in_copy: int
    #: 0..25, or ``CANTON_UNSET``.
    canton: int
    #: Identifies (sheet, render generation). A page whose nonce does not match
    #: the pile's sheet is from another sheet, or from a render whose geometry
    #: has since been replaced — both of which used to be silently gradeable.
    nonce: int


def _crc16(bits: list[int]) -> int:
    """CRC-16-CCITT over the payload bits, MSB first.

    Sixteen bits rather than v1's eight because the payload more than doubled.
    The guarantee that makes the whole scheme safe is that a misread grid
    *fails* rather than resolving to a different real student, and an 8-bit
    checksum over 56 bits on a creased photocopy no longer delivers it.
    """
    crc = 0xFFFF
    for i in range(0, len(bits), 8):
        byte = 0
        for b in bits[i : i + 8]:
            byte = (byte << 1) | (b & 1)
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ _CRC16_POLY) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode_page_code(code: PageCode) -> list[int]:
    """A ``PageCode`` -> the v2 grid's bits, in grid order."""
    grid = uid_grid("v2")
    parsed = parse_uid(code.uid)
    class_code = parsed.class_code
    year_part = "".join(c for c in class_code if c.isdigit())
    letters = "".join(c for c in class_code if c.isalpha())

    year = int(year_part)
    if not 1 <= year <= 15:
        raise UidCodeError(f"class year {year} outside 1..15")
    if not 1 <= len(letters) <= 2:
        raise UidCodeError(f"class code {class_code!r} must carry one or two letters")
    if not 0 <= code.school_year <= 7:
        raise UidCodeError(f"school year slot {code.school_year} outside 0..7")
    if not 1 <= code.page_in_copy <= 16:
        raise UidCodeError(f"page {code.page_in_copy} outside 1..16")
    if not (0 <= code.canton <= 25 or code.canton == CANTON_UNSET):
        raise UidCodeError(f"canton {code.canton} outside 0..25 and not CANTON_UNSET")
    if not 0 <= code.nonce < (1 << 23):
        raise UidCodeError(f"nonce {code.nonce} outside 23 bits")

    values = {
        "year": year,
        "letter1": ord(letters[0]) - ord("A"),
        "letter2": ord(letters[1]) - ord("A") if len(letters) == 2 else _LETTER_ABSENT,
        "number": parsed.number,
        "school_year": code.school_year,
        # Stored 0-based so the 4 bits reach 16 pages rather than 15.
        "page_in_copy": code.page_in_copy - 1,
        "canton": code.canton,
        "nonce": code.nonce,
    }
    payload: list[int] = []
    for name, width in _V2_FIELDS:
        payload += _int_to_bits(values[name], width)
    if len(payload) != grid.payload_bits:  # pragma: no cover - asserted by a test
        raise UidCodeError(
            f"v2 payload is {len(payload)} bits, grid holds {grid.payload_bits}"
        )
    return payload + _int_to_bits(_crc16(payload), grid.checksum_bits)


def decode_page_code(bits: list[int]) -> PageCode:
    """The v2 grid's bits -> a ``PageCode``. Raises on any inconsistency."""
    grid = uid_grid("v2")
    if len(bits) != grid.total_bits:
        raise UidCodeError(f"expected {grid.total_bits} bits, got {len(bits)}")

    payload = [b & 1 for b in bits[: grid.payload_bits]]
    checksum = _bits_to_int([b & 1 for b in bits[grid.payload_bits :]])
    if _crc16(payload) != checksum:
        raise UidCodeError("checksum mismatch — grid misread")

    fields: dict[str, int] = {}
    at = 0
    for name, width in _V2_FIELDS:
        fields[name] = _bits_to_int(payload[at : at + width])
        at += width

    year = fields["year"]
    l1 = fields["letter1"]
    l2 = fields["letter2"]
    if not 1 <= year <= 15:
        raise UidCodeError(f"decoded class year {year} out of range")
    if l1 > 25:
        raise UidCodeError(f"decoded class letter {l1} out of range")
    class_code = f"{year}{chr(ord('A') + l1)}"
    if l2 != _LETTER_ABSENT:
        if l2 > 25:
            raise UidCodeError(f"decoded second class letter {l2} out of range")
        class_code += chr(ord("A") + l2)

    try:
        uid = format_uid(class_code, fields["number"])
    except InvalidUidError as exc:
        raise UidCodeError(str(exc)) from exc

    return PageCode(
        uid=uid,
        school_year=fields["school_year"],
        page_in_copy=fields["page_in_copy"] + 1,
        canton=fields["canton"],
        nonce=fields["nonce"],
    )


#: Cantons in the order their code maps to a 5-bit field. Alphabetical, which
#: is arbitrary and therefore has to be FROZEN: renumbering it would silently
#: change what every already-printed v2 sheet says about where it came from.
CANTON_ORDER: Final[tuple[str, ...]] = (
    "AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU",
    "LU", "NE", "NW", "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR",
    "VD", "VS", "ZG", "ZH",
)


def canton_code(canton: str | None) -> int:
    """A canton's 5-bit value, or ``CANTON_UNSET`` for a school without one."""
    if not canton:
        return CANTON_UNSET
    try:
        return CANTON_ORDER.index(canton.strip().upper())
    except ValueError:
        # An unrecognised canton is "not declared" rather than an error: the
        # allowlist refuses one at the API, and a sheet must still print for a
        # school whose row predates that validation.
        return CANTON_UNSET


def sheet_nonce(sheet_id: uuid.UUID, render_generation: int) -> int:
    """The 23-bit value identifying one render of one sheet (B4).

    **Derived, not stored**, and that is the point: the renderer computes it
    when it prints and the scan pipeline computes it again from the sheet the
    pile claims to belong to, then compares. Nothing has to be carried between
    them, so there is no column to migrate and no row to fall out of step with
    the paper.

    It includes the render generation (B7), so the printed page says not only
    which sheet it belongs to but which *render* of it — which is what lets a
    pile printed on Tuesday be told apart from one printed on Wednesday after
    an edit, on the paper rather than by inference at upload.

    A hash rather than a counter: a counter would need a column, and a sheet id
    is already unique. 23 bits gives a 1-in-8.4M chance that two different
    sheets collide — and a collision is not a misgrade on its own, it only
    costs the cross-check its ability to notice one particular wrong sheet.
    """
    digest = hashlib.sha256(sheet_id.bytes + render_generation.to_bytes(4, "big")).digest()
    return int.from_bytes(digest[:4], "big") & ((1 << 23) - 1)


def school_year_slot(starts_on_year: int) -> int:
    """The 3-bit rolling school-year value.

    Three bits cannot hold a year id, and do not need to: the job is to make a
    copy from a neighbouring year fail the cross-check rather than resolve to a
    different real pupil (defence in depth for B3). Mod 8 means two years eight
    apart agree, which is well past the life of any pile of paper.
    """
    return starts_on_year % 8
