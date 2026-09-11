"""1 August, and the two hours before it.

``_school_year_bounds`` is the hinge of the whole identity-rollover design from
the first audit in this series: it decides which school year a class, a roster
and therefore a UID belong to. It had no test. The function is four lines and
obviously right, which is exactly the kind of function that is wrong at its
boundary — and its boundary moves once a year, on a day nobody is looking.

Three dates are enough to pin it, and the middle one is the whole point:
31 July is the old year, 1 August is the new one, and the year after tells the
label apart from the arithmetic that produced it.

The second half of this module is about **which** 1 August. ``current_school_year``
used to take its default from ``datetime.now(UTC).date()``, and Switzerland is
UTC+2 in summer: at 00:30 on 1 August in Sion it is still 31 July in UTC, so a
school set up that evening was given ``2025/26`` — the year that ended the day
before. The label is not decoration; ``current_school_year`` resolves a year BY
LABEL when one already exists, so the wrong label is durable. It now reads
``school_today()``, which is Europe/Zurich.

Deliberately NOT changed: ``validity.today()``, which stamps membership changes
and stays UTC. Being a couple of hours early on a membership costs nothing —
no read path compares it to a wall clock finer than a day — and making it
injectable would touch twenty call sites to fix a problem that is not one. The
two functions are separate because the same two hours means something different
to each.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant

from alppy.db.validity import SCHOOL_TZ, school_today, today
from alppy.models import SchoolYear
from alppy.services import class_service
from alppy.services.class_service import _school_year_bounds


@pytest.mark.parametrize(
    ("day", "label", "starts_on", "ends_on"),
    [
        # The last day of the old year. Everything about it says "2025/26".
        (date(2026, 7, 31), "2025/26", date(2025, 8, 1), date(2026, 7, 31)),
        # The first day of the new one. One day later, every field moves.
        (date(2026, 8, 1), "2026/27", date(2026, 8, 1), date(2027, 7, 31)),
        # A year on, so the label is not accidentally right for one year only.
        (date(2027, 7, 31), "2026/27", date(2026, 8, 1), date(2027, 7, 31)),
        (date(2027, 8, 1), "2027/28", date(2027, 8, 1), date(2028, 7, 31)),
        # Mid-year, both sides of the calendar new year — the other boundary a
        # reader might expect to matter, and which must not.
        (date(2026, 12, 31), "2026/27", date(2026, 8, 1), date(2027, 7, 31)),
        (date(2027, 1, 1), "2026/27", date(2026, 8, 1), date(2027, 7, 31)),
    ],
)
def test_the_year_turns_on_the_first_of_august(
    day: date, label: str, starts_on: date, ends_on: date
) -> None:
    assert _school_year_bounds(day) == (label, starts_on, ends_on)


def test_the_label_is_the_two_digit_swiss_form() -> None:
    """`2026/27`, not `2026/2027` and not `2026-27`.

    It is what a teacher writes at the top of a sheet, and 0036 made the
    database say so.
    """
    assert _school_year_bounds(date(2026, 9, 1))[0] == "2026/27"
    # The one case where naive string slicing goes wrong.
    assert _school_year_bounds(date(2099, 9, 1))[0] == "2099/00"


def test_every_day_of_a_year_lands_in_exactly_one_school_year() -> None:
    """No gap and no overlap, checked rather than reasoned about.

    A year of dates is cheap and this is the property that actually matters:
    the bounds a day reports must contain that day.
    """
    day = date(2026, 1, 1)
    while day < date(2028, 1, 1):
        _, starts_on, ends_on = _school_year_bounds(day)
        assert starts_on <= day <= ends_on, f"{day} fell outside its own year"
        day = date.fromordinal(day.toordinal() + 1)


# --- Which 1 August: the timezone half --------------------------------------


def test_the_school_year_is_computed_in_swiss_time_not_utc() -> None:
    """The 2-hour window this fix exists for, made concrete.

    23:30 UTC on 31 July is 01:30 on 1 August in Sion. The school year that
    starts in the morning has already started; UTC has not noticed.
    """
    instant = datetime(2026, 7, 31, 23, 30, tzinfo=UTC)

    utc_day = instant.astimezone(UTC).date()
    swiss_day = instant.astimezone(SCHOOL_TZ).date()

    assert utc_day == date(2026, 7, 31)
    assert swiss_day == date(2026, 8, 1)
    assert _school_year_bounds(utc_day)[0] == "2025/26"
    assert _school_year_bounds(swiss_day)[0] == "2026/27", (
        "the rollover resolved through UTC: a school set up on the evening of "
        "31 July gets the year that ended the day before, and the label is "
        "durable because current_school_year resolves by label"
    )


def test_school_today_is_zurich_and_today_is_utc() -> None:
    """The two are deliberately different functions; assert they stay so.

    Collapsing them into one would either make a membership change swing with
    Swiss DST or put the year boundary back in UTC.
    """
    assert ZoneInfo("Europe/Zurich") == SCHOOL_TZ
    assert school_today() == datetime.now(SCHOOL_TZ).date()
    assert today() == datetime.now(UTC).date()


def test_the_two_agree_on_every_day_except_the_late_evening() -> None:
    """Most of the time this distinction is invisible, which is why it was
    missed: the two answers differ only between local midnight and 02:00."""
    midday = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    assert midday.astimezone(SCHOOL_TZ).date() == midday.astimezone(UTC).date()

    late = datetime(2026, 8, 15, 23, 30, tzinfo=UTC)
    assert late.astimezone(SCHOOL_TZ).date() != late.astimezone(UTC).date()


@pytest.mark.parametrize(
    ("instant", "expected_swiss_day"),
    [
        # CET (+1) in winter, CEST (+2) in summer. The offset that carries the
        # date across is not a constant, which is why this reads a real tz
        # rather than subtracting an hour.
        (datetime(2026, 1, 15, 23, 30, tzinfo=UTC), date(2026, 1, 16)),
        (datetime(2026, 7, 15, 23, 30, tzinfo=UTC), date(2026, 7, 16)),
        (datetime(2026, 1, 15, 22, 30, tzinfo=UTC), date(2026, 1, 15)),
        (datetime(2026, 7, 15, 22, 30, tzinfo=UTC), date(2026, 7, 16)),
    ],
)
def test_the_offset_that_moves_the_date_is_not_a_constant(
    instant: datetime, expected_swiss_day: date
) -> None:
    """22:30 UTC is the same day in January and the next day in July."""
    assert instant.astimezone(SCHOOL_TZ).date() == expected_swiss_day


# --- The default actually in force ------------------------------------------
#
# Everything above tests the arithmetic, which was never the bug. These two go
# through `current_school_year` itself, because that is where the timezone is
# chosen — a test of `_school_year_bounds` alone passes whichever clock the
# caller hands it.


def test_current_school_year_takes_its_default_from_swiss_time(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Freeze the school clock on 1 August; the year created must be the new one.

    Monkeypatched on `class_service`'s own name rather than on `validity`, so
    this fails if someone reverts the call site to `datetime.now(UTC).date()`
    — which is the regression it exists for.

    The frozen date is deliberately FAR from the real one. Freezing on the
    nearest 1 August would have made this test pass against the reverted call
    site too, because the real clock produces the same label — a test that
    cannot tell the two apart is not testing the fix.
    """
    monkeypatch.setattr(class_service, "school_today", lambda: date(2030, 8, 1))
    db.query(SchoolYear).filter(SchoolYear.school_id == tenant.school.id).delete()
    db.flush()

    year = class_service.current_school_year(db, tenant.school.id)

    assert year.label == "2030/31", (
        "the default did not come from school_today(): the call site is reading "
        "a clock this test cannot freeze"
    )
    assert year.starts_on == date(2030, 8, 1)
    assert year.ends_on == date(2031, 7, 31)


def test_an_explicit_today_still_wins_over_the_clock(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The injectable argument is the one the seed and the tests use; the
    default must not quietly override it."""
    monkeypatch.setattr(class_service, "school_today", lambda: date(2026, 8, 1))
    db.query(SchoolYear).filter(SchoolYear.school_id == tenant.school.id).delete()
    db.flush()

    year = class_service.current_school_year(db, tenant.school.id, today=date(2026, 7, 31))

    assert year.label == "2025/26"
