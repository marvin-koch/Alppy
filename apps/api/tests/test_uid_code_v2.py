"""Layout v2's page code: the paper says which paper it is (audit 03, B4).

v1 encoded only the pupil, which is why three faults were possible at once: a
UID resolved across school years (B3), which page of a copy a photo showed came
from upload order (B5), and a page from a *different sheet* carrying the same
pupil's UID was read against whatever answer key the pile was attached to.
"""

from __future__ import annotations

import random

import pytest

from alppy.sheets import layout as L
from alppy.sheets.uid_code import (
    CANTON_UNSET,
    PageCode,
    UidCodeError,
    bits_to_cells,
    cells_to_bits,
    decode_page_code,
    decode_uid,
    encode_page_code,
    encode_uid,
)


def _code(**over: object) -> PageCode:
    base: dict[str, object] = {
        "uid": "7B_15",
        "school_year": 3,
        "page_in_copy": 2,
        "canton": 21,  # VS
        "nonce": 1234567,
    }
    base.update(over)
    return PageCode(**base)  # type: ignore[arg-type]


def test_the_v2_payload_exactly_fills_the_grid() -> None:
    """The bit budget, asserted rather than commented.

    12x6 = 72 bits, of which CRC-16 takes sixteen. The design was proposed with
    a 24-bit nonce and that is 73 bits — one over — so the nonce is 23. A
    comment claiming the arithmetic works is worth nothing; this fails if
    anybody widens a field without taking the bits from somewhere.
    """
    from alppy.sheets.uid_code import _V2_FIELDS

    grid = L.uid_grid("v2")
    assert sum(width for _name, width in _V2_FIELDS) == grid.payload_bits
    assert grid.payload_bits + grid.checksum_bits == grid.total_bits == 72


def test_a_page_code_survives_the_round_trip() -> None:
    code = _code()
    assert decode_page_code(encode_page_code(code)) == code


def test_every_field_round_trips_at_its_limits() -> None:
    """Boundaries, because an off-by-one in a bit field is silent.

    A page number stored 0-based to reach 16, a canton that may be unset, a
    nonce at the top of its range: each of these decodes to a *plausible* wrong
    value if its width or offset is wrong, never to an error.
    """
    for over in (
        {"page_in_copy": 1},
        {"page_in_copy": 16},
        {"school_year": 0},
        {"school_year": 7},
        {"canton": 0},
        {"canton": 25},
        {"canton": CANTON_UNSET},
        {"nonce": 0},
        {"nonce": (1 << 23) - 1},
        {"uid": "9A_01"},
    ):
        code = _code(**over)
        assert decode_page_code(encode_page_code(code)) == code, over


def test_a_field_out_of_range_is_refused_not_truncated() -> None:
    """Silently masking a too-large value would print a different real page."""
    for over in (
        {"page_in_copy": 0},
        {"page_in_copy": 17},
        {"school_year": 8},
        {"canton": 26},
        {"nonce": 1 << 23},
    ):
        with pytest.raises(UidCodeError):
            encode_page_code(_code(**over))


def test_a_single_flipped_cell_fails_rather_than_naming_another_pupil() -> None:
    """The guarantee the whole scheme rests on.

    A creased photocopy misreads cells. Failing sends the page to the teacher
    for manual assignment, which is recoverable; resolving to a different real
    pupil is not. Every single-bit error must be caught — that is why v2 moved
    to CRC-16: an 8-bit checksum over 56 payload bits no longer delivers this.
    """
    bits = encode_page_code(_code())
    for i in range(len(bits)):
        broken = list(bits)
        broken[i] ^= 1
        with pytest.raises(UidCodeError):
            decode_page_code(broken)


def test_every_two_bit_error_is_caught_too() -> None:
    """CRC-16-CCITT catches all 1- and 2-bit errors in a payload this size.

    Exhaustive over the pairs, because "catches every 1-2 bit error" is a claim
    the v1 docstring already makes and nothing checked.
    """
    bits = encode_page_code(_code())
    for i in range(len(bits)):
        for j in range(i + 1, len(bits)):
            broken = list(bits)
            broken[i] ^= 1
            broken[j] ^= 1
            with pytest.raises(UidCodeError):
                decode_page_code(broken)


def test_the_grid_ordering_is_column_major_in_both_versions() -> None:
    """The one thing a wider grid must not change.

    If v2 reordered the cells, a v1 page read against v2's row count would
    decode to a different, real pupil rather than failing — which is the exact
    failure mode the checksum exists to prevent, reintroduced by geometry.
    """
    for version, bits in (
        ("v1", encode_uid("7B_15")),
        ("v2", encode_page_code(_code())),
    ):
        cells = bits_to_cells(bits, version=version)
        assert cells_to_bits(cells, version=version) == bits
        rows = L.uid_grid(version).rows
        assert cells[1].slot == 0 and cells[1].row == 1, version
        assert cells[rows].slot == 1 and cells[rows].row == 0, version


def test_v1_still_decodes_exactly_as_it_did() -> None:
    """Every sheet already printed is v1 forever.

    The versioned-geometry work must not have moved a v1 cell or changed a v1
    bit: a pile photographed in March from a sheet printed in January is the
    ordinary case.
    """
    # Note `10VG3_07`, which appears in the decisions log as an example, is not
    # a UID this codebase parses — `core.uid._UID_RE` does not accept a
    # multi-letter niveau code with a trailing digit. Left out rather than
    # silently skipped, so this test says what it covers.
    for uid in ("7B_15", "9A_01", "11C_99"):
        bits = encode_uid(uid)
        assert len(bits) == 32
        assert decode_uid(bits) == uid


def test_a_v1_grid_is_not_a_valid_v2_grid() -> None:
    """Different sizes, so the wrong decoder refuses rather than guesses."""
    with pytest.raises(UidCodeError):
        decode_page_code(encode_uid("7B_15"))


def test_random_codes_round_trip() -> None:
    """A spread, because hand-picked values hide offset bugs that only show
    when two adjacent fields are both non-zero."""
    rng = random.Random(7)
    for _ in range(500):
        code = PageCode(
            uid=f"{rng.randint(7, 11)}{chr(rng.randrange(65, 91))}_{rng.randint(1, 99):02d}",
            school_year=rng.randint(0, 7),
            page_in_copy=rng.randint(1, 16),
            canton=rng.choice([*range(26), CANTON_UNSET]),
            nonce=rng.randrange(1 << 23),
        )
        assert decode_page_code(encode_page_code(code)) == code
