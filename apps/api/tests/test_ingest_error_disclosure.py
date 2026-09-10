"""What a failed ingest is allowed to tell the teacher.

`Source.error` is rendered verbatim by the /sources screen, so anything that
reaches it is on a teacher's monitor — and regularly on a projector. These
tests pin the boundary: prose for them, diagnostics for the log.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import ProgrammingError

from alppy.ingest.extract import PdfExtractionError
from alppy.ingest.pipeline import (
    UNEXPECTED_INGEST_ERROR,
    UNREADABLE_PDF_ERROR,
    _teacher_facing_error,
)


def test_unreadable_pdf_gets_its_own_sentence() -> None:
    assert _teacher_facing_error(PdfExtractionError("could not open PDF: XRefError")) == (
        UNREADABLE_PDF_ERROR
    )


@pytest.mark.parametrize(
    "exc",
    [
        # The three shapes that made this a disclosure rather than an untidy
        # string: SQL and column names, an absolute server path, and the
        # object store's endpoint.
        ProgrammingError("SELECT student.first_name FROM student", {}, Exception("boom")),
        OSError(2, "No such file or directory", "/srv/alppy/storage/sources/7b2f.pdf"),
        RuntimeError("EndpointConnectionError: http://minio:9000 bucket=alppy-prod"),
    ],
)
def test_unrecognised_failures_disclose_nothing(exc: Exception) -> None:
    message = _teacher_facing_error(exc)
    assert message == UNEXPECTED_INGEST_ERROR
    for leak in ("SELECT", "first_name", "/srv/", "minio", "alppy-prod", type(exc).__name__):
        assert leak not in message


def test_the_generic_sentence_carries_no_exception_shape() -> None:
    """A regression guard with teeth: the old code was an f-string over the
    exception, so anything of that shape reappearing is the bug coming back."""
    assert ":" not in UNEXPECTED_INGEST_ERROR.split(".")[0]
    assert "Error" not in UNEXPECTED_INGEST_ERROR
