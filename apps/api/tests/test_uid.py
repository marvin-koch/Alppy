"""Student UID parsing. Getting this wrong attaches answers to the wrong child."""

from __future__ import annotations

import pytest

from alppy.core.uid import (
    InvalidUidError,
    format_uid,
    is_valid_class_code,
    parse_uid,
    try_parse_uid,
)


@pytest.mark.parametrize(
    ("raw", "code", "number"),
    [
        ("7B_15", "7B", 15),
        ("7B_5", "7B", 5),
        ("11AB_99", "11AB", 99),
        ("  7b_15  ", "7B", 15),
        ("7b-15", "7B", 15),
        ("7 B _ 1 5", "7B", 15),
        ("9C_01", "9C", 1),
    ],
)
def test_parse_valid(raw: str, code: str, number: int) -> None:
    parsed = parse_uid(raw)
    assert parsed.class_code == code
    assert parsed.number == number


@pytest.mark.parametrize(
    "raw",
    ["7B15", "B_15", "_15", "7B_", "7B_0", "7B_100", "", "7B_1_2", "ABC_1", "7ABC_1"],
)
def test_parse_invalid(raw: str) -> None:
    with pytest.raises(InvalidUidError):
        parse_uid(raw)
    assert try_parse_uid(raw) is None


def test_number_is_zero_padded() -> None:
    # The printed sheet aligns a mono column; 7B_5 and 7B_15 must line up.
    assert format_uid("7B", 5) == "7B_05"
    assert format_uid("7b", 15) == "7B_15"


def test_round_trip() -> None:
    for code, n in [("7B", 1), ("11AB", 99), ("9C", 7)]:
        assert parse_uid(format_uid(code, n)).number == n


def test_format_rejects_bad_input() -> None:
    with pytest.raises(InvalidUidError):
        format_uid("BB", 1)
    with pytest.raises(InvalidUidError):
        format_uid("7B", 0)
    with pytest.raises(InvalidUidError):
        format_uid("7B", 100)


def test_class_code_validation() -> None:
    assert is_valid_class_code("7B")
    assert is_valid_class_code(" 11ab ")
    assert not is_valid_class_code("B7")
    assert not is_valid_class_code("7")
