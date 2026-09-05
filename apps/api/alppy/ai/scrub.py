"""The PII enforcement point.

Every prompt that leaves Alppy passes through here. Student names are stored in
the database because a teacher needs to read them, but no model provider ever
sees one: prompts carry the UID (``7B_15``) instead, and this module is what
guarantees it.

The guarantee is enforced twice, deliberately:

* ``build_safe_prompt`` is the path callers use, and it takes structured data
  that has no name field to fill in in the first place.
* ``assert_no_pii`` is a belt-and-braces check run on the final string, so a
  future caller who assembles a prompt by hand still cannot leak a roster.

See docs/privacy.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from alppy.core.uid import ParsedUid, parse_uid


class PiiLeakError(RuntimeError):
    """Raised when a prompt about to leave the process contains student PII."""


# Swiss school rosters are FR/DE/IT names; matching "a capitalised word" would
# flag half the mathematics vocabulary. So we do not guess at names — we check
# against the actual roster we were given, which is exact and has no false
# positives on words like "Pythagore" or "Zürich".
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_RE = re.compile(r"(?:\+41|0041|0)\s?\d{2}\s?\d{3}\s?\d{2}\s?\d{2}")
_AHV_RE = re.compile(r"756\.\d{4}\.\d{4}\.\d{2}")  # Swiss social security number


@dataclass(frozen=True, slots=True)
class StudentRef:
    """How a student is referred to in a prompt: by UID, never by name."""

    uid: str

    @property
    def parsed(self) -> ParsedUid:
        return parse_uid(self.uid)

    def __str__(self) -> str:
        return self.uid


def to_ref(uid: str) -> StudentRef:
    """Validate and wrap a UID. Raises if it is not a well-formed UID, which
    stops a name being passed where a UID was expected."""
    return StudentRef(uid=parse_uid(uid).uid)


def scrub(text: str, *, names: list[str] | None = None) -> str:
    """Remove known PII from free text.

    ``names`` is the roster of the class in question. Redacting against the
    actual roster is exact; pattern-guessing at names is not, and would mangle
    exercise statements.
    """
    out = _EMAIL_RE.sub("[email]", text)
    out = _PHONE_RE.sub("[phone]", out)
    out = _AHV_RE.sub("[ahv]", out)
    for name in sorted(names or [], key=len, reverse=True):
        cleaned = name.strip()
        if len(cleaned) < 2:
            continue
        out = re.sub(rf"\b{re.escape(cleaned)}\b", "[student]", out, flags=re.IGNORECASE)
    return out


def assert_no_pii(text: str, *, names: list[str] | None = None) -> None:
    """Final gate before a prompt is sent. Raises rather than silently redacting:
    a leak here is a bug in the caller and must not be papered over."""
    if _EMAIL_RE.search(text):
        raise PiiLeakError("prompt contains an email address")
    if _AHV_RE.search(text):
        raise PiiLeakError("prompt contains an AHV number")
    for name in names or []:
        cleaned = name.strip()
        if len(cleaned) < 2:
            continue
        if re.search(rf"\b{re.escape(cleaned)}\b", text, flags=re.IGNORECASE):
            raise PiiLeakError(f"prompt contains a student name ({cleaned[:1]}...)")
