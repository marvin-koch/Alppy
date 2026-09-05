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

from dataclasses import dataclass
from typing import Final

from alppy.core.uid import InvalidUidError, format_uid, parse_uid
from alppy.sheets.layout import UID_GRID_CELLS, UID_GRID_ROWS

TOTAL_BITS: Final = UID_GRID_CELLS * UID_GRID_ROWS  # 32
PAYLOAD_BITS: Final = 24
CHECKSUM_BITS: Final = TOTAL_BITS - PAYLOAD_BITS  # 8

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


def bits_to_cells(bits: list[int]) -> list[GridCell]:
    """Grid order is column-major: bit index = column * rows + row."""
    return [
        GridCell(slot=i // UID_GRID_ROWS, row=i % UID_GRID_ROWS, filled=bool(b))
        for i, b in enumerate(bits)
    ]


def cells_to_bits(cells: list[GridCell]) -> list[int]:
    bits = [0] * TOTAL_BITS
    for c in cells:
        bits[c.slot * UID_GRID_ROWS + c.row] = 1 if c.filled else 0
    return bits
