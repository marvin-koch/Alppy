"""The printed UID grid.

The property that matters is not "it decodes" but "a misread never decodes to a
*different real student*". A wrong-but-plausible UID silently files a child's
answers under someone else's name; a failed decode just asks the teacher.
"""

from __future__ import annotations

import itertools

import pytest

from alppy.sheets.uid_code import (
    TOTAL_BITS,
    UidCodeError,
    bits_to_cells,
    cells_to_bits,
    decode_uid,
    encode_uid,
)

UIDS = ["7B_15", "7A_01", "9C_07", "10B_42", "11AB_99", "8D_50"]


@pytest.mark.parametrize("uid", UIDS)
def test_round_trip(uid: str) -> None:
    assert decode_uid(encode_uid(uid)) == uid


@pytest.mark.parametrize("uid", UIDS)
def test_grid_is_exactly_the_layout_size(uid: str) -> None:
    assert len(encode_uid(uid)) == TOTAL_BITS


@pytest.mark.parametrize("uid", UIDS)
def test_every_single_bit_error_is_rejected(uid: str) -> None:
    bits = encode_uid(uid)
    for i in range(TOTAL_BITS):
        flipped = list(bits)
        flipped[i] ^= 1
        with pytest.raises(UidCodeError):
            decode_uid(flipped)


def test_every_double_bit_error_is_rejected() -> None:
    bits = encode_uid("7B_15")
    for i, j in itertools.combinations(range(TOTAL_BITS), 2):
        flipped = list(bits)
        flipped[i] ^= 1
        flipped[j] ^= 1
        with pytest.raises(UidCodeError):
            decode_uid(flipped)


def test_cells_round_trip() -> None:
    bits = encode_uid("7B_15")
    assert cells_to_bits(bits_to_cells(bits)) == bits


def test_wrong_length_rejected() -> None:
    with pytest.raises(UidCodeError):
        decode_uid([0] * 31)


def test_unrepresentable_class_year_rejected() -> None:
    # Layout v1 gives the year 4 bits. A year past 15 must fail loudly at print
    # time rather than produce a sheet that decodes to the wrong class.
    with pytest.raises(UidCodeError):
        encode_uid("16B_01")
