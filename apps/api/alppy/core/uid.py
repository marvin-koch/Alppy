"""Student UID parsing and formatting.

A UID looks like ``7B_15``: class code ``7B``, student number ``15``. It is
unique per school-year, and it is the *only* student identifier that is ever
printed on paper or sent to a model provider. Names never leave the database
for those purposes — see docs/privacy.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Class code: one or two digits (the school year, 7-11 in Swiss Sek I) followed
# by one or two letters (the parallel class). Student number: 1-99.
_UID_RE = re.compile(r"^(?P<class_code>\d{1,2}[A-Za-z]{1,2})_(?P<number>\d{1,2})$")
_CLASS_RE = re.compile(r"^\d{1,2}[A-Za-z]{1,2}$")

MAX_STUDENT_NUMBER = 99


class InvalidUidError(ValueError):
    """Raised when a string is not a well-formed student UID."""


@dataclass(frozen=True, slots=True)
class ParsedUid:
    class_code: str
    number: int

    @property
    def uid(self) -> str:
        return format_uid(self.class_code, self.number)


def parse_uid(raw: str) -> ParsedUid:
    """Parse ``7B_15``. Tolerant of surrounding whitespace and of lowercase.

    Deliberately strict about everything else: a UID read off a scanned page
    that does not parse must fail loudly so the teacher is asked, rather than
    silently attaching a stack of answers to the wrong child.
    """
    if not isinstance(raw, str):
        raise InvalidUidError("uid must be a string")
    candidate = raw.strip().upper().replace("-", "_").replace(" ", "")
    m = _UID_RE.match(candidate)
    if m is None:
        raise InvalidUidError(f"malformed student uid: {raw!r}")
    number = int(m.group("number"))
    if not 1 <= number <= MAX_STUDENT_NUMBER:
        raise InvalidUidError(f"student number out of range in {raw!r}")
    return ParsedUid(class_code=m.group("class_code").upper(), number=number)


def try_parse_uid(raw: str) -> ParsedUid | None:
    try:
        return parse_uid(raw)
    except InvalidUidError:
        return None


def format_uid(class_code: str, number: int) -> str:
    """Build a UID. Numbers are zero-padded to two digits so the printed grid
    and the mono column both align."""
    code = class_code.strip().upper()
    if not _CLASS_RE.match(code):
        raise InvalidUidError(f"malformed class code: {class_code!r}")
    if not 1 <= number <= MAX_STUDENT_NUMBER:
        raise InvalidUidError(f"student number out of range: {number}")
    return f"{code}_{number:02d}"


def is_valid_class_code(code: str) -> bool:
    return bool(_CLASS_RE.match(code.strip().upper()))
