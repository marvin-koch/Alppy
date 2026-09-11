"""The half-open validity predicate the membership tables are read through.

Its own module, below both ``services/enrollment`` and ``api/deps``, because
both need it and ``enrollment`` already imports ``deps`` for ``Scope``. Putting
these two functions in ``enrollment`` and importing them from ``deps`` would
close that loop.

Since 0027, ``class_student``, ``class_teacher_subject`` and ``teacher_school``
keep a row when a membership ends rather than deleting it (D87). Every read
that means "is this true NOW" has to say so, and this is where it is said —
once, rather than as two clauses repeated at twenty call sites, because the
failure mode of repeating them is one site that drops the ``IS NULL`` arm and
returns nothing at all. An empty roster does not read as a bug; it reads as a
missing child.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Table, and_, or_


def today() -> date:
    """The date a membership change is stamped with.

    UTC, like every other ``datetime.now`` in the codebase. Between local
    midnight and 02:00 CEST this is yesterday's date in Sion, which makes a
    membership read as having started a couple of hours early and nothing
    else — no read path compares it to a wall clock finer than a day.
    """
    return datetime.now(UTC).date()


#: Where the product's calendar lives. The school year, the timetable and the
#: date printed on a sheet are all facts about a Swiss school day, not about UTC.
SCHOOL_TZ = ZoneInfo("Europe/Zurich")


def school_today() -> date:
    """The date it is *at the school*.

    Distinct from ``today()`` above, and the distinction is worth two functions
    rather than one argument. ``today()`` stamps a membership change, where
    being a couple of hours early costs nothing — no read path compares it to a
    wall clock finer than a day. This one answers "which school year is it",
    where the same couple of hours straddles a YEAR boundary: at 00:30 on 1
    August in Sion it is still 31 July in UTC, so a school created in that
    window would be given ``2025/26`` — the year that ended the day before —
    and the label is not decoration, because `current_school_year` resolves a
    year BY LABEL when one already exists.

    Two hours once a year is a small window. It is also the two hours when a
    Swiss teacher is most likely to be setting up for the year that starts in
    the morning.
    """
    return datetime.now(SCHOOL_TZ).date()


def valid_on(table: Table, on: date) -> ColumnElement[bool]:
    """Was this membership row in force on ``on``?

    **Half-open**: ``valid_from <= on < valid_to``. A membership starting today
    counts today; one ending today does not. So unenrolling takes effect the
    moment the teacher does it rather than at midnight, and a pupil moved out
    of a group and back into it on one afternoon ends with one open row rather
    than two overlapping ones.

    ``valid_to IS NULL`` means still open, which is what every row backfilled
    by 0027 carries — and is why that migration is provably behaviour-
    preserving: applied to an all-open table this predicate selects exactly the
    rows an unqualified read selected before it.
    """
    return and_(
        table.c.valid_from <= on,
        or_(table.c.valid_to.is_(None), table.c.valid_to > on),
    )
